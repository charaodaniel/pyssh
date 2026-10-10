"""Testes da CLI ``pyssh-cli`` (sem Tkinter, sem rede externa)."""

import contextlib
import io
import json
import os
import shutil
import tempfile
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
    """Finge que o ``ssh`` existe SEM esconder os demais binários.

    O patch em ``shutil.which`` é global (o módulo é o mesmo objeto em todo
    o processo); por isso só o ``ssh`` é falsificado e qualquer outra busca
    (``ssh-keygen``, terminais) vai ao ``which`` real.
    """
    real_which = shutil.which

    def which(name, *args, **kwargs):
        if name == "ssh":
            return path
        return real_which(name, *args, **kwargs)

    with mock.patch("pyssh.ssh_client.shutil.which", side_effect=which):
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


class NewCommandsTests(unittest.TestCase):
    """Subcomandos connections/keys/history (isolados em XDG temporário)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = os.path.join(self.tmp.name, "cfg")
        data = os.path.join(self.tmp.name, "data")
        self.env = mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": cfg, "XDG_DATA_HOME": data}
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    # ----- connections -----

    def test_connections_add_list(self):
        code, out, _ = run(
            ["connections", "add", "-n", "Termux", "-H", "192.168.8.54", "-u", "termux"]
        )
        self.assertEqual(code, 0)
        self.assertIn("Conexão criada", out)

        code, out, _ = run(["connections", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Termux", out)
        self.assertIn("192.168.8.54", out)

    def test_connections_add_sem_args(self):
        code, _, err = run(["connections", "add"])
        self.assertEqual(code, 2)
        self.assertIn("--name", err)

    def test_connections_add_host_invalido(self):
        code, _, err = run(["connections", "add", "-n", "X", "-H", "999.999.999.999"])
        self.assertEqual(code, 2)
        self.assertIn("erro:", err)

    def test_connections_edit(self):
        run(["connections", "add", "-n", "Termux", "-H", "192.168.8.54"])
        code, out, _ = run(["connections", "edit", "Termux", "-u", "dev"])
        self.assertEqual(code, 0)
        self.assertIn("atualizada", out)

    def test_connections_delete_sem_confirmacao_nao_tty(self):
        run(["connections", "add", "-n", "Termux", "-H", "192.168.8.54"])
        code, _, err = run(["connections", "delete", "Termux"])  # stdin não-tty
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)

    def test_connections_delete_yes(self):
        run(["connections", "add", "-n", "Termux", "-H", "192.168.8.54"])
        code, out, _ = run(["connections", "delete", "Termux", "--yes"])
        self.assertEqual(code, 0)
        self.assertIn("excluída", out)

    def test_connections_delete_inexistente(self):
        code, _, err = run(["connections", "delete", "nao", "--yes"])
        self.assertEqual(code, 2)
        self.assertIn("não encontrada", err)

    def test_connections_duplicate(self):
        run(["connections", "add", "-n", "Termux", "-H", "192.168.8.54"])
        code, out, _ = run(["connections", "duplicate", "Termux"])
        self.assertEqual(code, 0)
        self.assertIn("duplicada", out)

    def test_connections_vazio(self):
        code, _, err = run(["connections", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Nenhuma conexão", err)

    def test_connect_por_nome_usa_conexao_salva(self):
        run(["connections", "add", "-n", "Termux", "-H", "192.168.8.54", "-p", "8022", "-u", "termux"])
        with mock.patch("cli.run_interactive", return_value=0) as run_ssh:
            code, _, _ = run(["connect", "Termux"])
        self.assertEqual(code, 0)
        command = run_ssh.call_args[0][0]
        self.assertIn("192.168.8.54", command)
        self.assertIn("termux", command)

    # ----- keys -----

    def test_keys_list_vazio(self):
        code, _, err = run(["keys", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Nenhuma chave", err)

    def test_keys_add_e_list(self):
        code, out, _ = run(["keys", "add", "-n", "casa", "--path", "/tmp/chave-x"])
        self.assertEqual(code, 0)
        self.assertIn("cadastrada", out)
        code, out, _ = run(["keys", "list"])
        self.assertIn("casa", out)
        self.assertIn("AUSENTE", out)  # arquivo não existe ainda

    def test_keys_add_sem_args(self):
        code, _, err = run(["keys", "add"])
        self.assertEqual(code, 2)
        self.assertIn("--name", err)

    def test_keys_delete_inexistente(self):
        code, _, err = run(["keys", "delete", "nao", "--yes"])
        self.assertEqual(code, 2)
        self.assertIn("não encontrada", err)

    def test_keys_show_dados_e_publica(self):
        key = os.path.join(self.tmp.name, "id_show")
        with open(key, "w") as fh:
            fh.write("x")
        pub = key + ".pub"
        with open(pub, "w") as fh:
            fh.write("ssh-ed25519 AAAA3Nza test@host\n")
        run(["keys", "add", "-n", "showcase", "--path", key])

        code, out, _ = run(["keys", "show", "showcase"])
        self.assertEqual(code, 0)
        self.assertIn("showcase", out)
        self.assertIn("ssh-ed25519 AAAA3Nza", out)
        self.assertIn("AAAA3Nza", out)

        # --public-only imprime só a linha da pública (para colar no servidor).
        code, out, _ = run(["keys", "show", "showcase", "--public-only"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "ssh-ed25519 AAAA3Nza test@host")

    def test_keys_show_inexistente(self):
        code, _, err = run(["keys", "show", "nao"])
        self.assertEqual(code, 2)
        self.assertIn("não encontrada", err)

    def test_keys_generate_sem_path_usa_padrao(self):
        if shutil.which("ssh-keygen") is None:
            self.skipTest("ssh-keygen indisponível")
        home = os.path.join(self.tmp.name, "home")
        os.makedirs(home)
        with mock.patch.dict(os.environ, {"HOME": home}):
            code, out, _ = run(["keys", "generate"])
        self.assertEqual(code, 0)
        expected = os.path.join(home, ".ssh", "id_ed25519")
        self.assertIn(expected, out)
        self.assertTrue(os.path.isfile(expected))
        self.assertIn("SHA256:", out)
        self.assertIn("salva como referência", out)

    # ----- history -----

    def test_history_list_vazio(self):
        code, _, err = run(["history", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Nenhum evento", err)

    def test_history_registra_e_lista(self):
        from pyssh import history

        history.record("scan_started", address="192.168.8.0/24", port=8022, status="ok")
        code, out, _ = run(["history", "list"])
        self.assertEqual(code, 0)
        self.assertIn("scan_started", out)

    def test_history_filtro_event(self):
        from pyssh import history

        history.record("scan_started", address="192.168.8.0/24")
        history.record("device_found", address="192.168.8.54")
        code, out, _ = run(["history", "list", "--event", "device_found"])
        self.assertEqual(code, 0)
        self.assertIn("device_found", out)
        self.assertNotIn("scan_started", out)

    def test_history_export_csv(self):
        from pyssh import history

        history.record("scan_started", address="192.168.8.0/24", port=8022, status="ok")
        destino = os.path.join(self.tmp.name, "out.csv")
        code, out, _ = run(["history", "export", "-o", destino, "-f", "csv"])
        self.assertEqual(code, 0)
        self.assertIn("Exportado", out)
        self.assertTrue(os.path.isfile(destino))
        with open(destino, encoding="utf-8") as fh:
            self.assertIn("scan_started", fh.read())

    def test_history_export_json(self):
        from pyssh import history

        history.record("scan_started", address="192.168.8.0/24", port=8022, status="ok")
        destino = os.path.join(self.tmp.name, "out.json")
        code, out, _ = run(["history", "export", "-o", destino, "-f", "json"])
        self.assertEqual(code, 0)
        self.assertIn("Exportado", out)
        with open(destino, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertIsInstance(payload, list)
        self.assertTrue(any(item["event"] == "scan_started" for item in payload))

    def test_history_export_sem_eventos(self):
        code, _, err = run(["history", "export"])
        self.assertEqual(code, 3)
        self.assertIn("Nenhum evento", err)

    def test_history_clear_yes(self):
        from pyssh import history

        history.record("scan_started", address="192.168.8.0/24")
        code, out, _ = run(["history", "clear", "--yes"])
        self.assertEqual(code, 0)
        self.assertIn("apagado", out)

    def test_history_fields(self):
        code, out, _ = run(["history", "fields"])
        self.assertEqual(code, 0)
        self.assertIn("scan_started", out)


if __name__ == "__main__":
    unittest.main()
