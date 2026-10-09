"""Preparação e inicialização de sessões SSH com o OpenSSH do sistema.

A autenticação fica sempre sob controle do usuário: nenhuma senha, chave ou
credencial é armazenada ou transmitida por este módulo.

Este módulo não importa nenhum módulo de interface gráfica.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from typing import Iterable, List, Optional, Sequence

from .settings import DEFAULT_PORT, SettingsError, validate_port


class SSHError(RuntimeError):
    """Erro ao preparar ou iniciar uma sessão SSH."""


class SSHClientNotFound(SSHError):
    """O cliente OpenSSH (``ssh``) não está instalado ou não foi encontrado."""


def find_ssh() -> Optional[str]:
    """Caminho do executável ``ssh`` ou ``None`` se não existir."""
    return shutil.which("ssh")


def require_ssh() -> str:
    """Retorna o caminho do ``ssh`` ou levanta :class:`SSHClientNotFound`."""
    path = find_ssh()
    if not path:
        raise SSHClientNotFound(
            "Cliente OpenSSH ('ssh') não encontrado. Instale o pacote 'openssh' do sistema."
        )
    return path


def build_command(
    host: str,
    user: Optional[str] = None,
    port: int = DEFAULT_PORT,
    extra: Sequence[str] = (),
) -> List[str]:
    """Monta o comando ``ssh`` como lista de argumentos (sem shell).

    Levanta :class:`SSHError` para porta inválida e
    :class:`SSHClientNotFound` quando o ``ssh`` não está disponível.
    """
    binary = require_ssh()

    try:
        port = validate_port(port)
    except SettingsError as exc:
        raise SSHError(str(exc)) from None

    command: List[str] = [binary, "-p", str(port)]
    if user:
        command += ["-l", str(user)]
    command += [str(arg) for arg in extra]
    command.append(str(host))
    return command


def format_command(command: Iterable[str]) -> str:
    """Representação legível e segura do comando (para exibição/log)."""
    return shlex.join([str(part) for part in command])


def run_interactive(command: Sequence[str]) -> int:
    """Executa o comando herdando o terminal atual (sessão interativa).

    Devolve o código de saída do processo. ``255`` indica falha do próprio
    ``ssh`` (conexão, autenticação ou configuração).
    """
    try:
        return subprocess.call([str(part) for part in command])
    except FileNotFoundError:
        raise SSHClientNotFound(
            "Cliente OpenSSH ('ssh') não encontrado. Instale o pacote 'openssh' do sistema."
        ) from None
    except OSError as exc:
        raise SSHError(f"Falha ao iniciar o ssh: {exc}") from None


__all__ = [
    "SSHClientNotFound",
    "SSHError",
    "build_command",
    "find_ssh",
    "format_command",
    "require_ssh",
    "run_interactive",
]
