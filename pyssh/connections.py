"""CRUD de conexões SSH salvas (Fase 3 do roadmap).

Cada conexão guarda nome amigável, endereço, porta (padrão ``8022``),
usuário, referência opcional a uma chave cadastrada em :mod:`pyssh.keys`,
observações e carimbos de data/hora.

Persistência: ``~/.config/pyssh/connections.json`` via escrita atômica
(:mod:`pyssh.storage`). Nenhum segredo é armazenado — a autenticação
continua sendo responsabilidade do OpenSSH.

Não importa Tkinter; a GUI e a CLI consomem esta mesma API.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from .network import NetworkError, validate_host
from .settings import DEFAULT_PORT, SettingsError, validate_port
from .storage import StorageError, config_dir, read_json, write_json_atomic

CONNECTIONS_FILENAME = "connections.json"
_STORE_VERSION = 1


class ConnectionsError(ValueError):
    """Dados de conexão inválidos ou operação não permitida."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Connection:
    """Registro de uma conexão salva."""

    name: str
    host: str
    port: int = DEFAULT_PORT
    user: Optional[str] = None
    key_id: Optional[str] = None
    notes: Optional[str] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Connection":
        """Reconstrói a partir do JSON, validando cada campo."""
        try:
            name = str(data.get("name") or "").strip()
            host = validate_host(str(data.get("host") or ""))
            port = validate_port(data.get("port", DEFAULT_PORT))
        except (NetworkError, SettingsError) as exc:
            raise ConnectionsError(str(exc)) from None
        if not name:
            raise ConnectionsError("Nome da conexão não informado.")

        user = str(data.get("user") or "").strip() or None
        key_id = str(data.get("key_id") or "").strip() or None
        notes = str(data.get("notes") or "").strip() or None
        conn_id = str(data.get("id") or "").strip() or uuid.uuid4().hex[:12]
        created = str(data.get("created_at") or "").strip() or _now()
        updated = str(data.get("updated_at") or "").strip() or created
        return cls(
            id=conn_id,
            name=name,
            host=host,
            port=port,
            user=user,
            key_id=key_id,
            notes=notes,
            created_at=created,
            updated_at=updated,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def connections_path() -> str:
    """Caminho do arquivo de conexões salvas."""
    return os.path.join(config_dir(), CONNECTIONS_FILENAME)


class ConnectionStore:
    """Repositório CRUD de conexões salvas."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or connections_path()
        self._items: Dict[str, Connection] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # Persistência
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        try:
            data = read_json(self.path, default={"version": _STORE_VERSION, "connections": []})
        except StorageError as exc:
            raise ConnectionsError(str(exc)) from None
        if not isinstance(data, Mapping):
            raise ConnectionsError(f"Estrutura inválida em {self.path}.")
        raw = data.get("connections", [])
        if not isinstance(raw, list):
            raise ConnectionsError(f"Estrutura inválida em {self.path}: 'connections' não é lista.")

        items: Dict[str, Connection] = {}
        for entry in raw:
            if not isinstance(entry, Mapping):
                raise ConnectionsError(f"Entrada inválida em {self.path}.")
            connection = Connection.from_dict(entry)
            if connection.id in items:
                raise ConnectionsError(f"ID duplicado no arquivo: {connection.id}.")
            items[connection.id] = connection
        self._items = items

    def _save(self) -> None:
        payload = {
            "version": _STORE_VERSION,
            "connections": [c.to_dict() for c in sorted(self._items.values(), key=lambda c: c.name.lower())],
        }
        try:
            write_json_atomic(self.path, payload)
        except StorageError as exc:
            raise ConnectionsError(str(exc)) from None

    # ------------------------------------------------------------------ #
    # Consulta
    # ------------------------------------------------------------------ #

    def list(self, search: Optional[str] = None) -> List[Connection]:
        """Lista ordenada por nome; ``search`` filtra nome/host/usuário."""
        items = sorted(self._items.values(), key=lambda c: c.name.lower())
        if search:
            needle = search.strip().lower()
            items = [
                c
                for c in items
                if needle in c.name.lower()
                or needle in c.host.lower()
                or needle in (c.user or "").lower()
            ]
        return items

    def get(self, ref: str) -> Optional[Connection]:
        """Busca por ID exato ou nome (sem diferenciar maiúsculas)."""
        if ref in self._items:
            return self._items[ref]
        lowered = ref.strip().lower()
        for connection in self._items.values():
            if connection.name.lower() == lowered:
                return connection
        return None

    def require(self, ref: str) -> Connection:
        """Igual a :meth:`get` mas levanta :class:`ConnectionsError` se faltar."""
        connection = self.get(ref)
        if connection is None:
            raise ConnectionsError(
                f"Conexão não encontrada: {ref!r}. Use 'connections list' para ver as salvas."
            )
        return connection

    # ------------------------------------------------------------------ #
    # Escrita
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate(
        name: Optional[str],
        host: Optional[str],
        port: Any,
        user: Optional[str],
        key_id: Optional[str],
        notes: Optional[str],
    ) -> Dict[str, Optional[str]]:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ConnectionsError("Nome da conexão não informado.")
        if host is None:
            raise ConnectionsError("Endereço não informado.")
        try:
            clean_host = validate_host(host)
            clean_port = validate_port(port if port is not None else DEFAULT_PORT)
        except (NetworkError, SettingsError) as exc:
            raise ConnectionsError(str(exc)) from None
        return {
            "name": clean_name,
            "host": clean_host,
            "port": str(clean_port),
            "user": (user or "").strip() or None,
            "key_id": (key_id or "").strip() or None,
            "notes": (notes or "").strip() or None,
        }

    def _check_name(self, name: str, ignore_id: Optional[str] = None) -> None:
        lowered = name.lower()
        for connection in self._items.values():
            if connection.id != ignore_id and connection.name.lower() == lowered:
                raise ConnectionsError(f"Já existe uma conexão chamada {name!r}.")

    def add(
        self,
        name: str,
        host: str,
        port: Any = DEFAULT_PORT,
        user: Optional[str] = None,
        key_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Connection:
        """Cria e persiste uma nova conexão."""
        fields = self._validate(name, host, port, user, key_id, notes)
        self._check_name(fields["name"])
        connection = Connection(
            name=fields["name"],
            host=fields["host"],
            port=int(fields["port"]),
            user=fields["user"],
            key_id=fields["key_id"],
            notes=fields["notes"],
        )
        self._items[connection.id] = connection
        self._save()
        return connection

    def update(self, ref: str, **changes: Any) -> Connection:
        """Atualiza campos de uma conexão existente (``None`` mantém o valor)."""
        connection = self.require(ref)
        allowed = {"name", "host", "port", "user", "key_id", "notes"}
        unknown = set(changes) - allowed
        if unknown:
            raise ConnectionsError(f"Campo não suportado: {sorted(unknown)[0]}.")

        name = changes.get("name", connection.name)
        host = changes.get("host", connection.host)
        port = changes.get("port", connection.port)
        user = changes.get("user", connection.user)
        key_id = changes.get("key_id", connection.key_id)
        notes = changes.get("notes", connection.notes)

        fields = self._validate(name, host, port, user, key_id, notes)
        self._check_name(fields["name"], ignore_id=connection.id)

        connection.name = fields["name"]
        connection.host = fields["host"]
        connection.port = int(fields["port"])
        connection.user = fields["user"]
        connection.key_id = fields["key_id"]
        connection.notes = fields["notes"]
        connection.updated_at = _now()
        self._save()
        return connection

    def delete(self, ref: str) -> Connection:
        """Remove uma conexão salva (apenas o registro, nunca arquivos)."""
        connection = self.require(ref)
        del self._items[connection.id]
        self._save()
        return connection

    def duplicate(self, ref: str, name: Optional[str] = None) -> Connection:
        """Duplica uma conexão para criar outra (nome precisa ser único)."""
        source = self.require(ref)
        new_name = (name or f"{source.name} (cópia)").strip()
        self._check_name(new_name)
        copy = Connection(
            name=new_name,
            host=source.host,
            port=source.port,
            user=source.user,
            key_id=source.key_id,
            notes=source.notes,
        )
        self._items[copy.id] = copy
        self._save()
        return copy


__all__ = [
    "CONNECTIONS_FILENAME",
    "Connection",
    "ConnectionStore",
    "ConnectionsError",
    "connections_path",
]
