"""Pruebas unitarias de la red privada: listeners, hosts de confianza y filtro de origen."""
from vexa.security import network


def test_listen_format_brackets_ipv6():
    assert network.format_listen([("127.0.0.1", 5000), ("::1", 5001)]) == "127.0.0.1:5000 [::1]:5001"
    assert network.format_listen([]) == ""


def test_filter_accepts_loopback_in_every_form():
    filtro = network.RemoteAddressFilter(None, allow_tailscale=False)
    for remote in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        assert filtro.allowed(remote), remote
    for remote in (None, "", "no-es-ip", "192.168.1.5", "fe80::1%3"):
        assert not filtro.allowed(remote), remote
