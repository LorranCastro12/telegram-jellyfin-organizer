"""Janela principal da aplicação.

Responsável por orquestrar a comunicação entre o `TelegramWorker` (core) e
os widgets da interface. Nenhuma lógica de rede/parsing mora aqui — esta
classe só conecta sinais e delega para os componentes certos.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.settings import SettingsManager
from core.credentials import CredentialStore
from core.models import DownloadStatus, DownloadTask, MediaFile, ParsedMediaInfo, TelegramGroup
from core.telegram_client import TelegramWorker
from ui.login_dialog import LoginDialog
from ui.settings_dialog import SettingsDialog
from ui.widgets.download_queue import DownloadQueueWidget
from ui.widgets.group_list import GroupListWidget
from ui.widgets.media_list import MediaListWidget
from ui.widgets.organize_panel import OrganizePanel
from ui.widgets.stats_panel import StatsPanel

logger = logging.getLogger(__name__)

NAV_GRUPOS, NAV_DOWNLOADS, NAV_STATS, NAV_SETTINGS = range(4)


class MainWindow(QMainWindow):
    def __init__(self, credential_store: CredentialStore, settings_manager: SettingsManager):
        super().__init__()
        self.setWindowTitle("Telegram → Jellyfin Organizer")
        self.resize(1280, 800)

        self.credential_store = credential_store
        self.settings_manager = settings_manager
        self.settings = settings_manager.load()

        self.current_group: TelegramGroup | None = None
        self._load_more_offset = 0
        # Maior message_id já carregado do grupo aberto: ponto de partida da
        # busca incremental do botão "Atualizar".
        self._newest_message_id = 0

        self.telegram_worker = TelegramWorker(self.credential_store.session_path)
        self._connect_worker_signals()
        self.telegram_worker.set_max_concurrent_downloads(self.settings.max_concurrent_downloads)
        self.telegram_worker.start()

        self._build_ui()
        self.organize_panel.set_library_roots(self.settings.library_paths())

        self.login_dialog: LoginDialog | None = None
        self._start_authentication()

    # ------------------------------------------------------------------
    # Construção da UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralArea")
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_groups_page())
        self.pages.addWidget(self._build_downloads_page())
        self.pages.addWidget(self._build_stats_page())
        root_layout.addWidget(self.pages, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Conectando ao Telegram...")

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("JELLYFIN ORGANIZER")
        title.setObjectName("appTitle")
        font = title.font()
        font.setBold(True)
        font.setPointSize(13)
        font.setLetterSpacing(QFont.PercentageSpacing, 105)
        title.setFont(font)
        layout.addWidget(title)

        subtitle = QLabel("baixe do Telegram, organize no padrão certo")
        subtitle.setObjectName("appSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.addItem(QListWidgetItem("Grupos"))
        self.nav_list.addItem(QListWidgetItem("Downloads"))
        self.nav_list.addItem(QListWidgetItem("Estatísticas"))
        self.nav_list.addItem(QListWidgetItem("Configurações"))
        self.nav_list.setCurrentRow(NAV_GRUPOS)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav_list, 1)

        return sidebar

    def _build_groups_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        splitter = QSplitter(Qt.Horizontal)

        self.group_list_widget = GroupListWidget()
        self.group_list_widget.group_selected.connect(self._on_group_selected)
        self.group_list_widget.pinned_changed.connect(self._on_pinned_groups_changed)
        self.group_list_widget.set_pinned_ids(self.settings.pinned_group_ids)
        splitter.addWidget(self.group_list_widget)

        right_splitter = QSplitter(Qt.Vertical)
        self.media_list_widget = MediaListWidget()
        self.media_list_widget.selection_changed.connect(self._on_media_selection_changed)
        self.media_list_widget.load_more_requested.connect(self._on_load_more_requested)
        self.media_list_widget.refresh_requested.connect(self._on_refresh_media_requested)
        right_splitter.addWidget(self.media_list_widget)

        self.organize_panel = OrganizePanel()
        self.organize_panel.queue_requested.connect(self._on_queue_requested)
        right_splitter.addWidget(self.organize_panel)
        right_splitter.setSizes([420, 280])

        splitter.addWidget(right_splitter)
        splitter.setSizes([300, 900])

        layout.addWidget(splitter)
        return page

    def _build_downloads_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        self.download_queue_widget = DownloadQueueWidget()
        self.download_queue_widget.cancel_requested.connect(self.telegram_worker.cancel_download)
        layout.addWidget(self.download_queue_widget)
        return page

    def _build_stats_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        self.stats_panel = StatsPanel()
        layout.addWidget(self.stats_panel)
        return page

    def _on_nav_changed(self, row: int) -> None:
        if row == NAV_SETTINGS:
            self._open_settings_dialog()
            self.nav_list.blockSignals(True)
            self.nav_list.setCurrentRow(NAV_GRUPOS if self.pages.currentIndex() == NAV_GRUPOS else self.pages.currentIndex())
            self.nav_list.blockSignals(False)
            return
        self.pages.setCurrentIndex(row)

    # ------------------------------------------------------------------
    # Autenticação
    # ------------------------------------------------------------------
    def _start_authentication(self) -> None:
        stored = self.credential_store.load_credentials()
        if stored and self.credential_store.has_active_session():
            self.statusBar().showMessage("Reconectando com sessão salva...")
            self.telegram_worker.auto_login(stored["api_id"], stored["api_hash"])
        else:
            self._show_login_dialog(prefill=stored)

    def _show_login_dialog(self, prefill=None) -> None:
        self.login_dialog = LoginDialog(self)
        if prefill:
            self.login_dialog.prefill(str(prefill["api_id"]), prefill["api_hash"], prefill["phone"])
        self.login_dialog.credentials_submitted.connect(self._on_credentials_submitted)
        self.login_dialog.code_submitted.connect(self.telegram_worker.submit_code)
        self.login_dialog.password_submitted.connect(self.telegram_worker.submit_password)
        self.login_dialog.exec()

    def _on_credentials_submitted(self, api_id: int, api_hash: str, phone: str) -> None:
        self.credential_store.save_credentials(api_id, api_hash, phone)
        self.telegram_worker.connect_and_login(api_id, api_hash, phone)

    def _connect_worker_signals(self) -> None:
        w = self.telegram_worker
        w.login_code_needed.connect(lambda: self.login_dialog and self.login_dialog.show_code_step())
        w.login_password_needed.connect(
            lambda: self.login_dialog and self.login_dialog.show_password_step()
        )
        w.login_success.connect(self._on_login_success)
        w.login_error.connect(self._on_login_error)
        w.dialogs_ready.connect(self._on_dialogs_ready)
        w.media_ready.connect(self._on_media_ready)
        w.new_media_ready.connect(self._on_new_media_ready)
        w.new_media_error.connect(self._on_new_media_error)
        w.download_progress.connect(self._on_download_progress)
        w.download_status_changed.connect(self._on_download_status_changed)
        w.download_completed.connect(self._on_download_completed)
        w.download_error.connect(self._on_download_error)
        w.status_message.connect(lambda msg: self.statusBar().showMessage(msg, 6000))

    def _on_login_success(self) -> None:
        if self.login_dialog:
            self.login_dialog.accept()
            self.login_dialog = None
        self.statusBar().showMessage("Conectado ao Telegram.", 4000)
        self.telegram_worker.list_dialogs()

    def _on_login_error(self, message: str) -> None:
        if self.login_dialog:
            self.login_dialog.show_error(message)
        else:
            self.statusBar().showMessage(f"Erro de conexão: {message}", 8000)
            self._show_login_dialog()

    # ------------------------------------------------------------------
    # Navegação de grupos e arquivos
    # ------------------------------------------------------------------
    def _on_dialogs_ready(self, groups: list[TelegramGroup]) -> None:
        self.group_list_widget.set_groups(groups)
        self.statusBar().showMessage(f"{len(groups)} grupos/canais encontrados.", 4000)

    def _on_group_selected(self, group: TelegramGroup) -> None:
        self.current_group = group
        self._load_more_offset = 0
        self._newest_message_id = 0
        self.media_list_widget.set_refresh_enabled(True)
        self.statusBar().showMessage(f"Carregando arquivos de '{group.title}'...")
        self.telegram_worker.list_media(group.id, limit=100, offset_id=0)

    def _on_pinned_groups_changed(self, group_ids: list[int]) -> None:
        # Salva na hora: fixar é uma ação pequena e o usuário não espera ter
        # que confirmar nada em Configurações para ela sobreviver ao restart.
        self.settings.pinned_group_ids = list(group_ids)
        self.settings_manager.save(self.settings)

    def _on_media_ready(self, files: list[MediaFile], has_more: bool) -> None:
        # Resposta atrasada de um grupo que o usuário já trocou: descarta.
        # Sem esta guarda, pedir "Carregar mais" e clicar em outro grupo antes
        # da resposta chegar misturava os arquivos dos dois grupos na mesma
        # lista — a página que volta é anexada à listagem do grupo novo.
        if files and self.current_group and files[0].group_id != self.current_group.id:
            logger.debug(
                "Ignorando %d arquivos do grupo %s; o grupo aberto agora é %s.",
                len(files),
                files[0].group_id,
                self.current_group.id,
            )
            return

        if self._load_more_offset == 0:
            self.media_list_widget.set_files(files)
        else:
            self.media_list_widget.append_files(files)
        if files:
            self._load_more_offset = files[-1].message_id
            self._newest_message_id = max(
                [self._newest_message_id] + [f.message_id for f in files]
            )
        self.statusBar().showMessage(f"{len(files)} arquivos carregados.", 4000)

    def _on_load_more_requested(self) -> None:
        if self.current_group and self._load_more_offset:
            self.telegram_worker.list_media(
                self.current_group.id, limit=100, offset_id=self._load_more_offset
            )

    def _on_refresh_media_requested(self) -> None:
        """Rebusca o grupo aberto: só o que chegou depois do que já está em tela.

        Sem nenhum arquivo carregado ainda (grupo vazio, ou a primeira
        listagem falhou), não há referência para a busca incremental — aí o
        caminho certo é recarregar a primeira página inteira.
        """
        if not self.current_group:
            return
        if not self._newest_message_id:
            self._load_more_offset = 0
            self.statusBar().showMessage(
                f"Recarregando arquivos de '{self.current_group.title}'..."
            )
            self.telegram_worker.list_media(self.current_group.id, limit=100, offset_id=0)
            return

        self.media_list_widget.set_refreshing(True)
        self.statusBar().showMessage("Buscando arquivos novos no grupo...")
        self.telegram_worker.check_new_media(
            self.current_group.id, after_message_id=self._newest_message_id
        )

    def _on_new_media_ready(self, files: list[MediaFile], truncated: bool) -> None:
        self.media_list_widget.set_refreshing(False)
        added = self.media_list_widget.prepend_new_files(files)
        if files:
            self._newest_message_id = max(
                [self._newest_message_id] + [f.message_id for f in files]
            )

        if not added:
            self.statusBar().showMessage("Nenhum arquivo novo no grupo.", 4000)
        elif truncated:
            self.statusBar().showMessage(
                f"{len(added)} arquivo(s) novo(s) no topo da lista — pode haver mais: "
                "selecione o grupo novamente para recarregar tudo.",
                10000,
            )
        else:
            self.statusBar().showMessage(
                f"{len(added)} arquivo(s) novo(s) no topo da lista.", 6000
            )

    def _on_new_media_error(self, message: str) -> None:
        self.media_list_widget.set_refreshing(False)
        self.statusBar().showMessage(f"Erro ao atualizar a lista: {message}", 8000)

    def _on_media_selection_changed(self, files: list[MediaFile]) -> None:
        self.organize_panel.set_selected_files(files)

    # ------------------------------------------------------------------
    # Downloads
    # ------------------------------------------------------------------
    def _on_queue_requested(self, entries: list[tuple[MediaFile, ParsedMediaInfo, Path]]) -> None:
        for media_file, _info, destination in entries:
            task = DownloadTask(media_file=media_file, destination_path=destination)
            self.download_queue_widget.add_task(task)
            self.telegram_worker.queue_download(task)
        self.pages.setCurrentIndex(NAV_DOWNLOADS)
        self.nav_list.setCurrentRow(NAV_DOWNLOADS)
        self.statusBar().showMessage(f"{len(entries)} arquivo(s) adicionados à fila.", 4000)

    def _on_download_progress(self, task_id: str, current: int, total: int, speed: float) -> None:
        self.download_queue_widget.update_progress(task_id, current, total, speed)
        self.stats_panel.on_progress(task_id, current, total, speed)

    def _on_download_status_changed(self, task_id: str, status: DownloadStatus) -> None:
        self.download_queue_widget.update_status(task_id, status)
        if status in (DownloadStatus.CANCELLED, DownloadStatus.ERROR):
            self.stats_panel.on_task_removed(task_id)

    def _on_download_completed(self, task_id: str, path: str) -> None:
        row = self.download_queue_widget.model.task_row(task_id)
        bytes_total = 0
        if row is not None:
            bytes_total = self.download_queue_widget.model.task_at(row).bytes_total
        self.stats_panel.on_task_finished(task_id, bytes_total)
        self.statusBar().showMessage(f"Download concluído: {path}", 6000)

    def _on_download_error(self, task_id: str, message: str) -> None:
        self.statusBar().showMessage(f"Erro no download: {message}", 8000)

    # ------------------------------------------------------------------
    # Configurações
    # ------------------------------------------------------------------
    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        dialog.logout_requested.connect(self._on_logout_requested)
        if dialog.exec():
            self.settings = dialog.updated_settings()
            self.settings_manager.save(self.settings)
            self.organize_panel.set_library_roots(self.settings.library_paths())
            self.telegram_worker.set_max_concurrent_downloads(self.settings.max_concurrent_downloads)

    def _on_logout_requested(self) -> None:
        self.credential_store.clear(remove_session=True)
        QMessageBox.information(
            self,
            "Sessão encerrada",
            "Credenciais removidas. Feche e abra o aplicativo novamente para fazer login "
            "com outra conta.",
        )

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        self.telegram_worker.shutdown()
        super().closeEvent(event)
