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
import os
import sys
from typing import List, Optional, Sequence, TextIO

from pyssh import history
from pyssh.history import EVENT_TYPES
from pyssh.connections import ConnectionStore, ConnectionsError
from pyssh.keys import (
    KEY_TYPES,
    KeyError_,
    KeyStore,
    default_key_path,
    fingerprint,
    generate_key,
    key_info,
    key_type,
)
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


def _build_connections_parser(sub) -> None:
    """Subcomandos de conexões salvas (Fase 3)."""
    conn = sub.add_parser(
        "connections",
        help="gerencia conexões SSH salvas (CRUD)",
        description="Cria, lista, edita, duplica e exclui conexões salvas "
        "(armazenadas em ~/.config/pyssh/connections.json).",
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    conn_sub = conn.add_subparsers(dest="action", metavar="ação")

    listing = conn_sub.add_parser("list", help="lista conexões salvas")
    listing.add_argument("--search", "-s", metavar="TEXTO", help="filtra por nome, host ou usuário")
    listing.add_argument("-q", "--quiet", action="store_true", help="suprime mensagens informativas")

    add = conn_sub.add_parser("add", help="cria uma conexão salva")
    add.add_argument("--name", "-n", metavar="NOME", help="nome amigável (obrigatório)")
    add.add_argument("--host", "-H", metavar="HOST", help="IPv4 ou nome do dispositivo (obrigatório)")
    add.add_argument("--port", "-p", metavar="PORTA", help=f"porta SSH (padrão: {DEFAULT_PORT})")
    add.add_argument("--user", "-u", metavar="USUÁRIO", help="usuário SSH")
    add.add_argument("--key", "-k", metavar="CHAVE", help="nome/id de uma chave cadastrada (keys list)")
    add.add_argument("--notes", metavar="TEXTO", help="observações")

    edit = conn_sub.add_parser("edit", help="edita uma conexão salva")
    edit.add_argument("ref", metavar="ID|NOME", help="ID ou nome da conexão")
    edit.add_argument("--name", "-n", metavar="NOME", help="novo nome")
    edit.add_argument("--host", "-H", metavar="HOST", help="novo endereço")
    edit.add_argument("--port", "-p", metavar="PORTA", help="nova porta")
    edit.add_argument("--user", "-u", metavar="USUÁRIO", help="novo usuário ('-' remove)")
    edit.add_argument("--key", "-k", metavar="CHAVE", help="nova chave ('-' remove)")
    edit.add_argument("--notes", metavar="TEXTO", help="novas observações ('-' remove)")

    delete = conn_sub.add_parser("delete", help="exclui uma conexão salva")
    delete.add_argument("ref", metavar="ID|NOME", help="ID ou nome da conexão")
    delete.add_argument("--yes", "-y", action="store_true", help="não pede confirmação")

    dup = conn_sub.add_parser("duplicate", help="duplica uma conexão salva")
    dup.add_argument("ref", metavar="ID|NOME", help="ID ou nome da conexão origem")
    dup.add_argument("--name", "-n", metavar="NOME", help="nome da cópia")

    conn_sub.add_parser("fields", help="mostra os campos aceitos por add/edit")


def _build_keys_parser(sub) -> None:
    """Subcomandos de referências a chaves SSH (Fase 4)."""
    keys = sub.add_parser(
        "keys",
        help="gerencia referências a chaves SSH",
        description="Cadastra e lista referências a chaves privadas existentes "
        "(o pyssh nunca copia a chave nem guarda senhas).",
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    keys_sub = keys.add_subparsers(dest="action", metavar="ação")

    klist = keys_sub.add_parser("list", help="lista chaves cadastradas")
    klist.add_argument("--search", "-s", metavar="TEXTO", help="filtra por nome ou caminho")
    klist.add_argument("-q", "--quiet", action="store_true", help="suprime mensagens informativas")

    kadd = keys_sub.add_parser("add", help="cadastra a referência de uma chave existente")
    kadd.add_argument("--name", "-n", metavar="NOME", help="nome amigável (obrigatório)")
    kadd.add_argument("--path", metavar="CAMINHO", help="caminho da chave privada (obrigatório)")
    kadd.add_argument("--notes", metavar="TEXTO", help="observações")

    kedit = keys_sub.add_parser("edit", help="edita nome/caminho de uma referência")
    kedit.add_argument("ref", metavar="ID|NOME", help="ID ou nome da chave")
    kedit.add_argument("--name", "-n", metavar="NOME", help="novo nome")
    kedit.add_argument("--path", metavar="CAMINHO", help="novo caminho")
    kedit.add_argument("--notes", metavar="TEXTO", help="novas observações ('-' remove)")

    kdel = keys_sub.add_parser("delete", help="remove a referência (não apaga o arquivo)")
    kdel.add_argument("ref", metavar="ID|NOME", help="ID ou nome da chave")
    kdel.add_argument("--yes", "-y", action="store_true", help="não pede confirmação")
    kdel.add_argument(
        "--delete-file",
        action="store_true",
        help="APAGA também o arquivo da chave (pede confirmação extra)",
    )

    kgen = keys_sub.add_parser("generate", help="gera uma nova chave com o ssh-keygen do sistema")
    kgen.add_argument(
        "--type", "-t", dest="key_type", choices=KEY_TYPES, default="ed25519",
        help="tipo da chave (padrão: ed25519)",
    )
    kgen.add_argument(
        "--path", metavar="CAMINHO",
        help="caminho de destino (padrão do OpenSSH: ~/.ssh/id_<tipo>)",
    )
    kgen.add_argument("--comment", "-C", metavar="TEXTO", help="comentário da chave")
    kgen.add_argument("--bits", type=int, metavar="N", help="tamanho (apenas rsa; padrão 4096)")
    kgen.add_argument("--name", "-n", metavar="NOME", help="nome para cadastrar a referência")

    kshow = keys_sub.add_parser("show", help="exibe os dados de uma chave (pública e digital)")
    kshow.add_argument("ref", metavar="ID|NOME", help="ID ou nome da chave")
    kshow.add_argument(
        "--public-only", "-p", action="store_true",
        help="imprime só a chave pública (útil para copiar no servidor)",
    )

    keys_sub.add_parser("fields", help="mostra os campos aceitos por add/edit")


def _build_history_parser(sub) -> None:
    """Subcomandos do histórico de atividades (Fase 5)."""
    hist = sub.add_parser(
        "history",
        help="consulta, exporta e limpa o histórico de atividades",
        description="Histórico em JSON Lines (~/.local/share/pyssh/history.jsonl). "
        "Nunca contém senhas, passphrases ou chaves.",
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    hist_sub = hist.add_subparsers(dest="action", metavar="ação")

    def add_filters(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--event", metavar="TIPO", help="filtra por tipo de evento")
        parser.add_argument("--address", metavar="HOST", help="filtra por endereço (substring)")
        parser.add_argument("--status", metavar="ESTADO", help="filtra por resultado/estado")
        parser.add_argument("--since", metavar="DATA", help="a partir de (AAAA-MM-DD)")
        parser.add_argument("--until", metavar="DATA", help="até (AAAA-MM-DD)")
        parser.add_argument("--connection", metavar="ID|NOME", help="filtra por conexão salva")

    hlist = hist_sub.add_parser("list", help="lista eventos do histórico")
    add_filters(hlist)
    hlist.add_argument("--limit", "-n", type=int, default=50, help="máximo de eventos (padrão: 50)")
    hlist.add_argument("-q", "--quiet", action="store_true", help="suprime mensagens informativas")

    hexp = hist_sub.add_parser("export", help="exporta o histórico (ou uma seleção)")
    add_filters(hexp)
    hexp.add_argument(
        "--format", "-f", choices=("csv", "jsonl"), default="csv",
        help="formato de saída (padrão: csv)",
    )
    hexp.add_argument("--output", "-o", metavar="ARQUIVO", help="arquivo de destino")
    hexp.add_argument("--limit", "-n", type=int, default=0, help="máximo de eventos (0 = todos)")

    hclear = hist_sub.add_parser("clear", help="apaga o histórico")
    hclear.add_argument("--yes", "-y", action="store_true", help="não pede confirmação")

    hist_sub.add_parser("fields", help="mostra os campos e tipos de evento")


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
        "Aceita um IPv4/nome ou o nome de uma conexão salva. "
        "A autenticação fica por conta do usuário.",
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    connect_p.add_argument(
        "host",
        metavar="HOST|NOME",
        help="IPv4, nome do dispositivo ou nome de uma conexão salva",
    )
    connect_p.add_argument(
        "-p",
        "--port",
        default=None,
        help=f"porta SSH (padrão: {DEFAULT_PORT} ou a da conexão salva)",
    )
    connect_p.add_argument("-u", "--user", help="usuário SSH")
    connect_p.add_argument("-q", "--quiet", action="store_true", help="suprime mensagens informativas")

    _build_connections_parser(sub)
    _build_keys_parser(sub)
    _build_history_parser(sub)

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
    connection_id: Optional[str] = None,
) -> int:
    try:
        command = build_command(host, user=user, port=port, extra=ssh_args)
    except SSHClientNotFound as exc:
        _error(str(exc))
        history.record_safe(
            "session_error", address=host, port=port, connection_id=connection_id,
            status="erro", message=str(exc),
        )
        return EXIT_SSH
    except SSHError as exc:
        _error(str(exc))
        history.record_safe(
            "session_error", address=host, port=port, connection_id=connection_id,
            status="erro", message=str(exc),
        )
        return EXIT_SSH

    history.record_safe(
        "session_started", address=host, port=port, connection_id=connection_id,
        status="processo_ssh_iniciado",
        message=f"abrindo sessão no terminal atual: {format_command(command)}",
    )
    _info(f"Conectando a {host}:{port} — {format_command(command)}", quiet)

    try:
        code = run_interactive(command)
    except SSHClientNotFound as exc:
        _error(str(exc))
        history.record_safe(
            "session_error", address=host, port=port, connection_id=connection_id,
            status="erro", message=str(exc),
        )
        return EXIT_SSH
    except SSHError as exc:
        _error(str(exc))
        history.record_safe(
            "session_error", address=host, port=port, connection_id=connection_id,
            status="erro", message=str(exc),
        )
        return EXIT_SSH

    if code == 255:
        _error("o ssh não conseguiu estabelecer a sessão (verifique host, porta e autenticação).")
        history.record_safe(
            "session_error", address=host, port=port, connection_id=connection_id,
            status="falha", message="ssh retornou 255 (conexão ou autenticação recusada)",
        )
        return EXIT_SSH
    history.record_safe(
        "session_finished", address=host, port=port, connection_id=connection_id,
        status=f"exit_{code}", message="sessão encerrada (autenticação confirmada pelo ssh)",
    )
    if code < 0:
        # Encerrado por sinal: converge para o padrão 128 + sinal.
        return 128 + (-code)
    return code


def cmd_connect(args: argparse.Namespace) -> int:
    # 1ª tentativa: conexão salva (ID ou nome); senão, trata como host.
    connection = None
    try:
        connection = ConnectionStore().get(args.host)
    except ConnectionsError as exc:
        _error(f"conexões salvas ilegíveis: {exc}")
        return EXIT_USAGE

    if connection is not None:
        host = connection.host
        port_arg = args.port if args.port is not None else connection.port
        user = args.user or connection.user
        connection_id = connection.id
        ssh_args = list(args.ssh_args)
        if connection.key_id:
            key = KeyStore().get(connection.key_id)
            if key is None:
                _error(
                    f"a conexão {connection.name!r} referencia uma chave inexistente "
                    f"({connection.key_id}); cadastre-a com: pyssh-cli keys add"
                )
                return EXIT_USAGE
            check = key.check_file()
            if not check["exists"]:
                _error(f"arquivo da chave não encontrado: {key.path}")
                return EXIT_USAGE
            ssh_args = ["-i", key.path] + ssh_args
        _info(f"Conexão salva: {connection.name} ({connection.host}:{connection.port})")
    else:
        try:
            host = validate_host(args.host)
        except NetworkError as exc:
            _error(str(exc))
            return EXIT_USAGE
        port_arg = args.port if args.port is not None else DEFAULT_PORT
        user = args.user
        connection_id = None
        ssh_args = list(args.ssh_args)

    try:
        port = validate_port(port_arg)
    except SettingsError as exc:
        _error(str(exc))
        return EXIT_USAGE

    history.record_safe(
        "connection_attempt", address=host, port=port, connection_id=connection_id,
        status="tentativa", message="abrindo sessão SSH",
    )
    return _open_session(host, port, user, ssh_args, quiet=args.quiet, connection_id=connection_id)


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

    history.record_safe(
        "scan_started", address=network, port=port, status="iniciado",
        message=f"varredura de {network} na porta {port}",
    )

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

    open_hosts = [r for r in results if r.open]
    history.record_safe(
        "scan_finished", address=network, port=port,
        status="cancelado" if interrupted else "ok",
        message=(
            f"{len(results)} verificação(ões), {len(open_hosts)} com a porta aberta"
            + (" (cancelada)" if interrupted else "")
        ),
    )
    for host in open_hosts:
        history.record_safe(
            "device_found", address=host.ip, port=host.port, status="aberta",
            message=host.hostname or "",
        )

    if interrupted:
        _error(f"busca cancelada após {len(results)} verificação(ões).")
    elif report is not None:
        _info(
            f"Busca concluída: {report.total} endereços em {report.elapsed}s "
            f"({len(report.open_hosts)} com a porta {port} aberta).",
            args.quiet,
        )

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
# Conexões salvas (Fase 3)
# --------------------------------------------------------------------------- #


def _confirm(question: str, assume_yes: bool) -> Optional[bool]:
    """Confirmação interativa.

    * ``True`` — confirmado (ou ``assume_yes``);
    * ``False`` — o usuário recusou;
    * ``None`` — não foi possível confirmar (sem tty e sem ``--yes``); o
      chamador deve tratar como erro de uso (exit 2).
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        _error(f"confirmação necessária: use --yes para {question}.")
        return None
    sys.stderr.write(f"{question} (s/N): ")
    sys.stderr.flush()
    answer = sys.stdin.readline().strip().lower()
    return answer in ("s", "sim", "y", "yes")


def _store_or_usage(factory, label: str):
    try:
        return factory()
    except (ConnectionsError, KeyError_) as exc:
        _error(str(exc))
        return None


def cmd_connections(args: argparse.Namespace) -> int:
    action = args.action or "list"
    store = _store_or_usage(ConnectionStore, "conexões")
    if store is None:
        return EXIT_USAGE

    try:
        if action == "list":
            items = store.list(search=getattr(args, "search", None))
            if not items:
                print("Nenhuma conexão salva.", file=sys.stderr)
                return EXIT_OK
            print(f"{'ID':<13} {'NOME':<18} {'HOST':<16} {'PORTA':>5}  {'USUÁRIO':<10} CHAVE")
            for c in items:
                print(
                    f"{c.id:<13} {c.name:<18} {c.host:<16} {c.port:>5}  "
                    f"{(c.user or '-'):<10} {c.key_id or '-'}"
                )
            _info(f"{len(items)} conexão(ões) salva(s).", args.quiet)
            return EXIT_OK

        if action == "add":
            if not args.name or not args.host:
                _error("informe --name e --host (ex.: pyssh-cli connections add -n Termux -H 192.168.8.54).")
                return EXIT_USAGE
            key_id = args.key
            if key_id:
                keys = _store_or_usage(KeyStore, "chaves")
                if keys is None:
                    return EXIT_USAGE
                try:
                    key_id = keys.require(key_id).id
                except KeyError_ as exc:
                    _error(str(exc))
                    return EXIT_USAGE
            created = store.add(
                args.name, args.host,
                port=args.port if args.port is not None else DEFAULT_PORT,
                user=args.user, key_id=key_id, notes=args.notes,
            )
            history.record_safe(
                "connection_created", connection_id=created.id, address=created.host,
                port=created.port, status="ok", message=f"conexão {created.name!r} criada",
            )
            print(f"Conexão criada: {created.name} [{created.id}]")
            return EXIT_OK

        if action == "edit":
            connection = store.require(args.ref)
            changes = {}
            for field in ("name", "host", "port", "user", "key_id", "notes"):
                value = getattr(args, field, None)
                if value is None:
                    continue
                if field in ("user", "key_id", "notes") and value == "-":
                    changes[field] = None
                elif field == "key_id":
                    keys = _store_or_usage(KeyStore, "chaves")
                    if keys is None:
                        return EXIT_USAGE
                    try:
                        changes[field] = keys.require(value).id
                    except KeyError_ as exc:
                        _error(str(exc))
                        return EXIT_USAGE
                else:
                    changes[field] = value
            if not changes:
                _error("nenhum campo informado; use os flags de edit (ou connections fields).")
                return EXIT_USAGE
            updated = store.update(connection.id, **changes)
            history.record_safe(
                "connection_updated", connection_id=updated.id, address=updated.host,
                port=updated.port, status="ok",
                message=f"conexão {updated.name!r} editada: {', '.join(changes)}",
            )
            print(f"Conexão atualizada: {updated.name} [{updated.id}]")
            return EXIT_OK

        if action == "delete":
            connection = store.require(args.ref)
            decision = _confirm(f"Excluir a conexão {connection.name!r}?", args.yes)
            if decision is None:
                return EXIT_USAGE
            if not decision:
                _info("Exclusão cancelada.")
                return EXIT_OK
            store.delete(connection.id)
            history.record_safe(
                "connection_deleted", connection_id=connection.id, address=connection.host,
                port=connection.port, status="ok",
                message=f"conexão {connection.name!r} excluída",
            )
            print(f"Conexão excluída: {connection.name} [{connection.id}]")
            return EXIT_OK

        if action == "duplicate":
            source = store.require(args.ref)
            copy = store.duplicate(source.id, name=args.name)
            history.record_safe(
                "connection_created", connection_id=copy.id, address=copy.host,
                port=copy.port, status="ok", message=f"duplicada de {source.name!r}",
            )
            print(f"Conexão duplicada: {copy.name} [{copy.id}]")
            return EXIT_OK

        if action == "fields":
            print("Campos de connections add/edit:")
            print("  --name   nome amigável (obrigatório no add; único)")
            print("  --host   IPv4 ou nome do dispositivo (obrigatório no add)")
            print(f"  --port   porta SSH (padrão {DEFAULT_PORT}; válida: 1-65535)")
            print("  --user   usuário SSH")
            print("  --key    chave cadastrada (keys list); '-' remove no edit")
            print("  --notes  observações; '-' remove no edit")
            return EXIT_OK

        _error(f"ação desconhecida: {action!r}.")
        return EXIT_USAGE
    except (ConnectionsError, KeyError_, history.HistoryError) as exc:
        _error(str(exc))
        return EXIT_USAGE


# --------------------------------------------------------------------------- #
# Chaves SSH (Fase 4)
# --------------------------------------------------------------------------- #


def cmd_keys(args: argparse.Namespace) -> int:
    action = args.action or "list"
    store = _store_or_usage(KeyStore, "chaves")
    if store is None:
        return EXIT_USAGE

    try:
        if action == "list":
            items = store.list(search=getattr(args, "search", None))
            if not items:
                print("Nenhuma chave cadastrada.", file=sys.stderr)
                return EXIT_OK
            print(f"{'ID':<13} {'NOME':<16} {'TIPO':<8} {'DIGITAL':<44} CAMINHO")
            warnings = []
            for key in items:
                check = key.check_file()
                info = f"{key.path}{' (AUSENTE)' if not check['exists'] else ''}"
                print(
                    f"{key.id:<13} {key.name:<16} {(key_type(key.path) or '-'):<8} "
                    f"{(fingerprint(key.path) or '-'):<44} {info}"
                )
                if check["permission_warning"]:
                    warnings.append(check["permission_warning"])
            for warning in warnings:
                _error(f"aviso: {warning}")
            _info(f"{len(items)} chave(s) cadastrada(s).", args.quiet)
            return EXIT_OK

        if action == "add":
            if not args.name or not args.path:
                _error("informe --name e --path (ex.: pyssh-cli keys add -n casa -p ~/.ssh/id_ed25519).")
                return EXIT_USAGE
            key = store.add(args.name, args.path, notes=args.notes)
            history.record_safe(
                "key_registered", connection_id=key.id, status="ok",
                message=f"chave {key.name!r} cadastrada ({key.path})",
            )
            check = key.check_file()
            print(f"Chave cadastrada: {key.name} [{key.id}]")
            if not check["exists"]:
                _error(f"aviso: o arquivo {key.path} ainda não existe; gere com: pyssh-cli keys generate")
            elif check["permission_warning"]:
                _error(f"aviso: {check['permission_warning']}")
            return EXIT_OK

        if action == "edit":
            key = store.require(args.ref)
            changes = {}
            for field in ("name", "path", "notes"):
                value = getattr(args, field, None)
                if value is None:
                    continue
                changes[field] = None if (field == "notes" and value == "-") else value
            if not changes:
                _error("nenhum campo informado; use os flags de edit (ou keys fields).")
                return EXIT_USAGE
            updated = store.update(key.id, **changes)
            history.record_safe(
                "key_updated", connection_id=updated.id, status="ok",
                message=f"chave {updated.name!r} editada: {', '.join(changes)}",
            )
            print(f"Chave atualizada: {updated.name} [{updated.id}]")
            return EXIT_OK

        if action == "delete":
            key = store.require(args.ref)
            extra = " E O ARQUIVO SERÁ APAGADO" if args.delete_file else " (o arquivo original é mantido)"
            decision = _confirm(f"Remover a referência {key.name!r}{extra}?", args.yes)
            if decision is None:
                return EXIT_USAGE
            if not decision:
                _info("Remoção cancelada.")
                return EXIT_OK
            store.delete(key.id, delete_file=args.delete_file)
            history.record_safe(
                "key_removed", connection_id=key.id, status="ok",
                message=(
                    f"chave {key.name!r} removida "
                    + ("junto com o arquivo" if args.delete_file else "(arquivo preservado)")
                ),
            )
            print(f"Referência removida: {key.name} [{key.id}]")
            return EXIT_OK

        if action == "generate":
            result = generate_key(
                args.key_type, args.path or "", comment=args.comment or "", bits=args.bits,
            )
            name = args.name or os.path.basename(result["path"])
            key = store.add(name, result["path"])
            history.record_safe(
                "key_generated", connection_id=key.id, status="ok",
                message=f"{result['type']} {result['path']} ({result['fingerprint'] or 'sem digital'})",
            )
            print(f"Chave gerada: {result['path']}")
            print(f"  tipo:       {result['type']}")
            print(f"  digital:    {result['fingerprint'] or '-'}")
            print(f"  pública:    {result['public_key'] or '-'}")
            print(f"  arquivo .pub: {result['public_key_path']}")
            print(f"  salva como referência: {key.name} [{key.id}]")
            _info(f"Veja depois com: pyssh-cli keys show {key.name}", getattr(args, "quiet", False))
            return EXIT_OK

        if action == "show":
            key = store.require(args.ref)
            info = key_info(key.path)
            if args.public_only:
                if not info["public_key"]:
                    _error(f"chave pública não encontrada: {info['public_key_path']}")
                    return EXIT_USAGE
                print(info["public_key"])
                return EXIT_OK
            state = "" if info["exists"] else " (AUSENTE)"
            print(f"Chave:      {key.name} [{key.id}]")
            print(f"  arquivo:  {key.path}{state}")
            print(f"  tipo:     {info['type'] or '-'}")
            print(f"  digital:  {info['fingerprint'] or '-'}")
            print(f"  pública:  {info['public_key'] or '-'}")
            print(f"  arquivo .pub: {info['public_key_path']}")
            if key.notes:
                print(f"  notas:    {key.notes}")
            if not info["exists"]:
                _error("aviso: o arquivo da chave privada não existe neste caminho.")
            return EXIT_OK

        if action == "fields":
            print("Campos de keys add/edit:")
            print("  --name   nome amigável (obrigatório no add; único)")
            print("  --path   caminho da chave privada (obrigatório no add)")
            print("  --notes  observações; '-' remove no edit")
            default = default_key_path(getattr(args, "key_type", "ed25519"))
            print(f"Geração: keys generate --type {', '.join(KEY_TYPES)} [--path CAMINHO]")
            print(f"  Sem --path usa o padrão do OpenSSH (ex.: {default}).")
            print("  A chave é criada SEM passphrase; proteja-a depois com: ssh-keygen -p")
            print("Visualização: keys show ID|NOME [--public-only]")
            return EXIT_OK

        _error(f"ação desconhecida: {action!r}.")
        return EXIT_USAGE
    except (KeyError_, ConnectionsError, history.HistoryError) as exc:
        _error(str(exc))
        return EXIT_USAGE


# --------------------------------------------------------------------------- #
# Histórico (Fase 5)
# --------------------------------------------------------------------------- #


def _history_filters(args: argparse.Namespace) -> dict:
    filters = {
        "event": getattr(args, "event", None),
        "address": getattr(args, "address", None),
        "status": getattr(args, "status", None),
        "since": getattr(args, "since", None),
        "until": getattr(args, "until", None),
    }
    ref = getattr(args, "connection", None)
    if ref:
        try:
            connection = ConnectionStore().get(ref)
        except ConnectionsError as exc:
            _error(str(exc))
            raise SystemExit(EXIT_USAGE) from None
        filters["connection_id"] = connection.id if connection else ref
    return filters


def cmd_history(args: argparse.Namespace) -> int:
    action = args.action or "list"
    try:
        if action == "list":
            filters = _history_filters(args)
            rows = history.events(limit=args.limit, **filters)
            if not rows:
                print("Nenhum evento no histórico.", file=sys.stderr)
                return EXIT_OK
            print(f"{'DATA/HORA':<20} {'EVENTO':<21} {'ENDEREÇO':<18} {'ESTADO':<22} DETALHE")
            for row in rows:
                address = row.get("address") or "-"
                if row.get("port"):
                    address = f"{address}:{row['port']}"
                print(
                    f"{str(row.get('timestamp', '')):<20} {str(row.get('event', '')):<21} "
                    f"{address:<18} {str(row.get('status') or '-'):<22} "
                    f"{row.get('message') or ''}"
                )
            _info(f"{len(rows)} evento(s).", args.quiet)
            return EXIT_OK

        if action == "export":
            filters = _history_filters(args)
            rows = history.events(limit=args.limit or None, **filters)
            if not rows:
                print("Nenhum evento para exportar.", file=sys.stderr)
                return EXIT_NOT_FOUND
            destination = args.output or f"pyssh-history.{args.format}"
            history.export(rows, destination, args.format)
            history.record_safe(
                "history_exported", status="ok",
                message=f"{len(rows)} evento(s) → {destination} ({args.format})",
            )
            print(f"Exportado: {destination} ({len(rows)} evento(s), {args.format}).")
            return EXIT_OK

        if action == "clear":
            decision = _confirm("Apagar TODO o histórico de atividades?", args.yes)
            if decision is None:
                return EXIT_USAGE
            if not decision:
                _info("Limpeza cancelada.")
                return EXIT_OK
            removed = history.clear()
            print(f"Histórico apagado ({removed} evento(s)).")
            return EXIT_OK

        if action == "fields":
            print("Campos de filtro (list/export):")
            print("  --event TIPO      tipo de evento (ex.: scan_started, session_started)")
            print("  --address HOST    endereço ou fragmento (ex.: 192.168.8)")
            print("  --status ESTADO   resultado (ex.: ok, falha, tentativa)")
            print("  --since AAAA-MM-DD / --until AAAA-MM-DD")
            print("  --connection ID|NOME   conexão salva relacionada")
            print("  --limit N         máximo de eventos (list padrão 50; export 0 = todos)")
            print("Tipos de evento:")
            for name in EVENT_TYPES:
                print(f"  {name}")
            return EXIT_OK

        _error(f"ação desconhecida: {action!r}.")
        return EXIT_USAGE
    except history.HistoryError as exc:
        _error(str(exc))
        return EXIT_USAGE
    except OSError as exc:
        _error(str(exc))
        return EXIT_ERROR


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
        if args.command == "connections":
            return cmd_connections(args)
        if args.command == "keys":
            return cmd_keys(args)
        if args.command == "history":
            return cmd_history(args)
        parser.print_help(sys.stdout)
        return EXIT_OK
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrompido pelo usuário.\n")
        return EXIT_INTERRUPTED
    except (NetworkError, SettingsError, ScanError, SSHError, ConnectionsError, KeyError_) as exc:
        _error(str(exc))
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 - CLI deve terminar com código claro
        _error(f"erro interno: {exc.__class__.__name__}: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
