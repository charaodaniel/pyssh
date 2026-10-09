"""Detecção de terminais e abertura de sessões fora do processo do pyssh.

A sessão é iniciada com ``start_new_session=True`` (``setsid``), de modo que
o terminal e o ``ssh`` sobrevivem ao fechamento da interface gráfica.

Este módulo não importa nenhum módulo de interface gráfica.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional, Sequence

from .ssh_client import SSHError

# Ordem = preferência. Cada entrada usa o comando base + o comando ssh.
TERMINALS = (
    ("kitty", ["kitty", "-e"]),
    ("konsole", ["konsole", "-e"]),
    ("xfce4-terminal", ["xfce4-terminal", "-x"]),
    ("alacritty", ["alacritty", "-e"]),
    ("gnome-terminal", ["gnome-terminal", "--"]),
    ("urxvt", ["urxvt", "-e"]),
    ("xterm", ["xterm", "-e"]),
)


# Sessões iniciadas: mantidas referenciadas até o programa terminar, para o
# GC não reiniciar o reaping e para permitir auditoria de PIDs.
_SESSIONS: List[subprocess.Popen] = []


class NoTerminalFound(SSHError):
    """Nenhum emulador de terminal compatível foi encontrado no sistema."""


def find_terminal(configured: Optional[str] = None) -> Optional[List[str]]:
    """Retorna a base do comando do terminal, ou ``None`` se não houver.

    ``configured`` permite forçar um terminal específico (ex.: ``kitty``).
    """
    if configured:
        path = shutil.which(configured)
        return [path] if path else None

    for _name, base in TERMINALS:
        path = shutil.which(base[0])
        if path:
            return [path] + list(base[1:])
    return None


def require_terminal(configured: Optional[str] = None) -> List[str]:
    """Igual a :func:`find_terminal`, mas levanta :class:`NoTerminalFound`."""
    terminal = find_terminal(configured)
    if not terminal:
        raise NoTerminalFound(
            "Nenhum terminal compatível encontrado. Instale kitty, konsole, "
            "xfce4-terminal, alacritty, gnome-terminal ou xterm."
        )
    return terminal


def build_terminal_command(terminal: Sequence[str], ssh_command: Sequence[str]) -> List[str]:
    """Junta a base do terminal com o comando ``ssh`` (sem shell)."""
    if not terminal:
        raise NoTerminalFound("Terminal não informado.")
    return [str(part) for part in terminal] + [str(part) for part in ssh_command]


def spawn_session(command: Sequence[str]) -> int:
    """Inicia a sessão em um novo grupo de processos (sobrevive ao pyssh).

    Devolve o PID do processo iniciado. A sessão é totalmente interativa:
    o terminal recebe stdin/stdout/stderr reais.
    """
    if not command:
        raise SSHError("Comando de sessão vazio.")
    try:
        process = subprocess.Popen(
            [str(part) for part in command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        raise NoTerminalFound("Executável do terminal não encontrado.") from None
    except OSError as exc:
        raise SSHError(f"Falha ao iniciar o terminal: {exc}") from None
    _SESSIONS.append(process)
    return process.pid


__all__ = [
    "NoTerminalFound",
    "TERMINALS",
    "build_terminal_command",
    "find_terminal",
    "require_terminal",
    "spawn_session",
]
