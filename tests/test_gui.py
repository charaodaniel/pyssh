"""Testes da lógica da GUI sem exigir Tkinter nem display.

O painel de logs, o worker de varredura e a formatação são testados sem
criar widgets; a montagem da janela só roda quando Tkinter e display existem.
"""

import queue
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


if __name__ == "__main__":
    unittest.main()
