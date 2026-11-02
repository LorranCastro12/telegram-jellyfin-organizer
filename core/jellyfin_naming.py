"""Reconhecimento de metadados e geração de caminhos no padrão Jellyfin.

Referência das convenções usadas (documentação oficial do Jellyfin):
- Filmes:  Movies/Nome do Filme (Ano)/Nome do Filme (Ano).ext
           (opcionalmente com o IMDb id: Nome do Filme (Ano) [imdbid-tt1234567].ext)
- Séries:  Shows/Nome da Série/Season 01/Nome da Série S01E01.ext
           (opcionalmente com o título do episódio depois do SxxExx)

Desenhos, animes e documentários usam exatamente o mesmo layout de séries
(ver `ContentType.is_season_based`); o que muda é só a raiz da biblioteca,
porque no Jellyfin cada um é cadastrado como uma biblioteca separada.

O parsing automático usa a biblioteca `guessit`, muito usada por ferramentas
como Sonarr/Radarr para extrair título, ano, temporada e episódio a partir de
nomes de arquivo "de cena" (scene release names). Como o grupo do usuário tem
conteúdo de domínio público, os nomes podem ser bem variados (ex.:
"Nosferatu.1922.mkv", "A.Dama.de.Shanghai.mp4"), então o resultado do parser
é sempre tratado como um *palpite* editável na interface, nunca como valor
final automático.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from core.models import ContentType, ParsedMediaInfo

# Caracteres proibidos (ou problemáticos) em nomes de arquivo/pasta no
# Windows, macOS e Linux. Trocamos por um hífen para manter legibilidade.
_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE_RE = re.compile(r"\s{2,}")


def sanitize_filename(name: str) -> str:
    """Remove caracteres inválidos para sistemas de arquivo, preservando acentos."""
    cleaned = _ILLEGAL_CHARS_RE.sub("-", name)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip(" .")
    return cleaned or "Sem Titulo"


def parse_filename(file_name: str) -> ParsedMediaInfo:
    """Tenta extrair título/ano/temporada/episódio do nome bruto do arquivo.

    Usa `guessit` quando disponível; se a biblioteca não estiver instalada ou
    falhar, cai para um parser simples baseado em regex como rede de segurança.
    """
    try:
        from guessit import guessit

        guess = guessit(file_name)
        is_series = guess.get("type") == "episode"
        info = ParsedMediaInfo(
            content_type=ContentType.SERIES if is_series else ContentType.MOVIE,
            title=str(guess.get("title", "")).strip(),
            year=guess.get("year"),
            season=guess.get("season") if is_series else None,
            episode=guess.get("episode") if is_series else None,
            episode_title=guess.get("episode_title"),
            quality=guess.get("screen_size") or guess.get("source"),
            source_confidence=0.85 if guess.get("title") else 0.2,
        )
        if info.title:
            return info
    except Exception:
        pass  # guessit ausente ou falhou: usamos o fallback abaixo.

    return _fallback_parse(file_name)


def _fallback_parse(file_name: str) -> ParsedMediaInfo:
    """Parser simples de reserva, sem dependências externas."""
    stem = Path(file_name).stem
    normalized = re.sub(r"[._]", " ", stem)

    season_ep = re.search(r"[Ss](\d{1,2})[Ee](\d{1,3})", normalized)
    year_match = re.search(r"(19\d{2}|20\d{2})", normalized)

    if season_ep:
        season = int(season_ep.group(1))
        episode = int(season_ep.group(2))
        title = normalized[: season_ep.start()].strip(" -")
        return ParsedMediaInfo(
            content_type=ContentType.SERIES,
            title=title or stem,
            season=season,
            episode=episode,
            source_confidence=0.5,
        )

    title = normalized
    year = None
    if year_match:
        year = int(year_match.group(1))
        title = normalized[: year_match.start()].strip(" -")

    return ParsedMediaInfo(
        content_type=ContentType.MOVIE,
        title=title.strip() or stem,
        year=year,
        source_confidence=0.4 if year else 0.2,
    )


def build_movie_path(library_root: Path, info: ParsedMediaInfo, extension: str) -> Path:
    """Movies/Titulo (Ano)/Titulo (Ano).ext"""
    title = sanitize_filename(info.title)
    folder_name = f"{title} ({info.year})" if info.year else title
    file_name = f"{folder_name}{extension}"
    return library_root / folder_name / file_name


def build_episode_path(library_root: Path, info: ParsedMediaInfo, extension: str) -> Path:
    """Raiz/Titulo/Season NN/Titulo SxxEyy[ - Titulo do Episodio].ext

    Usado por séries, desenhos, animes e documentários — todos organizados
    por temporada, mudando apenas `library_root`.
    """
    series_name = sanitize_filename(info.title)
    season = info.season or 1
    episode = info.episode or 1
    season_folder = f"Season {season:02d}"
    base = f"{series_name} S{season:02d}E{episode:02d}"
    if info.episode_title:
        base += f" - {sanitize_filename(info.episode_title)}"
    file_name = f"{base}{extension}"
    return library_root / series_name / season_folder / file_name


def build_destination_path(library_root: Path, info: ParsedMediaInfo, extension: str) -> Path:
    """Ponto único de entrada: escolhe o layout conforme `info.content_type`."""
    if not extension.startswith("."):
        extension = f".{extension}"
    if info.content_type.is_season_based:
        return build_episode_path(library_root, info, extension)
    return build_movie_path(library_root, info, extension)
