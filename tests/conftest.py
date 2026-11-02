"""Infraestrutura comum dos testes.

A instância de QApplication é única por processo e não pode ser recriada,
daí a fixture com escopo de sessão. O backend `offscreen` é forçado para que
`pytest tests/` rode igual em CI, container sem X11 e máquina com display —
e para que nenhuma janela pisque na tela durante os testes.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Esta é a ÚNICA fixture que pode criar ou guardar a QApplication. Todo
# módulo de teste que precise do Qt deve pedir `qt_app`, nunca montar a sua
# própria — já houve uma fixture `qapp` duplicada em test_media_list.py, e o
# efeito era dois donos Python para o mesmo objeto C++: ao desmontar a de
# escopo menor, o Qt reclamava "shared QObject was deleted directly" e o
# interpretador morria com SIGSEGV no fim da suíte (exit 139, sem nenhum
# teste vermelho para explicar o motivo). Só se manifestava em runner
# headless, nunca em máquina com display.
#
# A referência de módulo mantém o objeto vivo pela sessão inteira, em vez de
# depender da variável local da fixture.
_qt_app = None


@pytest.fixture(scope="session")
def qt_app():
    global _qt_app
    from PySide6.QtWidgets import QApplication

    if _qt_app is None:
        _qt_app = QApplication.instance() or QApplication([])
    return _qt_app
