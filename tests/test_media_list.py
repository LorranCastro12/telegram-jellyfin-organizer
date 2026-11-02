"""Testes da lista de mídia e do seu modelo Qt.

Foco no caminho do botão "Atualizar" (`prepend_new_files`), que é onde a
lista deixa de ser só "carrega e acrescenta no fim": arquivos entram no
topo, podem repetir e precisam respeitar o filtro ativo sem derrubar a
seleção em andamento.

Não precisa de display gráfico — a plataforma `offscreen` é definida antes
de importar o Qt.

Rodar com: pytest tests/
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt

from core.models import MediaFile, MediaKind
from ui.models import MediaTableModel
from ui.widgets.media_list import MediaListWidget

# A QApplication vem da fixture `qt_app` do conftest, de escopo de sessão.
# Este módulo já teve a sua própria fixture `qapp`, de escopo de módulo, e o
# resultado era dois donos Python para o mesmo objeto C++: ao desmontar a de
# módulo, o Qt avisava "shared QObject was deleted directly" e o interpretador
# morria com SIGSEGV no fim da suíte — exit 139, sem nenhum teste vermelho.


@pytest.fixture
def make_widget(qt_app):
    """Cria widgets e os destrói enquanto a QApplication ainda está viva.

    Não é zelo decorativo: deixar o widget ser coletado pelo garbage collector
    no encerramento do interpretador derruba o processo com PySide6 6.12.0 —
    os 64 testes passam e o processo morre em seguida (SIGSEGV/SIGBUS),
    quebrando o CI sem nenhum teste vermelho para explicar. Destruir aqui
    mantém a ordem de destruição dentro do tempo de vida da aplicação.
    """
    created: list[MediaListWidget] = []

    def factory() -> MediaListWidget:
        widget = MediaListWidget()
        created.append(widget)
        return widget

    yield factory

    for widget in created:
        widget.setParent(None)
        widget.deleteLater()
    qt_app.processEvents()


@pytest.fixture
def make_model(qt_app):
    """Mesma razão da `make_widget`, para o modelo usado fora de um widget."""
    created: list[MediaTableModel] = []

    def factory() -> MediaTableModel:
        model = MediaTableModel()
        created.append(model)
        return model

    yield factory

    for model in created:
        model.deleteLater()
    qt_app.processEvents()


def media(message_id: int, name: str, kind: MediaKind = MediaKind.VIDEO) -> MediaFile:
    return MediaFile(
        message_id=message_id,
        group_id=1,
        file_name=name,
        size=1024,
        kind=kind,
    )


def displayed(widget: MediaListWidget) -> list[str]:
    return [widget.model.file_at(row).file_name for row in range(widget.model.rowCount())]


# ----------------------------------------------------------------------
# Modelo
# ----------------------------------------------------------------------
def test_set_files_nao_compartilha_a_lista_recebida(make_model):
    # Se o modelo guardasse a própria lista do chamador, mutá-la fora daqui
    # inseriria linhas sem o modelo saber — e `append_files` duplicaria a
    # última página carregada.
    files = [media(30, "c.mkv"), media(20, "b.mkv")]
    model = make_model()
    model.set_files(files)

    files.append(media(10, "a.mkv"))

    assert model.rowCount() == 2


def test_prepend_mantem_a_selecao_no_arquivo_certo(make_model):
    model = make_model()
    model.set_files([media(30, "c.mkv"), media(20, "b.mkv"), media(10, "a.mkv")])
    model.setData(model.index(1, 0), Qt.Checked, Qt.CheckStateRole)

    model.prepend_files([media(40, "novo.mkv")])

    # A marcação é por message_id: as linhas desceram, o arquivo marcado não.
    assert [f.file_name for f in model.checked_files()] == ["b.mkv"]
    assert model.data(model.index(0, 0), Qt.CheckStateRole) == Qt.Unchecked
    assert model.data(model.index(2, 0), Qt.CheckStateRole) == Qt.Checked


def test_prepend_insere_no_topo_na_ordem_recebida(make_model):
    model = make_model()
    model.set_files([media(10, "antigo.mkv")])

    model.prepend_files([media(31, "novo2.mkv"), media(30, "novo1.mkv")])

    assert [model.file_at(r).file_name for r in range(model.rowCount())] == [
        "novo2.mkv",
        "novo1.mkv",
        "antigo.mkv",
    ]


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------
def test_carregar_mais_nao_duplica_a_pagina(make_widget):
    widget = make_widget()
    widget.set_files([media(30, "c.mkv"), media(20, "b.mkv")])

    widget.append_files([media(10, "a.mkv")])

    assert displayed(widget) == ["c.mkv", "b.mkv", "a.mkv"]


def test_atualizar_traz_so_o_que_e_novo(make_widget):
    widget = make_widget()
    widget.set_files([media(30, "c.mkv"), media(20, "b.mkv")])

    added = widget.prepend_new_files([media(40, "novo.mkv"), media(30, "c.mkv")])

    assert [f.file_name for f in added] == ["novo.mkv"]
    assert displayed(widget) == ["novo.mkv", "c.mkv", "b.mkv"]


def test_atualizar_duas_vezes_nao_repete_arquivo(make_widget):
    widget = make_widget()
    widget.set_files([media(20, "b.mkv")])
    widget.prepend_new_files([media(30, "novo.mkv")])

    assert widget.prepend_new_files([media(30, "novo.mkv")]) == []
    assert displayed(widget) == ["novo.mkv", "b.mkv"]


def test_atualizar_respeita_o_filtro_ativo(make_widget):
    widget = make_widget()
    widget.set_files([media(20, "serie.mkv")])
    widget.search_edit.setText("serie")

    added = widget.prepend_new_files([media(40, "filme.mkv"), media(39, "serie2.mkv")])

    # Os dois contam como novos, mas só o que casa com o filtro vai para a view.
    assert len(added) == 2
    assert displayed(widget) == ["serie2.mkv", "serie.mkv"]

    # Ao limpar o filtro, o que estava fora reaparece na posição certa.
    widget.search_edit.clear()
    assert displayed(widget) == ["filme.mkv", "serie2.mkv", "serie.mkv"]


def test_atualizar_respeita_o_filtro_de_tipo(make_widget):
    widget = make_widget()
    widget.set_files([media(20, "video.mkv", MediaKind.VIDEO)])
    widget.type_combo.setCurrentText("Vídeos")

    widget.prepend_new_files([media(40, "arquivo.rar", MediaKind.DOCUMENT)])

    assert displayed(widget) == ["video.mkv"]


def test_botao_atualizar_comeca_desabilitado_e_nao_emite(make_widget):
    widget = make_widget()
    emitted: list[int] = []
    widget.refresh_requested.connect(lambda: emitted.append(1))

    # Sem grupo aberto o botão está desabilitado; o atalho F5 cai no mesmo
    # guarda e não dispara uma consulta sem destino.
    assert not widget.refresh_btn.isEnabled()
    widget._request_refresh()
    assert emitted == []

    widget.set_refresh_enabled(True)
    widget._request_refresh()
    assert emitted == [1]


def test_set_refreshing_trava_o_botao_durante_a_consulta(make_widget):
    widget = make_widget()
    widget.set_refresh_enabled(True)

    widget.set_refreshing(True)
    assert not widget.refresh_btn.isEnabled()

    widget.set_refreshing(False)
    assert widget.refresh_btn.isEnabled()
    assert widget.refresh_btn.text() == "⟳ Atualizar"
