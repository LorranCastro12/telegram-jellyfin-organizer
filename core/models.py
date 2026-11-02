"""Estruturas de dados compartilhadas entre core e ui.

Mantidas como dataclasses simples (sem lógica de UI) para que possam ser
usadas tanto pela thread do Telegram quanto pelos modelos Qt da interface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional


class MediaKind(Enum):
    VIDEO = "video"
    DOCUMENT = "document"
    OTHER = "other"


class ContentType(Enum):
    """Tipo de conteúdo, que define o layout de pastas e a biblioteca destino.

    Só existem dois layouts de verdade: o de filme (uma pasta por título) e o
    de temporada (`Titulo/Season NN/Titulo SxxEyy.ext`). Desenhos, animes e
    documentários são tipos separados apenas porque no Jellyfin cada um vira
    uma biblioteca própria — a organização interna é idêntica à de séries.
    """

    MOVIE = "movie"
    SERIES = "series"
    CARTOON = "cartoon"
    ANIME = "anime"
    DOCUMENTARY = "documentary"
    UNKNOWN = "unknown"

    @property
    def is_season_based(self) -> bool:
        """True quando o conteúdo é organizado em temporadas/episódios."""
        return self in _SEASON_BASED_CONTENT_TYPES


# Definido depois da classe porque os membros do Enum só existem após ela.
_SEASON_BASED_CONTENT_TYPES = frozenset(
    {
        ContentType.SERIES,
        ContentType.CARTOON,
        ContentType.ANIME,
        ContentType.DOCUMENTARY,
    }
)


class DownloadStatus(Enum):
    QUEUED = "Na fila"
    DOWNLOADING = "Baixando"
    PAUSED = "Pausado"
    COMPLETED = "Concluído"
    ERROR = "Erro"
    CANCELLED = "Cancelado"


@dataclass
class TelegramGroup:
    """Representa um diálogo (grupo, canal ou chat) do Telegram."""

    id: int
    title: str
    is_channel: bool = False
    is_group: bool = False
    participants_count: Optional[int] = None
    unread_count: int = 0


@dataclass
class MediaFile:
    """Representa um arquivo de mídia encontrado em uma mensagem do Telegram."""

    message_id: int
    group_id: int
    file_name: str
    size: int
    mime_type: str = ""
    kind: MediaKind = MediaKind.OTHER
    date: Optional[str] = None  # ISO string, já formatado para exibição
    duration: Optional[int] = None  # segundos, quando vídeo


@dataclass
class ParsedMediaInfo:
    """Resultado da análise do nome do arquivo (via guessit) + ajustes manuais."""

    content_type: ContentType = ContentType.UNKNOWN
    title: str = ""
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: Optional[str] = None
    quality: Optional[str] = None
    source_confidence: float = 0.0  # 0..1, quão confiante foi o parser automático


@dataclass
class DownloadTask:
    """Uma tarefa de download na fila, do início ao fim do ciclo de vida."""

    media_file: MediaFile
    destination_path: Path
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: DownloadStatus = DownloadStatus.QUEUED
    bytes_done: int = 0
    bytes_total: int = 0
    speed_bps: float = 0.0
    error_message: str = ""

    @property
    def progress_percent(self) -> float:
        if self.bytes_total <= 0:
            return 0.0
        return min(100.0, (self.bytes_done / self.bytes_total) * 100)

    @property
    def eta_seconds(self) -> Optional[float]:
        if self.speed_bps <= 0 or self.bytes_total <= 0:
            return None
        remaining = self.bytes_total - self.bytes_done
        if remaining <= 0:
            return 0.0
        return remaining / self.speed_bps
