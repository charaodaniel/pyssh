#!/usr/bin/env python3
"""pyssh-cli — localiza dispositivos com SSH na rede local e abre sessões.

Uso:
    pyssh-cli scan [--network CIDR] [--port 8022] [opções]
    pyssh-cli connect HOST [--user USER] [--port 8022] [-- argumentos do ssh]
    pyssh-cli --help

Tudo que vier após ``--`` é repassado ao ``ssh``.

Códigos de saída:
    0    sucesso
    1    erro interno inesperado
    2    argumentos ou configuração inválidos
    3    nenhum dispositivo com a porta aberta
    4    OpenSSH ausente ou o ssh retornou 255 (falha de conexão/autenticação)
    130  interrompido pelo usuário (Ctrl+C)
    demais valores: propagados do próprio ``ssh`` (saída do shell remoto)

Não depende de Tkinter e não armazena senhas.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Sequence, TextIO

from pyssh.network import (
    NetworkError,
    guess_network,
    host_count,
    validate_host,
    validate_network,
)
from pyssh.scanner import HostResult, ScanAlreadyRunning, ScanError, scan
from pyssh.settings import (
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_WORKERS,
    SettingsError,
    validate_port,
    validate_timeout,
    validate_workers,
)
from pyssh.ssh_client import (
    SSHClientNotFound,
    SSHError,
    build_command,
    format_command,
    run_interactive,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_SSH = 4
EXIT_INTERRUPTED = 130

EXIT_CODES_HELP = """\
códigos de saída:
  0    sucesso
  1    erro interno inesperado
  2    argumentos ou configuração inválidos
  3    nenhum dispositivo com a porta aberta
  4    OpenSSH ausente ou falha do ssh (retorno 255)
  130  interrompido pelo usuário (Ctrl+C)
  restantes: propagados do ssh (saída do shell remoto)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyssh-cli",
        description="Localiza dispositivos com SSH na rede local e abre sessões.",
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="comando")

    scan_p = sub.add_parser(
        "scan",
        help="pesquisa dispositivos com a porta aberta em uma faixa de rede",
        description="Percorre a faixa de rede verificando a porta TCP informada. "
        "Uma porta aberta não garante que o serviço seja SSH.",
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scan_p.add_argument(
        "-n",
        "--network",
        metavar="CIDR",
        help="faixa de rede (ex.: 192.168.8.0/24); sem esta opção, a rede local é detectada",
    )
    scan_p.add_argument(
        "-p",
        "--port",
        default=DEFAULT_PORT,
        help=f"porta TCP a verificar (padrão: {DEFAULT_PORT})",
    )
    scan_p.add_argument(
        "-t",
        "--timeout",
        default=DEFAULT_TIMEOUT,
        help=f"timeout de cada tentativa em segundos (padrão: {DEFAULT_TIMEOUT})",
    )
    scan_p.add_argument(
        "-w",
        "--workers",
        default=DEFAULT_WORKERS,
        help=f"sondas simultâneas (padrão: {DEFAULT_WORKERS})",
    )
    scan_p.add_argument("-u", "--user", help="usuário SSH usado na conexão após a seleção")
    scan_p.add_argument(
        "--all",
        action="store_true",
        help="mostra também os endereços com a porta fechada",
    )
    scan_p.add_argument(
        "--no-hostname",
        action="store_true",
        help="não faz consulta reversa de nome (reverse DNS)",
    )
    scan_p.add_argument(
        "--no-interactive",
        action="store_true",
        help="não abre a seleção interativa após a busca",
    )
    scan_p.add_argument("-q", "--quiet", action="store_true", help="suprime mensagens de progresso")

    connect_p = sub.add_parser(
        "connect",
        help="abre uma sessão SSH interativa em um dispositivo",
        description="Abre uma sessão SSH interativa usando o OpenSSH do sistema. "
        "A autenticação fica por conta do usuário.",
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    connect_p.add_argument("host", metavar="HOST", help="IPv4 ou nome do dispositivo")
    connect_p.add_argument(
        "-p",
        "--port",
        default=DEFAULT_PORT,
        help=f"porta SSH (padrão: {DEFAULT_PORT})",
    )
    connect_p.add_argument("-u", "--user", help="usuário SSH")
    connect_p.add_argument("-q", "--quiet", action="store_true", help="suprime mensagens informativas")

    return parser


# --------------------------------------------------------------------------- #
# Saída
# --------------------------------------------------------------------------- #


def _info(message: str, quiet: bool = False) -> None:
    if not quiet:
        print(message, file=sys.stderr)


def _error(message: str) -> None:
    print(f"erro: {message}", file=sys.stderr)


def _print_results(results: Sequence[HostResult], show_closed: bool = False) -> None:
    rows = list(results) if show_closed else [r for r in results if r.open]
    if not rows:
        return
    print(f"{'IP':<15} {'PORTA':>5}  {'ESTADO':<7} HOSTNAME")
    for row in rows:
        print(f"{row.ip:<15} {row.port:>5}  {row.status:<7} {row.hostname or '-'}")


def _select_device(
    results: Sequence[HostResult],
    stdin: TextIO,
    stderr: TextIO,
) -> Optional[int]:
    """Lista numerada e leitura da escolha. Devolve o índice ou ``None``."""
    open_hosts = [r for r in results if r.open]
    stderr.write("\nDispositivos encontrados:\n\n")
    for index, host in enumerate(open_hosts, start=1):
        label = host.address + (f" ({host.hostname})" if host.hostname else "")
        stderr.write(f"[{index}] {label}\n")
    stderr.write("\nSelecione um dispositivo (Enter para sair): ")
    stderr.flush()

    while True:
        line = stdin.readline()
        if not line:  # EOF
            stderr.write("\n")
            return None
        text = line.strip()
        if not text:
            return None
        if text.isdigit() and 1 <= int(text) <= len(open_hosts):
            return int(text) - 1
        stderr.write(f"Opção inválida: {text!r}. Digite um número de 1 a {len(open_hosts)}: ")
        stderr.flush()


# --------------------------------------------------------------------------- #
# Conexão
# --------------------------------------------------------------------------- #


def _open_session(
    host: str,
    port: int,
    user: Optional[str],
    ssh_args: Sequence[str],
    quiet: bool = False,
) -> int:
    try:
        command = build_command(host, user=user, port=port, extra=ssh_args)
    except SSHClientNotFound as exc:
        _error(str(exc))
        return EXIT_SSH
    except SSHError as exc:
        _error(str(exc))
        return EXIT_SSH

    _info(f"Conectando a {host}:{port} — {format_command(command)}", quiet)

    try:
        code = run_interactive(command)
    except SSHClientNotFound as exc:
        _error(str(exc))
        return EXIT_SSH
    except SSHError as exc:
        _error(str(exc))
        return EXIT_SSH

    if code == 255:
        _error("o ssh não conseguiu estabelecer a sessão (verifique host, porta e autenticação).")
        return EXIT_SSH
    if code < 0:
        # Encerrado por sinal: converge para o padrão 128 + sinal.
        return 128 + (-code)
    return code


def cmd_connect(args: argparse.Namespace) -> int:
    try:
        host = validate_host(args.host)
    except NetworkError as exc:
        _error(str(exc))
        return EXIT_USAGE

    try:
        port = validate_port(args.port)
    except SettingsError as exc:
        _error(str(exc))
        return EXIT_USAGE

    return _open_session(host, port, args.user, args.ssh_args, quiet=args.quiet)


# --------------------------------------------------------------------------- #
# Busca
# --------------------------------------------------------------------------- #


def _resolve_network(network_arg: Optional[str], quiet: bool) -> Optional[str]:
    if network_arg:
        try:
            return validate_network(network_arg)
        except NetworkError as exc:
            _error(str(exc))
            return None

    interface = guess_network()
    if interface is None:
        _error(
            "não foi possível identificar a rede local. "
            "Informe a faixa com --network 192.168.8.0/24."
        )
        return None
    _info(f"Rede detectada: {interface.label}", quiet)
    return interface.network


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        port = validate_port(args.port)
        timeout = validate_timeout(args.timeout)
        workers = validate_workers(args.workers)
    except SettingsError as exc:
        _error(str(exc))
        return EXIT_USAGE

    network = _resolve_network(args.network, args.quiet)
    if network is None:
        return EXIT_USAGE

    total = host_count(network)
    show_progress = not args.quiet and sys.stderr.isatty()
    _info(f"Varrendo {network} na porta {port} ({total} endereços)...", args.quiet)

    collected: List[HostResult] = []
    done = 0
    opened = 0

    def on_progress(result: HostResult) -> None:
        nonlocal done, opened
        done += 1
        if result.open:
            opened += 1
        collected.append(result)
        if show_progress:
            sys.stderr.write(
                f"\r  {done}/{total} verificados | {opened} com a porta aberta"
            )
            sys.stderr.flush()

    report = None
    interrupted = False
    try:
        report = scan(
            network,
            port=port,
            timeout=timeout,
            workers=workers,
            progress=on_progress,
            lookup_hostname=not args.no_hostname,
        )
    except KeyboardInterrupt:
        interrupted = True
    except ScanAlreadyRunning as exc:
        _error(str(exc))
        return EXIT_ERROR
    except ScanError as exc:
        _error(str(exc))
        return EXIT_USAGE

    if show_progress:
        sys.stderr.write("\r" + " " * 60 + "\r")
        sys.stderr.flush()

    results = report.results if report is not None else collected

    if interrupted:
        _error(f"busca cancelada após {len(results)} verificação(ões).")
    elif report is not None:
        _info(
            f"Busca concluída: {report.total} endereços em {report.elapsed}s "
            f"({len(report.open_hosts)} com a porta {port} aberta).",
            args.quiet,
        )

    open_hosts = [r for r in results if r.open]
    rows = results if args.all else open_hosts
    if rows:
        _print_results(rows, show_closed=args.all)

    if not open_hosts:
        if interrupted:
            return EXIT_INTERRUPTED
        print(
            f"Nenhum dispositivo encontrado com a porta {port} aberta em {network}.",
            file=sys.stderr,
        )
        return EXIT_NOT_FOUND

    if interrupted:
        return EXIT_INTERRUPTED

    if args.no_interactive or not sys.stdin.isatty():
        return EXIT_OK

    index = _select_device(open_hosts, sys.stdin, sys.stderr)
    if index is None:
        _info("Seleção cancelada.", args.quiet)
        return EXIT_OK

    chosen = open_hosts[index]
    return _open_session(chosen.ip, port, args.user, args.ssh_args, quiet=args.quiet)


# --------------------------------------------------------------------------- #
# Ponto de entrada
# --------------------------------------------------------------------------- #


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # Tudo após `--` é repassado ao ssh.
    ssh_args: List[str] = []
    if "--" in raw:
        split = raw.index("--")
        ssh_args = raw[split + 1 :]
        raw = raw[:split]

    parser = build_parser()

    if not raw:
        parser.print_help(sys.stdout)
        return EXIT_OK

    try:
        args = parser.parse_args(raw)
    except SystemExit as exc:  # --help / erro de uso do argparse
        code = exc.code
        if code in (None, 0):
            return EXIT_OK
        try:
            return int(code)
        except (TypeError, ValueError):
            return EXIT_USAGE

    args.ssh_args = ssh_args

    try:
        if args.command == "scan":
            return cmd_scan(args)
        if args.command == "connect":
            return cmd_connect(args)
        parser.print_help(sys.stdout)
        return EXIT_OK
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrompido pelo usuário.\n")
        return EXIT_INTERRUPTED
    except (NetworkError, SettingsError, ScanError, SSHError) as exc:
        _error(str(exc))
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 - CLI deve terminar com código claro
        _error(f"erro interno: {exc.__class__.__name__}: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
