"""Testes do módulo pyssh.scanner (sem Tkinter)."""

import socket
import threading
import unittest

from pyssh import scanner
from pyssh.scanner import (
    HostResult,
    ScanAlreadyRunning,
    ScanError,
    check_port,
    probe,
    resolve_targets,
    scan,
)


def free_closed_port() -> int:
    """Reserva e libera uma porta para obter um número provavelmente fechado."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Listener:
    """Servidor TCP mínimo de apenas aceita conexões."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        # Timeout curto para que o accept() não trave o join() no encerramento.
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self.stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self.thread.join(timeout=1)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.listener = Listener()
        self.addCleanup(self.listener.close)

    def test_porta_aberta(self):
        self.assertTrue(check_port("127.0.0.1", self.listener.port, 0.5))
        result = probe("127.0.0.1", self.listener.port, 0.5)
        self.assertTrue(result.open)
        self.assertIsNone(result.error)
        self.assertEqual(result.port, self.listener.port)
        self.assertEqual(result.status, "aberta")
        self.assertEqual(result.address, f"127.0.0.1:{self.listener.port}")

    def test_porta_fechada(self):
        port = free_closed_port()
        self.assertFalse(check_port("127.0.0.1", port, 0.5))
        result = probe("127.0.0.1", port, 0.5)
        self.assertFalse(result.open)
        self.assertEqual(result.status, "fechada")

    def test_probe_nunca_lanca(self):
        # Endereço sem rota não deve levantar exceção.
        result = probe("203.0.113.1", 65000, 0.2)
        self.assertIsInstance(result, HostResult)
        self.assertFalse(result.open)


class ResolveTargetsTests(unittest.TestCase):
    def test_cidr(self):
        hosts = resolve_targets("192.168.8.0/24")
        self.assertEqual(len(hosts), 254)

    def test_lista(self):
        self.assertEqual(resolve_targets(["127.0.0.1", " 10.0.0.1 "]), ["127.0.0.1", "10.0.0.1"])

    def test_invalido(self):
        with self.assertRaises(ScanError):
            resolve_targets("rede-invalida")


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.listener = Listener()
        self.addCleanup(self.listener.close)

    def test_encontra_porta_aberta_em_lista(self):
        seen = []
        report = scan(
            ["127.0.0.1"],
            port=self.listener.port,
            timeout=0.5,
            progress=seen.append,
        )
        self.assertEqual(report.port, self.listener.port)
        self.assertEqual(report.total, 1)
        self.assertTrue(report.results[0].open)
        self.assertFalse(report.cancelled)
        self.assertEqual(len(seen), 1)

    def test_porta_padrao_e_8022(self):
        # Sem servidor: apenas garante que a porta padrão é aceita.
        report = scan(["127.0.0.1"], port=8022, timeout=0.1)
        self.assertEqual(report.port, 8022)

    def test_porta_invalida_impede_a_busca(self):
        for bad in (0, 65536, "abc", None):
            with self.assertRaises(ScanError):
                scan(["127.0.0.1"], port=bad, timeout=0.2)

    def test_timeout_invalido(self):
        with self.assertRaises(ScanError):
            scan(["127.0.0.1"], port=8022, timeout=0)

    def test_workers_invalidos(self):
        with self.assertRaises(ScanError):
            scan(["127.0.0.1"], port=8022, workers=0)

    def test_rede_invalida(self):
        with self.assertRaises(ScanError):
            scan("10.0.0.0/8", timeout=0.2)

    def test_varredura_em_cidr_de_loopback(self):
        report = scan("127.0.0.0/30", port=self.listener.port, timeout=0.5, workers=4)
        self.assertEqual(report.network, "127.0.0.0/30")
        self.assertEqual(report.total, 2)
        by_ip = {r.ip: r for r in report.results}
        self.assertTrue(by_ip["127.0.0.1"].open)
        self.assertFalse(by_ip["127.0.0.2"].open)

    def test_ordenacao_por_ip(self):
        report = scan(["127.0.0.3", "127.0.0.1", "127.0.0.2"], port=free_closed_port(), timeout=0.2)
        self.assertEqual([r.ip for r in report.results], ["127.0.0.1", "127.0.0.2", "127.0.0.3"])

    def test_cancelamento(self):
        event = threading.Event()
        event.set()
        report = scan(["127.0.0.1", "127.0.0.2"], port=8022, timeout=0.2, cancel_event=event)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.total, 0)

    def test_impede_buscas_simultaneas(self):
        # Segura o bloqueio global e garante que uma nova varredura é recusada.
        self.assertTrue(scanner._scan_lock.acquire(blocking=False))
        try:
            with self.assertRaises(ScanAlreadyRunning):
                scan(["127.0.0.1"], port=8022, timeout=0.1)
        finally:
            scanner._scan_lock.release()

    def test_lock_liberado_apos_erro(self):
        with self.assertRaises(ScanError):
            scan(["127.0.0.1"], port=0, timeout=0.1)
        # Deve ser possível varrer logo em seguida.
        report = scan(["127.0.0.1"], port=free_closed_port(), timeout=0.2)
        self.assertEqual(report.total, 1)

    def test_hostname_opcional(self):
        report = scan(
            ["127.0.0.1"],
            port=self.listener.port,
            timeout=0.5,
            lookup_hostname=True,
        )
        self.assertTrue(report.results[0].open)


if __name__ == "__main__":
    unittest.main()
