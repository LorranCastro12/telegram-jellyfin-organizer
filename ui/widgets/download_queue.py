"""Painel de downloads: fila, progresso individual, cancelamento e status."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.models import DownloadTask
from ui.models import DownloadQueueModel
from ui.widgets.film_progress_delegate import FilmProgressDelegate


class DownloadQueueWidget(QWidget):
    cancel_requested = Signal(str)  # task_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = DownloadQueueModel(self)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("Fila de downloads"))
        header.addStretch(1)
        self.cancel_selected_btn = QPushButton("Cancelar selecionado")
        self.cancel_selected_btn.setProperty("class", "danger")
        self.cancel_selected_btn.clicked.connect(self._cancel_selected)
        header.addWidget(self.cancel_selected_btn)
        layout.addLayout(header)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setItemDelegateForColumn(2, FilmProgressDelegate(self.table))
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

    def add_task(self, task: DownloadTask) -> None:
        self.model.add_task(task)

    def update_progress(self, task_id: str, current: int, total: int, speed: float) -> None:
        self.model.update_progress(task_id, current, total, speed)

    def update_status(self, task_id: str, status) -> None:
        self.model.update_status(task_id, status)

    def _cancel_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        for index in rows:
            task = self.model.task_at(index.row())
            self.cancel_requested.emit(task.id)
