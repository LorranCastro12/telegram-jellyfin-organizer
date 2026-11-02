# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller — gera o bundle onedir do app.

Duas decisões não óbvias aqui:

1. **Dois executáveis em um único COLLECT.** No Linux o bundle carrega tanto o
   app quanto o assistente gráfico de instalação (`install`). Ambos são
   PySide6, então colocá-los no mesmo diretório faz o PyInstaller deduplicar
   as bibliotecas do Qt — um Qt em vez de dois (~130 MB em vez de ~260 MB).
   No Windows esse alvo não é gerado: quem faz o papel de wizard lá é o Inno
   Setup, que já é nativo.

2. **Coleta explícita de dados de `guessit`/`babelfish`.** Essas bibliotecas
   leem arquivos de configuração e tabelas de idioma de dentro do próprio
   pacote. Sem `collect_data_files` elas importam, mas quebram em runtime na
   primeira análise de nome de arquivo — o tipo de erro que só aparece depois
   de empacotado.

Uso (não chame diretamente; use os scripts em packaging/):
    pyinstaller packaging/app.spec --noconfirm
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

PROJECT_ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from version import APP_ID, APP_NAME, __version__  # noqa: E402

IS_WINDOWS = sys.platform.startswith("win")
BUNDLE_NAME = "TelegramJellyfinOrganizer"
APP_EXE_NAME = "TelegramJellyfinOrganizer" if IS_WINDOWS else APP_ID
ASSETS = PROJECT_ROOT / "packaging" / "assets"


def _safe_metadata(dist: str):
    """`copy_metadata` explode se a distribuição não estiver instalada."""
    try:
        return copy_metadata(dist)
    except Exception:  # noqa: BLE001 - metadado é opcional, não vale abortar o build
        return []


datas = [
    (str(PROJECT_ROOT / "ui" / "styles" / "dark_theme.qss"), "ui/styles"),
    (str(ASSETS / "icon.png"), "packaging/assets"),
    (str(PROJECT_ROOT / "LICENSE"), "."),
]
for package in ("guessit", "babelfish", "rebulk"):
    datas += collect_data_files(package)
    datas += _safe_metadata(package)

hiddenimports = [
    "pyaes",
    "rsa",
    # Telethon escolhe a implementação de criptografia em runtime.
    "telethon.crypto",
]
# guessit/babelfish/rebulk carregam regras e conversores de idioma por entry
# point (`babelfish.converters.alpha2` e companhia), o que a análise estática
# do PyInstaller não enxerga. Sem isto o app abre, mas o parsing de nomes cai
# no fallback de regex — veja `main.py --self-test`.
for package in ("guessit", "babelfish", "babelfish.converters", "rebulk"):
    hiddenimports += collect_submodules(package)
# keyring descobre os backends por entry point; congelado, isso não acontece
# sozinho — sem isto o app cai sempre no fallback de arquivo .key.
hiddenimports += collect_submodules("keyring.backends")

# Módulos grandes do Qt que o app comprovadamente não usa (ele usa apenas
# QtCore/QtGui/QtWidgets/QtCharts). Cortar isso reduz o instalador pela metade.
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtTest",
    "tkinter",
    "matplotlib",
    "pytest",
]

app_analysis = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
app_pyz = PYZ(app_analysis.pure)

app_exe = EXE(
    app_pyz,
    app_analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX corrompe bibliotecas do Qt em algumas versões; não vale o risco.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS / "icon.ico") if IS_WINDOWS else None,
)

collect_args = [app_exe, app_analysis.binaries, app_analysis.datas]

if not IS_WINDOWS:
    installer_analysis = Analysis(
        [str(PROJECT_ROOT / "packaging" / "linux" / "installer_wizard.py")],
        pathex=[str(PROJECT_ROOT)],
        binaries=[],
        datas=[
            (str(ASSETS / "icon.png"), "packaging/assets"),
            (str(ASSETS / "icon_256.png"), "packaging/assets"),
            (str(ASSETS / "wizard_side.png"), "packaging/assets"),
            (str(PROJECT_ROOT / "LICENSE"), "."),
        ],
        hiddenimports=[],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=excludes + ["PySide6.QtCharts"],
        noarchive=False,
        optimize=0,
    )
    installer_pyz = PYZ(installer_analysis.pure)
    installer_exe = EXE(
        installer_pyz,
        installer_analysis.scripts,
        [],
        exclude_binaries=True,
        name="install",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    # Mesmo COLLECT → Qt deduplicado entre app e assistente.
    collect_args += [installer_exe, installer_analysis.binaries, installer_analysis.datas]

coll = COLLECT(
    *collect_args,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=BUNDLE_NAME,
)
