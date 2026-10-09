"""Testes do módulo pyssh.storage (sem Tkinter)."""

import json
import os
import tempfile
import unittest
from unittest import mock

from pyssh.storage import (
    StorageError,
    append_jsonl,
    config_dir,
    data_dir,
    private_key_warning,
    read_json,
    read_jsonl,
    write_csv,
    write_json_atomic,
)


class DirTests(unittest.TestCase):
    def test_config_dir_respeita_xdg(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg-cfg"}):
            self.assertEqual(config_dir(), "/tmp/xdg-cfg/pyssh")

    def test_data_dir_respeita_xdg(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg-data"}):
            self.assertEqual(data_dir(), "/tmp/xdg-data/pyssh")


class JsonTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.json")
            write_json_atomic(path, {"a": 1})
            self.assertEqual(read_json(path), {"a": 1})

    def test_ausente_devolve_default(self):
        self.assertEqual(read_json("/tmp/nao-existe.json", default={"k": 0}), {"k": 0})

    def test_default_e_copia(self):
        # Mutar o retorno não pode contaminar o default do chamador.
        default = {"lista": []}
        result = read_json("/tmp/nao-existe.json", default=default)
        result["lista"].append(1)
        self.assertEqual(default, {"lista": []})

    def test_corrompido_levanta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            with self.assertRaises(StorageError):
                read_json(path)

    def test_tipo_inesperado_levanta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "list.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([1, 2], fh)
            with self.assertRaises(StorageError):
                read_json(path, expected=(dict,))

    def test_gravacao_atômica_com_permissão_restrita(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cfg", "x.json")
            write_json_atomic(path, {"ok": True})
            self.assertTrue(os.path.isfile(path))
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600)
            # Nenhum arquivo temporário sobra.
            leftovers = [n for n in os.listdir(os.path.dirname(path)) if n.endswith(".tmp")]
            self.assertEqual(leftovers, [])


class JsonlTests(unittest.TestCase):
    def test_append_e_leitura(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            append_jsonl(path, {"n": 1})
            append_jsonl(path, {"n": 2})
            records = read_jsonl(path)
            self.assertEqual([r["n"] for r in records], [1, 2])

    def test_linha_corrompida_e_ignorada(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"ok": 1}\n{ lixo\n{"ok": 2}\n')
            self.assertEqual([r["ok"] for r in read_jsonl(path)], [1, 2])

    def test_ausente_devolve_lista_vazia(self):
        self.assertEqual(read_jsonl("/tmp/nao-existe.jsonl"), [])


class CsvTests(unittest.TestCase):
    def test_exporta_com_cabecalho(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            write_csv(path, [{"a": 1, "b": "x"}], ["a", "b"])
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            self.assertEqual(lines[0], "a,b")
            self.assertEqual(lines[1], "1,x")

    def test_none_vira_vazio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            write_csv(path, [{"a": None, "b": "y"}], ["a", "b"])
            with open(path, encoding="utf-8") as fh:
                self.assertIn(",y", fh.read())


class PermissionTests(unittest.TestCase):
    def test_permissao_restrita_sem_aviso(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "id")
            with open(path, "w") as fh:
                fh.write("x")
            os.chmod(path, 0o600)
            self.assertIsNone(private_key_warning(path))

    def test_permissao_ampla_avaisa(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "id")
            with open(path, "w") as fh:
                fh.write("x")
            os.chmod(path, 0o644)
            warning = private_key_warning(path)
            self.assertIsNotNone(warning)
            self.assertIn("chmod 600", warning)

    def test_arquivo_inexistente_sem_erro(self):
        self.assertIsNone(private_key_warning("/tmp/nao-existe-chave"))


if __name__ == "__main__":
    unittest.main()
