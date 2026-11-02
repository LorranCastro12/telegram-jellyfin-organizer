"""Configuração central de logging, com arquivo rotativo em disco."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from platformdirs import user_log_dir

APP_NAME = "TelegramJellyfinOrganizer"


def setup_logging(level: int = logging.INFO) -> None:
    log_dir = Path(user_log_dir(APP_NAME, appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Reduz verbosidade de bibliotecas de terceiros muito faladoras.
    logging.getLogger("telethon").setLevel(logging.WARNING)
