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
from typing import List, Optional

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
            self.minsize(760, 520)
            self.geometry("880x600")

            self.settings: Settings = load_settings()
            self.worker: Optional[ScanWorker] = None
            self.results: List[HostResult] = []

            self._build_form()
            self._build_results()
            self._build_logs()
            self._build_statusbar()

            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(self.POLL_MS, self._poll)

            self._prefill()
            self.log_panel.log("Interface pronta. Porta padrão 8022 (Termux).")

        # ---------------------------------------------------------------- #
        # Layout
        # ---------------------------------------------------------------- #

        def _build_form(self) -> None:
            form = ttk.Frame(self, padding=(10, 10, 10, 0))
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

        def _build_results(self) -> None:
            box = ttk.Frame(self, padding=(10, 8, 10, 0))
            box.pack(fill="both", expand=True)

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
            network = self.settings.last_network or (interface.network if interface else "")
            if network:
                self.network_var.set(network)
            if interface and not self.settings.last_network:
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
            try:
                terminal = find_terminal(self.settings.terminal)
                if terminal is None:
                    raise NoTerminalFound(
                        "Nenhum terminal compatível encontrado. Instale kitty, konsole, "
                        "xfce4-terminal, alacritty, gnome-terminal ou xterm."
                    )
                ssh_command = build_command(ip, user=user, port=port)
                session = build_terminal_command(terminal, ssh_command)
            except (SSHError, SSHClientNotFound) as exc:
                self.log_panel.log(str(exc), "error")
                messagebox.showerror("pyssh", str(exc), parent=self)
                return

            try:
                pid = spawn_session(session)
            except SSHError as exc:
                self.log_panel.log(str(exc), "error")
                messagebox.showerror("pyssh", str(exc), parent=self)
                return

            self.log_panel.log(
                f"Sessão iniciada (pid {pid}) fora do pyssh: {format_command(session)}"
            )
            self.status_var.set(f"Sessão SSH aberta para {ip}:{port}.")

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
