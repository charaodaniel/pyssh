#!/usr/bin/env bash
# Monta dist/pyssh-<versão>-<arch>.AppImage a partir do portátil onedir.
# Requer: build-portable.sh já executado (este script o chama se faltar),
# mksquashfs (squashfs-tools) e appimagetool (baixa se não existir).
# Uso: packaging/build-appimage.sh
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=${VERSION:-$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)}
ARCH=${ARCH:-$(uname -m)}
PORTABLE=dist/pyssh-portable
APPDIR=dist/pyssh.AppDir
OUTPUT="dist/pyssh-$VERSION-$ARCH.AppImage"

[ -x "$PORTABLE/pyssh/pyssh" ] || packaging/build-portable.sh

rm -rf "$APPDIR"
mkdir -p "$APPDIR" dist
cp -a "$PORTABLE/pyssh" "$APPDIR/pyssh"
cp -a "$PORTABLE/pyssh-cli" "$APPDIR/pyssh-cli"
cp packaging/pyssh.desktop "$APPDIR/pyssh.desktop"
cp packaging/icons/pyssh-256.png "$APPDIR/pyssh.png"
# AppRun: GUI por padrão; `pyssh.AppImage cli ...` roda a CLI.
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
case "${1:-}" in
  cli) shift; exec "$HERE/pyssh-cli/pyssh-cli" "$@" ;;
  *)   exec "$HERE/pyssh/pyssh" "$@" ;;
esac
EOF
chmod +x "$APPDIR/AppRun"

# appimagetool: do PATH, de $APPIMAGETOOL, ou baixa o continuous release.
AIT=${APPIMAGETOOL:-}
if [ -z "$AIT" ]; then
    AIT=$(command -v appimagetool || true)
fi
if [ -z "$AIT" ]; then
    AIT="$HOME/.cache/appimagetool-$ARCH.AppImage"
    if [ ! -f "$AIT" ]; then
        mkdir -p "$(dirname "$AIT")"
        curl -fsSL -o "$AIT" \
            "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-$ARCH.AppImage"
    fi
    chmod +x "$AIT"
fi
# Sem FUSE o AppImage não roda direto: extrai e usa o AppRun de dentro.
if ! "$AIT" --help >/dev/null 2>&1; then
    echo "extraindo appimagetool (sem FUSE)..."
    TMPX=$(mktemp -d)
    if ! ( cd "$TMPX" && "$AIT" --appimage-extract >/dev/null 2>&1 ) \
        || [ ! -e "$TMPX/squashfs-root/AppRun" ]; then
        echo "erro: falha ao extrair appimagetool ($AIT)" >&2
        exit 1
    fi
    AIT="$TMPX/squashfs-root/AppRun"
fi

command -v mksquashfs >/dev/null 2>&1 || {
    echo "erro: mksquashfs ausente — instale squashfs-tools" >&2
    exit 1
}

ARCH="$ARCH" "$AIT" --comp gzip "$APPDIR" "$OUTPUT"
echo "appimage: $OUTPUT"
