"""Testes do módulo pyssh.settings (sem Tkinter)."""

import os
import tempfile
import unittest

from pyssh.settings import (
    DEFAULT_PORT,
    Settings,
    SettingsError,
    load_settings,
    save_settings,
    validate_port,
    validate_timeout,
    validate_workers,
)


class PortTests(unittest.TestCase):
    def test_porta_padrao_e_8022(self):
        self.assertEqual(DEFAULT_PORT, 8022)
        self.assertEqual(validate_port(8022), 8022)
        self.assertEqual(validate_port("8022"), 8022)
        self.assertEqual(validate_port(" 22 "), 22)

    def test_limites(self):
        self.assertEqual(validate_port(1), 1)
        self.assertEqual(validate_port(65535), 65535)
        for bad in (0, 65536, -1, "0", "65536"):
            with self.assertRaises(SettingsError):
                validate_port(bad)

    def test_valores_invalidos(self):
        for bad in (None, "", "   ", "abc", "80a2", True, 1.5):
            with self.assertRaises(SettingsError):
                validate_port(bad)


class TimeoutAndWorkersTests(unittest.TestCase):
    def test_timeout(self):
        self.assertEqual(validate_timeout(0.5), 0.5)
        self.assertEqual(validate_timeout("1"), 1.0)
        for bad in (0, -0.1, None, "abc", True):
            with self.assertRaises(SettingsError):
                validate_timeout(bad)

    def test_workers(self):
        self.assertEqual(validate_workers(32), 32)
        for bad in (0, -5, None, "muitos", True):
            with self.assertRaises(SettingsError):
                validate_workers(bad)


class SettingsPersistenceTests(unittest.TestCase):
    def test_padroes(self):
        s = Settings()
        self.assertEqual(s.port, 8022)
        self.assertIsNone(s.last_network)

    def test_normaliza_na_criacao(self):
        s = Settings(port="22", timeout="0.2", workers="8")
        self.assertEqual(s.port, 22)
        self.assertEqual(s.timeout, 0.2)
        self.assertEqual(s.workers, 8)

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            original = Settings(port=8022, last_network="192.168.8.0/24", terminal="kitty")
            save_settings(original, path)
            loaded = load_settings(path)
            self.assertEqual(loaded.port, original.port)
            self.assertEqual(loaded.last_network, "192.168.8.0/24")
            self.assertEqual(loaded.terminal, "kitty")

    def test_arquivo_ausente_retorna_padroes(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_settings(os.path.join(tmp, "nao-existe.json"))
            self.assertEqual(loaded.port, 8022)

    def test_arquivo_corrompido_retorna_padroes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            self.assertEqual(load_settings(path).port, 8022)


if __name__ == "__main__":
    unittest.main()
