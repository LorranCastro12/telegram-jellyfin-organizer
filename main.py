#!/usr/bin/env python3
"""Telegram → Jellyfin Organizer.

Aplicação desktop (PySide6) para navegar em grupos/canais do Telegram dos
quais você participa, selecionar arquivos de mídia e baixá-los já
organizados no padrão de pastas esperado pelo Jellyfin.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from config.settings import SettingsManager
from core.credentials import CredentialStore
from ui.main_window import MainWindow
from utils.logger import setup_logging
from utils.resources import resource_path

logger = logging.getLogger(__name__)


def _load_stylesheet(app: QApplication) -> None:
    qss_path = resource_path("ui", "styles", "dark_theme.qss")
    try:
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Não foi possível carregar o tema (%s); usando estilo padrão.", exc)


def _load_icon(app: QApplication) -> None:
    icon_path = resource_path("packaging", "assets", "icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    else:
        logger.debug("Ícone não encontrado em %s; usando o padrão do sistema.", icon_path)


def _self_test() -> int:
    """Checagem de sanidade do executável empacotado (`--self-test`).

    Existe por causa de um modo de falha específico do PyInstaller: o app
    congelado *abre* normalmente mesmo quando os arquivos de dados do
    `guessit`/`babelfish` ficaram de fora do bundle — só que aí
    `parse_filename` cai no fallback de regex silenciosamente e o usuário vê
    metadados piores sem nenhum erro. Um teste que falha alto é a única forma
    de pegar isso na esteira de build, principalmente no instalador do
    Windows, que é gerado em CI e não dá para conferir à mão.
    """
    from core.jellyfin_naming import parse_filename

    failures: list[str] = []

    # 1. guessit de verdade (não o fallback): só ele extrai 'screen_size'.
    try:
        from guessit import guessit

        guess = guessit("Sherlock.Holmes.S01E03.1080p.BluRay.x264.mkv")
        if str(guess.get("title", "")).lower() != "sherlock holmes":
            failures.append(f"guessit devolveu título inesperado: {guess.get('title')!r}")
        if guess.get("season") != 1 or guess.get("episode") != 3:
            failures.append(f"guessit errou temporada/episódio: {guess!r}")
    except Exception as exc:  # noqa: BLE001 - qualquer falha aqui é fatal
        failures.append(f"guessit indisponível no bundle: {exc!r}")

    # 2. O caminho que o app realmente usa.
    info = parse_filename("Nosferatu.1922.1080p.mkv")
    if info.title != "Nosferatu" or info.year != 1922:
        failures.append(f"parse_filename devolveu {info!r}")

    # 3. Recursos empacotados.
    qss = resource_path("ui", "styles", "dark_theme.qss")
    if not qss.exists() or not qss.read_text(encoding="utf-8").strip():
        failures.append(f"folha de estilo ausente ou vazia em {qss}")
    icon = resource_path("packaging", "assets", "icon.png")
    if not icon.exists():
        failures.append(f"ícone ausente em {icon}")

    # 4. Módulos do Qt que o spec poderia ter excluído demais.
    app = QApplication(sys.argv[:1])
    _load_stylesheet(app)
    if not app.styleSheet().strip():
        failures.append("folha de estilo não foi aplicada ao QApplication")
    try:
        from PySide6.QtCharts import QChart, QChartView  # noqa: F401

        QChartView(QChart())
    except Exception as exc:  # noqa: BLE001
        failures.append(f"QtCharts indisponível (painel de estatísticas quebraria): {exc!r}")

    # 5. Telethon e sua criptografia.
    try:
        from telethon import TelegramClient  # noqa: F401
        from telethon.crypto import AES  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        failures.append(f"Telethon indisponível no bundle: {exc!r}")

    if failures:
        for item in failures:
            print(f"FALHOU: {item}", file=sys.stderr)
        return 1
    print("self-test OK: guessit, recursos, QtCharts e Telethon operacionais.")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()

    setup_logging()
    logger.info("Iniciando Telegram Jellyfin Organizer")

    app = QApplication(sys.argv)
    app.setApplicationName("Telegram Jellyfin Organizer")
    app.setOrganizationName("TelegramJellyfinOrganizer")
    _load_stylesheet(app)
    _load_icon(app)

    credential_store = CredentialStore()
    settings_manager = SettingsManager()

    window = MainWindow(credential_store, settings_manager)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
