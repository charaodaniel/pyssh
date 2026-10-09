"""Testes do módulo pyssh.connections (CRUD de conexões salvas)."""

import os
import tempfile
import unittest

from pyssh.connections import ConnectionStore, ConnectionsError


class BaseStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "connections.json")
        self.store = ConnectionStore(self.path)


class CrudTests(BaseStore):
    def test_add_e_list(self):
        self.store.add("Termux", "192.168.8.54", 8022, user="termux")
        items = self.store.list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Termux")
        self.assertEqual(items[0].port, 8022)

    def test_porta_padrao_e_8022(self):
        c = self.store.add("Casa", "192.168.1.10")
        self.assertEqual(c.port, 8022)

    def test_get_por_nome_e_id(self):
        c = self.store.add("Termux", "192.168.8.54")
        self.assertEqual(self.store.get("Termux").id, c.id)
        self.assertEqual(self.store.get(c.id).id, c.id)
        self.assertEqual(self.store.get("TERMUX").id, c.id)  # sem diferenciar caixa
        self.assertIsNone(self.store.get("nao-existe"))

    def test_require_inexistente_levanta(self):
        with self.assertRaises(ConnectionsError):
            self.store.require("fantasma")

    def test_update(self):
        c = self.store.add("Termux", "192.168.8.54")
        self.store.update(c.id, port=8023, user="dev")
        updated = self.store.get(c.id)
        self.assertEqual(updated.port, 8023)
        self.assertEqual(updated.user, "dev")
        self.assertEqual(updated.host, "192.168.8.54")  # não mudou

    def test_update_remove_opcional_com_none(self):
        c = self.store.add("Termux", "192.168.8.54", user="termux")
        self.store.update(c.id, user=None)
        self.assertIsNone(self.store.get(c.id).user)

    def test_update_campo_desconhecido(self):
        c = self.store.add("Termux", "192.168.8.54")
        with self.assertRaises(ConnectionsError):
            self.store.update(c.id, hacker=True)

    def test_delete(self):
        c = self.store.add("Termux", "192.168.8.54")
        self.store.delete(c.id)
        self.assertEqual(self.store.list(), [])

    def test_duplicate(self):
        c = self.store.add("Termux", "192.168.8.54", user="termux")
        copy = self.store.duplicate(c.id)
        self.assertNotEqual(copy.id, c.id)
        self.assertEqual(copy.host, c.host)
        self.assertEqual(copy.user, c.user)
        self.assertEqual(len(self.store.list()), 2)

    def test_search(self):
        self.store.add("Termux", "192.168.8.54", user="termux")
        self.store.add("Servidor", "10.0.0.5", user="root")
        self.assertEqual(len(self.store.list(search="termux")), 1)
        self.assertEqual(len(self.store.list(search="10.0.0")), 1)
        self.assertEqual(len(self.store.list()), 2)


class ValidationTests(BaseStore):
    def test_nome_obrigatorio(self):
        with self.assertRaises(ConnectionsError):
            self.store.add("", "192.168.8.54")
        with self.assertRaises(ConnectionsError):
            self.store.add("   ", "192.168.8.54")

    def test_host_invalido(self):
        with self.assertRaises(ConnectionsError):
            self.store.add("X", "999.999.999.999")

    def test_porta_invalida(self):
        for bad in (0, 70000, "abc"):
            with self.assertRaises(ConnectionsError):
                self.store.add("X", "192.168.8.54", port=bad)

    def test_nome_duplicado(self):
        self.store.add("Termux", "192.168.8.54")
        with self.assertRaises(ConnectionsError):
            self.store.add("termux", "192.168.8.55")  # mesma caixa baixa

    def test_hostname_dns_e_aceito(self):
        c = self.store.add("Casa", "meu-pc.local")
        self.assertEqual(c.host, "meu-pc.local")


class PersistenceTests(BaseStore):
    def test_sobrevive_a_reload(self):
        self.store.add("Termux", "192.168.8.54", user="termux")
        reloaded = ConnectionStore(self.path)
        self.assertEqual(len(reloaded.list()), 1)
        self.assertEqual(reloaded.list()[0].user, "termux")

    def test_arquivo_corrompido_levanta(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        with self.assertRaises(ConnectionsError):
            ConnectionStore(self.path)

    def test_arquivo_ausente_comeca_vazio(self):
        store = ConnectionStore(os.path.join(self.tmp.name, "novo.json"))
        self.assertEqual(store.list(), [])


if __name__ == "__main__":
    unittest.main()
