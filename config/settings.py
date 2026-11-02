"""Configurações não sensíveis da aplicação, persistidas em JSON simples.

Diferente de `core.credentials`, aqui não há nada que precise de
criptografia: apenas caminhos de biblioteca e preferências de download.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir

from core.models import ContentType

logger = logging.getLogger(__name__)

APP_NAME = "TelegramJellyfinOrganizer"

# Cada tipo de conteúdo tem sua própria raiz porque no Jellyfin cada
# biblioteca é cadastrada separadamente. Esta lista é a fonte única da
# ordem e dos rótulos usados na tela de Configurações — para suportar um
# tipo novo basta adicionar o campo no dataclass e uma linha aqui.
LIBRARY_FIELDS: list[tuple[ContentType, str, str]] = [
    (ContentType.MOVIE, "movies_library_path", "Filmes"),
    (ContentType.SERIES, "shows_library_path", "Séries"),
    (ContentType.CARTOON, "cartoons_library_path", "Desenhos"),
    (ContentType.ANIME, "animes_library_path", "Animes"),
    (ContentType.DOCUMENTARY, "documentaries_library_path", "Documentários"),
]

_FIELD_BY_CONTENT_TYPE = {content_type: name for content_type, name, _ in LIBRARY_FIELDS}
_LABEL_BY_CONTENT_TYPE = {content_type: label for content_type, _, label in LIBRARY_FIELDS}


def library_label(content_type: ContentType) -> str:
    """Nome da biblioteca como aparece na UI (ex.: 'Desenhos')."""
    return _LABEL_BY_CONTENT_TYPE.get(content_type, "Filmes")


@dataclass
class AppSettings:
    movies_library_path: str = ""
    shows_library_path: str = ""
    cartoons_library_path: str = ""
    animes_library_path: str = ""
    documentaries_library_path: str = ""
    max_concurrent_downloads: int = 3
    download_chunk_kb: int = 512
    remember_credentials: bool = True
    # Ids dos grupos/canais fixados no topo da lista da tela "Grupos".
    # Guardamos só o id (não o título) porque o título pode mudar no
    # Telegram; a lista é resolvida contra os diálogos recebidos a cada
    # sessão. Ids de grupos dos quais o usuário saiu simplesmente não
    # aparecem — não são removidos daqui, para o caso de ele voltar.
    pinned_group_ids: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        # O settings.json pode vir de uma versão anterior do app ou ter sido
        # editado à mão, então normalizamos em vez de confiar no conteúdo.
        raw_ids = self.pinned_group_ids if isinstance(self.pinned_group_ids, (list, tuple)) else []
        normalized: list[int] = []
        for raw in raw_ids:
            try:
                group_id = int(raw)
            except (TypeError, ValueError):
                continue
            if group_id not in normalized:
                normalized.append(group_id)
        self.pinned_group_ids = normalized

    def library_path_for(self, content_type: ContentType) -> Optional[Path]:
        """Raiz configurada para um tipo de conteúdo, ou None se vazia."""
        field_name = _FIELD_BY_CONTENT_TYPE.get(content_type)
        if field_name is None:
            return None
        raw = getattr(self, field_name, "")
        return Path(raw) if raw else None

    def library_paths(self) -> dict[ContentType, Optional[Path]]:
        """Mapa completo tipo → raiz, do jeito que a UI de organização consome."""
        return {
            content_type: self.library_path_for(content_type)
            for content_type, _, _ in LIBRARY_FIELDS
        }

    @property
    def movies_path(self) -> Optional[Path]:
        return self.library_path_for(ContentType.MOVIE)

    @property
    def shows_path(self) -> Optional[Path]:
        return self.library_path_for(ContentType.SERIES)

    def is_configured(self) -> bool:
        """Mínimo para o app ser útil: filmes e séries.

        As bibliotecas de desenhos/animes/documentários são opcionais — quem
        não usa esses tipos não precisa configurá-las.
        """
        return bool(self.movies_library_path and self.shows_library_path)


class SettingsManager:
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(user_config_dir(APP_NAME, appauthor=False))
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.config_dir / "settings.json"
        self._settings: Optional[AppSettings] = None

    def load(self) -> AppSettings:
        if self._settings is not None:
            return self._settings
        if self.settings_path.exists():
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                self._settings = AppSettings(**{**asdict(AppSettings()), **data})
            except (json.JSONDecodeError, TypeError) as exc:
                logger.error("settings.json corrompido (%s); usando padrões.", exc)
                self._settings = AppSettings()
        else:
            self._settings = AppSettings()
        return self._settings

    def save(self, settings: Optional[AppSettings] = None) -> None:
        settings = settings or self._settings or AppSettings()
        self._settings = settings
        self.settings_path.write_text(
            json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8"
        )
