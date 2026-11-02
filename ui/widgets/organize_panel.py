"""Painel de organização Jellyfin.

Para cada arquivo selecionado na lista de mídia, mostramos o palpite
automático (via guessit) de título/ano/temporada/episódio, sempre editável,
e o caminho final que será usado no download. O usuário confirma (ou ajusta)
antes de mandar para a fila — assim nomes de arquivo incomuns (comuns em
conteúdo de domínio público antigo) nunca geram uma pasta errada sem revisão.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.settings import LIBRARY_FIELDS, library_label
from core.jellyfin_naming import build_destination_path, parse_filename
from core.models import ContentType, MediaFile, ParsedMediaInfo

_COLUMNS = ["Arquivo", "Tipo", "Título", "Ano", "Temp.", "Epis.", "Destino final"]

# Rótulos (no singular) do combo de tipo, na mesma ordem das bibliotecas em
# Configurações. Desenhos, animes e documentários são tipos próprios porque
# cada um tem sua biblioteca, mas o layout de pastas é o de temporada —
# idêntico ao de séries.
_TYPE_LABELS: dict[ContentType, str] = {
    ContentType.MOVIE: "Filme",
    ContentType.SERIES: "Série",
    ContentType.CARTOON: "Desenho",
    ContentType.ANIME: "Anime",
    ContentType.DOCUMENTARY: "Documentário",
}
_TYPE_CHOICES = [
    (_TYPE_LABELS[content_type], content_type)
    for content_type, _, _ in LIBRARY_FIELDS
    if content_type in _TYPE_LABELS
]


class OrganizePanel(QWidget):
    queue_requested = Signal(list)  # list[tuple[MediaFile, ParsedMediaInfo, Path]]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[dict] = []  # cada item guarda media_file, info e widgets da linha
        self.library_roots: Dict[ContentType, Optional[Path]] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("Revise os metadados antes de baixar:"))
        header.addStretch(1)
        self.add_to_queue_btn = QPushButton("Adicionar à fila de downloads")
        self.add_to_queue_btn.setProperty("class", "primary")
        self.add_to_queue_btn.clicked.connect(self._emit_queue_request)
        header.addWidget(self.add_to_queue_btn)
        layout.addLayout(header)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        # QComboBox/QLineEdit/QSpinBox embutidos via setCellWidget precisam de
        # mais altura do que a linha padrão do QTableWidget — sem isso eles são
        # espremidos a poucos pixels e o texto vira um borrão ilegível.
        self.table.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self.table, 1)

    def set_library_roots(self, roots: Dict[ContentType, Optional[Path]]) -> None:
        """Recebe o mapa tipo de conteúdo → raiz da biblioteca (AppSettings.library_paths)."""
        self.library_roots = dict(roots)
        self._refresh_all_previews()

    def set_selected_files(self, files: List[MediaFile]) -> None:
        self.table.setRowCount(0)
        self._rows = []
        for media_file in files:
            self._add_row(media_file)

    def _add_row(self, media_file: MediaFile) -> None:
        info = parse_filename(media_file.file_name)
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(media_file.file_name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, name_item)

        type_combo = QComboBox()
        for label, content_type in _TYPE_CHOICES:
            type_combo.addItem(label, content_type)
        type_combo.setCurrentIndex(self._type_index(info.content_type))

        title_edit = QLineEdit(info.title)
        title_edit.setCursorPosition(0)
        year_edit = QLineEdit(str(info.year) if info.year else "")
        year_edit.setMaximumWidth(70)

        season_spin = QSpinBox()
        season_spin.setRange(0, 99)
        season_spin.setValue(info.season or 1)

        episode_spin = QSpinBox()
        episode_spin.setRange(0, 999)
        episode_spin.setValue(info.episode or 1)

        for widget in (type_combo, title_edit, year_edit, season_spin, episode_spin):
            widget.setMinimumHeight(30)

        self.table.setCellWidget(row, 1, type_combo)
        self.table.setCellWidget(row, 2, title_edit)
        self.table.setCellWidget(row, 3, year_edit)
        self.table.setCellWidget(row, 4, season_spin)
        self.table.setCellWidget(row, 5, episode_spin)

        preview_item = QTableWidgetItem("")
        preview_item.setFlags(preview_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 6, preview_item)

        row_state = {
            "media_file": media_file,
            "type_combo": type_combo,
            "title_edit": title_edit,
            "year_edit": year_edit,
            "season_spin": season_spin,
            "episode_spin": episode_spin,
            "preview_item": preview_item,
        }
        self._rows.append(row_state)

        for widget in (type_combo, title_edit, year_edit, season_spin, episode_spin):
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(lambda _=None, r=row_state: self._refresh_preview(r))
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(lambda _=None, r=row_state: self._refresh_preview(r))
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(lambda _=None, r=row_state: self._refresh_preview(r))

        self.table.resizeRowToContents(row)
        self._update_season_episode_visibility(row_state)
        self._refresh_preview(row_state)

    @staticmethod
    def _type_index(content_type: ContentType) -> int:
        """Posição do tipo no combo; cai em Filme quando o parser não decidiu."""
        for index, (_label, choice) in enumerate(_TYPE_CHOICES):
            if choice == content_type:
                return index
        return 0

    @staticmethod
    def _row_content_type(row_state: dict) -> ContentType:
        return row_state["type_combo"].currentData() or ContentType.MOVIE

    def _update_season_episode_visibility(self, row_state: dict) -> None:
        # Temporada/episódio só fazem sentido nos tipos organizados por
        # temporada: séries, desenhos, animes e documentários.
        season_based = self._row_content_type(row_state).is_season_based
        row_state["season_spin"].setEnabled(season_based)
        row_state["episode_spin"].setEnabled(season_based)

    def _row_info_and_root(self, row_state: dict):
        content_type = self._row_content_type(row_state)
        season_based = content_type.is_season_based
        year_text = row_state["year_edit"].text().strip()
        info = ParsedMediaInfo(
            content_type=content_type,
            title=row_state["title_edit"].text().strip() or "Sem Titulo",
            year=int(year_text) if year_text.isdigit() else None,
            season=row_state["season_spin"].value() if season_based else None,
            episode=row_state["episode_spin"].value() if season_based else None,
        )
        return info, self.library_roots.get(content_type)

    def _refresh_preview(self, row_state: dict) -> None:
        self._update_season_episode_visibility(row_state)
        info, root = self._row_info_and_root(row_state)
        extension = Path(row_state["media_file"].file_name).suffix or ".mkv"
        if root is None:
            row_state["preview_item"].setText(
                f"⚠ Configure a pasta de {library_label(info.content_type)} em Configurações"
            )
            return
        destination = build_destination_path(root, info, extension)
        row_state["preview_item"].setText(str(destination))

    def _refresh_all_previews(self) -> None:
        for row_state in self._rows:
            self._refresh_preview(row_state)

    def _emit_queue_request(self) -> None:
        entries = []
        for row_state in self._rows:
            info, root = self._row_info_and_root(row_state)
            if root is None:
                continue
            extension = Path(row_state["media_file"].file_name).suffix or ".mkv"
            destination = build_destination_path(root, info, extension)
            entries.append((row_state["media_file"], info, destination))
        if entries:
            self.queue_requested.emit(entries)
