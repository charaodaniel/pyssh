"""Testes do módulo pyssh.network (sem Tkinter)."""

import ipaddress
import unittest

from pyssh.network import (
    Interface,
    NetworkError,
    host_count,
    is_valid_ipv4,
    iter_hosts,
    normalize_network,
    parse_network,
    validate_ipv4,
    validate_network,
)


class ValidationTests(unittest.TestCase):
    def test_valid_ipv4(self):
        self.assertTrue(is_valid_ipv4("192.168.8.52"))
        self.assertTrue(is_valid_ipv4("127.0.0.1"))
        self.assertFalse(is_valid_ipv4("999.1.1.1"))
        self.assertFalse(is_valid_ipv4("nada"))
        self.assertFalse(is_valid_ipv4(""))
        self.assertFalse(is_valid_ipv4(None))

    def test_validate_ipv4_normaliza(self):
        self.assertEqual(validate_ipv4(" 192.168.8.52 "), "192.168.8.52")
        with self.assertRaises(NetworkError):
            validate_ipv4("abc")
        with self.assertRaises(NetworkError):
            validate_ipv4("")

    def test_parse_network(self):
        net = parse_network("192.168.8.0/24")
        self.assertIsInstance(net, ipaddress.IPv4Network)
        self.assertEqual(str(net), "192.168.8.0/24")
        # Host com máscara implícita é aceito.
        self.assertEqual(str(parse_network("192.168.8.52/24")), "192.168.8.0/24")

    def test_parse_network_invalida(self):
        for bad in ["", "  ", "rede.local/24", "10.0.0.0/99"]:
            with self.assertRaises(NetworkError):
                parse_network(bad)

    def test_validate_network_limite_de_tamanho(self):
        self.assertEqual(validate_network("192.168.8.0/24"), "192.168.8.0/24")
        with self.assertRaises(NetworkError):
            validate_network("10.0.0.0/8")  # 16M endereços

    def test_normalize_network(self):
        self.assertEqual(normalize_network("192.168.8.7/24"), "192.168.8.0/24")


class IterHostsTests(unittest.TestCase):
    def test_slash24_pula_rede_e_broadcast(self):
        hosts = list(iter_hosts("192.168.8.0/24"))
        self.assertEqual(len(hosts), 254)
        self.assertEqual(hosts[0], "192.168.8.1")
        self.assertEqual(hosts[-1], "192.168.8.254")
        self.assertNotIn("192.168.8.0", hosts)
        self.assertNotIn("192.168.8.255", hosts)

    def test_slash32_devolve_um_host(self):
        self.assertEqual(list(iter_hosts("192.168.8.52/32")), ["192.168.8.52"])

    def test_host_count(self):
        self.assertEqual(host_count("192.168.8.0/24"), 254)
        self.assertEqual(host_count("10.0.0.1/32"), 1)


class InterfaceTests(unittest.TestCase):
    def test_interface_network(self):
        iface = Interface(name="wlan0", ipv4="192.168.8.52", prefixlen=24)
        self.assertEqual(iface.network, "192.168.8.0/24")
        self.assertIn("wlan0", iface.label)

    def test_get_interfaces_via_iproute2(self):
        try:
            from pyssh.network import get_interfaces
            interfaces = get_interfaces()
        except NetworkError as exc:
            self.skipTest(f"iproute2 indisponível: {exc}")
        for iface in interfaces:
            self.assertTrue(is_valid_ipv4(iface.ipv4), iface.ipv4)
            self.assertFalse(iface.is_loopback)


if __name__ == "__main__":
    unittest.main()
