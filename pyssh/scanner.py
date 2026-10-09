"""Varredura TCP com timeouts, concorrência limitada e cancelamento.

O scanner apenas verifica a acessibilidade TCP de uma porta. Uma porta aberta
é um indício de serviço acessível, mas **não** garante que o serviço seja SSH
nem que a autenticação seja aceita.

Este módulo não importa nenhum módulo de interface gráfica.
"""

from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Union

from .network import NetworkError, iter_hosts, parse_network, validate_network
from .settings import DEFAULT_PORT, DEFAULT_TIMEOUT, DEFAULT_WORKERS, SettingsError, validate_port, validate_timeout, validate_workers

# Janela de sondas em andamento = workers * WINDOW_FACTOR.
WINDOW_FACTOR = 4


class ScanError(RuntimeError):
    """Erro impedindo a realização da varredura."""


class ScanAlreadyRunning(ScanError):
    """Já existe uma varredura em andamento."""


class ScanCancelled(ScanError):
    """A varredura foi cancelada pelo usuário."""


@dataclass(frozen=True)
class HostResult:
    """Resultado estruturado de uma verificação de porta."""

    ip: str
    port: int
    open: bool = False
    hostname: Optional[str] = None
    error: Optional[str] = None
    elapsed: float = 0.0

    @property
    def status(self) -> str:
        if self.error:
            return "erro"
        return "aberta" if self.open else "fechada"

    @property
    def address(self) -> str:
        return f"{self.ip}:{self.port}"


@dataclass
class ScanReport:
    """Resumo de uma varredura concluída (ou cancelada)."""

    network: str
    port: int
    results: List[HostResult] = field(default_factory=list)
    cancelled: bool = False
    elapsed: float = 0.0

    @property
    def open_hosts(self) -> List[HostResult]:
        return [r for r in self.results if r.open]

    @property
    def total(self) -> int:
        return len(self.results)


ProgressCallback = Callable[[HostResult], None]


# Impede buscas simultâneas acidentais (GUI + CLI no mesmo processo).
_scan_lock = threading.Lock()


def check_port(ip: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Verifica se ``ip:portaceita`` conexão TCP dentro de ``timeout`` segundos.

    Retorna ``True`` se a porta aceitar a conexão, ``False`` caso contrário.
    Levanta :class:`socket.gaierror` para nomes inválidos.
    """
    address = (ip, int(port))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        result = sock.connect_ex(address)
    return result == 0


def probe(ip: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> HostResult:
    """Executa uma única sondagem e devolve um :class:`HostResult`."""
    start = time.monotonic()
    try:
        is_open = check_port(ip, port, timeout)
        return HostResult(
            ip=ip,
            port=port,
            open=is_open,
            elapsed=round(time.monotonic() - start, 4),
        )
    except (socket.timeout, TimeoutError):
        return HostResult(
            ip=ip,
            port=port,
            open=False,
            error="timeout",
            elapsed=round(time.monotonic() - start, 4),
        )
    except OSError as exc:
        return HostResult(
            ip=ip,
            port=port,
            open=False,
            error=str(exc) or exc.__class__.__name__,
            elapsed=round(time.monotonic() - start, 4),
        )


def resolve_hostname(ip: str, timeout: float = 1.0) -> Optional[str]:
    """Reverse DNS opcional; devolve ``None`` quando não há nome."""
    try:
        old = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        try:
            return socket.gethostbyaddr(ip)[0]
        finally:
            socket.setdefaulttimeout(old)
    except (socket.herror, socket.gaierror, OSError):
        return None


def resolve_targets(target: Union[str, Iterable[str]]) -> List[str]:
    """Converte uma faixa CIDR (ou lista de IPs) na lista de endereços."""
    if isinstance(target, str):
        try:
            network = validate_network(target)
        except NetworkError as exc:
            raise ScanError(str(exc)) from None
        return list(iter_hosts(network))
    return [str(ip).strip() for ip in target if str(ip).strip()]


def scan(
    target: Union[str, Iterable[str]],
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT,
    workers: int = DEFAULT_WORKERS,
    progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    lookup_hostname: bool = False,
) -> ScanReport:
    """Varre ``target`` verificando a porta TCP informada.

    Parâmetros:
        target: faixa CIDR (``192.168.8.0/24``) ou lista de endereços.
        port: porta TCP (1-65535), padrão ``8022``.
        timeout: timeout por tentativa, em segundos.
        workers: quantidade máxima de sondas simultâneas.
        progress: chamado (em outra thread) a cada resultado obtido.
        cancel_event: ao ser sinalizado, interrompe a varredura.
        lookup_hostname: tenta reverse DNS nos hosts com a porta aberta.

    Levanta :class:`ScanError` para parâmetros inválidos ou varredura ativa.
    """
    # Validação antes de qualquer trabalho.
    try:
        port = validate_port(port)
        timeout = validate_timeout(timeout)
        workers = validate_workers(workers)
        hosts = resolve_targets(target)
    except (SettingsError, NetworkError) as exc:
        raise ScanError(str(exc)) from None

    if not hosts:
        raise ScanError("Nenhum endereço para varrer.")

    if isinstance(target, str):
        try:
            network_label = str(parse_network(target))
        except NetworkError:
            network_label = target
    else:
        network_label = f"{len(hosts)} endereços"

    if not _scan_lock.acquire(blocking=False):
        raise ScanAlreadyRunning("Já existe uma varredura em andamento.")

    cancel = cancel_event if cancel_event is not None else threading.Event()
    started = time.monotonic()
    results: List[HostResult] = []

    try:
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pyssh-scan")
        pending: dict = {}
        iterator = iter(hosts)
        cancelled = False

        try:
            # Janela limitada de futures: evita criar milhares de objetos de uma vez.
            for _ in range(workers * WINDOW_FACTOR):
                try:
                    ip = next(iterator)
                except StopIteration:
                    break
                future = executor.submit(probe, ip, port, timeout)
                pending[future] = ip

            while pending:
                if cancel.is_set():
                    cancelled = True
                    break
                done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    pending.pop(future, None)
                    result = future.result()
                    if lookup_hostname and result.open:
                        name = resolve_hostname(result.ip)
                        if name:
                            result = HostResult(
                                ip=result.ip,
                                port=result.port,
                                open=result.open,
                                hostname=name,
                                error=result.error,
                                elapsed=result.elapsed,
                            )
                    results.append(result)
                    if progress is not None:
                        progress(result)

                if not cancelled:
                    # Repõe a janela com novos endereços.
                    while len(pending) < workers * WINDOW_FACTOR:
                        try:
                            ip = next(iterator)
                        except StopIteration:
                            break
                        future = executor.submit(probe, ip, port, timeout)
                        pending[future] = ip
        finally:
            # Cancela o que ainda não começou e aguarda as em andamento.
            for future in list(pending):
                future.cancel()
            if cancelled:
                cancel.set()
            executor.shutdown(wait=True, cancel_futures=True)

        results.sort(key=lambda r: _ip_key(r.ip))
        return ScanReport(
            network=network_label,
            port=port,
            results=results,
            cancelled=cancelled,
            elapsed=round(time.monotonic() - started, 3),
        )
    finally:
        _scan_lock.release()


def _ip_key(ip: str):
    try:
        return tuple(int(part) for part in ip.split("."))
    except (ValueError, AttributeError):
        return (999, 999, 999, 999)


def scan_report_label(report: ScanReport, target: Union[str, Iterable[str]]) -> str:
    """Rótulo legível da faixa varrida (usado pela CLI/GUI)."""
    if isinstance(target, str):
        try:
            return str(parse_network(target))
        except NetworkError:
            return str(target)
    return f"{report.total} endereços"


__all__ = [
    "HostResult",
    "ScanAlreadyRunning",
    "ScanCancelled",
    "ScanError",
    "ScanReport",
    "check_port",
    "probe",
    "resolve_hostname",
    "resolve_targets",
    "scan",
    "scan_report_label",
]
