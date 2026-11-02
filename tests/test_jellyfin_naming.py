"""Testes do módulo core.jellyfin_naming.

Rodar com: pytest tests/
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.jellyfin_naming import (
    build_destination_path,
    build_episode_path,
    build_movie_path,
    sanitize_filename,
)
from core.models import ContentType, ParsedMediaInfo


def test_sanitize_filename_removes_illegal_chars():
    assert sanitize_filename('Metropolis: A Cidade?') == "Metropolis- A Cidade-"
    assert sanitize_filename("   Nosferatu   ") == "Nosferatu"
    assert sanitize_filename("") == "Sem Titulo"


def test_build_movie_path_with_year():
    info = ParsedMediaInfo(content_type=ContentType.MOVIE, title="Nosferatu", year=1922)
    path = build_movie_path(Path("/lib/Filmes"), info, ".mkv")
    assert path == Path("/lib/Filmes/Nosferatu (1922)/Nosferatu (1922).mkv")


def test_build_movie_path_without_year():
    info = ParsedMediaInfo(content_type=ContentType.MOVIE, title="Metropolis", year=None)
    path = build_movie_path(Path("/lib/Filmes"), info, ".mp4")
    assert path == Path("/lib/Filmes/Metropolis/Metropolis.mp4")


def test_build_episode_path_with_title():
    info = ParsedMediaInfo(
        content_type=ContentType.SERIES,
        title="Sherlock Holmes",
        season=1,
        episode=3,
        episode_title="A Queda",
    )
    path = build_episode_path(Path("/lib/Series"), info, ".mkv")
    assert path == Path(
        "/lib/Series/Sherlock Holmes/Season 01/Sherlock Holmes S01E03 - A Queda.mkv"
    )


def test_build_episode_path_defaults_season_one_episode_one():
    info = ParsedMediaInfo(content_type=ContentType.SERIES, title="Serie Sem Numero")
    path = build_episode_path(Path("/lib/Series"), info, ".mkv")
    assert path == Path("/lib/Series/Serie Sem Numero/Season 01/Serie Sem Numero S01E01.mkv")


def test_build_destination_path_dispatches_by_content_type():
    movie_info = ParsedMediaInfo(content_type=ContentType.MOVIE, title="Filme", year=2000)
    series_info = ParsedMediaInfo(content_type=ContentType.SERIES, title="Serie", season=2, episode=5)

    movie_path = build_destination_path(Path("/lib"), movie_info, "mp4")
    series_path = build_destination_path(Path("/lib"), series_info, "mp4")

    assert "Season" not in str(movie_path)
    assert "Season 02" in str(series_path)


@pytest.mark.parametrize(
    "content_type",
    [ContentType.SERIES, ContentType.CARTOON, ContentType.ANIME, ContentType.DOCUMENTARY],
)
def test_season_based_types_share_the_series_layout(content_type):
    """Desenhos, animes e documentários organizam igual a séries."""
    assert content_type.is_season_based
    info = ParsedMediaInfo(content_type=content_type, title="Titulo", season=3, episode=7)

    path = build_destination_path(Path("/lib"), info, "mkv")

    assert path == Path("/lib/Titulo/Season 03/Titulo S03E07.mkv")


@pytest.mark.parametrize("content_type", [ContentType.MOVIE, ContentType.UNKNOWN])
def test_non_season_based_types_use_the_movie_layout(content_type):
    assert not content_type.is_season_based
    info = ParsedMediaInfo(content_type=content_type, title="Titulo", year=1950)

    path = build_destination_path(Path("/lib"), info, "mkv")

    assert path == Path("/lib/Titulo (1950)/Titulo (1950).mkv")
