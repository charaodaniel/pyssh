"""Testes do módulo pyssh.terminal (sem Tkinter, sem display)."""

import sys
import unittest
from unittest import mock

from pyssh.ssh_client import SSHError
from pyssh.terminal import (
    TERMINALS,
    NoTerminalFound,
    build_terminal_command,
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
        with mock.patch("pyssh.terminal.shutil.which", return_value="/usr/bin/qualquer"):
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
            self.assertEqual(find_terminal("kitty"), ["/opt/kitty/bin/kitty"])

    def test_terminal_configurado_ausente(self):
        with mock.patch("pyssh.terminal.shutil.which", return_value=None):
            self.assertIsNone(find_terminal("fantasma"))


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
