"""Testes da CLI ``pyssh-cli`` (sem Tkinter, sem rede externa)."""

import contextlib
import io
import unittest
from unittest import mock

import cli
from pyssh.scanner import HostResult, ScanAlreadyRunning, ScanError
from tests.test_scanner import Listener, free_closed_port


class FakeTty(io.StringIO):
    """Stdin que se comporta como terminal (isatty() == True)."""

    def isatty(self) -> bool:  # noqa: D401
        return True


@contextlib.contextmanager
def fake_ssh(path="/usr/bin/ssh"):
    with mock.patch("pyssh.ssh_client.shutil.which", return_value=path):
        yield path


def run(argv, stdin=None):
    """Executa main() capturando stdout/stderr e devolvendo o código."""
    out, err = io.StringIO(), io.StringIO()
    stdin = stdin if stdin is not None else io.StringIO("")  # não-tty
    with mock.patch("sys.stdin", stdin), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with fake_ssh():
            code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class HelpTests(unittest.TestCase):
    def test_sem_argumentos_mostra_ajuda(self):
        code, out, _ = run([])
        self.assertEqual(code, 0)
        self.assertIn("usage", out)
        self.assertIn("scan", out)
        self.assertIn("connect", out)

    def test_ajuda_explicita(self):
        code, out, _ = run(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("códigos de saída", out)

    def test_ajuda_do_subcomando(self):
        code, out, _ = run(["scan", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("--network", out)

    def test_opcao_desconhecida_e_erro_de_uso(self):
        code, _, err = run(["scan", "--bogus"])
        self.assertEqual(code, 2)
        self.assertIn("usage", err)

    def test_comando_desconhecido(self):
        code, _, _ = run(["voar"])
        self.assertEqual(code, 2)


class ScanValidationTests(unittest.TestCase):
    def test_porta_invalida(self):
        for bad in ("0", "65536", "abc"):
            code, _, err = run(["scan", "--network", "192.168.8.0/24", "--port", bad])
            self.assertEqual(code, 2, bad)
            self.assertIn("erro:", err)

    def test_timeout_invalido(self):
        code, _, err = run(["scan", "--network", "192.168.8.0/24", "--timeout", "0"])
        self.assertEqual(code, 2)
        self.assertIn("erro:", err)

    def test_workers_invalidos(self):
        code, _, err = run(["scan", "--network", "192.168.8.0/24", "--workers", "0"])
        self.assertEqual(code, 2)
        self.assertIn("erro:", err)

    def test_rede_invalida(self):
        code, _, err = run(["scan", "--network", "abc"])
        self.assertEqual(code, 2)
        self.assertIn("erro:", err)

    def test_scan_com_erro_de_scan(self):
        with mock.patch("cli.scan", side_effect=ScanError("algo falhou")):
            code, _, err = run(["scan", "--network", "127.0.0.1/32"])
        self.assertEqual(code, 2)
        self.assertIn("algo falhou", err)

    def test_scan_ja_em_andamento(self):
        with mock.patch("cli.scan", side_effect=ScanAlreadyRunning("já existe uma varredura")):
            code, _, err = run(["scan", "--network", "127.0.0.1/32"])
        self.assertEqual(code, 1)
        self.assertIn("já existe uma varredura", err)


class ScanTests(unittest.TestCase):
    def test_encontra_dispositivo(self):
        listener = Listener()
        self.addCleanup(listener.close)
        code, out, err = run(
            ["scan", "--network", "127.0.0.1/32", "--port", str(listener.port), "--quiet"]
        )
        self.assertEqual(code, 0)
        self.assertIn("127.0.0.1", out)
        self.assertIn(str(listener.port), out)
        self.assertIn("aberta", out)

    def test_nenhum_dispositivo(self):
        code, out, err = run(
            ["scan", "--network", "127.0.0.1/32", "--port", str(free_closed_port()), "--quiet"]
        )
        self.assertEqual(code, 3)
        self.assertEqual(out.strip(), "")
        self.assertIn("Nenhum dispositivo", err)

    def test_all_mostra_portas_fechadas(self):
        port = free_closed_port()
        code, out, _ = run(["scan", "--network", "127.0.0.1/32", "--port", str(port), "--all", "--quiet"])
        self.assertEqual(code, 3)  # nenhum aberto
        # ...mas com --all os resultados fechados são listados antes.
        self.assertIn("fechada", out)

    def test_resultados_no_stdout_progresso_no_stderr(self):
        listener = Listener()
        self.addCleanup(listener.close)
        code, out, err = run(
            ["scan", "--network", "127.0.0.1/32", "--port", str(listener.port), "--no-interactive"]
        )
        self.assertEqual(code, 0)
        self.assertIn("IP", out)          # tabela no stdout
        self.assertIn("aberta", out)
        self.assertNotIn("Selecione", out)  # sem seleção sem tty
        self.assertNotIn("Selecione", err)
        self.assertIn("Varrendo", err)      # progresso/informativo no stderr

    def test_interrupcao_retorna_130_com_resultados_parciais(self):
        def fake_scan(*args, **kwargs):
            kwargs["progress"](HostResult(ip="127.0.0.1", port=8022, open=True))
            raise KeyboardInterrupt

        with mock.patch("cli.scan", side_effect=fake_scan):
            code, out, err = run(["scan", "--network", "127.0.0.1/32", "--quiet"])
        self.assertEqual(code, 130)
        self.assertIn("127.0.0.1", out)
        self.assertIn("8022", out)
        self.assertIn("cancelada", err)

    def test_sem_interatividade_quando_stdin_nao_e_tty(self):
        listener = Listener()
        self.addCleanup(listener.close)
        # stdin não-tty: não deve tentar ler seleção.
        code, out, err = run(
            ["scan", "--network", "127.0.0.1/32", "--port", str(listener.port), "--quiet"]
        )
        self.assertEqual(code, 0)
        self.assertIn("aberta", out)          # tabela impressa no stdout
        self.assertNotIn("Dispositivos", out)  # lista interativa não aparece
        self.assertNotIn("Selecione", err)


class InteractiveTests(unittest.TestCase):
    def _results(self):
        return [
            HostResult(ip="192.168.8.52", port=8022, open=True, hostname="termux"),
            HostResult(ip="192.168.8.71", port=8022, open=True),
        ]

    def test_seleciona_indice(self):
        stdin, stderr = FakeTty("2\n"), io.StringIO()
        self.assertEqual(cli._select_device(self._results(), stdin, stderr), 1)
        self.assertIn("[1] 192.168.8.52:8022 (termux)", stderr.getvalue())
        self.assertIn("[2] 192.168.8.71:8022", stderr.getvalue())
        self.assertIn("Selecione um dispositivo", stderr.getvalue())

    def test_entrada_invalida_repete(self):
        stdin, stderr = FakeTty("0\nabc\n1\n"), io.StringIO()
        self.assertEqual(cli._select_device(self._results(), stdin, stderr), 0)
        self.assertIn("Opção inválida", stderr.getvalue())

    def test_enter_cancela(self):
        stdin, stderr = FakeTty("\n"), io.StringIO()
        self.assertIsNone(cli._select_device(self._results(), stdin, stderr))

    def test_eof_cancela(self):
        stdin, stderr = FakeTty(""), io.StringIO()
        self.assertIsNone(cli._select_device(self._results(), stdin, stderr))


class ScanThenConnectTests(unittest.TestCase):
    def test_selecao_interativa_conecta(self):
        listener = Listener()
        self.addCleanup(listener.close)
        stdin = FakeTty("1\n")
        with mock.patch("cli.run_interactive", return_value=0) as run_ssh:
            code, out, err = run(
                ["scan", "--network", "127.0.0.1/32", "--port", str(listener.port), "--quiet"],
                stdin=stdin,
            )
        self.assertEqual(code, 0)
        self.assertIn("Selecione um dispositivo", err)
        command = run_ssh.call_args[0][0]
        self.assertEqual(command[0], "/usr/bin/ssh")
        self.assertEqual(command[1:3], ["-p", str(listener.port)])
        self.assertEqual(command[-1], "127.0.0.1")

    def test_no_interactive_nao_conecta(self):
        listener = Listener()
        self.addCleanup(listener.close)
        with mock.patch("cli.run_interactive", return_value=0) as run_ssh:
            code, _, _ = run(
                ["scan", "--network", "127.0.0.1/32", "--port", str(listener.port), "--no-interactive"],
                stdin=FakeTty("1\n"),
            )
        self.assertEqual(code, 0)
        run_ssh.assert_not_called()

    def test_falha_do_ssh_na_conexao_retorna_4(self):
        listener = Listener()
        self.addCleanup(listener.close)
        with mock.patch("cli.run_interactive", return_value=255):
            code, _, err = run(
                ["scan", "--network", "127.0.0.1/32", "--port", str(listener.port), "--quiet"],
                stdin=FakeTty("1\n"),
            )
        self.assertEqual(code, 4)
        self.assertIn("ssh não conseguiu", err)


class ConnectTests(unittest.TestCase):
    def test_conexao_valida(self):
        with mock.patch("cli.run_interactive", return_value=0) as run_ssh:
            code, _, err = run(["connect", "192.168.8.52", "--user", "dev"])
        self.assertEqual(code, 0)
        self.assertEqual(
            run_ssh.call_args[0][0],
            ["/usr/bin/ssh", "-p", "8022", "-l", "dev", "192.168.8.52"],
        )
        self.assertIn("Conectando a 192.168.8.52:8022", err)

    def test_porta_customizada(self):
        with mock.patch("cli.run_interactive", return_value=0) as run_ssh:
            code, _, _ = run(["connect", "192.168.8.52", "--port", "22"])
        self.assertEqual(code, 0)
        self.assertEqual(run_ssh.call_args[0][0][1:3], ["-p", "22"])

    def test_argumentos_extras_apos_separador(self):
        with mock.patch("cli.run_interactive", return_value=0) as run_ssh:
            code, _, _ = run(["connect", "192.168.8.52", "--", "-4", "-v"])
        self.assertEqual(code, 0)
        command = run_ssh.call_args[0][0]
        self.assertEqual(command[-3:], ["-4", "-v", "192.168.8.52"])

    def test_host_invalido(self):
        for bad in ("999.1.1.1", "host invalido", ""):
            code, _, err = run(["connect", bad])
            self.assertEqual(code, 2, repr(bad))
            self.assertIn("erro:", err)

    def test_opcao_desconhecida_no_connect(self):
        code, _, err = run(["connect", "-x"])
        self.assertEqual(code, 2)
        self.assertIn("usage", err)

    def test_nome_de_host_e_aceito(self):
        with mock.patch("cli.run_interactive", return_value=0) as run_ssh:
            code, _, _ = run(["connect", "meu-pc.local"])
        self.assertEqual(code, 0)
        self.assertEqual(run_ssh.call_args[0][0][-1], "meu-pc.local")

    def test_porta_invalida(self):
        code, _, err = run(["connect", "192.168.8.52", "--port", "0"])
        self.assertEqual(code, 2)
        self.assertIn("erro:", err)

    def test_ssh_ausente(self):
        with mock.patch("pyssh.ssh_client.shutil.which", return_value=None):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["connect", "192.168.8.52"])
        self.assertEqual(code, 4)
        self.assertIn("openssh", err.getvalue())

    def test_ssh_retorna_255(self):
        with mock.patch("cli.run_interactive", return_value=255):
            code, _, err = run(["connect", "192.168.8.52"])
        self.assertEqual(code, 4)
        self.assertIn("ssh não conseguiu", err)

    def test_codigo_do_shell_remoto_e_propagado(self):
        with mock.patch("cli.run_interactive", return_value=7):
            code, _, _ = run(["connect", "192.168.8.52"])
        self.assertEqual(code, 7)

    def test_sinal_de_saida_e_convertido(self):
        with mock.patch("cli.run_interactive", return_value=-2):
            code, _, _ = run(["connect", "192.168.8.52"])
        self.assertEqual(code, 130)

    def test_interrupcao_retorna_130(self):
        with mock.patch("cli.run_interactive", side_effect=KeyboardInterrupt):
            code, _, err = run(["connect", "192.168.8.52"])
        self.assertEqual(code, 130)
        self.assertIn("Interrompido", err)


if __name__ == "__main__":
    unittest.main()
