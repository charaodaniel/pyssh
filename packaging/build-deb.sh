#!/usr/bin/env bash
# Monta dist/pyssh_<versão>-all.deb (Debian/Ubuntu).
# Usa dpkg-deb quando existe; senão monta o .deb manualmente com ar+tar
# (formato: debian-binary + control.tar.gz + data.tar.gz).
# Uso: packaging/build-deb.sh
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=${VERSION:-$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)}
OUT="dist/pyssh_${VERSION}_all.deb"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

DEST=$STAGE/data
CTRL=$STAGE/control
mkdir -p "$DEST/usr/lib/pyssh" "$DEST/usr/bin" "$CTRL" dist

# Código-fonte instalável em /usr/lib/pyssh (wrappers resolvem o PYTHONPATH).
cp -r pyssh "$DEST/usr/lib/pyssh/pyssh"
cp main.py cli.py LICENSE README.md "$DEST/usr/lib/pyssh/"
find "$DEST" \( -name '__pycache__' -o -name '*.pyc' \) -prune -exec rm -rf {} + 2>/dev/null || true

install -m755 packaging/wrappers/pyssh     "$DEST/usr/bin/pyssh"
install -m755 packaging/wrappers/pyssh-cli "$DEST/usr/bin/pyssh-cli"
install -Dm644 packaging/pyssh.desktop "$DEST/usr/share/applications/pyssh.desktop"
install -Dm644 packaging/icons/pyssh-256.png "$DEST/usr/share/icons/hicolor/256x256/apps/pyssh.png"
install -Dm644 packaging/icons/pyssh-128.png "$DEST/usr/share/icons/hicolor/128x128/apps/pyssh.png"
install -Dm644 packaging/icons/pyssh-48.png  "$DEST/usr/share/icons/hicolor/48x48/apps/pyssh.png"
install -Dm644 LICENSE "$DEST/usr/share/doc/pyssh/copyright"
install -Dm644 README.md "$DEST/usr/share/doc/pyssh/README.md"

INSTALLED_SIZE=$(du -sk "$DEST" | cut -f1)
cat > "$CTRL/control" <<EOF
Package: pyssh
Version: $VERSION
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-tk, openssh-client
Installed-Size: $INSTALLED_SIZE
Maintainer: daniel <charaodaniel@users.noreply.github.com>
Homepage: https://github.com/charaodaniel/pyssh
Description: Localiza dispositivos SSH na rede local e abre sessões
 Varre a rede local pela porta SSH (padrão 8022, cenário Termux/Android),
 mantém conexões salvas, referências a chaves e histórico de atividades.
 Inclui a interface gráfica (pyssh) e a linha de comando (pyssh-cli).
EOF

mkdir -p dist
if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --build --root-owner-group "$DEST" "$OUT"
else
    # Fallback portátil: .deb é apenas um arquivo `ar` com três membros.
    tar -C "$DEST" --owner=0 --group=0 -czf "$STAGE/data.tar.gz" .
    tar -C "$CTRL"  --owner=0 --group=0 -czf "$STAGE/control.tar.gz" control
    echo "2.0" > "$STAGE/debian-binary"
    rm -f "$OUT"
    ( cd "$STAGE" && ar rc "$OLDPWD/$OUT" debian-binary control.tar.gz data.tar.gz )
fi

echo "deb: $OUT"
