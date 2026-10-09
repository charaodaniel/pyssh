"""Armazenamento local: diretórios XDG, JSON atômico e utilitários de arquivo.

Separa os dados do código-fonte (Fase 6 do roadmap):

    ~/.config/pyssh/        settings.json · connections.json · keys.json
    ~/.local/share/pyssh/   history.jsonl (com rotação .1 .2 .3)

Convenções deste módulo:

* gravação de JSON sempre **atômica** (temporário + ``os.replace``);
* permissões restritas — 0700 nos diretórios, 0600 nos arquivos;
* nenhum segredo (senhas, passphrases, material de chave privada) é gravado.

Não importa nenhum outro módulo do ``pyssh``.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import tempfile
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

# Permissões restritas (dono).
DIR_MODE = 0o700
FILE_MODE = 0o600

CONFIG_SUBDIR = "pyssh"
DATA_SUBDIR = "pyssh"


class StorageError(RuntimeError):
    """Falha ao ler, validar ou gravar um arquivo de dados."""


def config_dir() -> str:
    """Diretório de configuração (``$XDG_CONFIG_HOME/pyssh`` ou equivalente)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, CONFIG_SUBDIR)


def data_dir() -> str:
    """Diretório de dados (``$XDG_DATA_HOME/pyssh`` ou equivalente)."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(base, DATA_SUBDIR)


def ensure_dir(path: str, mode: int = DIR_MODE) -> str:
    """Cria o diretório (e os pais) com permissões restritas; devolve o caminho."""
    try:
        os.makedirs(path, mode=mode, exist_ok=True)
    except OSError as exc:
        raise StorageError(f"Não foi possível criar o diretório {path}: {exc}") from None
    try:
        os.chmod(path, mode)
    except OSError:
        pass  # FS sem suporte a chmod não deve derrubar a aplicação.
    return path


def read_json(
    path: str,
    default: Any = None,
    expected: Tuple[type, ...] = (dict, list),
) -> Any:
    """Lê um arquivo JSON.

    * ausente → devolve ``default`` (cópia, para o chamador poder mutate);
    * corrompido ou de tipo inesperado → :class:`StorageError`.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return copy.deepcopy(default)
    except json.JSONDecodeError as exc:
        raise StorageError(f"Arquivo corrompido ({path}): {exc}") from None
    except OSError as exc:
        raise StorageError(f"Não foi possível ler {path}: {exc}") from None

    if expected and not isinstance(data, expected):
        raise StorageError(
            f"Estrutura inválida em {path}: esperado "
            f"{' ou '.join(t.__name__ for t in expected)}, obtido {type(data).__name__}."
        )
    return data


def write_json_atomic(path: str, data: Any, mode: int = FILE_MODE) -> str:
    """Grava JSON de forma atômica (nunca deixa arquivo pela metade)."""
    directory = os.path.dirname(path) or "."
    ensure_dir(directory)

    fd, tmp = tempfile.mkstemp(prefix=".pyssh-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise StorageError(f"Falha ao gravar {path}: {exc}") from None
    return path


def append_jsonl(path: str, record: Mapping[str, Any]) -> str:
    """Acrescenta um registro JSON em uma linha (JSON Lines)."""
    ensure_dir(os.path.dirname(path) or ".")
    fresh = not os.path.exists(path)
    line = json.dumps(dict(record), ensure_ascii=False) + "\n"
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
        if fresh:
            os.chmod(path, FILE_MODE)
    except OSError as exc:
        raise StorageError(f"Falha ao gravar em {path}: {exc}") from None
    return path


def read_jsonl(path: str) -> List[dict]:
    """Lê um arquivo JSON Lines; linhas inválidas são ignoradas uma a uma."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise StorageError(f"Não foi possível ler {path}: {exc}") from None

    records: List[dict] = []
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError:
            continue  # linha corrompida não invalida o restante do arquivo
        if isinstance(item, dict):
            records.append(item)
    return records


def write_csv(
    path: str,
    rows: Iterable[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> str:
    """Grava um CSV com cabeçalho (usado na exportação do histórico)."""
    ensure_dir(os.path.dirname(path) or ".")
    try:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {key: ("" if row.get(key) is None else row.get(key)) for key in fieldnames}
                )
    except OSError as exc:
        raise StorageError(f"Falha ao gravar {path}: {exc}") from None
    return path


def private_key_warning(path: str) -> Optional[str]:
    """Avisa quando um arquivo de chave privada está legível por outros usuários.

    Devolve ``None`` quando as permissões estão adequadas (``600`` ou menos)
    ou uma mensagem de diagnóstico — nunca altera o arquivo.
    """
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        return None
    if mode & 0o077:
        return (
            f"permissões amplas ({oct(mode)}): outros usuários podem ler {path}. "
            f"Use: chmod 600 {path}"
        )
    return None


__all__ = [
    "DIR_MODE",
    "FILE_MODE",
    "StorageError",
    "append_jsonl",
    "config_dir",
    "data_dir",
    "ensure_dir",
    "private_key_warning",
    "read_json",
    "read_jsonl",
    "write_csv",
    "write_json_atomic",
]
