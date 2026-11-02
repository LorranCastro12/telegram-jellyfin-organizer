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


@pytest.fixture(scope="session")
def qt_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
