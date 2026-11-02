"""Fonte única da identidade/versão do produto.

Tanto o app quanto os três caminhos de empacotamento (Inno Setup no Windows,
assistente gráfico e `.deb` no Linux) leem daqui. Mantém o número de versão
em um lugar só — mudar aqui propaga para o instalador, o pacote e o release.
"""

from __future__ import annotations

__version__ = "1.0.1"

APP_NAME = "Telegram Jellyfin Organizer"
APP_ID = "telegram-jellyfin-organizer"
PUBLISHER = "LorranCastro12"
HOMEPAGE = "https://github.com/LorranCastro12/telegram-jellyfin-organizer"
DESCRIPTION = "Baixa mídia do Telegram já organizada no padrão de pastas do Jellyfin"
