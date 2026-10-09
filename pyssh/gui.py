"""Interface gráfica do pyssh (Tkinter/ttk).

Reutiliza o núcleo (`network`, `scanner`, `settings`, `ssh_client`,
`terminal`) sem duplicar lógica. A varredura roda em thread separada e os
resultados chegam à interface por uma fila consumida com `after()`, para
nunca bloquear a janela.

O Tkinter é importado de forma protegida: sem ele, `format_log` e
`ScanWorker` continuam utilizáveis e testáveis; apenas a montagem da janela
fica indisponível (`TK_AVAILABLE` é `False`).

Nenhuma senha ou credencial é exibida ou registrada nos logs.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Dict, List, Optional

from . import history
from .connections import ConnectionStore, ConnectionsError
from .keys import (
    KEY_TYPES,
    KeyError_,
    KeyStore,
    default_key_path,
    fingerprint,
    generate_key,
    key_info,
    key_type,
)
from .network import NetworkError, guess_network, validate_network
from .scanner import HostResult, ScanReport, scan
from .settings import (
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_WORKERS,
    Settings,
    SettingsError,
    load_settings,
    save_settings,
    validate_port,
)
from .ssh_client import SSHClientNotFound, SSHError, build_command, format_command
from .terminal import NoTerminalFound, build_terminal_command, find_terminal, spawn_session

try:  # Tkinter é opcional: a CLI e o núcleo nunca dependem dele.
    import tkinter as tk
    from tkinter import messagebox, ttk

    TK_AVAILABLE = True
    TK_ERROR: Optional[BaseException] = None
except Exception as exc:  # ImportError + falhas de biblioteca compartilhada
    tk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    TK_AVAILABLE = False
    TK_ERROR = exc

# Níveis de log usados pelo painel de saída.
LOG_LEVELS = {"info": "INFO", "warn": "AVISO", "error": "ERRO"}


def format_log(message: str, level: str = "info", timestamp: Optional[str] = None) -> str:
    """Formata uma linha do painel de logs: ``[HH:MM:SS] [NÍVEL] mensagem``."""
    stamp = timestamp or time.strftime("%H:%M:%S")
    label = LOG_LEVELS.get(level, str(level).upper())
    return f"[{stamp}] [{label:<5}] {message}"


class ScanWorker(threading.Thread):
    """Executa a varredura fora da thread da interface.

    Publica eventos na fila `events`:
    ``("result", HostResult)`` · ``("done", ScanReport)`` · ``("error", str)``.
    """

    def __init__(
        self,
        network: str,
        port: int,
        timeout: float = DEFAULT_TIMEOUT,
        workers: int = DEFAULT_WORKERS,
        lookup_hostname: bool = True,
        events: Optional["queue.Queue"] = None,
    ) -> None:
        super().__init__(name="pyssh-scan", daemon=True)
        self.network = network
        self.port = port
        self.timeout = timeout
        self.workers = workers
        self.lookup_hostname = lookup_hostname
        self.events: "queue.Queue" = queue.Queue() if events is None else events
        self.cancel_event = threading.Event()
        self.report: Optional[ScanReport] = None

    def run(self) -> None:
        try:
            self.report = scan(
                self.network,
                port=self.port,
                timeout=self.timeout,
                workers=self.workers,
                progress=lambda result: self.events.put(("result", result)),
                cancel_event=self.cancel_event,
                lookup_hostname=self.lookup_hostname,
            )
        except Exception as exc:  # noqa: BLE001 - o erro vira evento de log
            self.events.put(("error", f"{type(exc).__name__}: {exc}"))
            return
        self.events.put(("done", self.report))

    def cancel(self) -> None:
        """Pede o encerramento da varredura (respeitado entre as sondagens)."""
        self.cancel_event.set()


if TK_AVAILABLE:

    class LogPanel(ttk.Frame):
        """Área de logs com horário, níveis coloridos, limpar e copiar."""

        def __init__(self, master) -> None:
            super().__init__(master)
            self.text = tk.Text(
                self,
                height=10,
                wrap="word",
                state="disabled",
                background="#14161a",
                foreground="#d3d8e0",
                insertbackground="#d3d8e0",
                relief="flat",
                padx=6,
                pady=4,
            )
            scroll = ttk.Scrollbar(self, command=self.text.yview)
            self.text.configure(yscrollcommand=scroll.set)
            self.text.tag_configure("info", foreground="#d3d8e0")
            self.text.tag_configure("warn", foreground="#e5c07b")
            self.text.tag_configure("error", foreground="#e06c75")

            self.text.grid(row=0, column=0, sticky="nsew")
            scroll.grid(row=0, column=1, sticky="ns")
            self.rowconfigure(0, weight=1)
            self.columnconfigure(0, weight=1)

            buttons = ttk.Frame(self)
            buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
            ttk.Button(buttons, text="Limpar logs", command=self.clear).pack(side="left")
            ttk.Button(buttons, text="Copiar logs", command=self.copy).pack(side="left", padx=(6, 0))

        def log(self, message: str, level: str = "info") -> None:
            """Registra uma mensagem. Nunca deve conter senhas ou credenciais."""
            line = format_log(message, level) + "\n"
            self.text.configure(state="normal")
            self.text.insert("end", line, level if level in LOG_LEVELS else "info")
            self.text.see("end")
            self.text.configure(state="disabled")

        def clear(self) -> None:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.configure(state="disabled")

        def copy(self) -> None:
            content = self.text.get("1.0", "end-1c")
            if content:
                self.clipboard_clear()
                self.clipboard_append(content)

    class App(tk.Tk):
        """Janela principal do pyssh."""

        POLL_MS = 100

        def __init__(self) -> None:
            super().__init__()
            self.title("pyssh — dispositivos SSH na rede local")
            self.minsize(820, 560)
            self.geometry("960x660")

            self.settings: Settings = load_settings()
            self.worker: Optional[ScanWorker] = None
            self.results: List[HostResult] = []
            # Os stores podem falhar (arquivo corrompido); a GUI degrada e loga.
            self.connections = self._safe_store(ConnectionStore, "conexões")
            self.keys = self._safe_store(KeyStore, "chaves")

            self.notebook = ttk.Notebook(self)
            self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

            self._build_discovery_tab()
            self._build_connections_tab()
            self._build_keys_tab()
            self._build_history_tab()

            self._build_logs()
            self._build_statusbar()

            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(self.POLL_MS, self._poll)

            self._prefill()
            self.refresh_connections()
            self.refresh_keys()
            self.refresh_history()
            self.log_panel.log("Interface pronta. Porta padrão 8022 (Termux).")

        @staticmethod
        def _safe_store(factory, label: str):
            try:
                return factory()
            except (ConnectionsError, KeyError_) as exc:
                print(f"pyssh: {label} ilegíveis: {exc}")
                return None

        # ---------------------------------------------------------------- #
        # Layout
        # ---------------------------------------------------------------- #

        def _build_discovery_tab(self) -> None:
            tab = ttk.Frame(self.notebook, padding=(10, 10, 10, 6))
            self.notebook.add(tab, text="Descoberta")
            self._build_form(tab)
            self._build_results(tab)

        def _build_form(self, container) -> None:
            form = ttk.Frame(container)
            form.pack(fill="x")

            ttk.Label(form, text="Rede (CIDR):").grid(row=0, column=0, sticky="w")
            self.network_var = tk.StringVar()
            ttk.Entry(form, textvariable=self.network_var, width=18).grid(row=0, column=1, padx=(4, 12))

            ttk.Label(form, text="Porta:").grid(row=0, column=2, sticky="w")
            self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
            ttk.Entry(form, textvariable=self.port_var, width=7).grid(row=0, column=3, padx=(4, 12))

            ttk.Label(form, text="Usuário SSH:").grid(row=0, column=4, sticky="w")
            self.user_var = tk.StringVar()
            ttk.Entry(form, textvariable=self.user_var, width=12).grid(row=0, column=5, padx=(4, 12))

            self.scan_button = ttk.Button(form, text="Escanear rede", command=self.start_scan)
            self.scan_button.grid(row=0, column=6, padx=(0, 6))
            self.cancel_button = ttk.Button(
                form, text="Cancelar busca", command=self.cancel_scan, state="disabled"
            )
            self.cancel_button.grid(row=0, column=7, padx=(0, 6))
            ttk.Button(form, text="Conectar via SSH", command=self.connect).grid(row=0, column=8, padx=(0, 6))
            ttk.Button(form, text="Copiar IP", command=self.copy_ip).grid(row=0, column=9)

        def _build_results(self, container) -> None:
            box = ttk.Frame(container)
            box.pack(fill="both", expand=True, pady=(8, 0))

            columns = ("ip", "hostname", "port", "state")
            self.tree = ttk.Treeview(
                box, columns=columns, show="headings", selectmode="browse", height=8
            )
            self.tree.heading("ip", text="IP")
            self.tree.heading("hostname", text="Hostname")
            self.tree.heading("port", text="Porta")
            self.tree.heading("state", text="Estado")
            self.tree.column("ip", width=140, anchor="w")
            self.tree.column("hostname", width=260, anchor="w")
            self.tree.column("port", width=70, anchor="center")
            self.tree.column("state", width=90, anchor="center")

            scroll = ttk.Scrollbar(box, command=self.tree.yview)
            self.tree.configure(yscrollcommand=scroll.set)
            self.tree.grid(row=0, column=0, sticky="nsew")
            scroll.grid(row=0, column=1, sticky="ns")
            box.rowconfigure(0, weight=1)
            box.columnconfigure(0, weight=1)

        def _build_logs(self) -> None:
            self.log_panel = LogPanel(self)
            self.log_panel.pack(fill="both", expand=False, padx=10, pady=(8, 0))

        # ---------------------------------------------------------------- #
        # Aba: Conexões salvas
        # ---------------------------------------------------------------- #

        def _build_connections_tab(self) -> None:
            tab = ttk.Frame(self.notebook, padding=(10, 10, 10, 6))
            self.notebook.add(tab, text="Conexões")

            bar = ttk.Frame(tab)
            bar.pack(fill="x", pady=(0, 6))
            ttk.Button(bar, text="Adicionar", command=self.connection_add).pack(side="left")
            ttk.Button(bar, text="Editar", command=self.connection_edit).pack(side="left", padx=6)
            ttk.Button(bar, text="Duplicar", command=self.connection_duplicate).pack(side="left")
            ttk.Button(bar, text="Excluir", command=self.connection_delete).pack(side="left", padx=6)
            ttk.Button(bar, text="Conectar", command=self.connection_connect).pack(side="left")
            ttk.Label(bar, text="  Buscar:").pack(side="left")
            self.conn_search_var = tk.StringVar()
            self.conn_search_var.trace_add("write", lambda *_: self.refresh_connections())
            ttk.Entry(bar, textvariable=self.conn_search_var, width=18).pack(side="left", padx=4)

            columns = ("name", "host", "port", "user", "key")
            self.conn_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
            for col, label, width in (
                ("name", "Nome", 150), ("host", "Host", 150),
                ("port", "Porta", 60), ("user", "Usuário", 100), ("key", "Chave", 120),
            ):
                self.conn_tree.heading(col, text=label)
                self.conn_tree.column(col, width=width, anchor="w")
            scroll = ttk.Scrollbar(tab, command=self.conn_tree.yview)
            self.conn_tree.configure(yscrollcommand=scroll.set)
            self.conn_tree.pack(side="left", fill="both", expand=True)
            scroll.pack(side="left", fill="y")
            self.conn_tree.bind("<Double-1>", lambda _e: self.connection_connect())

        # ---------------------------------------------------------------- #
        # Aba: Chaves SSH
        # ---------------------------------------------------------------- #

        def _build_keys_tab(self) -> None:
            tab = ttk.Frame(self.notebook, padding=(10, 10, 10, 6))
            self.notebook.add(tab, text="Chaves")

            bar = ttk.Frame(tab)
            bar.pack(fill="x", pady=(0, 6))
            ttk.Button(bar, text="Cadastrar", command=self.key_add).pack(side="left")
            ttk.Button(bar, text="Editar", command=self.key_edit).pack(side="left", padx=6)
            ttk.Button(bar, text="Remover", command=self.key_delete).pack(side="left")
            ttk.Button(bar, text="Gerar nova", command=self.key_generate).pack(side="left", padx=6)
            ttk.Button(bar, text="Ver chave", command=self.key_show).pack(side="left")

            columns = ("name", "type", "fingerprint", "path")
            self.key_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
            for col, label, width in (
                ("name", "Nome", 130), ("type", "Tipo", 80),
                ("fingerprint", "Impressão digital", 300), ("path", "Caminho", 240),
            ):
                self.key_tree.heading(col, text=label)
                self.key_tree.column(col, width=width, anchor="w")
            scroll = ttk.Scrollbar(tab, command=self.key_tree.yview)
            self.key_tree.configure(yscrollcommand=scroll.set)
            self.key_tree.pack(side="left", fill="both", expand=True)
            scroll.pack(side="left", fill="y")

        # ---------------------------------------------------------------- #
        # Aba: Histórico
        # ---------------------------------------------------------------- #

        def _build_history_tab(self) -> None:
            tab = ttk.Frame(self.notebook, padding=(10, 10, 10, 6))
            self.notebook.add(tab, text="Histórico")

            bar = ttk.Frame(tab)
            bar.pack(fill="x", pady=(0, 6))
            ttk.Button(bar, text="Atualizar", command=self.refresh_history).pack(side="left")
            ttk.Button(bar, text="Exportar CSV", command=self.history_export).pack(side="left", padx=6)
            ttk.Button(bar, text="Limpar", command=self.history_clear).pack(side="left")
            ttk.Label(bar, text="  Evento:").pack(side="left")
            self.hist_event_var = tk.StringVar()
            self.hist_event_var.trace_add("write", lambda *_: self.refresh_history())
            ttk.Entry(bar, textvariable=self.hist_event_var, width=16).pack(side="left", padx=4)
            ttk.Label(bar, text="Endereço:").pack(side="left")
            self.hist_address_var = tk.StringVar()
            self.hist_address_var.trace_add("write", lambda *_: self.refresh_history())
            ttk.Entry(bar, textvariable=self.hist_address_var, width=14).pack(side="left", padx=4)

            columns = ("timestamp", "event", "address", "status", "message")
            self.hist_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
            for col, label, width in (
                ("timestamp", "Data/hora", 150), ("event", "Evento", 150),
                ("address", "Endereço", 140), ("status", "Estado", 120),
                ("message", "Detalhe", 280),
            ):
                self.hist_tree.heading(col, text=label)
                self.hist_tree.column(col, width=width, anchor="w")
            scroll = ttk.Scrollbar(tab, command=self.hist_tree.yview)
            self.hist_tree.configure(yscrollcommand=scroll.set)
            self.hist_tree.pack(side="left", fill="both", expand=True)
            scroll.pack(side="left", fill="y")

        def _build_logs(self) -> None:
            self.log_panel = LogPanel(self)
            self.log_panel.pack(fill="both", expand=False, padx=10, pady=(8, 0))

        def _build_statusbar(self) -> None:
            bar = ttk.Frame(self, padding=(10, 6, 10, 8))
            bar.pack(fill="x")
            self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
            self.progress.pack(side="left")
            self.status_var = tk.StringVar(value="Pronto.")
            ttk.Label(bar, textvariable=self.status_var).pack(side="left", padx=8)

        # ---------------------------------------------------------------- #
        # Estado inicial
        # ---------------------------------------------------------------- #

        def _prefill(self) -> None:
            interface = guess_network()
            # A rede DETECTADA tem prioridade: o objetivo do pyssh é achar o
            # dispositivo na rede local mesmo depois que o IP muda. `last_network`
            # só entra como fallback quando não há detecção (ex.: interface
            # atípica), para não congelar a busca numa faixa antiga/estreita.
            detected = interface.network if interface else ""
            network = detected or self.settings.last_network or ""
            if network:
                self.network_var.set(network)
            if interface:
                self.log_panel.log(f"Rede detectada: {interface.label}")

        # ---------------------------------------------------------------- #
        # Varredura
        # ---------------------------------------------------------------- #

        def start_scan(self) -> None:
            if self.worker is not None and self.worker.is_alive():
                self.log_panel.log("Já existe uma busca em andamento.", "warn")
                return

            try:
                network = validate_network(self.network_var.get())
                port = validate_port(self.port_var.get())
            except (NetworkError, SettingsError) as exc:
                self.log_panel.log(str(exc), "error")
                messagebox.showerror("pyssh", str(exc), parent=self)
                return

            self.network_var.set(network)
            self.port_var.set(str(port))
            self.tree.delete(*self.tree.get_children())
            self.results = []

            self.worker = ScanWorker(network=network, port=port)
            self.worker.start()
            self.scan_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self.progress.start(12)
            self.status_var.set(f"Varrendo {network} na porta {port}...")
            self.log_panel.log(f"Iniciando busca em {network} na porta {port}.")
            history.record_safe(
                "scan_started", address=network, port=port, status="iniciado",
                message=f"varredura de {network} na porta {port}",
            )

            self.settings.last_network = network
            try:
                save_settings(self.settings)
            except OSError as exc:
                self.log_panel.log(f"Não foi possível salvar as preferências: {exc}", "warn")

        def cancel_scan(self) -> None:
            if self.worker is None or not self.worker.is_alive():
                return
            self.worker.cancel()
            self.log_panel.log("Cancelamento solicitado; aguardando as sondagens em andamento.", "warn")

        def _poll(self) -> None:
            worker = self.worker
            if worker is not None:
                handled = 0
                while handled < 400:
                    try:
                        kind, payload = worker.events.get_nowait()
                    except queue.Empty:
                        break
                    handled += 1
                    if kind == "result":
                        self._on_result(payload)
                    elif kind == "done":
                        self._on_done(payload)
                    elif kind == "error":
                        self._on_error(payload)
            self.after(self.POLL_MS, self._poll)

        def _on_result(self, result: HostResult) -> None:
            self.results.append(result)
            if result.open:
                self.tree.insert(
                    "",
                    "end",
                    values=(result.ip, result.hostname or "-", result.port, result.status),
                )
                host = result.address + (f" ({result.hostname})" if result.hostname else "")
                self.log_panel.log(f"Dispositivo encontrado: {host}")

        def _on_done(self, report: ScanReport) -> None:
            self._finish_scan()
            total_open = len(report.open_hosts)
            history.record_safe(
                "scan_finished", address=report.network, port=report.port,
                status="cancelado" if report.cancelled else "ok",
                message=f"{report.total} endereços, {total_open} com a porta aberta",
            )
            for host in report.open_hosts:
                history.record_safe(
                    "device_found", address=host.ip, port=host.port, status="aberta",
                    message=host.hostname or "",
                )
            self.log_panel.log(
                f"Busca concluída em {report.elapsed}s: {report.total} endereços, "
                f"{total_open} com a porta {report.port} aberta."
            )
            if report.cancelled:
                self.log_panel.log("Busca cancelada pelo usuário.", "warn")
                self.status_var.set(f"Busca cancelada ({len(self.results)} verificações).")
            elif total_open == 0:
                self.log_panel.log("Nenhum dispositivo encontrado.", "warn")
                messagebox.showinfo(
                    "pyssh",
                    f"Nenhum dispositivo com a porta {report.port} aberta em {report.network}.",
                    parent=self,
                )
                self.status_var.set("Nenhum dispositivo encontrado.")
            else:
                self.status_var.set(f"{total_open} dispositivo(s) com a porta {report.port} aberta.")

        def _on_error(self, message: str) -> None:
            self._finish_scan()
            self.log_panel.log(message, "error")
            self.status_var.set("Erro durante a busca.")

        def _finish_scan(self) -> None:
            self.progress.stop()
            self.scan_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.worker = None

        # ---------------------------------------------------------------- #
        # Conexão
        # ---------------------------------------------------------------- #

        def _selected_ip(self) -> Optional[str]:
            selection = self.tree.selection()
            if not selection:
                return None
            return str(self.tree.item(selection[0], "values")[0])

        def copy_ip(self) -> None:
            ip = self._selected_ip()
            if not ip:
                self.log_panel.log("Selecione um dispositivo para copiar o IP.", "warn")
                return
            self.clipboard_clear()
            self.clipboard_append(ip)
            self.log_panel.log(f"IP {ip} copiado para a área de transferência.")

        def connect(self) -> None:
            ip = self._selected_ip()
            if not ip:
                self.log_panel.log("Selecione um dispositivo na lista antes de conectar.", "warn")
                messagebox.showwarning("pyssh", "Selecione um dispositivo na lista.", parent=self)
                return

            try:
                port = validate_port(self.port_var.get())
            except SettingsError as exc:
                self.log_panel.log(str(exc), "error")
                messagebox.showerror("pyssh", str(exc), parent=self)
                return

            user = self.user_var.get().strip() or None
            self._spawn_ssh(ip, port, user, [])

        # ---------------------------------------------------------------- #
        # Diálogo simples de formulário (usado por conexões e chaves)
        # ---------------------------------------------------------------- #

        def _ask_form(self, title: str, fields: List[tuple]) -> Optional[Dict[str, str]]:
            """``fields``: lista de ``(chave, rótulo, valor_inicial)``.

            Devolve o dicionário preenchido ou ``None`` se cancelado.
            """
            dialog = tk.Toplevel(self)
            dialog.title(title)
            dialog.transient(self)
            dialog.grab_set()
            dialog.resizable(False, False)

            vars_: Dict[str, tk.StringVar] = {}
            for row, (key, label, initial) in enumerate(fields):
                ttk.Label(dialog, text=label + ":").grid(row=row, column=0, sticky="w", padx=10, pady=4)
                var = tk.StringVar(value=initial or "")
                vars_[key] = var
                ttk.Entry(dialog, textvariable=var, width=34).grid(row=row, column=1, padx=10, pady=4)

            result: Dict[str, str] = {}

            def accept() -> None:
                result.update({k: v.get() for k, v in vars_.items()})
                dialog.destroy()

            buttons = ttk.Frame(dialog)
            buttons.grid(row=len(fields), column=0, columnspan=2, pady=(8, 10))
            ttk.Button(buttons, text="OK", command=accept).pack(side="left", padx=(0, 6))
            ttk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(side="left")
            dialog.bind("<Return>", lambda _e: accept())
            dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
            self.wait_window(dialog)
            return result or None

        def _selected(self, tree: ttk.Treeview) -> Optional[str]:
            selection = tree.selection()
            return selection[0] if selection else None

        def _require_store(self, store, what: str) -> bool:
            if store is None:
                self.log_panel.log(f"{what} indisponíveis (arquivo ilegível).", "error")
                return False
            return True

        # ---------------------------------------------------------------- #
        # Conexões salvas (ações)
        # ---------------------------------------------------------------- #

        def refresh_connections(self) -> None:
            self.conn_tree.delete(*self.conn_tree.get_children())
            if self.connections is None:
                return
            search = self.conn_search_var.get().strip()
            for c in self.connections.list(search=search or None):
                self.conn_tree.insert(
                    "", "end", iid=c.id,
                    values=(c.name, c.host, c.port, c.user or "-", c.key_id or "-"),
                )

        def connection_add(self) -> None:
            if not self._require_store(self.connections, "conexões"):
                return
            form = self._ask_form(
                "Adicionar conexão",
                [("name", "Nome", ""), ("host", "Host", ""), ("port", "Porta", str(DEFAULT_PORT)),
                 ("user", "Usuário", ""), ("notes", "Observações", "")],
            )
            if not form:
                return
            try:
                created = self.connections.add(
                    form["name"], form["host"], port=form["port"] or DEFAULT_PORT,
                    user=form.get("user") or None, notes=form.get("notes") or None,
                )
            except ConnectionsError as exc:
                self.log_panel.log(str(exc), "error")
                messagebox.showerror("pyssh", str(exc), parent=self)
                return
            history.record_safe(
                "connection_created", connection_id=created.id, address=created.host,
                port=created.port, status="ok", message=f"conexão {created.name!r} criada",
            )
            self.log_panel.log(f"Conexão salva: {created.name} ({created.host}:{created.port}).")
            self.refresh_connections()

        def connection_edit(self) -> None:
            if not self._require_store(self.connections, "conexões"):
                return
            ref = self._selected(self.conn_tree)
            if not ref:
                self.log_panel.log("Selecione uma conexão para editar.", "warn")
                return
            c = self.connections.require(ref)
            form = self._ask_form(
                "Editar conexão",
                [("name", "Nome", c.name), ("host", "Host", c.host), ("port", "Porta", str(c.port)),
                 ("user", "Usuário", c.user or ""), ("notes", "Observações", c.notes or "")],
            )
            if not form:
                return
            try:
                updated = self.connections.update(
                    c.id, name=form["name"], host=form["host"], port=form["port"] or c.port,
                    user=form.get("user") or None, notes=form.get("notes") or None,
                )
            except ConnectionsError as exc:
                self.log_panel.log(str(exc), "error")
                messagebox.showerror("pyssh", str(exc), parent=self)
                return
            history.record_safe(
                "connection_updated", connection_id=updated.id, address=updated.host,
                port=updated.port, status="ok", message=f"conexão {updated.name!r} editada",
            )
            self.log_panel.log(f"Conexão atualizada: {updated.name}.")
            self.refresh_connections()

        def connection_duplicate(self) -> None:
            if not self._require_store(self.connections, "conexões"):
                return
            ref = self._selected(self.conn_tree)
            if not ref:
                self.log_panel.log("Selecione uma conexão para duplicar.", "warn")
                return
            source = self.connections.require(ref)
            try:
                copy = self.connections.duplicate(source.id)
            except ConnectionsError as exc:
                self.log_panel.log(str(exc), "error")
                return
            history.record_safe(
                "connection_created", connection_id=copy.id, address=copy.host,
                port=copy.port, status="ok", message=f"duplicada de {source.name!r}",
            )
            self.log_panel.log(f"Conexão duplicada: {copy.name}.")
            self.refresh_connections()

        def connection_delete(self) -> None:
            if not self._require_store(self.connections, "conexões"):
                return
            ref = self._selected(self.conn_tree)
            if not ref:
                self.log_panel.log("Selecione uma conexão para excluir.", "warn")
                return
            c = self.connections.require(ref)
            if not messagebox.askyesno(
                "pyssh", f"Excluir a conexão {c.name!r}?", parent=self
            ):
                return
            self.connections.delete(c.id)
            history.record_safe(
                "connection_deleted", connection_id=c.id, address=c.host, port=c.port,
                status="ok", message=f"conexão {c.name!r} excluída",
            )
            self.log_panel.log(f"Conexão excluída: {c.name}.")
            self.refresh_connections()

        def connection_connect(self) -> None:
            if not self._require_store(self.connections, "conexões"):
                return
            ref = self._selected(self.conn_tree)
            if not ref:
                self.log_panel.log("Selecione uma conexão para conectar.", "warn")
                return
            c = self.connections.require(ref)
            extra: List[str] = []
            if c.key_id and self.keys is not None:
                key = self.keys.get(c.key_id)
                if key is None:
                    self.log_panel.log("A chave associada não está cadastrada.", "warn")
                elif not key.check_file()["exists"]:
                    self.log_panel.log(f"Arquivo da chave ausente: {key.path}", "warn")
                else:
                    extra = ["-i", key.path]
            self._spawn_ssh(c.host, c.port, c.user, extra, connection_id=c.id)

        # ---------------------------------------------------------------- #
        # Chaves (ações)
        # ---------------------------------------------------------------- #

        def refresh_keys(self) -> None:
            self.key_tree.delete(*self.key_tree.get_children())
            if self.keys is None:
                return
            for k in self.keys.list():
                status = "" if k.check_file()["exists"] else " (ausente)"
                self.key_tree.insert(
                    "", "end", iid=k.id,
                    values=(k.name + status, key_type(k.path) or "-", fingerprint(k.path) or "-", k.path),
                )

        def key_add(self) -> None:
            if not self._require_store(self.keys, "chaves"):
                return
            form = self._ask_form(
                "Cadastrar chave",
                [("name", "Nome", ""), ("path", "Caminho (privada)", ""), ("notes", "Observações", "")],
            )
            if not form:
                return
            try:
                key = self.keys.add(form["name"], form["path"], notes=form.get("notes") or None)
            except KeyError_ as exc:
                self.log_panel.log(str(exc), "error")
                messagebox.showerror("pyssh", str(exc), parent=self)
                return
            history.record_safe(
                "key_registered", connection_id=key.id, status="ok",
                message=f"chave {key.name!r} cadastrada ({key.path})",
            )
            check = key.check_file()
            if not check["exists"]:
                self.log_panel.log(f"Atenção: o arquivo {key.path} ainda não existe.", "warn")
            elif check["permission_warning"]:
                self.log_panel.log(check["permission_warning"], "warn")
            self.log_panel.log(f"Chave cadastrada: {key.name}.")
            self.refresh_keys()

        def key_edit(self) -> None:
            if not self._require_store(self.keys, "chaves"):
                return
            ref = self._selected(self.key_tree)
            if not ref:
                self.log_panel.log("Selecione uma chave para editar.", "warn")
                return
            k = self.keys.require(ref)
            form = self._ask_form(
                "Editar chave",
                [("name", "Nome", k.name), ("path", "Caminho", k.path), ("notes", "Observações", k.notes or "")],
            )
            if not form:
                return
            try:
                updated = self.keys.update(
                    k.id, name=form["name"], path=form["path"], notes=form.get("notes") or None,
                )
            except KeyError_ as exc:
                self.log_panel.log(str(exc), "error")
                messagebox.showerror("pyssh", str(exc), parent=self)
                return
            history.record_safe(
                "key_updated", connection_id=updated.id, status="ok",
                message=f"chave {updated.name!r} editada",
            )
            self.log_panel.log(f"Chave atualizada: {updated.name}.")
            self.refresh_keys()

        def key_delete(self) -> None:
            if not self._require_store(self.keys, "chaves"):
                return
            ref = self._selected(self.key_tree)
            if not ref:
                self.log_panel.log("Selecione uma chave para remover.", "warn")
                return
            k = self.keys.require(ref)
            if not messagebox.askyesno(
                "pyssh",
                f"Remover a referência {k.name!r}?\nO arquivo {k.path} NÃO será apagado.",
                parent=self,
            ):
                return
            self.keys.delete(k.id)
            history.record_safe(
                "key_removed", connection_id=k.id, status="ok",
                message=f"chave {k.name!r} removida (arquivo preservado)",
            )
            self.log_panel.log(f"Referência removida: {k.name} (arquivo original mantido).")
            self.refresh_keys()

        def key_generate(self) -> None:
            if not self._require_store(self.keys, "chaves"):
                return
            form = self._ask_form(
                "Gerar chave",
                [("type", "Tipo (ed25519/rsa/ecdsa)", "ed25519"),
                 ("path", "Caminho (vazio = padrão do sistema)", default_key_path("ed25519")),
                 ("name", "Nome da referência", "")],
            )
            if not form:
                return
            etype = (form.get("type") or "ed25519").strip()
            path = form.get("path", "").strip()
            # Campo com o padrão do ed25519 e tipo trocado → segue o padrão do tipo.
            if not path or (etype != "ed25519" and path == default_key_path("ed25519")):
                path = default_key_path(etype)
            try:
                result = generate_key(etype, path)
                name = form.get("name") or result["path"].split("/")[-1]
                key = self.keys.add(name, result["path"])
            except (KeyError_, KeyError) as exc:
                self.log_panel.log(str(exc), "error")
                messagebox.showerror("pyssh", str(exc), parent=self)
                return
            history.record_safe(
                "key_generated", connection_id=key.id, status="ok",
                message=f"{result['type']} {result['path']} ({result['fingerprint'] or 'sem digital'})",
            )
            self.log_panel.log(
                f"Chave {result['type']} gerada em {result['path']} — digital {result['fingerprint'] or '-'}"
            )
            self.refresh_keys()
            # Mostra a chave recém-gerada (pública + digital) sem precisar procurá-la.
            self.key_show(key.id)

        def key_show(self, ref: Optional[str] = None) -> None:
            """Exibe os dados de uma chave: caminho, tipo, digital e pública.

            A chave privada nunca é exibida — apenas a pública (segura).
            """
            if not self._require_store(self.keys, "chaves"):
                return
            if ref is None:
                ref = self._selected(self.key_tree)
                if not ref:
                    self.log_panel.log("Selecione uma chave para visualizar.", "warn")
                    return
            try:
                k = self.keys.require(ref)
            except KeyError_ as exc:
                self.log_panel.log(str(exc), "error")
                return
            info = key_info(k.path)
            state = "" if info["exists"] else " (AUSENTE)"
            lines = [
                f"Chave:      {k.name} [{k.id}]",
                f"Arquivo:    {k.path}{state}",
                f"Tipo:       {info['type'] or '-'}",
                f"Digital:    {info['fingerprint'] or '-'}",
                f"Arquivo .pub: {info['public_key_path']}",
            ]
            if k.notes:
                lines.append(f"Notas:      {k.notes}")
            lines += ["", "Chave pública:", info["public_key"] or "(não encontrada)"]
            self._show_text_dialog(f"Chave: {k.name}", "\n".join(lines))

        def _show_text_dialog(self, title: str, text: str) -> None:
            """Janela com texto somente leitura (visualização de chave)."""
            dialog = tk.Toplevel(self)
            dialog.title(title)
            dialog.transient(self)
            dialog.geometry("720x360")
            widget = tk.Text(dialog, wrap="none", width=80, height=18)
            widget.pack(fill="both", expand=True, padx=8, pady=8)
            widget.insert("1.0", text)
            widget.configure(state="disabled")
            ttk.Button(dialog, text="Fechar", command=dialog.destroy).pack(pady=(0, 8))
            dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        # ---------------------------------------------------------------- #
        # Histórico (ações)
        # ---------------------------------------------------------------- #

        def refresh_history(self) -> None:
            self.hist_tree.delete(*self.hist_tree.get_children())
            event = self.hist_event_var.get().strip() or None
            address = self.hist_address_var.get().strip() or None
            try:
                rows = history.events(limit=300, event=event, address=address)
            except history.HistoryError as exc:
                self.log_panel.log(f"Histórico ilegível: {exc}", "warn")
                return
            for row in reversed(rows):
                address_value = row.get("address") or "-"
                if row.get("port"):
                    address_value = f"{address_value}:{row['port']}"
                self.hist_tree.insert(
                    "", "end",
                    values=(
                        row.get("timestamp", ""), row.get("event", ""), address_value,
                        row.get("status") or "-", row.get("message") or "",
                    ),
                )

        def history_export(self) -> None:
            from tkinter import filedialog

            try:
                rows = history.events(limit=0)
            except history.HistoryError as exc:
                self.log_panel.log(str(exc), "error")
                return
            if not rows:
                self.log_panel.log("Nenhum evento para exportar.", "warn")
                return
            destination = filedialog.asksaveasfilename(
                parent=self, title="Exportar histórico",
                defaultextension=".csv", filetypes=[("CSV", "*.csv"), ("JSON Lines", "*.jsonl")],
            )
            if not destination:
                return
            fmt = "jsonl" if destination.endswith(".jsonl") else "csv"
            try:
                history.export(rows, destination, fmt)
            except history.HistoryError as exc:
                self.log_panel.log(str(exc), "error")
                return
            history.record_safe(
                "history_exported", status="ok", message=f"{len(rows)} evento(s) → {destination}",
            )
            self.log_panel.log(f"Histórico exportado: {destination} ({len(rows)} evento(s)).")

        def history_clear(self) -> None:
            if not messagebox.askyesno("pyssh", "Apagar TODO o histórico de atividades?", parent=self):
                return
            try:
                removed = history.clear()
            except history.HistoryError as exc:
                self.log_panel.log(str(exc), "error")
                return
            self.log_panel.log(f"Histórico apagado ({removed} evento(s)).")
            self.refresh_history()

        # ---------------------------------------------------------------- #
        # Sessão SSH em terminal independente (reutilizado por tudo)
        # ---------------------------------------------------------------- #

        def _spawn_ssh(
            self, host: str, port: int, user: Optional[str],
            extra: List[str], connection_id: Optional[str] = None,
        ) -> None:
            history.record_safe(
                "connection_attempt", address=host, port=port, connection_id=connection_id,
                status="tentativa", message="abrindo sessão SSH",
            )
            try:
                terminal = find_terminal(self.settings.terminal)
                if terminal is None:
                    raise NoTerminalFound(
                        "Nenhum terminal compatível encontrado. Instale kitty, konsole, "
                        "xfce4-terminal, alacritty, gnome-terminal ou xterm."
                    )
                ssh_command = build_command(host, user=user, port=port, extra=extra)
                session = build_terminal_command(terminal, ssh_command)
            except (SSHError, SSHClientNotFound) as exc:
                self.log_panel.log(str(exc), "error")
                history.record_safe(
                    "session_error", address=host, port=port, connection_id=connection_id,
                    status="erro", message=str(exc),
                )
                messagebox.showerror("pyssh", str(exc), parent=self)
                return

            try:
                pid = spawn_session(session)
            except SSHError as exc:
                self.log_panel.log(str(exc), "error")
                history.record_safe(
                    "session_error", address=host, port=port, connection_id=connection_id,
                    status="erro", message=str(exc),
                )
                messagebox.showerror("pyssh", str(exc), parent=self)
                return

            history.record_safe(
                "session_started", address=host, port=port, connection_id=connection_id,
                status="processo_ssh_iniciado", message=f"pid {pid}: {format_command(session)}",
            )
            self.log_panel.log(
                f"Sessão iniciada (pid {pid}) fora do pyssh: {format_command(session)}"
            )
            self.status_var.set(f"Sessão SSH aberta para {host}:{port}.")

        # ---------------------------------------------------------------- #
        # Encerramento
        # ---------------------------------------------------------------- #

        def _on_close(self) -> None:
            if self.worker is not None and self.worker.is_alive():
                self.worker.cancel()
                self.log_panel.log("Encerrando: busca cancelada.", "warn")
            try:
                save_settings(self.settings)
            except OSError:
                pass
            self.destroy()

else:  # sem Tkinter, apenas a lógica fica disponível

    class LogPanel:  # type: ignore[no-redef]
        """Indisponível sem Tkinter."""

    class App:  # type: ignore[no-redef]
        """Indisponível sem Tkinter."""


def run_app(selftest: bool = False) -> int:
    """Cria a janela e entra no loop. ``selftest`` abre e fecha sozinho."""
    if not TK_AVAILABLE:
        raise RuntimeError(f"Tkinter indisponível: {TK_ERROR}")
    app = App()
    if selftest:
        app.after(1200, app.destroy)
    app.mainloop()
    return 0


__all__ = ["App", "LOG_LEVELS", "LogPanel", "ScanWorker", "TK_AVAILABLE", "format_log", "run_app"]
