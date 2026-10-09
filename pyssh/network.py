"""Descoberta e validação de redes e interfaces.

Usa ``iproute2`` (``ip``) para identificar as interfaces e a faixa IPv4 local.
Este módulo não importa nenhum módulo de interface gráfica.
"""

from __future__ import annotations

import ipaddress
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Sequence, Union

IPAddress = Union[str, "ipaddress.IPv4Address"]
NetworkInput = Union[str, "ipaddress.IPv4Network"]

# Interfaces que normalmente não representam a rede local de interesse.
_IGNORED_IFACES = {"lo", "docker0", "virbr0", "veth", "br-"}

# Interfaces de túnel/VPN descartadas por padrão.
_TUNNEL_PREFIXES = ("tun", "wg", "tailscale", "zt")


class NetworkError(ValueError):
    """Erro de validação de endereço, rede ou interface."""


def is_valid_ipv4(value: str) -> bool:
    """Retorna ``True`` se ``value`` for um IPv4 textual válido."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        ipaddress.IPv4Address(value.strip())
    except (ipaddress.AddressValueError, ValueError):
        return False
    return True


def validate_ipv4(value: str) -> str:
    """Valida e normaliza um IPv4. Levanta :class:`NetworkError` se inválido."""
    if not isinstance(value, str) or not value.strip():
        raise NetworkError("Endereço IPv4 não informado.")
    text = value.strip()
    try:
        return str(ipaddress.IPv4Address(text))
    except (ipaddress.AddressValueError, ValueError):
        raise NetworkError(f"Endereço IPv4 inválido: {value!r}.") from None


def validate_port(value) -> int:
    """Valida uma porta TCP (1-65535)."""
    # Import local evita importação circular desnecessária no nível do pacote.
    from .settings import SettingsError, validate_port as _validate_port

    try:
        return _validate_port(value)
    except SettingsError as exc:
        raise NetworkError(str(exc)) from None


# Nome de host DNS: rótulos alfanuméricos com hífen, separados por pontos.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)


def validate_host(value: str) -> str:
    """Valida um endereço para conexão: IPv4 ou nome de host DNS.

    Levanta :class:`NetworkError` quando o valor é vazio ou inválido.
    """
    if not isinstance(value, str) or not value.strip():
        raise NetworkError("Endereço não informado.")

    text = value.strip()
    if is_valid_ipv4(text):
        return text
    # Só dígitos e pontos: é uma tentativa de IPv4, não um nome de host.
    if re.fullmatch(r"[0-9.]+", text):
        raise NetworkError(
            f"Endereço IPv4 inválido: {value!r}. Use algo como 192.168.8.52."
        )
    if _HOSTNAME_RE.match(text) and not text.startswith("."):
        return text
    raise NetworkError(
        f"Endereço inválido: {value!r}. Use um IPv4 (ex.: 192.168.8.52) ou nome de host."
    )


def parse_network(value: str) -> "ipaddress.IPv4Network":
    """Converte ``value`` em ``IPv4Network``.

    Aceita ``192.168.8.0/24`` ou um IPv4 simples (ex.: ``192.168.8.52``),
    que é interpretado como rede ``/32``.
    """
    if not isinstance(value, str) or not value.strip():
        raise NetworkError("Faixa de rede não informada.")

    text = value.strip()
    try:
        network = ipaddress.IPv4Network(text, strict=False)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
        raise NetworkError(f"Faixa de rede inválida: {value!r}. Use algo como 192.168.8.0/24.") from None
    return network


def normalize_network(value: str) -> str:
    """Devolve a faixa no formato canônico ``a.b.c.d/mask``."""
    return str(parse_network(value))


def validate_network(value: str) -> str:
    """Valida a faixa e limita o tamanho para evitar varreduras gigantes."""
    network = parse_network(value)
    if network.num_addresses > 65536:
        raise NetworkError(
            f"Faixa grande demais ({network.num_addresses} endereços). "
            "Use uma faixa no máximo /16."
        )
    return str(network)


def iter_hosts(network: Union[str, "ipaddress.IPv4Network"]) -> Iterator[str]:
    """Percorre os endereços utilizáveis de uma faixa.

    Para redes com máscara de 30 ou menos, pula a rede e o broadcast.
    Para ``/31`` e ``/32``, devolve todos os endereços.
    """
    net = parse_network(network) if isinstance(network, str) else network
    if net.prefixlen >= 31:
        yield from (str(host) for host in net)
        return
    for host in net.hosts():
        yield str(host)


def host_count(network: Union[str, "ipaddress.IPv4Network"]) -> int:
    """Quantidade de endereços que serão varridos."""
    return sum(1 for _ in iter_hosts(network))


@dataclass(frozen=True)
class Interface:
    """Descrição de uma interface de rede com endereço IPv4."""

    name: str
    ipv4: str
    prefixlen: int
    scope: str = "global"
    is_loopback: bool = False

    @property
    def network(self) -> str:
        """Faixa CIDR correspondente ao endereço da interface."""
        addr = ipaddress.IPv4Address(self.ipv4)
        mask = ipaddress.IPv4Address((0xFFFFFFFF << (32 - self.prefixlen)) & 0xFFFFFFFF)
        return str(ipaddress.IPv4Network(f"{addr}/{mask}", strict=False))

    @property
    def label(self) -> str:
        return f"{self.name} ({self.ipv4}/{self.prefixlen})"


def _run_ip(args: Sequence[str]) -> str:
    """Executa o comando ``ip`` e devolve a saída em texto."""
    ip_bin = shutil.which("ip")
    if not ip_bin:
        raise NetworkError(
            "Comando 'ip' não encontrado. Instale o iproute2 para descobrir a rede automaticamente."
        )
    try:
        result = subprocess.run(
            [ip_bin, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkError(f"Falha ao executar 'ip': {exc}") from None

    if result.returncode != 0:
        message = (result.stderr or "").strip()
        raise NetworkError(f"'ip {' '.join(args)}' falhou: {message or 'erro desconhecido'}.")

    return result.stdout


def get_interfaces(include_loopback: bool = False) -> List[Interface]:
    """Lista as interfaces com endereço IPv4 usando ``ip -json addr``.

    Faz um fallback para a saída textual caso o JSON não esteja disponível.
    """
    interfaces: List[Interface] = []
    try:
        raw = _run_ip(["-json", "-4", "addr", "show"])
        payload = json.loads(raw or "[]")
    except (NetworkError, json.JSONDecodeError):
        payload = None

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("ifname", "")).strip()
            if not name:
                continue
            for info in item.get("addr_info", []) or []:
                if not isinstance(info, dict):
                    continue
                if info.get("family") not in (None, "inet"):
                    continue
                local = info.get("local")
                if not local:
                    continue
                prefix = int(info.get("prefixlen", 32) or 32)
                scope = str(info.get("scope", "global") or "global")
                iface = Interface(
                    name=name,
                    ipv4=str(local),
                    prefixlen=prefix,
                    scope=scope,
                    is_loopback=(scope == "host" or name == "lo"),
                )
                if iface.is_loopback and not include_loopback:
                    continue
                interfaces.append(iface)
        return interfaces

    # Fallback: parsing da saída textual de `ip -4 addr show`.
    text = _run_ip(["-4", "addr", "show"])
    current = ""
    for line in text.splitlines():
        m = re.match(r"^\d+:\s+([^:@\s]+)", line)
        if m:
            current = m.group(1)
            continue
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
        if m and current:
            iface = Interface(
                name=current,
                ipv4=m.group(1),
                prefixlen=int(m.group(2)),
                is_loopback=(current == "lo"),
            )
            if iface.is_loopback and not include_loopback:
                continue
            interfaces.append(iface)
    return interfaces


def _is_candidate(iface: Interface) -> bool:
    if iface.is_loopback or iface.scope not in ("global", "link"):
        return False
    if iface.name in _IGNORED_IFACES or iface.name.startswith(("docker", "veth", "br-")):
        return False
    if iface.name.startswith(_TUNNEL_PREFIXES):
        return False
    if iface.prefixlen > 30:
        return False
    return True


def detect_networks(include_loopback: bool = False) -> List[Interface]:
    """Interfaces consideradas utilizáveis para descoberta (sem loopback/VPN)."""
    return [i for i in get_interfaces(include_loopback=include_loopback) if _is_candidate(i)]


def guess_network() -> Optional[Interface]:
    """Melhor candidato para a rede local, ou ``None`` se não houver."""
    candidates = detect_networks()
    if not candidates:
        return None
    # Prefere interfaces físicas (eth/wlan/en) e redes maiores que /30.
    candidates.sort(key=lambda i: (not i.name.startswith(("eth", "wlan", "en", "wl")), -i.prefixlen))
    return candidates[0]


def available_networks() -> List[str]:
    """Faixas CIDR candidatas, sem repetições, ordenadas."""
    seen = []
    for iface in detect_networks():
        net = iface.network
        if net not in seen:
            seen.append(net)
    return seen


__all__ = [
    "Interface",
    "NetworkError",
    "available_networks",
    "detect_networks",
    "get_interfaces",
    "guess_network",
    "host_count",
    "is_valid_ipv4",
    "iter_hosts",
    "normalize_network",
    "parse_network",
    "validate_host",
    "validate_ipv4",
    "validate_network",
    "validate_port",
]
