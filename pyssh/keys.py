"""Cadastro e gerenciamento de referências a chaves SSH (Fase 4 do roadmap).

O ``pyssh`` **não** implementa criptografia própria: aqui só são guardadas
*referências* (nome + caminho) para chaves privadas já existentes. A geração
de novas chaves delega ao ``ssh-keygen`` do sistema e a autenticação ao
OpenSSH (e ao ``ssh-agent`` quando em uso).

Segurança (exigências do roadmap):

* as chaves privadas **não** são copiadas para o diretório do ``pyssh``;
* nenhuma senha ou passphrase é armazenada;
* remover uma referência **nunca** apaga o arquivo original;
* ``check_file`` alerta quando o arquivo está ausente ou com permissões
  amplas — sem alterá-lo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from .storage import StorageError, config_dir, private_key_warning, read_json, write_json_atomic

KEYS_FILENAME = "keys.json"
_STORE_VERSION = 1

# Tipos aceitos pelo ssh-keygen neste módulo.
KEY_TYPES = ("ed25519", "rsa", "ecdsa")

# Nome de arquivo padrão do OpenSSH para cada tipo (dentro de ~/.ssh).
DEFAULT_KEY_NAMES = {"ed25519": "id_ed25519", "rsa": "id_rsa", "ecdsa": "id_ecdsa"}

_KEYGEN_TIMEOUT = 60  # segundos; geração local é instantânea na prática


class KeyError_(ValueError):
    """Dados de chave inválidos ou operação não permitida.

    (Sufixo ``_`` para não sobrescrever o ``KeyError`` built-in.)
    """


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def keys_path() -> str:
    """Caminho do arquivo de referências a chaves."""
    return os.path.join(config_dir(), KEYS_FILENAME)


@dataclass
class KeyRef:
    """Referência a uma chave privada existente no sistema."""

    name: str
    path: str
    notes: Optional[str] = None
    id: str = field(default_factory=lambda: _make_id())
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KeyRef":
        name = str(data.get("name") or "").strip()
        path = str(data.get("path") or "").strip()
        if not name:
            raise KeyError_("Nome da chave não informado.")
        if not path:
            raise KeyError_("Caminho da chave não informado.")
        created = str(data.get("created_at") or "").strip() or _now()
        return cls(
            id=str(data.get("id") or "").strip() or _make_id(),
            name=name,
            path=os.path.expanduser(path),
            notes=str(data.get("notes") or "").strip() or None,
            created_at=created,
            updated_at=str(data.get("updated_at") or "").strip() or created,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # ------------------------------------------------------------------ #
    # Inspeção do arquivo referenciado (somente leitura)
    # ------------------------------------------------------------------ #

    def check_file(self) -> Dict[str, Any]:
        """Status do arquivo: existe, permissões e aviso (sem alterar nada)."""
        info: Dict[str, Any] = {
            "exists": os.path.isfile(self.path),
            "permission_warning": None,
        }
        if info["exists"]:
            info["permission_warning"] = private_key_warning(self.path)
        return info


def _make_id() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


def default_key_path(key_type: str = "ed25519") -> str:
    """Caminho padrão do OpenSSH para o tipo (``~/.ssh/id_ed25519`` etc.)."""
    name = DEFAULT_KEY_NAMES.get(key_type, f"id_{key_type}")
    return os.path.join(os.path.expanduser("~"), ".ssh", name)


def public_key_path(path: str) -> str:
    """Caminho esperado da chave pública correspondente (``<chave>.pub``)."""
    return path if path.endswith(".pub") else path + ".pub"


def read_public_key(path: str) -> Optional[str]:
    """Lê a chave pública correspondente, quando existir."""
    candidate = public_key_path(path)
    try:
        with open(candidate, "r", encoding="utf-8") as handle:
            line = handle.readline().strip()
    except OSError:
        return None
    return line or None


def key_type(path: str) -> Optional[str]:
    """Identifica o tipo lendo o comentário do ``.pub`` (quando disponível)."""
    line = read_public_key(path)
    if not line:
        return None
    algorithm = line.split()[0] if line.split() else ""
    mapping = {
        "ssh-ed25519": "ed25519",
        "ssh-rsa": "rsa",
        "ecdsa-sha2-nistp256": "ecdsa",
        "ecdsa-sha2-nistp384": "ecdsa",
        "ecdsa-sha2-nistp521": "ecdsa",
        "ssh-dss": "dsa",
    }
    return mapping.get(algorithm)


def fingerprint(path: str) -> Optional[str]:
    """Impressão digital da chave pública via ``ssh-keygen -lf`` (ou ``None``)."""
    pub = public_key_path(path)
    if not os.path.isfile(pub):
        return None
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        return None
    try:
        proc = subprocess.run(
            [keygen, "-lf", pub],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    # Ex.: "256 SHA256:abc... comentário (ED25519)"
    parts = proc.stdout.strip().split()
    return parts[1] if len(parts) > 1 else None


def generate_key(
    key_type: str = "ed25519",
    dest: str = "",
    comment: str = "",
    bits: Optional[int] = None,
) -> Dict[str, Any]:
    """Gera uma nova chave com o ``ssh-keygen`` do sistema.

    * ``key_type``: ``ed25519`` (padrão), ``rsa`` ou ``ecdsa``;
    * ``dest``: caminho de destino (expande ``~``); quando vazio, é usado o
      caminho padrão do OpenSSH para o tipo (``~/.ssh/id_ed25519`` etc.) e o
      diretório ``~/.ssh`` é criado com permissões 0700 se não existir;
    * ``bits``: tamanho para ``rsa`` (ex.: 4096);
    * a chave é gerada **sem passphrase** (o usuário pode protegê-la depois
      com ``ssh-keygen -p``); nenhuma senha passa por este processo.

    Devolve ``{"path", "public_key", "public_key_path", "fingerprint",
    "type", "stdout", "exists"}``.
    Levanta :class:`KeyError_` quando o ``ssh-keygen`` está ausente ou falha.
    """
    if key_type not in KEY_TYPES:
        raise KeyError_(f"Tipo de chave inválido: {key_type!r}. Use {', '.join(KEY_TYPES)}.")

    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise KeyError_("ssh-keygen não encontrado. Instale o pacote 'openssh' do sistema.")

    if dest:
        dest = os.path.expanduser(dest)
    else:
        # Caminho padrão do OpenSSH para o tipo escolhido.
        dest = default_key_path(key_type)

    if os.path.exists(dest):
        raise KeyError_(f"O arquivo {dest} já existe; escolha outro caminho (nada foi alterado).")
    parent = os.path.dirname(dest) or "."
    if not os.path.isdir(parent):
        # Cria apenas o diretório padrão (~/.ssh); para caminhos explícitos,
        # um diretório ausente é erro do usuário (evita criar lixo por engano).
        if dest == default_key_path(key_type):
            try:
                os.makedirs(parent, mode=0o700, exist_ok=True)
            except OSError as exc:
                raise KeyError_(f"Não foi possível criar {parent}: {exc}") from None
        else:
            raise KeyError_(f"O diretório de destino não existe: {parent}.")

    command = [keygen, "-t", key_type, "-f", dest, "-N", "", "-C", comment or "pyssh"]
    if key_type == "rsa":
        command += ["-b", str(bits or 4096)]

    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=_KEYGEN_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise KeyError_("ssh-keygen excedeu o tempo limite.") from None
    except OSError as exc:
        raise KeyError_(f"Falha ao executar ssh-keygen: {exc}") from None

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise KeyError_(detail[-1] if detail else "ssh-keygen falhou.")

    # O ssh-keygen cria a chave privada com 600; garantimos o .pub também.
    pub = public_key_path(dest)
    return {
        "path": dest,
        "public_key": read_public_key(dest),
        "public_key_path": pub,
        "fingerprint": fingerprint(dest),
        "type": key_type,
        "stdout": proc.stdout.strip(),
        "exists": os.path.isfile(pub),
    }


def key_info(path: str) -> Dict[str, Any]:
    """Reúne os dados de uma chave para exibição (nunca a privada).

    Devolve ``{"path", "public_key_path", "public_key", "type",
    "fingerprint", "exists"}``. A chave privada não é lida nem exibida —
    só a pública, que é segura para compartilhar.
    """
    return {
        "path": path,
        "public_key_path": public_key_path(path),
        "public_key": read_public_key(path),
        "type": key_type(path),
        "fingerprint": fingerprint(path),
        "exists": os.path.isfile(path),
    }


class KeyStore:
    """Repositório CRUD de referências a chaves."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or keys_path()
        self._items: Dict[str, KeyRef] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # Persistência
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        try:
            data = read_json(self.path, default={"version": _STORE_VERSION, "keys": []})
        except StorageError as exc:
            raise KeyError_(str(exc)) from None
        if not isinstance(data, Mapping):
            raise KeyError_(f"Estrutura inválida em {self.path}.")
        raw = data.get("keys", [])
        if not isinstance(raw, list):
            raise KeyError_(f"Estrutura inválida em {self.path}: 'keys' não é lista.")
        items: Dict[str, KeyRef] = {}
        for entry in raw:
            if not isinstance(entry, Mapping):
                raise KeyError_(f"Entrada inválida em {self.path}.")
            key = KeyRef.from_dict(entry)
            if key.id in items:
                raise KeyError_(f"ID duplicado no arquivo: {key.id}.")
            items[key.id] = key
        self._items = items

    def _save(self) -> None:
        payload = {
            "version": _STORE_VERSION,
            "keys": [k.to_dict() for k in sorted(self._items.values(), key=lambda k: k.name.lower())],
        }
        try:
            write_json_atomic(self.path, payload)
        except StorageError as exc:
            raise KeyError_(str(exc)) from None

    # ------------------------------------------------------------------ #
    # Consulta
    # ------------------------------------------------------------------ #

    def list(self, search: Optional[str] = None) -> List[KeyRef]:
        items = sorted(self._items.values(), key=lambda k: k.name.lower())
        if search:
            needle = search.strip().lower()
            items = [k for k in items if needle in k.name.lower() or needle in k.path.lower()]
        return items

    def get(self, ref: str) -> Optional[KeyRef]:
        if ref in self._items:
            return self._items[ref]
        lowered = ref.strip().lower()
        for key in self._items.values():
            if key.name.lower() == lowered:
                return key
        return None

    def require(self, ref: str) -> KeyRef:
        key = self.get(ref)
        if key is None:
            raise KeyError_(f"Chave não encontrada: {ref!r}. Use 'keys list' para ver as salvas.")
        return key

    # ------------------------------------------------------------------ #
    # Escrita
    # ------------------------------------------------------------------ #

    def _check_name(self, name: str, ignore_id: Optional[str] = None) -> None:
        lowered = name.lower()
        for key in self._items.values():
            if key.id != ignore_id and key.name.lower() == lowered:
                raise KeyError_(f"Já existe uma chave chamada {name!r}.")

    def add(self, name: str, path: str, notes: Optional[str] = None) -> KeyRef:
        """Cadastra a referência de uma chave privada existente."""
        clean_name = (name or "").strip()
        clean_path = os.path.expanduser((path or "").strip())
        if not clean_name:
            raise KeyError_("Nome da chave não informado.")
        if not clean_path:
            raise KeyError_("Caminho da chave não informado.")
        self._check_name(clean_name)
        key = KeyRef(name=clean_name, path=clean_path, notes=(notes or "").strip() or None)
        self._items[key.id] = key
        self._save()
        return key

    def update(self, ref: str, **changes: Any) -> KeyRef:
        key = self.require(ref)
        allowed = {"name", "path", "notes"}
        unknown = set(changes) - allowed
        if unknown:
            raise KeyError_(f"Campo não suportado: {sorted(unknown)[0]}.")

        name = (changes.get("name") or key.name).strip()
        path = os.path.expanduser((changes.get("path") or key.path).strip())
        notes_val = changes.get("notes", key.notes)
        if not name:
            raise KeyError_("Nome da chave não informado.")
        if not path:
            raise KeyError_("Caminho da chave não informado.")
        self._check_name(name, ignore_id=key.id)

        key.name = name
        key.path = path
        key.notes = (str(notes_val).strip() or None) if notes_val is not None else None
        key.updated_at = _now()
        self._save()
        return key

    def delete(self, ref: str, delete_file: bool = False) -> KeyRef:
        """Remove a **referência**; o arquivo original só sai com
        ``delete_file=True`` (que exige confirmação na camada de interface)."""
        key = self.require(ref)
        del self._items[key.id]
        self._save()
        if delete_file:
            try:
                os.unlink(key.path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise KeyError_(
                    f"Referência removida, mas não foi possível apagar {key.path}: {exc}"
                ) from None
            # Chave pública correspondente (se existir) também é removida.
            pub = public_key_path(key.path)
            if pub != key.path:
                try:
                    os.unlink(pub)
                except OSError:
                    pass
        return key


__all__ = [
    "DEFAULT_KEY_NAMES",
    "KEY_TYPES",
    "KEYS_FILENAME",
    "KeyError_",
    "KeyRef",
    "KeyStore",
    "default_key_path",
    "fingerprint",
    "generate_key",
    "key_info",
    "key_type",
    "keys_path",
    "public_key_path",
    "read_public_key",
]
