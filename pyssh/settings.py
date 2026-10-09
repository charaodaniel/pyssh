"""Preferências compartilhadas entre a GUI e a CLI.

Mantém a porta padrão, validação de valores e persistência simples em JSON.
Nenhum dado sensível (senhas, chaves, tokens) deve ser armazenado aqui.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional

# Porta padrão do Termux (servidor SSH).
DEFAULT_PORT = 8022

# Faixa válida de portas TCP.
MIN_PORT = 1
MAX_PORT = 65535

# Timeout padrão de cada tentativa de conexão, em segundos.
DEFAULT_TIMEOUT = 0.5

# Quantidade máxima de sondas simultâneas.
DEFAULT_WORKERS = 64

# Nome do arquivo de preferências (na pasta do usuário).
SETTINGS_FILENAME = ".pyssh-settings.json"


class SettingsError(ValueError):
    """Valor de configuração inválido."""


def validate_port(value: Any) -> int:
    """Converte e valida uma porta TCP.

    Aceita ``int`` ou ``str`` (ex.: ``"8022"``). Devolve a porta como ``int``.
    Levanta :class:`SettingsError` para valores ausentes ou fora de 1-65535.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SettingsError("Porta não informada.")

    if isinstance(value, bool):
        raise SettingsError(f"Porta inválida: {value!r}.")

    if isinstance(value, str):
        value = value.strip()
        try:
            port = int(value, 10)
        except ValueError:
            raise SettingsError(f"Porta inválida: {value!r}. Use um número de 1 a 65535.") from None
    elif isinstance(value, int):
        port = value
    else:
        raise SettingsError(f"Porta inválida: {value!r}.")

    if not MIN_PORT <= port <= MAX_PORT:
        raise SettingsError(f"Porta fora do intervalo válido ({MIN_PORT}-{MAX_PORT}): {port}.")

    return port


def validate_timeout(value: Any) -> float:
    """Valida o timeout em segundos (deve ser positivo)."""
    if value is None or isinstance(value, bool):
        raise SettingsError(f"Timeout inválido: {value!r}.")

    try:
        timeout = float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"Timeout inválido: {value!r}.") from None

    if timeout <= 0:
        raise SettingsError(f"Timeout deve ser maior que zero: {timeout}.")

    return timeout


def validate_workers(value: Any) -> int:
    """Valida a quantidade de threads simultâneas."""
    if value is None or isinstance(value, bool):
        raise SettingsError(f"Concorrência inválida: {value!r}.")

    try:
        workers = int(value)
    except (TypeError, ValueError):
        raise SettingsError(f"Concorrência inválida: {value!r}.") from None

    if workers < 1:
        raise SettingsError(f"Concorrência deve ser pelo menos 1: {workers}.")

    return workers


@dataclass
class Settings:
    """Preferências básicas da aplicação."""

    port: int = DEFAULT_PORT
    timeout: float = DEFAULT_TIMEOUT
    workers: int = DEFAULT_WORKERS
    last_network: Optional[str] = None
    last_interface: Optional[str] = None
    terminal: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normaliza sempre que instanciada diretamente com valores brutos.
        self.port = validate_port(self.port)
        self.timeout = validate_timeout(self.timeout)
        self.workers = validate_workers(self.workers)

    def to_dict(self) -> dict:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Settings":
        known = {
            "port": data.get("port", DEFAULT_PORT),
            "timeout": data.get("timeout", DEFAULT_TIMEOUT),
            "workers": data.get("workers", DEFAULT_WORKERS),
            "last_network": data.get("last_network"),
            "last_interface": data.get("last_interface"),
            "terminal": data.get("terminal"),
        }
        # Chaves desconhecidas viram ``extra``; a própria chave "extra" é o
        # recipiente gravado em disco e NÃO pode entrar aqui (senão cada
        # ciclo de carga/gravação aninha mais um nível — bug corrigido).
        extra = {k: v for k, v in data.items() if k not in known and k != "extra"}
        saved = data.get("extra")
        # Repara arquivos corrompidos pelo bug antigo: {"extra": {"extra": ...}}.
        while isinstance(saved, Mapping) and set(saved) == {"extra"}:
            saved = saved["extra"]
        if isinstance(saved, Mapping):
            extra = {**saved, **extra}
        known["extra"] = extra
        return cls(**known)


def settings_path() -> str:
    """Caminho do arquivo de preferências do usuário."""
    return os.path.join(os.path.expanduser("~"), SETTINGS_FILENAME)


def load_settings(path: Optional[str] = None) -> Settings:
    """Carrega as preferências; devolve os padrões se o arquivo não existir."""
    target = path or settings_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return Settings()
    except (OSError, json.JSONDecodeError, ValueError):
        # Arquivo corrompido ou inacessível não deve impedir a aplicação.
        return Settings()

    if not isinstance(data, dict):
        return Settings()

    try:
        return Settings.from_dict(data)
    except SettingsError:
        return Settings()


def save_settings(settings: Settings, path: Optional[str] = None) -> str:
    """Grava as preferências em JSON e devolve o caminho utilizado."""
    target = path or settings_path()
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(settings.to_dict(), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, target)
    return target


__all__ = [
    "DEFAULT_PORT",
    "DEFAULT_TIMEOUT",
    "DEFAULT_WORKERS",
    "MAX_PORT",
    "MIN_PORT",
    "Settings",
    "SettingsError",
    "load_settings",
    "save_settings",
    "settings_path",
    "validate_port",
    "validate_timeout",
    "validate_workers",
]
