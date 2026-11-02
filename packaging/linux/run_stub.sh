#!/bin/sh
# Cabeçalho do instalador auto-extraível (.run).
#
# O arquivo final é este script com um tar.gz concatenado logo após a linha
# __PAYLOAD_BELOW__. O shell para de interpretar no `exit` antes do marcador,
# então os bytes binários do arquivo nunca são executados — é a mesma técnica
# usada pelo makeself e pelos instaladores da NVIDIA.
#
# Responsabilidade daqui: extrair o bundle para um diretório temporário com
# espaço suficiente e entregar o controle ao assistente gráfico.

set -eu

APP_NAME="Telegram Jellyfin Organizer"
BUNDLE_NAME="TelegramJellyfinOrganizer"
NEEDED_KB=__NEEDED_KB__

SELF=$(readlink -f "$0" 2>/dev/null || echo "$0")

if [ ! -r "$SELF" ]; then
    echo "Erro: não consegui ler o próprio instalador ($SELF)." >&2
    exit 1
fi

# Sem servidor gráfico não há assistente — avisa em vez de falhar com um
# erro críptico do Qt.
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    echo "Erro: este é um instalador gráfico e precisa de uma sessão de desktop." >&2
    echo "Se você está em um servidor sem interface, use o pacote .deb." >&2
    exit 1
fi

# Escolhe um destino de extração que realmente comporte o bundle: /tmp é
# tmpfs (RAM) em muitas distros e costuma ser pequeno demais.
pick_tmp_root() {
    for candidate in "${TMPDIR:-}" /tmp "${XDG_CACHE_HOME:-$HOME/.cache}" "$HOME"; do
        [ -n "$candidate" ] || continue
        [ -d "$candidate" ] || continue
        [ -w "$candidate" ] || continue
        avail=$(df -Pk "$candidate" 2>/dev/null | awk 'NR==2 {print $4}')
        [ -n "$avail" ] || continue
        if [ "$avail" -gt "$NEEDED_KB" ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

TMP_ROOT=$(pick_tmp_root) || {
    echo "Erro: não há espaço livre suficiente para descompactar o instalador." >&2
    echo "São necessários cerca de $((NEEDED_KB / 1024)) MB temporários." >&2
    exit 1
}

WORK=$(mktemp -d "$TMP_ROOT/tjo-setup-XXXXXX")
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT INT TERM HUP

printf 'Preparando o instalador do %s...\n' "$APP_NAME"

ARCHIVE_LINE=$(awk '/^__PAYLOAD_BELOW__$/ { print NR + 1; exit 0; }' "$SELF")
if [ -z "$ARCHIVE_LINE" ]; then
    echo "Erro: instalador corrompido (payload não encontrado)." >&2
    exit 1
fi

if ! tail -n +"$ARCHIVE_LINE" "$SELF" | tar xzf - -C "$WORK"; then
    echo "Erro: falha ao descompactar o instalador (download incompleto?)." >&2
    exit 1
fi

INSTALLER="$WORK/$BUNDLE_NAME/install"
if [ ! -x "$INSTALLER" ]; then
    chmod +x "$INSTALLER" 2>/dev/null || true
fi
if [ ! -x "$INSTALLER" ]; then
    echo "Erro: assistente de instalação não encontrado no pacote." >&2
    exit 1
fi

"$INSTALLER" "$@"
exit $?

__PAYLOAD_BELOW__
