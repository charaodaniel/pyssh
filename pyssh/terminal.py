"""Detecção de terminais e abertura de sessões fora do processo do pyssh.

A sessão é iniciada com ``start_new_session=True`` (``setsid``), de modo que
o terminal e o ``ssh`` sobrevivem ao fechamento da interface gráfica.

Este módulo não importa nenhum módulo de interface gráfica.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Optional, Sequence

from .ssh_client import SSHError

# Ordem = preferência da busca por detecção. Cada entrada usa o comando base
# + o comando ssh. O terminal padrão do sistema tem prioridade sobre esta
# lista (ver detect_system_terminal).
TERMINALS = (
    ("kitty", ["kitty", "-e"]),
    ("konsole", ["konsole", "-e"]),
    ("xfce4-terminal", ["xfce4-terminal", "-x"]),
    ("alacritty", ["alacritty", "-e"]),
    ("gnome-terminal", ["gnome-terminal", "--"]),
    ("urxvt", ["urxvt", "-e"]),
    ("xterm", ["xterm", "-e"]),
)

# Argumento usado quando o terminal não está na tabela: convenção xterm
# (a maioria dos emuladores aceita ``-e``; os conhecidos têm entrada na
# tabela e usam o argumento próprio, ex.: gnome-terminal usa ``--``).
DEFAULT_EXEC_ARG = "-e"


# Sessões iniciadas: mantidas referenciadas até o programa terminar, para o
# GC não reiniciar o reaping e para permitir auditoria de PIDs.
_SESSIONS: List[subprocess.Popen] = []


class NoTerminalFound(SSHError):
    """Nenhum emulador de terminal compatível foi encontrado no sistema."""


def exec_args_for(executable: str) -> List[str]:
    """Argumento de execução do terminal ``executable`` (ex.: ``["-e"]``).

    Usa a entrada da tabela :data:`TERMINALS` quando o nome é conhecido;
    para terminais desconhecidos devolve a convenção xterm (``-e``).
    """
    name = os.path.basename(executable)
    for known, base in TERMINALS:
        if known == name:
            return list(base[1:])
    return [DEFAULT_EXEC_ARG]


def detect_system_terminal() -> Optional[List[str]]:
    """Retorna o terminal padrão do sistema, ou ``None`` se não houver.

    Ordem de detecção (prioridade decrescente):

    1. ``xdg-terminal-exec`` — implementação de referência da proposta de
       spec do freedesktop.org (configuração por desktop entries).
    2. ``$TERMINAL`` — convenção usada por i3, sway e outros WM.
    3. ``x-terminal-emulator`` — alternatives do Debian/Ubuntu.

    O valor deve ser um único nome de programa (a convenção de ``$TERMINAL``).
    """
    # Spec XDG: recebe o comando diretamente (sem argumento de execução);
    # ``--`` garante que os argumentos do ``ssh`` não sejam interpretados.
    path = shutil.which("xdg-terminal-exec")
    if path:
        return [path, "--"]

    env_terminal = os.environ.get("TERMINAL", "").strip()
    if env_terminal:
        path = shutil.which(env_terminal)
        if path:
            return [path] + exec_args_for(path)

    path = shutil.which("x-terminal-emulator")
    if path:
        # O alternative é um link; o alvo real tem o nome correto na tabela.
        return [path] + exec_args_for(os.path.realpath(path))

    return None


def find_terminal(configured: Optional[str] = None) -> Optional[List[str]]:
    """Retorna a base do comando do terminal, ou ``None`` se não houver.

    ``configured`` força um terminal específico (ex.: ``kitty``), vindo de
    ``settings.terminal``. Sem ``configured``, o terminal padrão do sistema
    é detectado (spec XDG / ``$TERMINAL`` / ``x-terminal-emulator``) antes
    de recorrer à lista :data:`TERMINALS`.
    """
    if configured:
        path = shutil.which(configured)
        if not path:
            return None
        return [path] + exec_args_for(path)

    system = detect_system_terminal()
    if system:
        return system

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
            "xfce4-terminal, alacritty, gnome-terminal ou xterm, ou informe "
            "um em settings.terminal."
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
    "detect_system_terminal",
    "exec_args_for",
    "find_terminal",
    "require_terminal",
    "spawn_session",
]
