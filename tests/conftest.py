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

# Referência de módulo proposital: sem ela, a única referência viva ao
# QApplication é a variável local da fixture, que some quando a sessão
# termina. O coletor de lixo então destrói o QApplication enquanto objetos
# e tipos do Qt ainda estão sendo finalizados, e o interpretador morre com
# SIGSEGV *depois* de todos os testes terem passado — exit 139, que derruba
# o CI sem nenhum teste vermelho para explicar o motivo. Não reproduz em
# máquina com display; aparece em runner headless.
_qt_app = None


@pytest.fixture(scope="session")
def qt_app():
    global _qt_app
    from PySide6.QtWidgets import QApplication

    if _qt_app is None:
        _qt_app = QApplication.instance() or QApplication([])
    return _qt_app
