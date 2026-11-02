"""Camada core: regras de negócio, integração com Telegram e organização de mídia.

Esta camada não deve importar nada de PySide6.QtWidgets (apenas QtCore quando
necessário para sinais/threads). Isso mantém a lógica testável e independente
da interface gráfica.
"""
