#!/usr/bin/env bash
# Instala o pyssh portátil adicionando os executáveis ao PATH do usuário.
#
#   ./packaging/portable-install.sh [pasta/pyssh-portable]
#
# Padrão: PREFIX=~/.local  →  ~/.local/bin/{pyssh,pyssh-cli} (symlinks)
# Sistema: PREFIX=/usr/local sudo ./packaging/portable-install.sh
# Desfazer: ./packaging/portable-install.sh --remove
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$SCRIPT_DIR/.." && pwd)
SRC=${1:-$REPO/dist/pyssh-portable}
PREFIX=${PREFIX:-$HOME/.local}
BINDIR=$PREFIX/bin

if [ "${1:-}" = "--remove" ]; then
    rm -f "$BINDIR/pyssh" "$BINDIR/pyssh-cli"
    echo "removidos: $BINDIR/pyssh $BINDIR/pyssh-cli"
    exit 0
fi

GUI_EXE=$SRC/pyssh/pyssh
CLI_EXE=$SRC/pyssh-cli/pyssh-cli
for exe in "$GUI_EXE" "$CLI_EXE"; do
    if [ ! -x "$exe" ]; then
        echo "erro: executável não encontrado: $exe (rode packaging/build-portable.sh)" >&2
        exit 1
    fi
done

mkdir -p "$BINDIR"
ln -sf "$GUI_EXE" "$BINDIR/pyssh"
ln -sf "$CLI_EXE" "$BINDIR/pyssh-cli"
echo "instalados: $BINDIR/pyssh -> $GUI_EXE"
echo "            $BINDIR/pyssh-cli -> $CLI_EXE"

case ":$PATH:" in
    *":$BINDIR:"*) echo "PATH já inclui $BINDIR" ;;
    *)
        echo "para usar agora, adicione ao PATH:"
        echo "  export PATH=\"$BINDIR:\$PATH\"   # (ou adicione ao ~/.bashrc)"
        ;;
esac
