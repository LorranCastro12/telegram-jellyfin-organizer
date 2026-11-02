"""Painel esquerdo: lista de grupos/canais do Telegram, com filtro e grupos fixados.

A lista de diálogos de uma conta real tem facilmente centenas de entradas,
mas na prática o usuário baixa mídia sempre dos mesmos poucos canais. Daí a
função de fixar: os grupos marcados vão para uma seção própria no topo,
antes do restante da lista, e continuam lá entre sessões (os ids são
persistidos em `config.settings.AppSettings.pinned_group_ids` pela
MainWindow, que escuta o sinal `pinned_changed`).

Há duas formas de fixar/desafixar, de propósito: clicar no alfinete à
esquerda do nome (atalho visível, descoberto sozinho) e o menu de contexto
do botão direito (que também permite limpar todos de uma vez). O alfinete
aparece em todas as linhas — apagado quando não fixado, em latão quando
fixado — justamente para servir de afordância sem precisar de hover.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from PySide6.QtCore import QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from core.models import TelegramGroup

# Roles customizados do item. Antes era um 1000 mágico; com mais de um dado
# por item vale nomear.
GROUP_ROLE = Qt.UserRole + 1
PINNED_ROLE = Qt.UserRole + 2

_ICON_SIZE = 14
# Largura da área clicável do alfinete: o ícone (14px) mais o padding
# lateral que o QSS aplica em QListView::item. Folga suficiente para o alvo
# não ficar minúsculo, mas sem invadir o início do título — clicar no texto
# tem que continuar abrindo o grupo.
_PIN_HOTSPOT_WIDTH = _ICON_SIZE + 10

_PIN_COLOR_ON = QColor("#C89B3C")   # latão: acento primário do tema
_PIN_COLOR_OFF = QColor("#3A3841")  # cinza de borda: visível, mas não compete
_HEADER_COLOR = QColor("#6F6C75")


def _drop_path(side: float, width: float, top: float, bottom: float) -> QPainterPath:
    """Silhueta de alfinete: cabeça redonda em cima, ponta embaixo."""
    center_x = side * 0.5
    radius = side * width / 2
    center_y = side * top + radius

    head = QPainterPath()
    head.addEllipse(QPointF(center_x, center_y), radius, radius)
    tip = QPainterPath()
    tip.moveTo(center_x - radius * 0.86, center_y + radius * 0.52)
    tip.lineTo(center_x + radius * 0.86, center_y + radius * 0.52)
    tip.lineTo(center_x, side * bottom)
    tip.closeSubpath()
    return head.united(tip)


def _build_pin_icon(color: QColor, filled: bool) -> QIcon:
    """Desenha o alfinete em código, para não depender de arquivo de asset.

    A silhueta é de cabeça redonda, e não a tachinha vista de lado que seria
    o desenho mais óbvio: a 14px a agulha da tachinha some no anti-aliasing e
    o ícone vira um "T" (testado). Cheio = fixado, contornado = não fixado —
    assim o estado se lê pela forma, não só pela cor.

    O desenho é feito 4x maior e marcado com devicePixelRatio, o que deixa o
    Qt reduzir com anti-aliasing em vez de produzir uma borda serrada.
    """
    scale = 4
    side = _ICON_SIZE * scale
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    if filled:
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPath(_drop_path(side, 0.56, 0.08, 0.97))
    else:
        pen = QPen(color, side * 0.085)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(_drop_path(side, 0.52, 0.11, 0.93))
    painter.end()

    pixmap.setDevicePixelRatio(float(scale))
    return QIcon(pixmap)


class _GroupListView(QListWidget):
    """QListWidget que trata o clique sobre o alfinete como fixar/desafixar.

    Sem interceptar aqui, o clique no ícone cairia no `itemClicked` normal e
    abriria o grupo — o alvo mais óbvio da tela faria a coisa errada.
    """

    pin_clicked = Signal(QListWidgetItem)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._swallow_release = False

    def _pin_hotspot(self, item: QListWidgetItem) -> QRect:
        rect = self.visualItemRect(item)
        return QRect(rect.left(), rect.top(), _PIN_HOTSPOT_WIDTH, rect.height())

    def _pin_item_at(self, pos) -> Optional[QListWidgetItem]:
        item = self.itemAt(pos)
        if item is None or item.data(GROUP_ROLE) is None:
            return None  # cabeçalho de seção
        return item if self._pin_hotspot(item).contains(pos) else None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            item = self._pin_item_at(event.position().toPoint())
            if item is not None:
                self._swallow_release = True
                self.pin_clicked.emit(item)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        # Quem emite `clicked` é o release, comparando o índice solto com o
        # índice pressionado guardado internamente. Com o press engolido
        # acima, o Qt 6.11 já não emite nada (ele zera esse índice no release
        # anterior) — isto aqui é cinto de segurança: o requirements aceita
        # PySide6 6.7+ e esse detalhe interno não é contrato público.
        if self._swallow_release:
            self._swallow_release = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class GroupListWidget(QWidget):
    group_selected = Signal(object)  # TelegramGroup
    refresh_requested = Signal()
    pinned_changed = Signal(list)  # list[int] — ids fixados, na ordem em que foram fixados

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: List[TelegramGroup] = []
        self._pinned_ids: List[int] = []
        self._pin_icon_on = _build_pin_icon(_PIN_COLOR_ON, filled=True)
        self._pin_icon_off = _build_pin_icon(_PIN_COLOR_OFF, filled=False)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar grupo ou canal...")
        self.search_edit.textChanged.connect(self._refresh_list)
        layout.addWidget(self.search_edit)

        self.list_widget = _GroupListView()
        self.list_widget.setObjectName("groupList")
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.pin_clicked.connect(self._on_pin_clicked)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def set_groups(self, groups: List[TelegramGroup]) -> None:
        self._groups = sorted(groups, key=lambda g: g.title.lower())
        self._refresh_list()

    def set_pinned_ids(self, group_ids: Iterable[int]) -> None:
        """Carrega os fixados persistidos. Não emite `pinned_changed`."""
        self._pinned_ids = []
        for group_id in group_ids:
            if group_id not in self._pinned_ids:
                self._pinned_ids.append(group_id)
        self._refresh_list()

    def pinned_ids(self) -> List[int]:
        return list(self._pinned_ids)

    def toggle_pin(self, group: TelegramGroup) -> None:
        """Fixa ou desafixa um grupo e avisa quem persiste (via `pinned_changed`)."""
        if group.id in self._pinned_ids:
            self._pinned_ids.remove(group.id)
        else:
            self._pinned_ids.append(group.id)
        self._refresh_list(keep_scroll=True)
        self.pinned_changed.emit(list(self._pinned_ids))

    def unpin_all(self) -> None:
        self._pinned_ids = []
        self._refresh_list(keep_scroll=True)
        self.pinned_changed.emit([])

    # ------------------------------------------------------------------
    # Montagem da lista
    # ------------------------------------------------------------------
    def _refresh_list(self, *_, keep_scroll: bool = False) -> None:
        """Reconstrói a lista a partir do filtro atual, preservando a seleção.

        `keep_scroll` serve para fixar/desafixar: a lista é remontada inteira,
        e sem isso a rolagem voltaria ao topo a cada alfinete clicado — quem
        está marcando vários grupos lá embaixo perderia o lugar toda vez.
        Ao filtrar é o contrário: o conteúdo é outro e começar do topo é o
        esperado.
        """
        text = self.search_edit.text().strip().lower()
        groups = [g for g in self._groups if text in g.title.lower()] if text else self._groups

        selected_id = self._selected_group_id()
        scroll_position = self.list_widget.verticalScrollBar().value()
        pinned = [g for g in groups if g.id in self._pinned_ids]
        others = [g for g in groups if g.id not in self._pinned_ids]

        self.list_widget.clear()
        if pinned:
            self._add_header(f"FIXADOS ({len(pinned)})")
            for group in pinned:
                self._add_group(group, pinned=True)
            if others:
                self._add_header("TODOS OS GRUPOS")
        for group in others:
            self._add_group(group, pinned=False)

        self._restore_selection(selected_id)
        if keep_scroll:
            self.list_widget.verticalScrollBar().setValue(scroll_position)
        else:
            # Explícito porque o Qt não zera sozinho: ele mantém o
            # deslocamento antigo e só o corta no máximo novo, o que deixaria
            # o resultado do filtro começando no meio.
            self.list_widget.scrollToTop()

    def _add_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)  # não selecionável, não clicável
        item.setForeground(_HEADER_COLOR)
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(7.0, font.pointSizeF() - 2))
        font.setLetterSpacing(QFont.PercentageSpacing, 112)
        item.setFont(font)
        self.list_widget.addItem(item)

    def _add_group(self, group: TelegramGroup, pinned: bool) -> None:
        kind = "Canal" if group.is_channel and not group.is_group else "Grupo"
        label = f"{group.title}  ·  {kind}"
        if group.unread_count:
            label += f"  ·  {group.unread_count} não lidas"

        item = QListWidgetItem(self._pin_icon_on if pinned else self._pin_icon_off, label)
        item.setData(GROUP_ROLE, group)
        item.setData(PINNED_ROLE, pinned)
        item.setToolTip(
            f"{group.title}\n"
            + ("Fixado — clique no alfinete para desafixar." if pinned
               else "Clique no alfinete para fixar no topo.")
        )
        self.list_widget.addItem(item)

    def _selected_group_id(self) -> Optional[int]:
        item = self.list_widget.currentItem()
        group: Optional[TelegramGroup] = item.data(GROUP_ROLE) if item else None
        return group.id if group else None

    def _restore_selection(self, group_id: Optional[int]) -> None:
        """Mantém a linha destacada depois de fixar/desafixar ou filtrar.

        Reconstruir a lista perde a seleção, e o grupo aberto à direita
        continuaria carregado — o destaque sumindo passaria a impressão
        errada de que nada está selecionado.
        """
        if group_id is None:
            return
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            group: Optional[TelegramGroup] = item.data(GROUP_ROLE)
            if group and group.id == group_id:
                # O autoScroll faria a view pular até o item selecionado, o que
                # aqui seria um salto inesperado: quem clicou num alfinete não
                # pediu para ir até a linha que estava selecionada antes.
                auto_scroll = self.list_widget.hasAutoScroll()
                self.list_widget.setAutoScroll(False)
                self.list_widget.setCurrentItem(item)
                self.list_widget.setAutoScroll(auto_scroll)
                return

    # ------------------------------------------------------------------
    # Interação
    # ------------------------------------------------------------------
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        group: Optional[TelegramGroup] = item.data(GROUP_ROLE)
        if group:
            self.group_selected.emit(group)

    def _on_pin_clicked(self, item: QListWidgetItem) -> None:
        group: Optional[TelegramGroup] = item.data(GROUP_ROLE)
        if group:
            self.toggle_pin(group)

    def _build_context_menu(self, group: Optional[TelegramGroup]) -> QMenu:
        """Monta o menu com as ações já ligadas aos slots.

        Separado do `exec` de propósito: assim dá para testar o conteúdo e o
        efeito das ações sem abrir um menu modal, que travaria a suíte.
        `group` é None quando o clique caiu no vazio ou num cabeçalho — aí
        sobra só a ação de limpar tudo (se houver algo fixado).
        """
        menu = QMenu(self)
        if group is not None:
            is_pinned = group.id in self._pinned_ids
            action = menu.addAction(
                self._pin_icon_off if is_pinned else self._pin_icon_on,
                "Desafixar grupo" if is_pinned else "Fixar grupo",
            )
            action.triggered.connect(lambda _checked=False, g=group: self.toggle_pin(g))
            if self._pinned_ids:
                menu.addSeparator()
        if self._pinned_ids:
            unpin_all = menu.addAction("Desafixar todos")
            unpin_all.triggered.connect(lambda _checked=False: self.unpin_all())
        return menu

    def _show_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        group: Optional[TelegramGroup] = item.data(GROUP_ROLE) if item else None
        menu = self._build_context_menu(group)
        if not menu.isEmpty():
            menu.exec(self.list_widget.viewport().mapToGlobal(pos))
        menu.deleteLater()  # senão sobra um QMenu filho vivo a cada clique direito
