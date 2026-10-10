#!/usr/bin/env bash
# Monta dist/pyssh-portable/{pyssh,pyssh-cli}/ — GUI e CLI, cada um onedir
# (executável + _internal/), com zip correspondente para distribuição.
# Uso: packaging/build-portable.sh   [PYINSTALLER=/caminho/pyinstaller]
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-$(command -v python3 || command -v python)}
PYINSTALLER=${PYINSTALLER:-}
if [ -z "$PYINSTALLER" ]; then
    if command -v pyinstaller >/dev/null 2>&1; then
        PYINSTALLER=pyinstaller
    elif [ -x .venv/bin/pyinstaller ]; then
        PYINSTALLER=.venv/bin/pyinstaller
    else
        echo "erro: pyinstaller ausente (pip install pyinstaller)" >&2
        exit 1
    fi
fi

# Dois specs separados: um spec/um EXE por aplicação (COLLECT com duas
# Análises colide o PYZ-00.pyz compartilhado — PYI-41745).
"$PYINSTALLER" --noconfirm --clean packaging/pyssh-gui.spec
"$PYINSTALLER" --noconfirm --clean packaging/pyssh-cli.spec

rm -rf dist/pyssh-portable
mkdir -p dist/pyssh-portable
mv dist/pyssh dist/pyssh-portable/pyssh
mv dist/pyssh-cli dist/pyssh-portable/pyssh-cli

# Cópia zipada para distribuição (mesmo conteúdo da pasta).
rm -f dist/pyssh-portable.zip
( cd dist && "$PYTHON" -m zipfile -c pyssh-portable.zip pyssh-portable )

echo "portátil: dist/pyssh-portable/{pyssh,pyssh-cli}/ (+ pyssh-portable.zip)"
