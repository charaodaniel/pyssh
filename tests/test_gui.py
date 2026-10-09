"""Testes da lógica da GUI sem exigir Tkinter nem display.

O painel de logs, o worker de varredura e a formatação são testados sem
criar widgets; a montagem da janela só roda quando Tkinter e display existem.
"""

import queue
import time
import unittest

from pyssh.gui import LOG_LEVELS, ScanWorker, format_log
from tests.test_scanner import Listener


def tk_display_available() -> bool:
    """True apenas quando há Tkinter funcional e um display utilizável."""
    try:
        import tkinter
    except Exception:
        return False
    try:
        root = tkinter.Tk()
    except Exception:
        return False
    root.destroy()
    return True


HAS_DISPLAY = tk_display_available()


class FormatLogTests(unittest.TestCase):
    def test_formato_com_horario_fixo(self):
        line = format_log("Busca concluída", "info", timestamp="12:34:56")
        self.assertEqual(line, "[12:34:56] [INFO ] Busca concluída")

    def test_niveis(self):
        self.assertEqual(LOG_LEVELS["info"], "INFO")
        self.assertEqual(LOG_LEVELS["warn"], "AVISO")
        self.assertEqual(LOG_LEVELS["error"], "ERRO")
        self.assertIn("[AVISO]", format_log("cuidado", "warn", timestamp="00:00:00"))
        self.assertIn("[ERRO ]", format_log("falhou", "error", timestamp="00:00:00"))

    def test_nivel_desconhecido_vira_maiusculo(self):
        self.assertIn("[CUSTOM", format_log("x", "custom", timestamp="00:00:00"))

    def test_horario_real_quando_nao_informado(self):
        self.assertRegex(format_log("ok"), r"^\[\d{2}:\d{2}:\d{2}\] \[INFO \] ok$")


class ScanWorkerTests(unittest.TestCase):
    def test_publica_resultados_e_conclusao(self):
        listener = Listener()
        self.addCleanup(listener.close)
        worker = ScanWorker(network="127.0.0.1/32", port=listener.port, timeout=0.5)
        worker.start()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive())

        events = self._drain(worker.events)
        kinds = [kind for kind, _ in events]
        self.assertIn("result", kinds)
        self.assertIn("done", kinds)
        self.assertNotIn("error", kinds)

        done = [payload for kind, payload in events if kind == "done"][0]
        self.assertTrue(done.open_hosts)
        self.assertEqual(done.port, listener.port)

    def test_erro_vira_evento(self):
        worker = ScanWorker(network="127.0.0.1/32", port=0)
        worker.start()
        worker.join(timeout=10)
        events = self._drain(worker.events)
        kinds = [kind for kind, _ in events]
        self.assertIn("error", kinds)
        self.assertNotIn("done", kinds)

    def test_cancelamento(self):
        worker = ScanWorker(network="192.0.2.0/29", port=8022, timeout=1.0, workers=2)
        worker.cancel()
        worker.start()
        worker.join(timeout=15)
        events = self._drain(worker.events)
        done = [payload for kind, payload in events if kind == "done"]
        self.assertTrue(done and done[0].cancelled)

    @staticmethod
    def _drain(events: "queue.Queue"):
        items = []
        while True:
            try:
                items.append(events.get_nowait())
            except queue.Empty:
                return items


@unittest.skipUnless(HAS_DISPLAY, "Tkinter ou display indisponível")
class AppSmokeTests(unittest.TestCase):
    """Montagem da janela — só com Tkinter funcional e display."""

    def test_janela_abre_e_fecha(self):
        from pyssh.gui import App

        app = App()
        try:
            self.assertIn("pyssh", app.title())
            self.assertEqual(app.port_var.get(), "8022")
            app.log_panel.log("teste", "info")
            self.assertIn("teste", app.log_panel.text.get("1.0", "end"))
        finally:
            app.destroy()

    def test_busca_insere_dispositivo_na_tabela_e_registra_logs(self):
        from pyssh.gui import App

        listener = Listener()
        self.addCleanup(listener.close)
        app = App()
        try:
            app.network_var.set("127.0.0.1/32")
            app.port_var.set(str(listener.port))
            app.start_scan()

            limite = time.time() + 15
            while app.worker is not None and time.time() < limite:
                app.update()
                time.sleep(0.02)
            self.assertIsNone(app.worker, "a busca deveria ter terminado")

            linhas = app.tree.get_children()
            self.assertEqual(len(linhas), 1)
            valores = app.tree.item(linhas[0], "values")
            self.assertEqual(valores[0], "127.0.0.1")
            self.assertEqual(str(valores[2]), str(listener.port))
            self.assertEqual(valores[3], "aberta")

            logs = app.log_panel.text.get("1.0", "end")
            self.assertIn("Iniciando busca em 127.0.0.1/32", logs)
            self.assertIn("Dispositivo encontrado", logs)
            self.assertIn("Busca concluída", logs)
            self.assertIn("dispositivo(s) com a porta", app.status_var.get())
        finally:
            app.destroy()

    def test_porta_invalida_impede_a_busca(self):
        from unittest import mock

        from pyssh.gui import App

        app = App()
        try:
            app.network_var.set("127.0.0.1/32")
            app.port_var.set("0")
            # A caixa de diálogo é modal: evitamos que bloqueie o teste.
            with mock.patch("pyssh.gui.messagebox.showerror") as showerror:
                app.start_scan()
            showerror.assert_called_once()
            self.assertIsNone(app.worker)
            self.assertIn("Porta", app.log_panel.text.get("1.0", "end"))
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
