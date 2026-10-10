# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller — pyssh CLI (onedir portátil: ``pyssh-cli`` + ``_internal/``).

Um spec por aplicação: cada EXE precisa do próprio PYZ/Análise — dois EXEs
num mesmo COLLECT colidem o ``PYZ-00.pyz`` compartilhado (PYI-41745).

    pyinstaller --noconfirm --clean packaging/pyssh-cli.spec
"""

import sys
from pathlib import Path

PKG = Path(SPECPATH).resolve()
ROOT = PKG.parent

DATAS = [
    (str(ROOT / "pyssh" / "icon.png"), "pyssh"),
    (str(ROOT / "pyssh" / "watermark.png"), "pyssh"),
]

a = Analysis(
    [str(ROOT / "cli.py")],
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    noarchive=False,
)

pyz = PYZ(a.pure)  # obrigatório: sem ele o EXE falha com PYI-41745

exe_kwargs = {"name": "pyssh-cli", "console": True, "strip": False, "upx": False}
if sys.platform == "win32":
    exe_kwargs["icon"] = [str(PKG / "icons" / "pyssh.ico")]

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **exe_kwargs)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="pyssh-cli")
