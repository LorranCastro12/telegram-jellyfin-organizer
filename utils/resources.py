"""Resolução de caminhos de arquivos de recurso (QSS, ícones).

Por que isso existe: rodando do código-fonte, um recurso é simplesmente um
caminho relativo à raiz do projeto. Dentro de um executável gerado pelo
PyInstaller não é — os dados são desempacotados em outro lugar, e `__file__`
aponta para um caminho virtual dentro do bundle. Centralizar a resolução aqui
evita espalhar `if getattr(sys, "frozen", ...)` pelos módulos de UI.

A regra é: o layout dos recursos é **o mesmo** nos dois modos (`ui/styles/...`,
`packaging/assets/...` a partir da raiz), então quem chama não precisa saber
se está congelado ou não.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    """Raiz sob a qual os recursos empacotados vivem."""
    if getattr(sys, "frozen", False):
        # PyInstaller define _MEIPASS tanto no modo onedir (aponta para a pasta
        # `_internal`) quanto no onefile (pasta temporária de extração).
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Caminho absoluto de um recurso, a partir da raiz do projeto/bundle."""
    return resource_root().joinpath(*parts)
