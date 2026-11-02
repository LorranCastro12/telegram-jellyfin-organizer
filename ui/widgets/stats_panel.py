"""Painel de desempenho: velocidade agregada, downloads ativos e histórico.

Usa QtCharts quando disponível (módulo `PySide6.QtCharts`, que acompanha o
PySide6 em instalações padrão) para o gráfico de velocidade ao longo do
tempo. Se por algum motivo o módulo não estiver presente no ambiente, o
painel degrada graciosamente para exibir só os cartões numéricos.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Tuple

from PySide6.QtCore import Qt, QMargins
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from utils.formatters import format_bytes, format_speed

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis

    _CHARTS_AVAILABLE = True
except ImportError:  # pragma: no cover - degrade graciosamente sem QtCharts
    _CHARTS_AVAILABLE = False


class _StatCard(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.value_label = QLabel("0")
        self.value_label.setProperty("class", "statValue")
        self.caption_label = QLabel(label.upper())
        self.caption_label.setProperty("class", "statLabel")
        layout.addWidget(self.value_label)
        layout.addWidget(self.caption_label)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)


class StatsPanel(QWidget):
    HISTORY_SECONDS = 120

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: Deque[Tuple[float, float]] = deque(maxlen=240)  # (timestamp, total_speed)
        self._active_speeds: dict[str, float] = {}
        self._completed_count = 0
        self._total_bytes_session = 0
        self._start_time = time.monotonic()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        cards_layout = QGridLayout()
        cards_layout.setSpacing(12)

        self.active_card = _StatCard("Downloads ativos")
        self.speed_card = _StatCard("Velocidade agregada")
        self.completed_card = _StatCard("Concluídos na sessão")
        self.total_card = _StatCard("Total baixado na sessão")

        cards_layout.addWidget(self.active_card, 0, 0)
        cards_layout.addWidget(self.speed_card, 0, 1)
        cards_layout.addWidget(self.completed_card, 0, 2)
        cards_layout.addWidget(self.total_card, 0, 3)
        layout.addLayout(cards_layout)

        if _CHARTS_AVAILABLE:
            self.series = QLineSeries()
            self.chart = QChart()
            self.chart.addSeries(self.series)
            self.chart.legend().hide()
            self.chart.setBackgroundVisible(False)
            self.chart.setMargins(QMargins(0, 0, 0, 0))

            self.axis_x = QValueAxis()
            self.axis_x.setLabelsVisible(False)
            self.axis_x.setRange(0, self.HISTORY_SECONDS)
            self.axis_y = QValueAxis()
            self.axis_y.setLabelFormat("%.0f KB/s")
            self.chart.addAxis(self.axis_x, Qt.AlignBottom)
            self.chart.addAxis(self.axis_y, Qt.AlignLeft)
            self.series.attachAxis(self.axis_x)
            self.series.attachAxis(self.axis_y)

            pen = self.series.pen()
            pen.setColor("#C89B3C")
            pen.setWidth(2)
            self.series.setPen(pen)

            self.chart_view = QChartView(self.chart)
            self.chart_view.setRenderHint(self.chart_view.renderHints())
            self.chart_view.setMinimumHeight(220)
            self.chart_view.setStyleSheet("background: transparent;")
            layout.addWidget(self.chart_view, 1)
        else:
            fallback = QLabel(
                "Gráfico de desempenho indisponível: módulo PySide6.QtCharts não encontrado."
            )
            fallback.setProperty("class", "muted")
            fallback.setAlignment(Qt.AlignCenter)
            layout.addWidget(fallback, 1)

        layout.addStretch(0)

    # ------------------------------------------------------------------
    # Atualizações vindas dos sinais do TelegramWorker
    # ------------------------------------------------------------------
    def on_progress(self, task_id: str, current: int, total: int, speed: float) -> None:
        self._active_speeds[task_id] = speed
        self._refresh_cards()
        self._push_history_point()

    def on_task_finished(self, task_id: str, bytes_downloaded: int = 0) -> None:
        self._active_speeds.pop(task_id, None)
        self._completed_count += 1
        self._total_bytes_session += bytes_downloaded
        self._refresh_cards()

    def on_task_removed(self, task_id: str) -> None:
        self._active_speeds.pop(task_id, None)
        self._refresh_cards()

    def _refresh_cards(self) -> None:
        total_speed = sum(self._active_speeds.values())
        self.active_card.set_value(str(len(self._active_speeds)))
        self.speed_card.set_value(format_speed(total_speed))
        self.completed_card.set_value(str(self._completed_count))
        self.total_card.set_value(format_bytes(self._total_bytes_session))

    def _push_history_point(self) -> None:
        if not _CHARTS_AVAILABLE:
            return
        now = time.monotonic() - self._start_time
        total_speed_kb = sum(self._active_speeds.values()) / 1024
        self._history.append((now, total_speed_kb))
        self.series.clear()
        for x, y in self._history:
            self.series.append(x, y)
        if self._history:
            latest = self._history[-1][0]
            self.axis_x.setRange(max(0, latest - self.HISTORY_SECONDS), max(latest, 10))
            max_y = max((y for _, y in self._history), default=10)
            self.axis_y.setRange(0, max(10.0, max_y * 1.2))
