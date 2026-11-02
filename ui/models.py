"""Modelos Qt que conectam os dados do core (dataclasses) às views da UI."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from core.models import DownloadTask, MediaFile, MediaKind
from utils.formatters import format_bytes, format_eta, format_speed


class MediaTableModel(QAbstractTableModel):
    """Lista de arquivos de mídia de um grupo, com checkbox de seleção."""

    HEADERS = ["", "Arquivo", "Tamanho", "Data"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: List[MediaFile] = []
        # Marcação guardada por `message_id`, não por índice de linha: o
        # "Atualizar" insere arquivos novos no topo, e com índices toda a
        # seleção existente passaria a apontar para o arquivo errado.
        self._checked: set[int] = set()

    def set_files(self, files: List[MediaFile]) -> None:
        self.beginResetModel()
        # Cópia, não a lista recebida: o chamador (MediaListWidget) mantém a
        # sua própria lista completa e a mutaria aqui também se fosse o mesmo
        # objeto — os arquivos entrariam duas vezes no modelo.
        self._files = list(files)
        self._checked = set()
        self.endResetModel()

    def append_files(self, files: List[MediaFile]) -> None:
        if not files:
            return
        start = len(self._files)
        self.beginInsertRows(QModelIndex(), start, start + len(files) - 1)
        self._files.extend(files)
        self.endInsertRows()

    def prepend_files(self, files: List[MediaFile]) -> None:
        """Insere arquivos no topo (mais novos primeiro), mantendo a seleção."""
        if not files:
            return
        self.beginInsertRows(QModelIndex(), 0, len(files) - 1)
        self._files[:0] = files
        self.endInsertRows()

    def file_at(self, row: int) -> MediaFile:
        return self._files[row]

    def checked_files(self) -> List[MediaFile]:
        """Arquivos marcados, no máximo um por `message_id`.

        A desduplicação aqui é a segunda linha de defesa: quem alimenta o
        modelo já evita inserir o mesmo arquivo duas vezes, mas esta lista vai
        direto para a fila de downloads. Se uma linha repetida escapar, o
        prejuízo é baixar o mesmo arquivo duas vezes em cima do mesmo destino
        — então o custo de garantir aqui é menor que o risco.
        """
        seen: set[int] = set()
        unique: List[MediaFile] = []
        for media_file in self._files:
            if media_file.message_id not in self._checked:
                continue
            if media_file.message_id in seen:
                continue
            seen.add(media_file.message_id)
            unique.append(media_file)
        return unique

    def set_all_checked(self, checked: bool) -> None:
        self.beginResetModel()
        self._checked = {f.message_id for f in self._files} if checked else set()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._files)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index: QModelIndex):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            return base | Qt.ItemIsUserCheckable
        return base

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self._files[index.row()]
        col = index.column()

        if role == Qt.CheckStateRole and col == 0:
            return Qt.Checked if item.message_id in self._checked else Qt.Unchecked

        if role == Qt.DisplayRole:
            if col == 1:
                return item.file_name
            if col == 2:
                return format_bytes(item.size)
            if col == 3:
                return (item.date or "—")[:16].replace("T", " ")

        if role == Qt.DecorationRole and col == 1:
            return None  # ponto de extensão: ícone por tipo (vídeo/documento)

        return None

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if role == Qt.CheckStateRole and index.column() == 0:
            message_id = self._files[index.row()].message_id
            if value == Qt.Checked:
                self._checked.add(message_id)
            else:
                self._checked.discard(message_id)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False


class DownloadQueueModel(QAbstractTableModel):
    """Fila de downloads em andamento/concluídos, atualizada via sinais do worker."""

    HEADERS = ["Arquivo", "Destino", "Progresso", "Velocidade", "ETA", "Status"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: List[DownloadTask] = []
        self._id_to_row = {}

    def add_task(self, task: DownloadTask) -> None:
        row = len(self._tasks)
        self.beginInsertRows(QModelIndex(), row, row)
        self._tasks.append(task)
        self._id_to_row[task.id] = row
        self.endInsertRows()

    def task_row(self, task_id: str) -> Optional[int]:
        return self._id_to_row.get(task_id)

    def task_at(self, row: int) -> DownloadTask:
        return self._tasks[row]

    def update_progress(self, task_id: str, current: int, total: int, speed: float) -> None:
        row = self._id_to_row.get(task_id)
        if row is None:
            return
        task = self._tasks[row]
        task.bytes_done = current
        task.bytes_total = total or task.bytes_total
        task.speed_bps = speed
        top_left = self.index(row, 2)
        bottom_right = self.index(row, 4)
        self.dataChanged.emit(top_left, bottom_right)

    def update_status(self, task_id: str, status) -> None:
        row = self._id_to_row.get(task_id)
        if row is None:
            return
        self._tasks[row].status = status
        idx = self.index(row, 5)
        self.dataChanged.emit(idx, idx)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._tasks)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        task = self._tasks[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return task.media_file.file_name
            if col == 1:
                return str(task.destination_path)
            if col == 2:
                return f"{task.progress_percent:.0f}%"
            if col == 3:
                return format_speed(task.speed_bps)
            if col == 4:
                return format_eta(task.eta_seconds)
            if col == 5:
                return task.status.value

        if role == Qt.UserRole and col == 2:
            return task.progress_percent

        return None
