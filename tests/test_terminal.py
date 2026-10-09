"""Testes do módulo pyssh.terminal (sem Tkinter, sem display)."""

import os
import sys
import unittest
from unittest import mock

from pyssh.ssh_client import SSHError
from pyssh.terminal import (
    TERMINALS,
    NoTerminalFound,
    build_terminal_command,
    detect_system_terminal,
    exec_args_for,
    find_terminal,
    require_terminal,
    spawn_session,
)


class FindTerminalTests(unittest.TestCase):
    def test_ordem_de_preferencia(self):
        nomes = [name for name, _ in TERMINALS]
        self.assertEqual(nomes[0], "kitty")
        self.assertIn("xterm", nomes)

    def test_primeiro_terminal_instalado(self):
        def fake_which(name):
            return "/usr/bin/xfce4-terminal" if name == "xfce4-terminal" else None

        with mock.patch("pyssh.terminal.shutil.which", side_effect=fake_which):
            self.assertEqual(find_terminal(), ["/usr/bin/xfce4-terminal", "-x"])

    def test_kitty_tem_prioridade(self):
        with mock.patch("pyssh.terminal.detect_system_terminal", return_value=None), mock.patch(
            "pyssh.terminal.shutil.which", return_value="/usr/bin/qualquer"
        ):
            terminal = find_terminal()
        self.assertEqual(terminal[0], "/usr/bin/qualquer")
        self.assertEqual(terminal[1], "-e")  # base do primeiro item (kitty)

    def test_nenhum_terminal(self):
        with mock.patch("pyssh.terminal.shutil.which", return_value=None):
            self.assertIsNone(find_terminal())
            with self.assertRaises(NoTerminalFound) as ctx:
                require_terminal()
        self.assertIn("Instale", str(ctx.exception))

    def test_terminal_configurado(self):
        with mock.patch("pyssh.terminal.shutil.which", return_value="/opt/kitty/bin/kitty"):
            self.assertEqual(find_terminal("kitty"), ["/opt/kitty/bin/kitty", "-e"])

    def test_terminal_configurado_desconhecido_usa_convencao_e(self):
        # Sem entrada na tabela, vale a convenção xterm: -e (alacritty exige).
        with mock.patch("pyssh.terminal.shutil.which", return_value="/usr/bin/alacritty"):
            self.assertEqual(find_terminal("alacritty"), ["/usr/bin/alacritty", "-e"])
        with mock.patch("pyssh.terminal.shutil.which", return_value="/usr/bin/gnome-terminal"):
            self.assertEqual(find_terminal("gnome-terminal"), ["/usr/bin/gnome-terminal", "--"])

    def test_terminal_configurado_ausente(self):
        with mock.patch("pyssh.terminal.shutil.which", return_value=None):
            self.assertIsNone(find_terminal("fantasma"))

    def test_terminal_configurado_vence_o_sistema(self):
        with mock.patch("pyssh.terminal.detect_system_terminal") as detect, mock.patch(
            "pyssh.terminal.shutil.which", return_value="/usr/bin/kitty"
        ):
            terminal = find_terminal("kitty")
        detect.assert_not_called()
        self.assertEqual(terminal, ["/usr/bin/kitty", "-e"])


class DetectSystemTerminalTests(unittest.TestCase):
    def test_xdg_terminal_exec_tem_prioridade(self):
        def fake_which(name):
            return "/usr/bin/xdg-terminal-exec" if name == "xdg-terminal-exec" else None

        with mock.patch("pyssh.terminal.shutil.which", side_effect=fake_which):
            self.assertEqual(detect_system_terminal(), ["/usr/bin/xdg-terminal-exec", "--"])

    def test_variavel_ambient_terminal(self):
        def fake_which(name):
            return "/usr/bin/alacritty" if name == "alacritty" else None

        with mock.patch.dict(os.environ, {"TERMINAL": "alacritty"}), mock.patch(
            "pyssh.terminal.shutil.which", side_effect=fake_which
        ):
            self.assertEqual(detect_system_terminal(), ["/usr/bin/alacritty", "-e"])

    def test_variavel_ambient_terminal_vazia_e_ignorada(self):
        with mock.patch.dict(os.environ, {"TERMINAL": ""}), mock.patch(
            "pyssh.terminal.shutil.which", return_value=None
        ):
            self.assertIsNone(detect_system_terminal())

    def test_x_terminal_emulator_usa_o_alvo_do_link(self):
        def fake_which(name):
            return "/usr/bin/x-terminal-emulator" if name == "x-terminal-emulator" else None

        with mock.patch("pyssh.terminal.shutil.which", side_effect=fake_which), mock.patch(
            "pyssh.terminal.os.path.realpath", return_value="/usr/bin/gnome-terminal"
        ):
            self.assertEqual(detect_system_terminal(), ["/usr/bin/x-terminal-emulator", "--"])

    def test_nenhuma_fonte_do_sistema(self):
        with mock.patch.dict(os.environ, {"TERMINAL": ""}), mock.patch(
            "pyssh.terminal.shutil.which", return_value=None
        ):
            self.assertIsNone(detect_system_terminal())

    def test_find_terminal_prefere_o_sistema(self):
        # Sem terminal configurado, a detecção do sistema vence a lista fixa.
        with mock.patch("pyssh.terminal.detect_system_terminal", return_value=["/usr/bin/alacritty", "-e"]), mock.patch(
            "pyssh.terminal.shutil.which", return_value="/usr/bin/kitty"
        ):
            self.assertEqual(find_terminal(), ["/usr/bin/alacritty", "-e"])

    def test_find_terminal_cai_na_lista_sem_sistema(self):
        def fake_which(name):
            return "/usr/bin/xfce4-terminal" if name == "xfce4-terminal" else None

        with mock.patch("pyssh.terminal.detect_system_terminal", return_value=None), mock.patch(
            "pyssh.terminal.shutil.which", side_effect=fake_which
        ):
            self.assertEqual(find_terminal(), ["/usr/bin/xfce4-terminal", "-x"])


class ExecArgsTests(unittest.TestCase):
    def test_tabela_conhecida(self):
        self.assertEqual(exec_args_for("/usr/bin/kitty"), ["-e"])
        self.assertEqual(exec_args_for("/usr/bin/gnome-terminal"), ["--"])
        self.assertEqual(exec_args_for("/usr/bin/xfce4-terminal"), ["-x"])

    def test_desconhecido_vira_e(self):
        self.assertEqual(exec_args_for("/usr/bin/fantasma"), ["-e"])
        self.assertEqual(exec_args_for("fantasma"), ["-e"])


class BuildTerminalCommandTests(unittest.TestCase):
    def test_junta_terminal_e_ssh(self):
        cmd = build_terminal_command(["kitty", "-e"], ["ssh", "-p", "8022", "192.168.8.52"])
        self.assertEqual(cmd, ["kitty", "-e", "ssh", "-p", "8022", "192.168.8.52"])

    def test_gnome_terminal_usa_separador(self):
        cmd = build_terminal_command(["gnome-terminal", "--"], ["ssh", "192.168.8.52"])
        self.assertEqual(cmd[-3:], ["--", "ssh", "192.168.8.52"])

    def test_terminal_vazio(self):
        with self.assertRaises(NoTerminalFound):
            build_terminal_command([], ["ssh", "x"])


class SpawnSessionTests(unittest.TestCase):
    def test_devolve_pid(self):
        pid = spawn_session([sys.executable, "-c", "pass"])
        self.assertIsInstance(pid, int)
        self.assertGreater(pid, 0)

    def test_comando_vazio(self):
        with self.assertRaises(SSHError):
            spawn_session([])

    def test_executavel_inexistente(self):
        with self.assertRaises(NoTerminalFound):
            spawn_session(["/bin/nao-existe-pyssh"])

    def test_sessao_sobrevive_ao_processo_pai(self):
        # O processo é criado em novo grupo de sessão (setsid) e não bloqueia.
        codigo = (
            "import sys, time;"
            "time.sleep(0.2)"
        )
        pid = spawn_session([sys.executable, "-c", codigo])
        self.assertGreater(pid, 0)


if __name__ == "__main__":
    unittest.main()
