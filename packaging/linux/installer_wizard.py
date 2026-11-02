#!/usr/bin/env python3
"""Assistente gráfico de instalação para Linux (estilo "Próximo → Próximo").

Por que isto existe: o Linux não tem um formato de instalador com assistente
que funcione em qualquer distro. `.deb` só cobre Debian/Ubuntu, AppImage não
instala nada (só executa) e Flatpak exige infraestrutura de repositório. Para
dar ao usuário final a mesma experiência do instalador do Windows — aceitar a
licença, escolher a pasta, marcar atalhos, ver a barra de progresso — a saída
mais direta é escrever o assistente com o toolkit que o projeto já usa.

Ele é empacotado junto com o app no mesmo bundle do PyInstaller (veja
`packaging/app.spec`), de modo que app e assistente compartilham as mesmas
bibliotecas do Qt, e o conjunto vira um único arquivo `.run` auto-extraível
(veja `packaging/linux/build_installer.sh`).

A instalação é **relocável e sem root**: por padrão vai para `~/.local/share`.
Se o assistente for executado como root, ele muda os destinos para os
equivalentes de sistema (`/opt`, `/usr/share/applications`). Nenhum dado do
usuário (sessão do Telegram, credenciais, preferências) mora na pasta de
instalação — isso fica em `platformdirs`, então desinstalar não apaga login.

Para testar sem gerar o `.run`:
    python packaging/linux/installer_wizard.py --payload dist/TelegramJellyfinOrganizer
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

APP_NAME = "Telegram Jellyfin Organizer"
APP_ID = "telegram-jellyfin-organizer"
APP_EXE = "telegram-jellyfin-organizer"
DESCRIPTION = "Baixa mídia do Telegram já organizada no padrão de pastas do Jellyfin"

BRASS = "#C89B3C"
TEAL = "#4FA3A0"
INK = "#0B0B0C"
SURFACE = "#141417"
TEXT = "#E8E6E1"
MUTED = "#9A958C"

STYLESHEET = f"""
QWizard, QWizardPage, QWidget {{
    background-color: {INK};
    color: {TEXT};
    font-size: 13px;
}}
QLabel {{ background: transparent; color: {TEXT}; }}
QLabel#subtitle {{ color: {MUTED}; }}
QLineEdit, QTextBrowser {{
    background-color: {SURFACE};
    border: 1px solid #2A2A2F;
    border-radius: 4px;
    padding: 6px;
    color: {TEXT};
    selection-background-color: {BRASS};
    selection-color: {INK};
}}
QPushButton {{
    background-color: {SURFACE};
    border: 1px solid #343439;
    border-radius: 4px;
    padding: 6px 18px;
    color: {TEXT};
    min-width: 88px;
}}
QPushButton:hover {{ border-color: {BRASS}; }}
QPushButton:disabled {{ color: #5A5751; border-color: #262629; }}
QPushButton:default {{
    background-color: {BRASS};
    border-color: {BRASS};
    color: {INK};
    font-weight: 600;
}}
QPushButton:default:hover {{ background-color: #D9AC4D; }}
QCheckBox {{ spacing: 8px; padding: 3px 0; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid #3A3A40;
    border-radius: 3px;
    background: {SURFACE};
}}
QCheckBox::indicator:checked {{ background: {BRASS}; border-color: {BRASS}; }}
QProgressBar {{
    background-color: {SURFACE};
    border: 1px solid #2A2A2F;
    border-radius: 4px;
    height: 20px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{ background-color: {TEAL}; border-radius: 3px; }}
"""


# ----------------------------------------------------------------------------
# Localização dos arquivos — modo congelado (PyInstaller) e modo script
# ----------------------------------------------------------------------------

def asset(name: str) -> Path:
    """Arquivo empacotado junto com o assistente."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "packaging" / "assets" / name
        if candidate.exists():
            return candidate
        return base / name
    return Path(__file__).resolve().parent.parent / "assets" / name


def license_text() -> str:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        path = base / "LICENSE"
    else:
        path = Path(__file__).resolve().parent.parent.parent / "LICENSE"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return "Licença MIT. Veja o arquivo LICENSE no repositório do projeto."


def payload_dir(override: str | None) -> Path:
    """Pasta com o bundle do app a ser copiado.

    Congelado, o assistente vive dentro do próprio bundle: o diretório do
    executável já é o payload.
    """
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    raise SystemExit(
        "Rodando a partir do código-fonte é obrigatório passar --payload "
        "<pasta do bundle gerado pelo PyInstaller>."
    )


# ----------------------------------------------------------------------------
# Destinos de instalação
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Targets:
    """Onde cada artefato vai parar, conforme usuário comum ou root."""

    install_dir: Path
    applications_dir: Path
    icons_dir: Path
    bin_dir: Path
    system_wide: bool

    @classmethod
    def detect(cls) -> "Targets":
        if os.geteuid() == 0:
            return cls(
                install_dir=Path("/opt") / APP_ID,
                applications_dir=Path("/usr/share/applications"),
                icons_dir=Path("/usr/share/icons/hicolor"),
                bin_dir=Path("/usr/local/bin"),
                system_wide=True,
            )
        data_home = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        )
        return cls(
            install_dir=data_home / APP_ID,
            applications_dir=data_home / "applications",
            icons_dir=data_home / "icons" / "hicolor",
            bin_dir=Path.home() / ".local" / "bin",
            system_wide=False,
        )


@dataclass
class Options:
    install_dir: Path
    menu_shortcut: bool = True
    desktop_shortcut: bool = False
    path_symlink: bool = True


def run_optional(command: list[str]) -> bool:
    """Executa um utilitário de desktop que pode simplesmente não existir.

    `subprocess.run(..., check=False)` **não** cobre este caso: `check=False`
    silencia código de saída diferente de zero, mas o binário ausente levanta
    FileNotFoundError antes disso. Numa distro enxuta (ou num container sem
    `desktop-file-utils`), isso derrubava a instalação inteira depois de os
    arquivos já terem sido copiados.

    Nenhum destes comandos é essencial — são otimizações de integração com o
    desktop. Falhar neles jamais pode falhar a instalação.
    """
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except (FileNotFoundError, OSError):
        return False
    return result.returncode == 0


# ----------------------------------------------------------------------------
# Worker: a cópia roda fora da thread da UI para a barra de progresso andar
# ----------------------------------------------------------------------------

class InstallWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, source: Path, options: Options, targets: Targets) -> None:
        super().__init__()
        self.source = source
        self.options = options
        self.targets = targets

    # -- utilidades -------------------------------------------------------
    def _files_to_copy(self) -> list[Path]:
        skip = {"install"}  # o próprio assistente não vai junto
        return [
            p
            for p in self.source.rglob("*")
            if p.is_file() and p.relative_to(self.source).parts[0] not in skip
        ]

    def _desktop_entry(self, exec_path: Path, icon: str) -> str:
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            f"Comment={DESCRIPTION}\n"
            f'Exec="{exec_path}" %U\n'
            f"Icon={icon}\n"
            "Terminal=false\n"
            f"StartupWMClass={APP_EXE}\n"
            "Categories=AudioVideo;Video;Network;FileTransfer;\n"
            "Keywords=telegram;jellyfin;download;midia;\n"
        )

    @staticmethod
    def _looks_like_our_install(path: Path) -> bool:
        """Confere a assinatura de uma instalação feita por este assistente.

        Esta é a trava de segurança de um `rm -rf` cujo caminho foi *lido de
        um arquivo*: se o `.desktop` estiver corrompido, editado à mão ou
        apontando para outro programa, o alvo pode ser qualquer pasta —
        inclusive o `$HOME`. Só removemos o que tem o executável **e** o
        `uninstall.sh` que nós mesmos escrevemos.

        De quebra, exigir o `uninstall.sh` impede mexer numa instalação feita
        pelo `.deb`: lá a remoção é do dpkg, e apagar os arquivos por fora
        deixaria o pacote registrado como instalado sem os arquivos.
        """
        if not path.is_dir():
            return False
        return (path / APP_EXE).is_file() and (path / "uninstall.sh").is_file()

    def _previous_install_dirs(self, new_dir: Path) -> list[Path]:
        """Instalações anteriores que estejam fora da pasta de destino.

        A versão antiga não está necessariamente onde a nova vai: o usuário
        pode ter trocado a pasta no assistente, ou instalado antes como root
        (`/opt`) e agora como usuário comum (`~/.local/share`). Sem procurar,
        a cópia velha fica no disco com atalho e tudo, e o usuário termina com
        duas versões instaladas sem saber qual delas abriu.

        As pistas são o que o próprio instalador escreveu na vez anterior: o
        `Exec=` do atalho de menu e o alvo do symlink no PATH.
        """
        candidates: set[Path] = set()

        entries = [self.targets.applications_dir / f"{APP_ID}.desktop"]
        desktop_dir = self._user_desktop_dir()
        if desktop_dir is not None:
            entries.append(desktop_dir / f"{APP_ID}.desktop")
        for entry in entries:
            try:
                content = entry.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in content.splitlines():
                if not line.startswith("Exec="):
                    continue
                target = line.removeprefix("Exec=").removesuffix(" %U").strip().strip('"')
                if target:
                    candidates.add(Path(target).parent)

        link = self.targets.bin_dir / APP_EXE
        if link.is_symlink():
            try:
                candidates.add(Path(os.readlink(link)).resolve().parent)
            except OSError:
                pass

        found = []
        for candidate in sorted(candidates):
            if candidate == new_dir or not self._looks_like_our_install(candidate):
                continue
            found.append(candidate)
        return found

    def _write_uninstaller(self, install_dir: Path, created: list[Path]) -> Path:
        """Gera um script que desfaz exatamente o que foi criado agora."""
        lines = [
            "#!/usr/bin/env bash",
            "# Desinstalador gerado automaticamente pelo instalador do",
            f"# {APP_NAME}. Remove apenas os arquivos do programa — sua sessão",
            "# do Telegram e suas preferências NÃO são apagadas (ficam em",
            "# ~/.config/telegram-jellyfin-organizer).",
            "set -u",
            "",
            'echo "Removendo ' + APP_NAME + '..."',
            "",
        ]
        for path in created:
            lines.append(f'rm -f "{path}"')
        lines += [
            f'rm -rf "{install_dir}"',
            "",
            "if command -v update-desktop-database >/dev/null 2>&1; then",
            f'  update-desktop-database "{self.targets.applications_dir}" >/dev/null 2>&1 || true',
            "fi",
            "",
            'echo "Pronto. Para apagar também as credenciais e preferências:"',
            'echo "  rm -rf ~/.config/' + APP_ID + '"',
        ]
        script = install_dir / "uninstall.sh"
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return script

    # -- execução ---------------------------------------------------------
    def run(self) -> None:
        try:
            self._install()
        except PermissionError as exc:
            self.finished.emit(
                False,
                f"Sem permissão de escrita em {exc.filename or self.options.install_dir}.\n"
                "Escolha outra pasta ou execute o instalador como administrador.",
            )
        except OSError as exc:
            self.finished.emit(False, f"Falha ao instalar: {exc}")

    def _install(self) -> None:
        install_dir = self.options.install_dir
        files = self._files_to_copy()
        total = max(len(files), 1)

        # Procura a versão antiga ANTES de mexer em qualquer coisa: as pistas
        # (symlink do PATH) apontam para dentro das pastas que vamos apagar.
        elsewhere = self._previous_install_dirs(install_dir)

        # Instalação por cima de uma versão anterior: limpa antes para não
        # deixar arquivos órfãos de uma release velha.
        if install_dir.exists() and (install_dir / APP_EXE).exists():
            self.progress.emit(0, "Removendo a versão anterior...")
            shutil.rmtree(install_dir, ignore_errors=True)

        for old_dir in elsewhere:
            self.progress.emit(0, f"Removendo a versão anterior em {old_dir}...")
            shutil.rmtree(old_dir, ignore_errors=True)

        install_dir.mkdir(parents=True, exist_ok=True)

        for index, src in enumerate(files, start=1):
            rel = src.relative_to(self.source)
            dest = install_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest, follow_symlinks=False)
            self.progress.emit(int(index / total * 88), f"Copiando {rel}")

        exec_path = install_dir / APP_EXE
        if exec_path.exists():
            exec_path.chmod(exec_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        created: list[Path] = []

        # Ícone no tema hicolor; se não der, o .desktop aponta pro caminho absoluto.
        self.progress.emit(90, "Instalando o ícone...")
        icon_name = str(install_dir / "packaging" / "assets" / "icon.png")
        source_icon = install_dir / "packaging" / "assets" / "icon.png"
        if source_icon.exists():
            try:
                icon_dest = self.targets.icons_dir / "256x256" / "apps" / f"{APP_ID}.png"
                icon_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_icon, icon_dest)
                created.append(icon_dest)
                icon_name = APP_ID
            except OSError:
                pass  # mantém o caminho absoluto como ícone

        if self.options.menu_shortcut:
            self.progress.emit(93, "Criando o atalho no menu...")
            self.targets.applications_dir.mkdir(parents=True, exist_ok=True)
            entry = self.targets.applications_dir / f"{APP_ID}.desktop"
            entry.write_text(self._desktop_entry(exec_path, icon_name), encoding="utf-8")
            entry.chmod(entry.stat().st_mode | stat.S_IXUSR)
            created.append(entry)

        if self.options.desktop_shortcut:
            self.progress.emit(95, "Criando o atalho na área de trabalho...")
            desktop = self._user_desktop_dir()
            if desktop is not None:
                desktop.mkdir(parents=True, exist_ok=True)
                link = desktop / f"{APP_ID}.desktop"
                link.write_text(self._desktop_entry(exec_path, icon_name), encoding="utf-8")
                link.chmod(link.stat().st_mode | stat.S_IXUSR)
                # GNOME exige que o lançador seja marcado como confiável.
                run_optional(["gio", "set", str(link), "metadata::trusted", "true"])
                created.append(link)

        if self.options.path_symlink:
            self.progress.emit(97, "Adicionando o comando ao PATH...")
            try:
                self.targets.bin_dir.mkdir(parents=True, exist_ok=True)
                link = self.targets.bin_dir / APP_EXE
                if link.exists() or link.is_symlink():
                    link.unlink()
                link.symlink_to(exec_path)
                created.append(link)
            except OSError:
                pass  # atalho de conveniência; não é motivo para falhar a instalação

        self.progress.emit(98, "Gerando o desinstalador...")
        self._write_uninstaller(install_dir, created)

        run_optional(["update-desktop-database", str(self.targets.applications_dir)])

        self.progress.emit(100, "Instalação concluída.")
        self.finished.emit(True, str(exec_path))

    @staticmethod
    def _user_desktop_dir() -> Path | None:
        """Respeita o nome localizado da Área de Trabalho (xdg-user-dirs)."""
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
        except (FileNotFoundError, OSError):
            pass
        fallback = Path.home() / "Desktop"
        return fallback if fallback.exists() else None


# ----------------------------------------------------------------------------
# Páginas do assistente
# ----------------------------------------------------------------------------

class WelcomePage(QWizardPage):
    def __init__(self, targets: Targets) -> None:
        super().__init__()
        self.setTitle(" ")
        watermark = QPixmap(str(asset("wizard_side.png")))
        if not watermark.isNull():
            self.setPixmap(QWizard.WizardPixmap.WatermarkPixmap, watermark)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 24)
        layout.setSpacing(14)

        heading = QLabel(f"Bem-vindo ao instalador do\n{APP_NAME}")
        font = QFont()
        font.setPointSize(15)
        font.setBold(True)
        heading.setFont(font)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        body = QLabel(
            f"{DESCRIPTION}.\n\n"
            "Este assistente vai guiar você pela instalação. Nada é enviado "
            "para a internet durante o processo e não é preciso ser "
            "administrador — por padrão o programa é instalado na sua pasta "
            "pessoal.\n\n"
            "Clique em Próximo para continuar."
        )
        body.setWordWrap(True)
        body.setObjectName("subtitle")
        layout.addWidget(body)

        if targets.system_wide:
            note = QLabel(
                "Executando como root: a instalação será feita para todos os "
                "usuários do sistema."
            )
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {BRASS};")
            layout.addWidget(note)

        layout.addStretch(1)


class LicensePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Contrato de licença")
        self.setSubTitle("Leia os termos antes de continuar.")

        layout = QVBoxLayout(self)
        view = QTextBrowser()
        view.setPlainText(license_text())
        layout.addWidget(view)

        self.accept_box = QCheckBox("Eu aceito os termos da licença")
        layout.addWidget(self.accept_box)

        # O botão Próximo só habilita com a caixa marcada.
        self.registerField("licenseAccepted*", self.accept_box)
        self.accept_box.toggled.connect(self.completeChanged)

    def isComplete(self) -> bool:
        return self.accept_box.isChecked()


class DestinationPage(QWizardPage):
    def __init__(self, targets: Targets, payload_size: int) -> None:
        super().__init__()
        self.targets = targets
        self.payload_size = payload_size
        self.setTitle("Pasta de destino")
        self.setSubTitle("Escolha onde o programa será instalado.")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        row = QHBoxLayout()
        self.path_edit = QLineEdit(str(targets.install_dir))
        browse = QPushButton("Procurar...")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        self.space_label = QLabel()
        self.space_label.setObjectName("subtitle")
        self.space_label.setWordWrap(True)
        layout.addWidget(self.space_label)

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(f"color: {BRASS};")
        layout.addWidget(self.warning_label)

        layout.addStretch(1)

        self.registerField("installDir", self.path_edit)
        self.path_edit.textChanged.connect(self._refresh)
        self._refresh()

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Escolha a pasta de instalação", str(Path.home())
        )
        if chosen:
            # Evita instalar solto dentro de uma pasta cheia de outras coisas.
            target = Path(chosen)
            if target.name != APP_ID:
                target = target / APP_ID
            self.path_edit.setText(str(target))

    def _refresh(self) -> None:
        target = Path(self.path_edit.text()).expanduser()
        required = self.payload_size / (1024 * 1024)

        probe = target
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            free = shutil.disk_usage(probe).free / (1024 * 1024)
            self.space_label.setText(
                f"Espaço necessário: {required:,.0f} MB  ·  "
                f"Disponível em {probe}: {free:,.0f} MB".replace(",", ".")
            )
            enough = free > required * 1.1
        except OSError:
            self.space_label.setText(f"Espaço necessário: {required:,.0f} MB")
            enough = True

        messages = []
        if not enough:
            messages.append("Espaço em disco insuficiente nessa pasta.")
        if target.exists() and (target / APP_EXE).exists():
            messages.append(
                "Já existe uma instalação aqui — ela será substituída por esta versão."
            )
        if not os.access(probe, os.W_OK):
            messages.append(f"Sem permissão de escrita em {probe}.")
        self.warning_label.setText("\n".join(messages))

    def validatePage(self) -> bool:
        text = self.path_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "Pasta inválida", "Informe uma pasta de instalação.")
            return False
        return True


class OptionsPage(QWizardPage):
    def __init__(self, targets: Targets) -> None:
        super().__init__()
        self.setTitle("Atalhos")
        self.setSubTitle("Escolha como você quer abrir o programa depois.")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.menu_box = QCheckBox("Criar atalho no menu de aplicativos")
        self.menu_box.setChecked(True)
        self.desktop_box = QCheckBox("Criar atalho na área de trabalho")
        self.path_box = QCheckBox(
            f"Permitir abrir pelo terminal com o comando '{APP_EXE}'"
        )
        self.path_box.setChecked(True)

        for box in (self.menu_box, self.desktop_box, self.path_box):
            layout.addWidget(box)

        hint = QLabel(
            f"O comando do terminal é um link em {targets.bin_dir}. "
            "Se essa pasta não estiver no seu PATH, o atalho do menu continua "
            "funcionando normalmente."
        )
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        layout.addSpacing(6)
        layout.addWidget(hint)
        layout.addStretch(1)

        self.registerField("menuShortcut", self.menu_box)
        self.registerField("desktopShortcut", self.desktop_box)
        self.registerField("pathSymlink", self.path_box)


class InstallPage(QWizardPage):
    """Página que efetivamente copia os arquivos (bloqueia Voltar/Próximo)."""

    def __init__(self, source: Path, targets: Targets) -> None:
        super().__init__()
        self.source = source
        self.targets = targets
        self.thread: QThread | None = None
        self.worker: InstallWorker | None = None
        self._done = False
        self._error = ""
        self.exec_path = ""

        self.setTitle("Instalando")
        self.setSubTitle("Aguarde enquanto os arquivos são copiados.")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar)

        self.status = QLabel("Preparando...")
        self.status.setObjectName("subtitle")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        layout.addStretch(1)

    def initializePage(self) -> None:
        options = Options(
            install_dir=Path(self.field("installDir")).expanduser(),
            menu_shortcut=bool(self.field("menuShortcut")),
            desktop_shortcut=bool(self.field("desktopShortcut")),
            path_symlink=bool(self.field("pathSymlink")),
        )
        wizard = self.wizard()
        wizard.button(QWizard.WizardButton.BackButton).setEnabled(False)
        wizard.button(QWizard.WizardButton.CancelButton).setEnabled(False)

        self.thread = QThread(self)
        self.worker = InstallWorker(self.source, options, self.targets)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.thread.start()

    def _on_progress(self, percent: int, message: str) -> None:
        self.bar.setValue(percent)
        self.status.setText(message)

    def _on_finished(self, ok: bool, detail: str) -> None:
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
        self._done = True
        wizard = self.wizard()
        wizard.button(QWizard.WizardButton.CancelButton).setEnabled(True)
        if ok:
            self.exec_path = detail
            self.status.setText("Todos os arquivos foram copiados com sucesso.")
            wizard.installed_path = detail
            self.completeChanged.emit()
            # Avança sozinho: não faz sentido pedir "Próximo" depois do 100%.
            wizard.next()
        else:
            self._error = detail
            self.bar.setValue(0)
            self.status.setText(detail)
            self.status.setStyleSheet("color: #D96C6C;")
            self.completeChanged.emit()
            QMessageBox.critical(self, "Falha na instalação", detail)

    def isComplete(self) -> bool:
        return self._done and not self._error


class FinishPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle(" ")
        watermark = QPixmap(str(asset("wizard_side.png")))
        if not watermark.isNull():
            self.setPixmap(QWizard.WizardPixmap.WatermarkPixmap, watermark)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 24)
        layout.setSpacing(14)

        heading = QLabel("Instalação concluída")
        font = QFont()
        font.setPointSize(15)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setObjectName("subtitle")
        layout.addWidget(self.detail)

        self.run_box = QCheckBox(f"Executar o {APP_NAME} agora")
        self.run_box.setChecked(True)
        layout.addWidget(self.run_box)
        layout.addStretch(1)

        self.registerField("runNow", self.run_box)

    def initializePage(self) -> None:
        install_dir = Path(self.field("installDir")).expanduser()
        self.detail.setText(
            f"O {APP_NAME} foi instalado em:\n{install_dir}\n\n"
            "Na primeira execução você vai informar seu api_id e api_hash do "
            "Telegram (obtidos em my.telegram.org/apps). Depois disso o login "
            "fica salvo.\n\n"
            f"Para desinstalar, execute:\n{install_dir / 'uninstall.sh'}"
        )


class InstallerWizard(QWizard):
    def __init__(self, source: Path, targets: Targets) -> None:
        super().__init__()
        self.installed_path = ""
        self.setWindowTitle(f"Instalar {APP_NAME}")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.NoCancelButtonOnLastPage, True)
        self.setMinimumSize(640, 460)

        self.setButtonText(QWizard.WizardButton.NextButton, "Próximo >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Voltar")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Cancelar")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Concluir")

        logo = QPixmap(str(asset("icon.png")))
        if not logo.isNull():
            self.setPixmap(
                QWizard.WizardPixmap.LogoPixmap,
                logo.scaled(
                    48,
                    48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )

        payload_size = sum(p.stat().st_size for p in source.rglob("*") if p.is_file())

        self.addPage(WelcomePage(targets))
        self.addPage(LicensePage())
        self.addPage(DestinationPage(targets, payload_size))
        self.addPage(OptionsPage(targets))
        self.addPage(InstallPage(source, targets))
        self.addPage(FinishPage())


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Instalador do {APP_NAME}")
    parser.add_argument(
        "--payload",
        help="Pasta do bundle a instalar (apenas para testar fora do .run)",
    )
    args = parser.parse_args()

    source = payload_dir(args.payload)

    app = QApplication(sys.argv)
    app.setApplicationName(f"Instalador do {APP_NAME}")
    app.setStyleSheet(STYLESHEET)

    icon_path = asset("icon.png")
    if icon_path.exists():
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(str(icon_path)))

    targets = Targets.detect()
    wizard = InstallerWizard(source, targets)
    wizard.show()
    result = wizard.exec()

    if result == QWizard.DialogCode.Accepted and wizard.field("runNow"):
        exec_path = wizard.installed_path
        if exec_path and Path(exec_path).exists():
            subprocess.Popen(
                [exec_path],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
