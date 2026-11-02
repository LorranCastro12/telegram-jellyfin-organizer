"""Delegate de progresso com visual de "película de filme" (sprocket holes).

Este é o elemento de assinatura visual do app: em vez de uma barra de
progresso genérica, desenhamos pequenas perfurações no topo e na base,
como os furos de tração de um rolo de filme de 35mm — uma referência direta
ao domínio do produto (organização de filmes/séries) em vez de um enfeite
gratuito.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

_TRACK_COLOR = QColor("#111013")
_BORDER_COLOR = QColor("#2E2C33")
_FILL_COLOR = QColor("#4FA3A0")
_HOLE_COLOR = QColor("#0B0B0C")
_TEXT_COLOR = QColor("#EDEAE3")


class FilmProgressDelegate(QStyledItemDelegate):
    """Espera que `index.data(Qt.UserRole)` retorne um float 0-100."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        progress = index.data(Qt.UserRole)
        if progress is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect: QRect = option.rect.adjusted(6, 6, -6, -6)
        painter.setPen(_BORDER_COLOR)
        painter.setBrush(_TRACK_COLOR)
        painter.drawRoundedRect(rect, 3, 3)

        fill_width = int(rect.width() * max(0.0, min(100.0, progress)) / 100)
        if fill_width > 0:
            fill_rect = QRect(rect.x(), rect.y(), fill_width, rect.height())
            painter.setPen(Qt.NoPen)
            painter.setBrush(_FILL_COLOR)
            painter.drawRoundedRect(fill_rect, 3, 3)

        # Perfurações estilo filme de cinema, distribuídas ao longo da barra.
        hole_radius = 2
        spacing = 10
        y_top = rect.y() + 3
        y_bottom = rect.y() + rect.height() - 3 - hole_radius * 2
        painter.setBrush(_HOLE_COLOR)
        x = rect.x() + 6
        while x < rect.x() + rect.width() - 6:
            painter.drawEllipse(x, y_top, hole_radius * 2, hole_radius * 2)
            painter.drawEllipse(x, y_bottom, hole_radius * 2, hole_radius * 2)
            x += spacing

        painter.setPen(_TEXT_COLOR)
        painter.drawText(rect, Qt.AlignCenter, f"{progress:.0f}%")

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 26))
        return size
