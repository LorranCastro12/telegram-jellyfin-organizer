"""Testes da lista de grupos — principalmente da função de fixar.

O valor aqui está em dois pontos frágeis: a ordenação (fixados primeiro,
com cabeçalhos de seção) e o clique no alfinete, que precisa fixar *sem*
selecionar o grupo. Esse segundo depende de interceptar press e release no
QListWidget, então é testado com clique sintético de verdade (QTest) em vez
de chamar o método direto.
"""

from __future__ import annotations

from typing import List

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from core.models import TelegramGroup
from ui.widgets.group_list import GROUP_ROLE, PINNED_ROLE, GroupListWidget

GROUPS = [
    TelegramGroup(id=1, title="Zumbis Filmes", is_channel=True),
    TelegramGroup(id=2, title="Animes BR", is_channel=True, unread_count=12),
    TelegramGroup(id=3, title="Cinema Clássico", is_group=True),
    TelegramGroup(id=4, title="Documentários", is_channel=True),
]


@pytest.fixture
def widget(qt_app):
    w = GroupListWidget()
    w.resize(320, 500)
    w.show()
    yield w
    w.close()


def rows(widget: GroupListWidget) -> List[str]:
    """Texto de cada linha, cabeçalhos incluídos, na ordem exibida."""
    return [widget.list_widget.item(r).text() for r in range(widget.list_widget.count())]


def group_rows(widget: GroupListWidget) -> List[str]:
    """Só os títulos dos grupos, na ordem exibida."""
    titles = []
    for r in range(widget.list_widget.count()):
        group = widget.list_widget.item(r).data(GROUP_ROLE)
        if group:
            titles.append(group.title)
    return titles


def row_of(widget: GroupListWidget, group_id: int) -> int:
    for r in range(widget.list_widget.count()):
        group = widget.list_widget.item(r).data(GROUP_ROLE)
        if group and group.id == group_id:
            return r
    raise AssertionError(f"grupo {group_id} não está na lista")


def click_pin(widget: GroupListWidget, group_id: int) -> None:
    rect = widget.list_widget.visualItemRect(widget.list_widget.item(row_of(widget, group_id)))
    QTest.mouseClick(
        widget.list_widget.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        QPoint(rect.left() + 8, rect.center().y()),
    )


def click_title(widget: GroupListWidget, group_id: int) -> None:
    rect = widget.list_widget.visualItemRect(widget.list_widget.item(row_of(widget, group_id)))
    QTest.mouseClick(
        widget.list_widget.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        QPoint(rect.left() + 120, rect.center().y()),
    )


def test_sem_fixados_lista_fica_em_ordem_alfabetica(widget):
    widget.set_groups(GROUPS)
    assert group_rows(widget) == [
        "Animes BR",
        "Cinema Clássico",
        "Documentários",
        "Zumbis Filmes",
    ]
    assert not any(r.startswith("FIXADOS") for r in rows(widget))


def test_fixados_vao_para_o_topo_com_cabecalhos(widget):
    widget.set_pinned_ids([3])
    widget.set_groups(GROUPS)

    assert rows(widget)[0] == "FIXADOS (1)"
    assert rows(widget)[2] == "TODOS OS GRUPOS"
    assert group_rows(widget) == [
        "Cinema Clássico",
        "Animes BR",
        "Documentários",
        "Zumbis Filmes",
    ]


def test_set_pinned_ids_nao_emite_sinal_de_mudanca(widget):
    """Carregar o que veio do disco não é uma alteração — senão o app
    regravaria settings.json em todo startup."""
    emitted = []
    widget.pinned_changed.connect(emitted.append)
    widget.set_pinned_ids([1, 2])
    widget.set_groups(GROUPS)
    assert emitted == []


def test_clique_no_alfinete_fixa_sem_abrir_o_grupo(widget):
    widget.set_groups(GROUPS)
    pinned, opened = [], []
    widget.pinned_changed.connect(pinned.append)
    widget.group_selected.connect(opened.append)

    click_pin(widget, 2)

    assert pinned == [[2]]
    assert opened == [], "clicar no alfinete não pode disparar o carregamento do grupo"
    assert group_rows(widget)[0] == "Animes BR"
    assert widget.list_widget.item(row_of(widget, 2)).data(PINNED_ROLE) is True


def test_clique_no_alfinete_de_fixado_desafixa(widget):
    widget.set_pinned_ids([2])
    widget.set_groups(GROUPS)
    pinned = []
    widget.pinned_changed.connect(pinned.append)

    click_pin(widget, 2)

    assert pinned == [[]]
    assert widget.pinned_ids() == []


def test_clique_no_titulo_abre_o_grupo_e_nao_mexe_no_pin(widget):
    widget.set_groups(GROUPS)
    pinned, opened = [], []
    widget.pinned_changed.connect(pinned.append)
    widget.group_selected.connect(opened.append)

    click_title(widget, 1)

    assert [g.id for g in opened] == [1]
    assert pinned == []


def test_clique_no_alfinete_de_linha_ja_aberta_nao_reabre_o_grupo(widget):
    """Fixar um grupo que já está aberto não pode recarregar a lista de
    arquivos dele — seria uma ida à rede à toa a cada clique no alfinete."""
    widget.set_groups(GROUPS)
    opened = []
    click_title(widget, 1)
    widget.group_selected.connect(opened.append)

    click_pin(widget, 1)

    assert opened == []
    assert widget.pinned_ids() == [1]


def test_filtro_preserva_a_secao_de_fixados(widget):
    widget.set_pinned_ids([2])
    widget.set_groups(GROUPS)

    widget.search_edit.setText("ani")
    assert rows(widget) == ["FIXADOS (1)", "Animes BR  ·  Canal  ·  12 não lidas"]

    widget.search_edit.setText("zumbi")
    assert group_rows(widget) == ["Zumbis Filmes"]
    assert not any(r.startswith("FIXADOS") for r in rows(widget))


def test_selecao_sobrevive_a_reconstrucao_da_lista(widget):
    widget.set_groups(GROUPS)
    click_title(widget, 1)

    widget.toggle_pin(GROUPS[3])  # reconstrói a lista inteira

    current = widget.list_widget.currentItem().data(GROUP_ROLE)
    assert current.id == 1


def test_unpin_all_limpa_tudo_e_avisa(widget):
    widget.set_pinned_ids([1, 2, 3])
    widget.set_groups(GROUPS)
    pinned = []
    widget.pinned_changed.connect(pinned.append)

    widget.unpin_all()

    assert pinned == [[]]
    assert group_rows(widget) == [g.title for g in sorted(GROUPS, key=lambda g: g.title.lower())]


def menu_labels(menu) -> List[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


# `_build_context_menu` é privado, mas é o ponto certo para testar o menu:
# chamar o handler de verdade abriria um QMenu modal e travaria a suíte.
def test_menu_de_contexto_fixa_grupo_nao_fixado(widget):
    widget.set_groups(GROUPS)

    menu = widget._build_context_menu(GROUPS[2])
    assert menu_labels(menu) == ["Fixar grupo"]

    menu.actions()[0].trigger()
    assert widget.pinned_ids() == [3]


def test_menu_de_contexto_de_grupo_fixado_oferece_desafixar_todos(widget):
    widget.set_pinned_ids([3])
    widget.set_groups(GROUPS)

    menu = widget._build_context_menu(GROUPS[2])
    assert menu_labels(menu) == ["Desafixar grupo", "Desafixar todos"]

    next(a for a in menu.actions() if a.text() == "Desafixar todos").trigger()
    assert widget.pinned_ids() == []


def test_menu_de_contexto_no_vazio_so_oferece_limpar(widget):
    widget.set_pinned_ids([1])
    widget.set_groups(GROUPS)

    assert menu_labels(widget._build_context_menu(None)) == ["Desafixar todos"]
    # sem nada fixado não há menu nenhum a mostrar
    widget.unpin_all()
    assert widget._build_context_menu(None).isEmpty()


def scrolled_to_bottom(widget: GroupListWidget, qt_app):
    """Rola até o fim e devolve o scrollbar já posicionado.

    O `processEvents` é necessário: sem ele o layout da view ainda não rodou e
    o scrollbar reporta maximum == 0.
    """
    qt_app.processEvents()
    scrollbar = widget.list_widget.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    assert scrollbar.value() > 0, "a lista precisa estar rolável para o teste fazer sentido"
    return scrollbar


def test_fixar_grupo_la_embaixo_nao_joga_a_rolagem_para_o_topo(widget, qt_app):
    muitos = [TelegramGroup(id=i, title=f"Grupo {i:03d}") for i in range(60)]
    widget.set_groups(muitos)
    scrollbar = scrolled_to_bottom(widget, qt_app)
    antes = scrollbar.value()

    widget.toggle_pin(muitos[55])

    assert scrollbar.value() == antes


def test_filtrar_volta_para_o_topo(widget, qt_app):
    widget.set_groups([TelegramGroup(id=i, title=f"Grupo {i:03d}") for i in range(60)])
    scrolled_to_bottom(widget, qt_app)

    widget.search_edit.setText("grupo 0")

    assert widget.list_widget.verticalScrollBar().value() == 0


def test_grupo_fixado_que_nao_esta_mais_na_conta_e_ignorado(widget):
    """Ids de grupos dos quais o usuário saiu continuam salvos, mas não podem
    aparecer nem quebrar a montagem da lista."""
    widget.set_pinned_ids([999])
    widget.set_groups(GROUPS)

    assert len(group_rows(widget)) == len(GROUPS)
    assert not any(r.startswith("FIXADOS") for r in rows(widget))
    assert widget.pinned_ids() == [999]
