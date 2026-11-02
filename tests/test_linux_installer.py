"""Testes da lógica de instalação do assistente gráfico do Linux.

O assistente só pode ser exercitado de ponta a ponta clicando nos botões, mas
a parte que de fato pode quebrar o computador do usuário — copiar arquivos,
escrever atalhos, criar o desinstalador — mora em `InstallWorker`, que é um
`QObject` puro, sem janela. É isso que este módulo cobre, com destinos
redirecionados para um `tmp_path` em vez do `$HOME` real.

Erros que estes testes pegam e que só apareceriam na máquina do usuário: o
desinstalador apagando o diretório errado, o `.desktop` apontando para um
executável inexistente, e a reinstalação por cima deixando arquivos órfãos de
uma versão anterior.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WIZARD_PATH = PROJECT_ROOT / "packaging" / "linux" / "installer_wizard.py"

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="o assistente .run é específico de Linux",
)


def _load_wizard_module():
    """Carrega o assistente por caminho — `packaging/` não é um pacote.

    O registro em `sys.modules` antes do `exec_module` não é opcional:
    `@dataclass` resolve as anotações consultando `sys.modules[cls.__module__]`
    e estoura com AttributeError se o módulo ainda não estiver lá.
    """
    spec = importlib.util.spec_from_file_location("installer_wizard", WIZARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def wizard(qt_app):  # qt_app garante QApplication antes de tocar em QtWidgets
    return _load_wizard_module()


@pytest.fixture(autouse=True)
def area_de_trabalho_isolada(wizard, tmp_path: Path, monkeypatch):
    """Redireciona a Área de Trabalho do usuário para um tmp_path.

    Não é cosmético: `_previous_install_dirs` lê o `.desktop` da Área de
    Trabalho para descobrir onde está a versão anterior, e `_install` remove o
    que encontra. Sem este redirecionamento, rodar a suíte numa máquina que
    tenha o programa instalado com atalho na Área de Trabalho apagaria a
    instalação de verdade do usuário. Autouse de propósito — vale para todo
    teste do módulo, inclusive os que ainda não existem.
    """
    fake_desktop = tmp_path / "area-de-trabalho"
    fake_desktop.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        wizard.InstallWorker, "_user_desktop_dir", staticmethod(lambda: fake_desktop)
    )
    return fake_desktop


@pytest.fixture
def fake_payload(tmp_path: Path) -> Path:
    """Imita o layout do bundle do PyInstaller, sem os 222 MB de Qt."""
    source = tmp_path / "payload"
    (source / "_internal" / "ui" / "styles").mkdir(parents=True)
    (source / "packaging" / "assets").mkdir(parents=True)

    app_exe = source / "telegram-jellyfin-organizer"
    app_exe.write_text("#!/bin/sh\necho app\n", encoding="utf-8")
    app_exe.chmod(0o755)

    installer_exe = source / "install"
    installer_exe.write_text("#!/bin/sh\necho installer\n", encoding="utf-8")
    installer_exe.chmod(0o755)

    (source / "_internal" / "ui" / "styles" / "dark_theme.qss").write_text("QWidget {}", encoding="utf-8")
    (source / "packaging" / "assets" / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return source


@pytest.fixture
def targets(wizard, tmp_path: Path):
    """Destinos isolados: nada escapa para o $HOME de quem roda os testes."""
    return wizard.Targets(
        install_dir=tmp_path / "opt" / "telegram-jellyfin-organizer",
        applications_dir=tmp_path / "share" / "applications",
        icons_dir=tmp_path / "share" / "icons" / "hicolor",
        bin_dir=tmp_path / "bin",
        system_wide=False,
    )


def _run(wizard, source: Path, targets, **option_kwargs):
    install_dir = option_kwargs.pop("install_dir", targets.install_dir)
    options = wizard.Options(install_dir=install_dir, **option_kwargs)
    worker = wizard.InstallWorker(source, options, targets)
    results: list[tuple[bool, str]] = []
    worker.finished.connect(lambda ok, detail: results.append((ok, detail)))
    worker.run()
    assert results, "o worker terminou sem emitir o sinal finished"
    return results[0]


def test_instala_arquivos_e_marca_o_executavel(wizard, fake_payload, targets):
    ok, detail = _run(wizard, fake_payload, targets)

    assert ok, detail
    installed = targets.install_dir / "telegram-jellyfin-organizer"
    assert installed.exists()
    assert os.access(installed, os.X_OK), "o app precisa ficar executável"
    assert (targets.install_dir / "_internal" / "ui" / "styles" / "dark_theme.qss").exists()
    assert detail == str(installed)


def test_nao_copia_o_proprio_assistente(wizard, fake_payload, targets):
    """O `install` serve para instalar; dentro da pasta instalada é lixo."""
    _run(wizard, fake_payload, targets)
    assert not (targets.install_dir / "install").exists()


def test_atalho_do_menu_aponta_para_o_executavel_instalado(wizard, fake_payload, targets):
    _run(wizard, fake_payload, targets, menu_shortcut=True)

    entry = targets.applications_dir / "telegram-jellyfin-organizer.desktop"
    assert entry.exists()
    content = entry.read_text(encoding="utf-8")
    exec_line = next(line for line in content.splitlines() if line.startswith("Exec="))
    referenced = exec_line.removeprefix("Exec=").removesuffix(" %U").strip('"')
    assert Path(referenced).exists(), "o .desktop aponta para um caminho inexistente"
    assert "Type=Application" in content
    assert "StartupWMClass=telegram-jellyfin-organizer" in content


def test_sem_atalho_quando_desmarcado(wizard, fake_payload, targets):
    _run(wizard, fake_payload, targets, menu_shortcut=False, path_symlink=False)
    assert not (targets.applications_dir / "telegram-jellyfin-organizer.desktop").exists()
    assert not (targets.bin_dir / "telegram-jellyfin-organizer").exists()


def test_symlink_do_path_resolve_para_o_app(wizard, fake_payload, targets):
    _run(wizard, fake_payload, targets, path_symlink=True)

    link = targets.bin_dir / "telegram-jellyfin-organizer"
    assert link.is_symlink()
    assert link.resolve() == (targets.install_dir / "telegram-jellyfin-organizer").resolve()


def test_icone_vai_para_o_tema_hicolor(wizard, fake_payload, targets):
    _run(wizard, fake_payload, targets)
    icon = targets.icons_dir / "256x256" / "apps" / "telegram-jellyfin-organizer.png"
    assert icon.exists()


def test_desinstalador_e_executavel_e_remove_o_que_foi_criado(wizard, fake_payload, targets):
    _run(wizard, fake_payload, targets, menu_shortcut=True, path_symlink=True)

    script = targets.install_dir / "uninstall.sh"
    assert script.exists()
    assert script.stat().st_mode & stat.S_IXUSR

    body = script.read_text(encoding="utf-8")
    assert f'rm -rf "{targets.install_dir}"' in body
    assert str(targets.applications_dir / "telegram-jellyfin-organizer.desktop") in body
    assert str(targets.bin_dir / "telegram-jellyfin-organizer") in body

    # A sessão do Telegram e as credenciais jamais podem entrar num `rm`
    # automático — desinstalar o programa não é pedir para deslogar. O script
    # só pode *mencionar* ~/.config dentro de um `echo` instrutivo.
    removals = [line for line in body.splitlines() if line.startswith("rm ")]
    assert removals, "o desinstalador não remove nada"
    assert not any(".config" in line for line in removals)


def test_reinstalar_por_cima_nao_deixa_arquivo_orfao(wizard, fake_payload, targets):
    _run(wizard, fake_payload, targets)
    orphan = targets.install_dir / "_internal" / "arquivo_de_versao_antiga.so"
    orphan.write_text("sobra da versão anterior", encoding="utf-8")

    ok, detail = _run(wizard, fake_payload, targets)

    assert ok, detail
    assert not orphan.exists(), "a versão anterior deveria ter sido limpa antes de copiar"
    assert (targets.install_dir / "telegram-jellyfin-organizer").exists()


def test_erro_de_permissao_vira_mensagem_amigavel(wizard, fake_payload, targets, tmp_path):
    locked = tmp_path / "somente-leitura"
    locked.mkdir()
    locked.chmod(0o500)
    blocked = wizard.Targets(
        install_dir=locked / "app",
        applications_dir=targets.applications_dir,
        icons_dir=targets.icons_dir,
        bin_dir=targets.bin_dir,
        system_wide=False,
    )
    try:
        ok, detail = _run(wizard, fake_payload, blocked)
        assert not ok
        assert "permissão" in detail.lower()
    finally:
        locked.chmod(0o700)  # senão o tmp_path não é removível


def test_instala_em_sistema_sem_utilitarios_de_desktop(
    wizard, fake_payload, targets, monkeypatch
):
    """Distro enxuta, sem `update-desktop-database`/`gio`/`xdg-user-dir`.

    Regressão: `subprocess.run(..., check=False)` não cobre binário ausente —
    `check=False` só silencia código de saída, enquanto o executável
    inexistente levanta FileNotFoundError. O resultado era a instalação
    abortar com "Falha ao instalar" *depois* de já ter copiado tudo.
    """
    sem_utilitarios = targets.install_dir.parent / "path-vazio"
    sem_utilitarios.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PATH", str(sem_utilitarios))

    ok, detail = _run(
        wizard, fake_payload, targets, menu_shortcut=True, desktop_shortcut=True
    )

    assert ok, detail
    assert (targets.install_dir / "telegram-jellyfin-organizer").exists()
    assert (targets.applications_dir / "telegram-jellyfin-organizer.desktop").exists()


def test_run_optional_tolera_comando_inexistente(wizard):
    assert wizard.run_optional(["este-binario-nao-existe-em-lugar-nenhum"]) is False
    assert wizard.run_optional(["true"]) is True
    assert wizard.run_optional(["false"]) is False


def test_targets_padrao_respeitam_xdg_data_home(wizard, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(wizard.os, "geteuid", lambda: 1000)

    detected = wizard.Targets.detect()

    assert detected.install_dir == tmp_path / "xdg" / "telegram-jellyfin-organizer"
    assert not detected.system_wide


def test_como_root_instala_para_todo_o_sistema(wizard, monkeypatch):
    monkeypatch.setattr(wizard.os, "geteuid", lambda: 0)

    detected = wizard.Targets.detect()

    assert detected.install_dir == Path("/opt/telegram-jellyfin-organizer")
    assert detected.applications_dir == Path("/usr/share/applications")
    assert detected.system_wide


# ----------------------------------------------------------------------
# Atualizar deve excluir a versão anterior, inclusive em outra pasta
# ----------------------------------------------------------------------
def test_remove_instalacao_anterior_em_outra_pasta(
    wizard, fake_payload, targets, tmp_path
):
    """Trocar a pasta de instalação não pode deixar duas versões no disco.

    Instalar por cima já limpava a pasta de destino, mas a versão anterior
    pode estar em outro lugar — o usuário mudou a pasta no assistente, ou
    antes instalou como root em /opt e agora como usuário comum. A cópia velha
    ficava no disco, e o atalho do menu continuava apontando para ela.
    """
    antiga = targets.install_dir
    _run(wizard, fake_payload, targets, menu_shortcut=True, path_symlink=True)
    assert (antiga / "telegram-jellyfin-organizer").exists()

    nova = tmp_path / "outro-lugar" / "telegram-jellyfin-organizer"
    ok, detail = _run(
        wizard, fake_payload, targets, install_dir=nova, menu_shortcut=True
    )

    assert ok, detail
    assert (nova / "telegram-jellyfin-organizer").exists()
    assert not antiga.exists(), "a instalação anterior ficou para trás"


def test_atalho_passa_a_apontar_para_a_pasta_nova(wizard, fake_payload, targets, tmp_path):
    _run(wizard, fake_payload, targets, menu_shortcut=True)
    nova = tmp_path / "outro-lugar" / "telegram-jellyfin-organizer"

    _run(wizard, fake_payload, targets, install_dir=nova, menu_shortcut=True)

    entry = targets.applications_dir / "telegram-jellyfin-organizer.desktop"
    exec_line = next(
        line for line in entry.read_text(encoding="utf-8").splitlines()
        if line.startswith("Exec=")
    )
    assert str(nova) in exec_line
    assert Path(exec_line.removeprefix("Exec=").removesuffix(" %U").strip('"')).exists()


def test_nao_remove_pasta_sem_a_assinatura_da_instalacao(
    wizard, fake_payload, targets, tmp_path
):
    """A trava do `rm -rf` guiado por caminho lido de arquivo.

    O `.desktop` pode estar corrompido, editado à mão ou apontando para outro
    programa. Sem exigir a assinatura (executável + uninstall.sh), o alvo
    poderia ser qualquer pasta — inclusive o $HOME.
    """
    inocente = tmp_path / "documentos-importantes"
    inocente.mkdir()
    (inocente / "tese.odt").write_text("não me apague", encoding="utf-8")

    targets.applications_dir.mkdir(parents=True, exist_ok=True)
    (targets.applications_dir / "telegram-jellyfin-organizer.desktop").write_text(
        f'[Desktop Entry]\nType=Application\nExec="{inocente}/telegram-jellyfin-organizer" %U\n',
        encoding="utf-8",
    )

    ok, detail = _run(wizard, fake_payload, targets)

    assert ok, detail
    assert (inocente / "tese.odt").exists(), "apagou uma pasta que não era nossa"


def test_nao_mexe_em_instalacao_gerenciada_pelo_deb(
    wizard, fake_payload, targets, tmp_path
):
    """Instalação do .deb não tem uninstall.sh: a remoção é do dpkg.

    Apagar os arquivos por fora deixaria o pacote registrado como instalado
    sem os arquivos — um estado que só o usuário consegue desfazer à mão.
    """
    do_deb = tmp_path / "opt-deb" / "telegram-jellyfin-organizer"
    do_deb.mkdir(parents=True)
    (do_deb / "telegram-jellyfin-organizer").write_text("#!/bin/sh\n", encoding="utf-8")

    targets.applications_dir.mkdir(parents=True, exist_ok=True)
    (targets.applications_dir / "telegram-jellyfin-organizer.desktop").write_text(
        f'[Desktop Entry]\nType=Application\nExec="{do_deb}/telegram-jellyfin-organizer" %U\n',
        encoding="utf-8",
    )

    _run(wizard, fake_payload, targets)

    assert (do_deb / "telegram-jellyfin-organizer").exists()


def test_reinstalar_na_mesma_pasta_nao_se_autodestroi(wizard, fake_payload, targets):
    """A pasta de destino não pode entrar na lista de "instalações anteriores".

    Se entrasse, seria removida *depois* da cópia e a instalação terminaria
    com a pasta vazia, relatando sucesso.
    """
    _run(wizard, fake_payload, targets, menu_shortcut=True, path_symlink=True)
    ok, detail = _run(wizard, fake_payload, targets, menu_shortcut=True, path_symlink=True)

    assert ok, detail
    assert (targets.install_dir / "telegram-jellyfin-organizer").exists()
    assert (targets.install_dir / "uninstall.sh").exists()
