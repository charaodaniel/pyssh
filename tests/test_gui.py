"""Testes da lógica da GUI sem exigir Tkinter nem display.

O painel de logs, o worker de varredura e a formatação são testados sem
criar widgets; a montagem da janela só roda quando Tkinter e display existem.
"""

import queue
import time
import unittest

from pyssh.gui import CATPPUCCIN_MOCHA, LOG_LEVELS, ScanWorker, format_log
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


class ThemeTests(unittest.TestCase):
    """Paleta Catppuccin Mocha — válida sem Tk nem display."""

    def test_paleta_tem_as_cores_essenciais(self):
        essenciais = (
            "base", "mantle", "crust", "text", "subtext0", "subtext1",
            "surface0", "surface1", "surface2", "overlay0",
            "blue", "yellow", "red", "green", "mauve", "lavender",
        )
        for name in essenciais:
            self.assertIn(name, CATPPUCCIN_MOCHA)

    def test_todas_as_cores_sao_hex_de_6_digitos(self):
        for name, value in CATPPUCCIN_MOCHA.items():
            self.assertRegex(
                value, r"^#[0-9a-f]{6}$",
                f"cor {name!r} fora do formato #rrggbb minúsculo: {value!r}",
            )

    def test_cores_de_log_sao_da_paleta(self):
        from pyssh.gui import LogPanel  # noqa: F401 - garante que a classe existe

        self.assertEqual(CATPPUCCIN_MOCHA["yellow"], "#f9e2af")
        self.assertEqual(CATPPUCCIN_MOCHA["red"], "#f38ba8")
        self.assertEqual(CATPPUCCIN_MOCHA["base"], "#1e1e2e")


class IconTests(unittest.TestCase):
    """Ícone do pyssh — verificável sem Tk nem display."""

    def test_icone_empacotado_existe_e_eh_png(self):
        from pathlib import Path

        from pyssh.gui import ICON_MAX_LOAD_PX, icon_paths

        primary = Path(icon_paths()[0])
        self.assertTrue(primary.is_file(), f"ícone empacotado ausente: {primary}")
        with primary.open("rb") as fh:
            self.assertEqual(
                fh.read(8), b"\x89PNG\r\n\x1a\n",
                f"{primary} não é um PNG válido",
            )

    def test_icone_dentro_do_limite_que_o_tk_consegue_decodificar(self):
        """PNG ≥768px trava o decoder do Tk neste sistema (ver gui.py)."""
        from pathlib import Path

        import struct

        from pyssh.gui import ICON_MAX_LOAD_PX, icon_paths

        path = Path(icon_paths()[0])
        with path.open("rb") as fh:
            header = fh.read(26)
        width, height = struct.unpack(">II", header[16:24])
        self.assertLessEqual(width, ICON_MAX_LOAD_PX)
        self.assertLessEqual(height, ICON_MAX_LOAD_PX)

    def test_load_icon_degrada_quando_arquivo_falta(self):
        """Ícone ausente nunca impede a janela: devolve None em vez de erro."""
        from unittest import mock

        from pyssh import gui

        if not gui.TK_AVAILABLE:
            self.skipTest("Tk indisponível")
        with mock.patch.object(
            gui, "icon_paths", return_value=["/nonexistent/pyssh-icon.png"]
        ):
            self.assertIsNone(gui.load_icon())

    def test_load_icon_nunca_levanta_excecao(self):
        """Falha do PhotoImage (ex.: sem root) vira None, não exceção."""
        from unittest import mock

        from pyssh import gui

        if not gui.TK_AVAILABLE:
            self.skipTest("Tk indisponível")
        with mock.patch.object(
            gui.tk, "PhotoImage", side_effect=RuntimeError("no default root window")
        ):
            self.assertIsNone(gui.load_icon())


class WatermarkTests(unittest.TestCase):
    """Marca d'água — verificável sem Tk nem display."""

    def test_watermark_existe_e_eh_png(self):
        from pathlib import Path

        from pyssh.gui import watermark_path

        path = Path(watermark_path())
        self.assertTrue(path.is_file(), f"marca d'água ausente: {path}")
        with path.open("rb") as fh:
            self.assertEqual(fh.read(8), b"\x89PNG\r\n\x1a\n")

    def test_watermark_dentro_do_limite_do_tk(self):
        """PNG ≥768px trava o decoder do Tk neste sistema (ver gui.py)."""
        import struct
        from pathlib import Path

        from pyssh.gui import WATERMARK_MAX_LOAD_PX, watermark_path

        path = Path(watermark_path())
        with path.open("rb") as fh:
            header = fh.read(26)
        width, height = struct.unpack(">II", header[16:24])
        self.assertGreater(width, 0)
        self.assertLessEqual(width, WATERMARK_MAX_LOAD_PX)
        self.assertLessEqual(height, WATERMARK_MAX_LOAD_PX)

    def test_load_watermark_degrada_quando_arquivo_falta(self):
        """Marca ausente nunca impede a janela: devolve None, não erro."""
        from unittest import mock

        from pyssh import gui

        if not gui.TK_AVAILABLE:
            self.skipTest("Tk indisponível")
        with mock.patch.object(
            gui, "watermark_path", return_value="/nonexistent/watermark.png"
        ):
            self.assertIsNone(gui.load_watermark())


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
    """Montagem da janela — só com Tkinter funcional e display.

    As preferências são isoladas num `Settings()` em memória para os testes
    nunca lerem nem gravarem o `~/.pyssh-settings.json` real do usuário.
    """

    def setUp(self):
        from unittest import mock

        from pyssh.settings import Settings

        self._settings_patch = mock.patch(
            "pyssh.gui.load_settings", return_value=Settings()
        )
        self._save_patch = mock.patch("pyssh.gui.save_settings", return_value="/tmp/nul")
        self._settings_patch.start()
        self._save_patch.start()
        self.addCleanup(self._settings_patch.stop)
        self.addCleanup(self._save_patch.stop)

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

    def test_prefill_prioriza_rede_detectada_sobre_a_antiga(self):
        """A rede detectada vence `last_network` (bug: buscava só 1 IP)."""
        from unittest import mock

        from pyssh.gui import App
        from pyssh.settings import Settings

        # Preferência antiga aponta para um IP único; a detectada é a LAN real.
        stale = Settings(last_network="127.0.0.1/32")
        with mock.patch("pyssh.gui.load_settings", return_value=stale), mock.patch(
            "pyssh.gui.save_settings", return_value="/tmp/nul"
        ), mock.patch(
            "pyssh.gui.guess_network",
            return_value=mock.Mock(label="enp (192.168.8.50/24)", network="192.168.8.0/24"),
        ):
            app = App()
            try:
                self.assertEqual(app.network_var.get(), "192.168.8.0/24")
            finally:
                app.destroy()

    def test_marca_dagua_aplicada(self):
        """Fundo (canvas), banner e marcas nas áreas vazias estão na janela."""
        from pyssh.gui import WATERMARK_MAX_LOAD_PX, App

        app = App()
        try:
            self.assertIsNotNone(app._watermark, "load_watermark devolveu None")
            self.assertGreater(app._watermark.width(), 0)
            self.assertLessEqual(app._watermark.width(), WATERMARK_MAX_LOAD_PX)
            self.assertIsNotNone(app._wm_small)
            self.assertGreater(app._wm_small.width(), 0)
            self.assertIsNotNone(app._wm_dialog)
            self.assertIsNotNone(app._banner_logo)
            # Canvas de fundo com a imagem criada e centralizada no resize.
            self.assertTrue(app._bg_canvas.winfo_exists())
            self.assertIsNotNone(app._bg_item, "item da marca no canvas não criado")
            app._bg_canvas.update_idletasks()
            coords = app._bg_canvas.coords(app._bg_item)
            self.assertEqual(len(coords), 2)
        finally:
            app.destroy()

    def test_icone_da_janela_carregado(self):
        """O PNG da raiz é carregado e definido como ícone da janela."""
        from pyssh.gui import App, load_icon

        app = App()
        try:
            self.assertIsNotNone(app._icon, "load_icon devolveu None")
            self.assertGreater(app._icon.width(), 0)
            icon = load_icon(app)
            self.assertIsNotNone(icon)
            self.assertGreater(icon.width(), 0)
        finally:
            app.destroy()

    def test_tema_catppuccin_aplicado_na_janela(self):
        """A janela usa a paleta Mocha no fundo e nos widgets ttk."""
        from pyssh.gui import App

        app = App()
        try:
            self.assertEqual(str(app.cget("background")), CATPPUCCIN_MOCHA["base"])
            self.assertEqual(
                app.style.lookup("TButton", "background"),
                CATPPUCCIN_MOCHA["surface1"],
            )
            self.assertEqual(
                app.style.lookup("Treeview", "background"),
                CATPPUCCIN_MOCHA["mantle"],
            )
            self.assertEqual(
                str(app.log_panel.text.cget("background")),
                CATPPUCCIN_MOCHA["crust"],
            )
            self.assertEqual(
                app.log_panel.text.tag_cget("warn", "foreground"),
                CATPPUCCIN_MOCHA["yellow"],
            )
            self.assertEqual(
                app.log_panel.text.tag_cget("error", "foreground"),
                CATPPUCCIN_MOCHA["red"],
            )
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
