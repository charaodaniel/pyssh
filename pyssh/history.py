"""Histórico de atividades em JSON Lines (Fase 5 do roadmap).

Cada evento é uma linha JSON com os campos:

    timestamp · event · connection_id · address · port · status · message

O registro distingue **tentativa iniciada**, **sessão iniciada** e **falha**;
o ``pyssh`` nunca declara "autenticado" porque não possui confirmação
confiável disso — a autenticação é do próprio OpenSSH.

Garantias:

* nunca grava senhas, passphrases ou material de chave privada;
* ``record`` propaga erros de gravação; ``record_safe`` é o variant que
  apenas reporta ``False`` (usado onde uma falha de disco não pode derrubar
  a interface);
* arquivos corrompidos são tolerados linha a linha (leitura tolerante);
* rotação por tamanho antes de cada gravação (``MAX_BYTES``).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .storage import (
    StorageError,
    append_jsonl,
    data_dir,
    read_jsonl,
    write_csv,
)

HISTORY_FILENAME = "history.jsonl"

# Limite de tamanho do arquivo ativo e quantidade de rotações retidas.
MAX_BYTES = 1_048_576  # 1 MiB
KEEP_ROTATED = 3

# Ordem dos campos no CSV exportado.
FIELDS: Sequence[str] = (
    "timestamp",
    "event",
    "connection_id",
    "address",
    "port",
    "status",
    "message",
)

_MAX_MESSAGE = 1000

# Tipos de evento reconhecidos (documentados em `pyssh-cli history fields`).
EVENT_TYPES: Sequence[str] = (
    "scan_started",
    "scan_finished",
    "device_found",
    "connection_attempt",
    "connection_created",
    "connection_updated",
    "connection_deleted",
    "session_started",
    "session_finished",
    "session_error",
    "key_registered",
    "key_updated",
    "key_removed",
    "key_generated",
    "history_exported",
    "history_cleared",
)


class HistoryError(RuntimeError):
    """Falha ao gravar, consultar, exportar ou limpar o histórico."""


def history_path() -> str:
    """Caminho do arquivo ativo do histórico."""
    return os.path.join(data_dir(), HISTORY_FILENAME)


def _rotated_paths(path: str) -> List[str]:
    """Caminhos rotacionados, do mais antigo ao mais novo."""
    return [f"{path}.{n}" for n in range(KEEP_ROTATED, 0, -1)]


def _rotate_if_needed(path: str, max_bytes: int) -> None:
    try:
        if not os.path.exists(path) or os.path.getsize(path) < max_bytes:
            return
    except OSError:
        return

    rotated = _rotated_paths(path)
    try:
        # Descarta a mais antiga; depois desloca cada uma para a seguinte.
        if os.path.exists(rotated[-1]):
            os.unlink(rotated[-1])
        for index in range(len(rotated) - 1):
            current = rotated[index]
            if os.path.exists(current):
                os.replace(current, rotated[index + 1])
        os.replace(path, rotated[0])
    except OSError as exc:
        raise HistoryError(f"Falha na rotação do histórico: {exc}") from None


def record(
    event: str,
    *,
    connection_id: Optional[str] = None,
    address: Optional[str] = None,
    port: Optional[int] = None,
    status: Optional[str] = None,
    message: str = "",
    path: Optional[str] = None,
    max_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    """Registra um evento; devolve o registro gravado.

    Levanta :class:`HistoryError` quando a gravação falha (sem permissão,
    disco cheio etc.).
    """
    if not event or not isinstance(event, str):
        raise HistoryError("Tipo de evento do histórico não informado.")

    text = str(message or "")
    if len(text) > _MAX_MESSAGE:
        text = text[: _MAX_MESSAGE - 1] + "…"

    entry: Dict[str, Any] = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": event,
        "connection_id": connection_id,
        "address": address,
        "port": port,
        "status": status,
        "message": text,
    }

    target = path or history_path()
    limit = MAX_BYTES if max_bytes is None else max_bytes
    try:
        _rotate_if_needed(target, limit)
        append_jsonl(target, entry)
    except (StorageError, OSError) as exc:
        raise HistoryError(str(exc)) from None
    return entry


def record_safe(
    event: str,
    *,
    connection_id: Optional[str] = None,
    address: Optional[str] = None,
    port: Optional[int] = None,
    status: Optional[str] = None,
    message: str = "",
    path: Optional[str] = None,
) -> bool:
    """Igual a :func:`record` mas devolve ``False`` em vez de levantar erro."""
    try:
        record(
            event,
            connection_id=connection_id,
            address=address,
            port=port,
            status=status,
            message=message,
            path=path,
        )
    except HistoryError:
        return False
    return True


def events(
    path: Optional[str] = None,
    *,
    event: Optional[str] = None,
    address: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    connection_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Consulta o histórico (arquivo ativo + rotações), do mais antigo ao mais novo.

    Filtros (todos opcionais e combináveis):

    * ``event`` / ``status`` / ``connection_id`` — igualdade exata;
    * ``address`` — correspondência por substring, sem diferenciar maiúsculas;
    * ``since`` / ``until`` — limites de data/hora comparados
      lexicograficamente com o ISO 8601 (``AAAA-MM-DD`` funciona);
    * ``limit`` — mantém apenas os N registros mais recentes após o filtro.
    """
    target = path or history_path()
    records: List[Dict[str, Any]] = []
    for candidate in _rotated_paths(target) + [target]:
        try:
            records.extend(read_jsonl(candidate))
        except StorageError:
            # Rotação ilegível não impede a leitura do restante.
            continue

    def matches(item: Mapping[str, Any]) -> bool:
        if event is not None and item.get("event") != event:
            return False
        if status is not None and item.get("status") != status:
            return False
        if connection_id is not None and item.get("connection_id") != connection_id:
            return False
        if address is not None:
            needle = str(item.get("address") or "")
            if address.lower() not in needle.lower():
                return False
        stamp = str(item.get("timestamp") or "")
        if since is not None and stamp < since:
            return False
        if until is not None and stamp > until + "\x7f":
            return False
        return True

    filtered = [item for item in records if matches(item)]
    if limit is not None and limit >= 0:
        filtered = filtered[-limit:] if limit else []
    return filtered


def export(
    rows: Sequence[Mapping[str, Any]],
    destination: str,
    fmt: str = "csv",
) -> str:
    """Exporta seleção do histórico para ``csv`` ou ``jsonl``.

    O destino é um arquivo novo de exportação (nunca o histórico original).
    Levanta :class:`HistoryError` para formato desconhecido ou falha de escrita.
    """
    fmt = (fmt or "").lower()
    if fmt == "csv":
        return write_csv(destination, rows, FIELDS)
    if fmt == "jsonl":
        try:
            import json

            directory = os.path.dirname(destination) or "."
            os.makedirs(directory, exist_ok=True)
            with open(destination, "w", encoding="utf-8") as handle:
                for row in rows:
                    payload = {key: row.get(key) for key in FIELDS}
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except (OSError, ValueError) as exc:
            raise HistoryError(f"Falha ao exportar {destination}: {exc}") from None
        return destination
    raise HistoryError(f"Formato de exportação não suportado: {fmt!r} (use csv ou jsonl).")


def clear(path: Optional[str] = None) -> int:
    """Remove o histórico (arquivo ativo e rotações); devolve o total removido."""
    target = path or history_path()
    removed = 0
    for candidate in _rotated_paths(target) + [target]:
        try:
            removed += len(read_jsonl(candidate))
            os.unlink(candidate)
        except FileNotFoundError:
            continue
        except (StorageError, OSError) as exc:
            raise HistoryError(f"Falha ao limpar {candidate}: {exc}") from None
    return removed


__all__ = [
    "EVENT_TYPES",
    "FIELDS",
    "HISTORY_FILENAME",
    "KEEP_ROTATED",
    "MAX_BYTES",
    "HistoryError",
    "clear",
    "events",
    "export",
    "history_path",
    "record",
    "record_safe",
]
