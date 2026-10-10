"""Testes do módulo pyssh.history (JSONL, filtros, exportação, rotação)."""

import csv
import json
import os
import tempfile
import unittest

from pyssh import history


class BaseHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "history.jsonl")


class RecordTests(BaseHistory):
    def test_registra_e_lista(self):
        history.record("scan_started", address="192.168.8.0/24", port=8022, status="iniciado", path=self.path)
        rows = history.events(path=self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "scan_started")
        self.assertEqual(rows[0]["port"], 8022)
        self.assertIn("timestamp", rows[0])

    def _unwritable_path(self):
        """Caminho cujo diretório pai é um ARQUIVO (gravação impossível)."""
        blocker = os.path.join(self.tmp.name, "bloqueador")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("x")
        return os.path.join(blocker, "sub", "h.jsonl")

    def test_record_safe_nao_levanta(self):
        self.assertFalse(history.record_safe("x", path=self._unwritable_path()))

    def test_record_levanta_em_falha(self):
        with self.assertRaises(history.HistoryError):
            history.record("x", path=self._unwritable_path())

    def test_evento_vazio_levanta(self):
        with self.assertRaises(history.HistoryError):
            history.record("", path=self.path)

    def test_mensagem_longa_e_truncada(self):
        history.record("evt", message="A" * 2000, path=self.path)
        rows = history.events(path=self.path)
        self.assertLessEqual(len(rows[0]["message"]), 1000)


class FilterTests(BaseHistory):
    def _seed(self):
        history.record("scan_started", address="192.168.8.0/24", status="iniciado", path=self.path)
        history.record("device_found", address="192.168.8.54", status="aberta", path=self.path)
        history.record("connection_attempt", address="192.168.8.54", status="tentativa", path=self.path)

    def test_filtro_event(self):
        self._seed()
        rows = history.events(path=self.path, event="device_found")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "device_found")

    def test_filtro_status(self):
        self._seed()
        self.assertEqual(len(history.events(path=self.path, status="tentativa")), 1)

    def test_filtro_address_substring(self):
        self._seed()
        rows = history.events(path=self.path, address="192.168.8")
        self.assertEqual(len(rows), 3)
        rows = history.events(path=self.path, address=".54")
        self.assertEqual(len(rows), 2)

    def test_filtro_since_until(self):
        self._seed()
        self.assertEqual(len(history.events(path=self.path, since="2099-01-01")), 0)
        self.assertEqual(len(history.events(path=self.path, since="2000-01-01")), 3)
        self.assertEqual(len(history.events(path=self.path, until="2000-01-01")), 0)

    def test_limit(self):
        self._seed()
        rows = history.events(path=self.path, limit=2)
        self.assertEqual(len(rows), 2)
        # Mantém os mais recentes.
        self.assertEqual(rows[-1]["event"], "connection_attempt")

    def test_arquivo_corrompido_linha_ignorada(self):
        history.record("ok", path=self.path)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write("{ lixo\n")
        history.record("ok2", path=self.path)
        self.assertEqual(len(history.events(path=self.path)), 2)

    def test_limit_zero_significa_todos(self):
        """Regressão: limit=0 retornava vazio e quebrava a exportação da GUI."""
        for i in range(3):
            history.record(f"e{i}", path=self.path)
        self.assertEqual(len(history.events(limit=0, path=self.path)), 3)
        self.assertEqual(len(history.events(limit=None, path=self.path)), 3)
        self.assertEqual(len(history.events(limit=2, path=self.path)), 2)


class ExportTests(BaseHistory):
    def _seed(self):
        history.record("scan_started", address="192.168.8.0/24", port=8022, status="ok", path=self.path)

    def test_export_csv(self):
        self._seed()
        rows = history.events(path=self.path)
        out = os.path.join(self.tmp.name, "out.csv")
        history.export(rows, out, "csv")
        with open(out, encoding="utf-8", newline="") as fh:
            reader = list(csv.DictReader(fh))
        self.assertEqual(reader[0]["event"], "scan_started")
        self.assertEqual(reader[0]["port"], "8022")

    def test_export_jsonl(self):
        self._seed()
        rows = history.events(path=self.path)
        out = os.path.join(self.tmp.name, "out.jsonl")
        history.export(rows, out, "jsonl")
        with open(out, encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(lines[0]["event"], "scan_started")

    def test_export_json(self):
        self._seed()
        rows = history.events(path=self.path)
        out = os.path.join(self.tmp.name, "out.json")
        history.export(rows, out, "json")
        with open(out, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["event"], "scan_started")
        self.assertEqual(payload[0]["port"], 8022)

    def test_export_formato_invalido(self):
        self._seed()
        rows = history.events(path=self.path)
        with self.assertRaises(history.HistoryError):
            history.export(rows, os.path.join(self.tmp.name, "x"), "xml")


class RotationTests(BaseHistory):
    def test_rotacao_por_tamanho(self):
        # Limite minúsculo força rotação a cada evento.
        history.record("e1", path=self.path, max_bytes=10)
        history.record("e2", path=self.path, max_bytes=10)
        history.record("e3", path=self.path, max_bytes=10)
        # O arquivo ativo tem no máximo o último; os anteriores giraram.
        self.assertTrue(os.path.exists(self.path))
        self.assertTrue(os.path.exists(self.path + ".1"))
        # A leitura junta ativo + rotações.
        all_rows = history.events(path=self.path)
        self.assertGreaterEqual(len(all_rows), 2)


class ClearTests(BaseHistory):
    def test_clear_remove_tudo(self):
        history.record("a", path=self.path)
        history.record("b", path=self.path)
        removed = history.clear(path=self.path)
        self.assertEqual(removed, 2)
        self.assertEqual(history.events(path=self.path), [])

    def test_clear_arquivo_inexistente(self):
        self.assertEqual(history.clear(path=os.path.join(self.tmp.name, "nao.jsonl")), 0)


if __name__ == "__main__":
    unittest.main()
