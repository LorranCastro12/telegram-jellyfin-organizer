#!/usr/bin/env bash
# Gera os artefatos de distribuição para Linux:
#
#   dist/TelegramJellyfinOrganizer-<versão>-linux-<arch>.run   assistente gráfico
#   dist/telegram-jellyfin-organizer_<versão>_<arch>.deb       pacote Debian/Ubuntu
#
# Uso:  ./packaging/linux/build.sh [--skip-deb]
#
# Pré-requisitos: as dependências de requirements-build.txt instaladas no
# Python atual (de preferência num venv) e `dpkg-deb` para o .deb.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
fi

SKIP_DEB=0
for arg in "$@"; do
    case "$arg" in
        --skip-deb) SKIP_DEB=1 ;;
        *) echo "Argumento desconhecido: $arg" >&2; exit 2 ;;
    esac
done

VERSION="$("$PYTHON" -c 'import version; print(version.__version__)')"
APP_ID="$("$PYTHON" -c 'import version; print(version.APP_ID)')"
APP_NAME="$("$PYTHON" -c 'import version; print(version.APP_NAME)')"
DESCRIPTION="$("$PYTHON" -c 'import version; print(version.DESCRIPTION)')"
HOMEPAGE="$("$PYTHON" -c 'import version; print(version.HOMEPAGE)')"
BUNDLE_NAME="TelegramJellyfinOrganizer"
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"

echo "==> Construindo $APP_NAME $VERSION ($ARCH)"

# ---------------------------------------------------------------------------
# 1. Assets visuais (ícone/BMPs). Baratos de gerar e evitam build com ícone
#    desatualizado se alguém mexer no make_icon.py.
# ---------------------------------------------------------------------------
echo "==> Gerando assets"
"$PYTHON" packaging/assets/make_icon.py

# ---------------------------------------------------------------------------
# 2. Bundle do PyInstaller (app + assistente compartilhando o Qt)
# ---------------------------------------------------------------------------
echo "==> Empacotando com PyInstaller"
rm -rf build "dist/$BUNDLE_NAME"
"$PYTHON" -m PyInstaller packaging/app.spec --noconfirm --distpath dist --workpath build

BUNDLE_DIR="dist/$BUNDLE_NAME"
[ -d "$BUNDLE_DIR" ] || { echo "Bundle não foi gerado em $BUNDLE_DIR" >&2; exit 1; }
[ -x "$BUNDLE_DIR/$APP_ID" ] || { echo "Executável do app ausente no bundle" >&2; exit 1; }
[ -x "$BUNDLE_DIR/install" ] || { echo "Assistente de instalação ausente no bundle" >&2; exit 1; }

# Um bundle incompleto abre normalmente e só falha quando o usuário tenta
# organizar um arquivo; melhor quebrar o build. Veja `main.py --self-test`.
echo "==> Verificando o bundle (self-test)"
if ! QT_QPA_PLATFORM=offscreen "$BUNDLE_DIR/$APP_ID" --self-test; then
    echo "O self-test do bundle falhou — nada será empacotado." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Instalador auto-extraível (.run)
# ---------------------------------------------------------------------------
echo "==> Montando o instalador .run"
RUN_NAME="$BUNDLE_NAME-$VERSION-linux-$ARCH.run"
PAYLOAD="build/payload.tar.gz"

tar czf "$PAYLOAD" -C dist "$BUNDLE_NAME"

# Espaço temporário necessário = bundle descompactado + folga.
NEEDED_KB=$(( $(du -sk "$BUNDLE_DIR" | cut -f1) + 51200 ))

sed "s/__NEEDED_KB__/$NEEDED_KB/" packaging/linux/run_stub.sh > "build/stub.sh"
cat "build/stub.sh" "$PAYLOAD" > "dist/$RUN_NAME"
chmod +x "dist/$RUN_NAME"

echo "    dist/$RUN_NAME ($(du -h "dist/$RUN_NAME" | cut -f1))"

# ---------------------------------------------------------------------------
# 4. Pacote .deb
# ---------------------------------------------------------------------------
if [ "$SKIP_DEB" -eq 1 ]; then
    echo "==> .deb pulado (--skip-deb)"
    exit 0
fi
if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "==> dpkg-deb não encontrado; pulando o .deb"
    exit 0
fi

echo "==> Montando o pacote .deb"
DEB_ROOT="build/debroot"
rm -rf "$DEB_ROOT"
mkdir -p "$DEB_ROOT/DEBIAN" \
         "$DEB_ROOT/opt" \
         "$DEB_ROOT/usr/bin" \
         "$DEB_ROOT/usr/share/applications" \
         "$DEB_ROOT/usr/share/doc/$APP_ID"

cp -a "$BUNDLE_DIR" "$DEB_ROOT/opt/$APP_ID"
# O assistente gráfico não faz sentido dentro do .deb: quem instala aqui é o apt.
rm -f "$DEB_ROOT/opt/$APP_ID/install"

ln -s "/opt/$APP_ID/$APP_ID" "$DEB_ROOT/usr/bin/$APP_ID"

for size in 16 24 32 48 64 128 256 512; do
    icon_src="packaging/assets/icon_${size}.png"
    [ -f "$icon_src" ] || continue
    icon_dir="$DEB_ROOT/usr/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$icon_dir"
    cp "$icon_src" "$icon_dir/$APP_ID.png"
done

cat > "$DEB_ROOT/usr/share/applications/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=$DESCRIPTION
Exec=/opt/$APP_ID/$APP_ID %U
Icon=$APP_ID
Terminal=false
StartupWMClass=$APP_ID
Categories=AudioVideo;Video;Network;FileTransfer;
Keywords=telegram;jellyfin;download;midia;
EOF

cp LICENSE "$DEB_ROOT/usr/share/doc/$APP_ID/copyright"

INSTALLED_KB=$(du -sk "$DEB_ROOT" | cut -f1)

cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $APP_ID
Version: $VERSION
Section: video
Priority: optional
Architecture: $ARCH
Installed-Size: $INSTALLED_KB
Maintainer: LorranCastro12 <lorransllima2@gmail.com>
Homepage: $HOMEPAGE
Depends: libc6
Recommends: libglib2.0-0, libgl1, libxkbcommon0, libfontconfig1, libdbus-1-3
Description: $APP_NAME
 $DESCRIPTION.
 .
 Navega nos grupos e canais do Telegram dos quais voce ja e membro, analisa o
 nome de cada arquivo para extrair titulo, ano, temporada e episodio, e baixa
 tudo ja na estrutura de pastas que o Jellyfin reconhece automaticamente.
 .
 Todas as dependencias (Python, Qt, Telethon) vao embutidas no pacote.
EOF

# As dependências do Qt entram como Recommends de propósito: os nomes desses
# pacotes mudaram entre releases do Ubuntu (libglib2.0-0 virou libglib2.0-0t64
# no 24.04). Como Depends, isso tornaria o .deb não-instalável em metade das
# distros; como Recommends, o apt instala quando existe e ignora quando não.

cat > "$DEB_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF

cat > "$DEB_ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF

chmod 755 "$DEB_ROOT/DEBIAN/postinst" "$DEB_ROOT/DEBIAN/postrm"

DEB_NAME="${APP_ID}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$DEB_ROOT" "dist/$DEB_NAME" >/dev/null

echo "    dist/$DEB_NAME ($(du -h "dist/$DEB_NAME" | cut -f1))"
echo "==> Pronto."
