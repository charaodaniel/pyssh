"""Testes do módulo pyssh.keys (referências a chaves + ssh-keygen real)."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from pyssh.keys import (
    KeyError_,
    KeyStore,
    default_key_path,
    fingerprint,
    generate_key,
    key_info,
    key_type,
    public_key_path,
)

HAS_KEYGEN = shutil.which("ssh-keygen") is not None


class BaseStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "keys.json")
        self.store = KeyStore(self.path)

    def _make_keypair(self, name="id_test"):
        """Gera um par real (se houver ssh-keygen) e devolve o caminho privado."""
        dest = os.path.join(self.tmp.name, name)
        generate_key("ed25519", dest, comment="teste")
        return dest


class CrudTests(BaseStore):
    def test_add_e_list(self):
        key = self.store.add("casa", "/home/u/.ssh/id_ed25519")
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(key.name, "casa")
        # O caminho é expandido.
        self.assertNotIn("~", key.path)

    def test_get_por_nome_e_id(self):
        key = self.store.add("casa", "/tmp/id")
        self.assertEqual(self.store.get("casa").id, key.id)
        self.assertEqual(self.store.get(key.id).id, key.id)
        self.assertEqual(self.store.get("CASA").id, key.id)
        self.assertIsNone(self.store.get("nao-existe"))

    def test_require_inexistente(self):
        with self.assertRaises(KeyError_):
            self.store.require("fantasma")

    def test_update(self):
        key = self.store.add("casa", "/tmp/id")
        self.store.update(key.id, name="trabalho", notes="anotação")
        updated = self.store.get(key.id)
        self.assertEqual(updated.name, "trabalho")
        self.assertEqual(updated.notes, "anotação")
        self.assertEqual(updated.path, "/tmp/id")

    def test_update_remove_notes_com_none(self):
        key = self.store.add("casa", "/tmp/id", notes="x")
        self.store.update(key.id, notes=None)
        self.assertIsNone(self.store.get(key.id).notes)

    def test_update_campo_desconhecido(self):
        key = self.store.add("casa", "/tmp/id")
        with self.assertRaises(KeyError_):
            self.store.update(key.id, algo=True)

    def test_delete_preserva_arquivo(self):
        dest = os.path.join(self.tmp.name, "id_real")
        with open(dest, "w") as fh:
            fh.write("chave")
        key = self.store.add("real", dest)
        self.store.delete(key.id)  # sem delete_file
        self.assertTrue(os.path.isfile(dest))  # arquivo NÃO apagado

    def test_delete_com_arquivo(self):
        dest = os.path.join(self.tmp.name, "id_apagar")
        with open(dest, "w") as fh:
            fh.write("chave")
        key = self.store.add("apagar", dest)
        self.store.delete(key.id, delete_file=True)
        self.assertFalse(os.path.exists(dest))

    def test_add_nome_duplicado(self):
        self.store.add("casa", "/tmp/a")
        with self.assertRaises(KeyError_):
            self.store.add("CASA", "/tmp/b")

    def test_add_validacao(self):
        with self.assertRaises(KeyError_):
            self.store.add("", "/tmp/a")
        with self.assertRaises(KeyError_):
            self.store.add("nome", "")

    def test_sobrevive_a_reload(self):
        self.store.add("casa", "/tmp/id")
        self.assertEqual(len(KeyStore(self.path).list()), 1)


class CheckFileTests(BaseStore):
    def test_check_arquivo_ausente(self):
        key = self.store.add("fantasma", "/tmp/chave-que-nao-existe")
        info = key.check_file()
        self.assertFalse(info["exists"])
        self.assertIsNone(info["permission_warning"])

    def test_check_permissao_ampla(self):
        dest = os.path.join(self.tmp.name, "id_amplo")
        with open(dest, "w") as fh:
            fh.write("x")
        os.chmod(dest, 0o644)
        key = self.store.add("amplo", dest)
        info = key.check_file()
        self.assertTrue(info["exists"])
        self.assertIn("chmod 600", info["permission_warning"])


@unittest.skipUnless(HAS_KEYGEN, "ssh-keygen indisponível")
class GenerateTests(BaseStore):
    def test_gera_ed25519_com_fingerprint(self):
        dest = os.path.join(self.tmp.name, "id_novo")
        result = generate_key("ed25519", dest, comment="pyssh")
        self.assertEqual(result["path"], dest)
        self.assertTrue(os.path.isfile(dest))
        self.assertTrue(os.path.isfile(public_key_path(dest)))
        self.assertTrue(result["fingerprint"].startswith("SHA256:"))
        self.assertEqual(result["type"], "ed25519")
        # tipo identificado a partir do .pub
        self.assertEqual(key_type(dest), "ed25519")
        self.assertEqual(fingerprint(dest), result["fingerprint"])

    def test_recusa_destino_existente(self):
        dest = os.path.join(self.tmp.name, "id_ocupado")
        with open(dest, "w") as fh:
            fh.write("x")
        with self.assertRaises(KeyError_):
            generate_key("ed25519", dest)

    def test_recusa_tipo_invalido(self):
        with self.assertRaises(KeyError_):
            generate_key("desconhecido", os.path.join(self.tmp.name, "z"))

    def test_exige_destino(self):
        # Sem destino, o caminho padrão do OpenSSH é usado (~/.ssh/id_<tipo>).
        # O HOME é redirecionado para não tocar na máquina real.
        with mock.patch.dict(os.environ, {"HOME": self.tmp.name}):
            result = generate_key("ed25519", "")
            expected = os.path.join(self.tmp.name, ".ssh", "id_ed25519")
            self.assertEqual(result["path"], expected)
            self.assertTrue(os.path.isfile(expected))
            # Diretório ~/.ssh criado com permissões restritivas.
            self.assertEqual(os.stat(os.path.dirname(expected)).st_mode & 0o777, 0o700)

    def test_recusa_diretorio_inexistente(self):
        with self.assertRaises(KeyError_):
            generate_key("ed25519", "/tmp/dir-que-nao-existe-xyz/id")


class DefaultPathTests(BaseStore):
    def test_padrao_por_tipo(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/u"}):
            self.assertEqual(default_key_path("ed25519"), "/home/u/.ssh/id_ed25519")
            self.assertEqual(default_key_path("rsa"), "/home/u/.ssh/id_rsa")
            self.assertEqual(default_key_path("ecdsa"), "/home/u/.ssh/id_ecdsa")

    def test_geracao_no_padrao_e_key_info(self):
        with mock.patch.dict(os.environ, {"HOME": self.tmp.name}):
            result = generate_key("ed25519", "", comment="padrao")
            info = key_info(result["path"])
            self.assertTrue(info["exists"])
            self.assertEqual(info["type"], "ed25519")
            self.assertEqual(info["fingerprint"], result["fingerprint"])
            self.assertEqual(info["public_key"], result["public_key"])
            self.assertEqual(info["public_key_path"], public_key_path(result["path"]))
            # A privada nunca aparece em info (só a pública).
            self.assertNotIn("private", info)

    def test_key_info_arquivo_ausente(self):
        info = key_info(os.path.join(self.tmp.name, "nao-existe"))
        self.assertFalse(info["exists"])
        self.assertIsNone(info["fingerprint"])
        self.assertIsNone(info["public_key"])


class StoreWithRealKey(BaseStore):
    @unittest.skipUnless(HAS_KEYGEN, "ssh-keygen indisponível")
    def test_ciclo_completo(self):
        dest = self._make_keypair("id_ciclo")
        key = self.store.add("ciclo", dest)
        info = key.check_file()
        self.assertTrue(info["exists"])
        self.assertEqual(key_type(key.path), "ed25519")
        self.assertIsNotNone(fingerprint(key.path))
        # Remover a referência preserva o arquivo.
        self.store.delete(key.id)
        self.assertTrue(os.path.isfile(dest))


if __name__ == "__main__":
    unittest.main()
