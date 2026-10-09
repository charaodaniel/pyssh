"""Testes do módulo pyssh.ssh_client (sem Tkinter, sem rede)."""

import shutil
import sys
import unittest
from unittest import mock

from pyssh.ssh_client import (
    SSHClientNotFound,
    SSHError,
    build_command,
    find_ssh,
    format_command,
    require_ssh,
    run_interactive,
)


class FindSSHTests(unittest.TestCase):
    def test_require_ssh_quando_instalado(self):
        if not shutil.which("ssh"):
            self.skipTest("OpenSSH não instalado")
        path = require_ssh()
        self.assertTrue(path.endswith("ssh"))

    def test_require_ssh_ausente(self):
        with mock.patch("pyssh.ssh_client.shutil.which", return_value=None):
            self.assertIsNone(find_ssh())
            with self.assertRaises(SSHClientNotFound) as ctx:
                require_ssh()
        self.assertIn("openssh", str(ctx.exception))

    def test_erro_e_ssh_error(self):
        with mock.patch("pyssh.ssh_client.shutil.which", return_value=None):
            with self.assertRaises(SSHError):
                require_ssh()  # SSHClientNotFound é subclasse de SSHError


class BuildCommandTests(unittest.TestCase):
    def test_comando_padrao(self):
        with mock.patch("pyssh.ssh_client.shutil.which", return_value="/usr/bin/ssh"):
            cmd = build_command("192.168.8.52")
        self.assertEqual(cmd, ["/usr/bin/ssh", "-p", "8022", "192.168.8.52"])

    def test_comando_com_usuario_e_porta(self):
        with mock.patch("pyssh.ssh_client.shutil.which", return_value="/usr/bin/ssh"):
            cmd = build_command("192.168.8.52", user="dev", port=22)
        self.assertEqual(cmd, ["/usr/bin/ssh", "-p", "22", "-l", "dev", "192.168.8.52"])

    def test_argumentos_extras_antes_do_host(self):
        with mock.patch("pyssh.ssh_client.shutil.which", return_value="/usr/bin/ssh"):
            cmd = build_command("192.168.8.52", extra=["-4", "-v"])
        self.assertEqual(cmd[-3:], ["-4", "-v", "192.168.8.52"])
        self.assertEqual(cmd[0], "/usr/bin/ssh")

    def test_porta_invalida(self):
        with mock.patch("pyssh.ssh_client.shutil.which", return_value="/usr/bin/ssh"):
            for bad in (0, 65536, "abc", None):
                with self.assertRaises(SSHError):
                    build_command("192.168.8.52", port=bad)

    def test_nao_usa_shell(self):
        with mock.patch("pyssh.ssh_client.shutil.which", return_value="/usr/bin/ssh"):
            cmd = build_command("192.168.8.52", user="a b")
        self.assertIn("a b", cmd)  # argumento único, não dividido
        self.assertEqual(len(cmd), 6)


class FormatCommandTests(unittest.TestCase):
    def test_formatacao_segura(self):
        text = format_command(["ssh", "-p", "8022", "dev@192.168.8.52"])
        self.assertEqual(text, "ssh -p 8022 dev@192.168.8.52")

    def test_aspas_em_argumento_com_espaco(self):
        text = format_command(["ssh", "a b"])
        self.assertEqual(text, "ssh 'a b'")


class RunInteractiveTests(unittest.TestCase):
    def test_retorna_codigo_do_processo(self):
        code = run_interactive([sys.executable, "-c", "import sys; sys.exit(7)"])
        self.assertEqual(code, 7)

    def test_sucesso(self):
        code = run_interactive([sys.executable, "-c", "pass"])
        self.assertEqual(code, 0)

    def test_binario_inexistente(self):
        with self.assertRaises(SSHClientNotFound):
            run_interactive(["/bin/nao-existe-pyssh"])

    def test_permissao_negada(self):
        with self.assertRaises(SSHError):
            run_interactive(["/proc/1/mem"])


if __name__ == "__main__":
    unittest.main()
