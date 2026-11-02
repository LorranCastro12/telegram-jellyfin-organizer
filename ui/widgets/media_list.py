"""Painel central: arquivos de mídia do grupo selecionado, com seleção via checkbox."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.models import MediaFile
from ui.models import MediaTableModel


class MediaListWidget(QWidget):
    selection_changed = Signal(list)  # list[MediaFile]
    load_more_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_files: List[MediaFile] = []
        self._known_ids: set[int] = set()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar arquivo...")
        self.search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_edit, 1)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Todos", "Vídeos", "Documentos"])
        self.type_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.type_combo)

        self.refresh_btn = QPushButton("⟳ Atualizar")
        self.refresh_btn.setToolTip(
            "Busca arquivos enviados ao grupo depois do último carregamento (F5)"
        )
        self.refresh_btn.setEnabled(False)  # habilita quando um grupo é aberto
        self.refresh_btn.clicked.connect(self._request_refresh)
        toolbar.addWidget(self.refresh_btn)

        # F5 é o reflexo de "atualizar a página"; o atalho respeita o mesmo
        # estado do botão para não disparar sem grupo aberto.
        self._refresh_shortcut = QShortcut(QKeySequence.Refresh, self)
        self._refresh_shortcut.activated.connect(self._request_refresh)

        self.select_all_btn = QPushButton("Marcar todos")
        self.select_all_btn.clicked.connect(lambda: self._toggle_all(True))
        toolbar.addWidget(self.select_all_btn)

        self.select_none_btn = QPushButton("Limpar seleção")
        self.select_none_btn.clicked.connect(lambda: self._toggle_all(False))
        toolbar.addWidget(self.select_none_btn)

        layout.addLayout(toolbar)

        self.model = MediaTableModel(self)
        self.model.dataChanged.connect(self._emit_selection)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 32)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 130)
        self.table.verticalHeader().setVisible(False)
        self.table.clicked.connect(self._toggle_row_checked)
        layout.addWidget(self.table, 1)

        self.load_more_btn = QPushButton("Carregar mais arquivos...")
        self.load_more_btn.clicked.connect(self.load_more_requested.emit)
        layout.addWidget(self.load_more_btn)

    def set_files(self, files: List[MediaFile]) -> None:
        self._all_files = list(files)
        self._known_ids = {f.message_id for f in files}
        self.model.set_files(files)

    def append_files(self, files: List[MediaFile]) -> None:
        self._all_files.extend(files)
        self._known_ids.update(f.message_id for f in files)
        self.model.append_files(files)

    def prepend_new_files(self, files: List[MediaFile]) -> List[MediaFile]:
        """Insere no topo os arquivos que ainda não estão na lista.

        Devolve só os que de fato eram novos — a MainWindow usa isso para
        relatar na barra de status. A deduplicação por `message_id` protege
        contra o caso de borda em que a mesma mensagem volta em duas
        checagens (e também de um duplo clique no botão).
        """
        new_files = [f for f in files if f.message_id not in self._known_ids]
        if not new_files:
            return []

        self._all_files[:0] = new_files
        self._known_ids.update(f.message_id for f in new_files)
        # Com filtro ativo, só entram na view os que casam com ele; os demais
        # ficam em `_all_files` e aparecem quando o filtro mudar. Assim o
        # "Atualizar" não precisa refazer a listagem — e a seleção em
        # andamento sobrevive.
        self.model.prepend_files([f for f in new_files if self._matches_filter(f)])
        self.table.scrollToTop()
        return new_files

    def set_refresh_enabled(self, enabled: bool) -> None:
        self.refresh_btn.setEnabled(enabled)

    def set_refreshing(self, refreshing: bool) -> None:
        """Trava o botão durante a consulta, para não empilhar requisições."""
        self.refresh_btn.setEnabled(not refreshing)
        self.refresh_btn.setText("⟳ Atualizando..." if refreshing else "⟳ Atualizar")

    def _request_refresh(self) -> None:
        if self.refresh_btn.isEnabled():
            self.refresh_requested.emit()

    def _matches_filter(self, media_file: MediaFile) -> bool:
        text = self.search_edit.text().strip().lower()
        if text and text not in media_file.file_name.lower():
            return False
        kind_filter = self.type_combo.currentText()
        if kind_filter == "Vídeos":
            return media_file.kind.value == "video"
        if kind_filter == "Documentos":
            return media_file.kind.value == "document"
        return True

    def _apply_filter(self) -> None:
        # Filtro simples: refaz a listagem completa (ok para volumes moderados;
        # para grupos gigantes, o Claude Code pode evoluir para filtro incremental).
        self.model.set_files([f for f in self._all_files if self._matches_filter(f)])

    def _toggle_row_checked(self, index) -> None:
        # O hit-test nativo do Qt para o indicador de checkbox dentro de
        # QTableView se mostrou pouco confiável (clique no quadradinho não
        # registrava). Por isso o toggle é feito manualmente aqui, a partir
        # de qualquer clique na linha, em vez de depender do editorEvent
        # padrão da view.
        check_index = self.model.index(index.row(), 0)
        current = self.model.data(check_index, Qt.CheckStateRole)
        new_state = Qt.Unchecked if current == Qt.Checked else Qt.Checked
        self.model.setData(check_index, new_state, Qt.CheckStateRole)

    def _toggle_all(self, checked: bool) -> None:
        self.model.set_all_checked(checked)
        self._emit_selection()

    def _emit_selection(self, *_) -> None:
        self.selection_changed.emit(self.model.checked_files())
