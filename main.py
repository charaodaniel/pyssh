#!/usr/bin/env python3
"""pyssh — interface gráfica (Tkinter/ttk).

Uso:
    pyssh            # abre a janela
    pyssh --selftest # abre e fecha a janela sozinho (verificação automatizada)

Requisito: Tkinter do sistema (Arch/CachyOS: `sudo pacman -S tk`).
A interface não é obrigatória para o núcleo nem para o `pyssh-cli`.
"""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="pyssh",
        description="Interface gráfica para localizar dispositivos SSH na rede local.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="abre e fecha a janela automaticamente (verificação sem interação)",
    )
    args = parser.parse_args(argv)

    try:
        import tkinter  # noqa: F401
    except Exception as exc:  # ImportError + falhas de biblioteca compartilhada
        print(
            "erro: Tkinter indisponível neste sistema "
            f"({exc}). Instale o pacote 'tk' (Arch/CachyOS: sudo pacman -S tk). "
            "A CLI continua funcionando: pyssh-cli --help",
            file=sys.stderr,
        )
        return 4

    from pyssh.gui import run_app

    return run_app(selftest=args.selftest)


if __name__ == "__main__":
    sys.exit(main())
