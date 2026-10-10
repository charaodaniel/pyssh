#!/usr/bin/env bash
# Gera o tarball de fonte pyssh-<versão>.tar.gz com raiz pyssh-<versão>/.
# Usado pelo PKGBUILD (Arch), pelo spec do RPM (Fedora) e pelo CI.
# Uso: packaging/make-source-tarball.sh [caminho/saída.tar.gz]
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=${VERSION:-$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)}
OUT=${1:-dist/pyssh-$VERSION.tar.gz}
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/pyssh-$VERSION" "$(dirname "$OUT")"
cp -r pyssh main.py cli.py packaging README.md ROADMAP.md LICENSE pyproject.toml \
    "$STAGE/pyssh-$VERSION/"
find "$STAGE" \( -name '__pycache__' -o -name '*.pyc' \) -prune -exec rm -rf {} + 2>/dev/null || true

tar -C "$STAGE" --owner=0 --group=0 -czf "$OUT" "pyssh-$VERSION"
echo "$OUT"
