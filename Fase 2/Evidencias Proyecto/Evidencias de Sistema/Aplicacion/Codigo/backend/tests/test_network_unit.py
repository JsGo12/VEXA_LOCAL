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


def test_filter_accepts_tailscale_only_when_enabled():
    assert not network.RemoteAddressFilter(None, allow_tailscale=False).allowed("100.100.1.1")
    filtro = network.RemoteAddressFilter(None, allow_tailscale=True)
    assert filtro.allowed("100.100.1.1")
    assert filtro.allowed("fd7a:115c:a1e0::5")
    assert not filtro.allowed("100.128.0.1")


def test_filter_answers_403_before_reaching_the_app():
    llamado = []
    filtro = network.RemoteAddressFilter(lambda env, start: llamado.append(True) or [b"ok"], False)
    estados = []
    cuerpo = filtro({"REMOTE_ADDR": "8.8.8.8"}, lambda status, headers: estados.append(status))
    assert estados == ["403 Forbidden"] and not llamado
    assert b"Acceso denegado" in cuerpo[0]


def test_tailscale_interface_requires_its_name():
    from types import SimpleNamespace
    addr = [SimpleNamespace(address="100.70.0.1")]
    assert network.tailscale_interface_ipv4({"eth0": addr}) is None
    assert network.tailscale_interface_ipv4({"Tailscale": addr}) == "100.70.0.1"
    assert network.tailscale_interface_ipv4({"tailscale0": [SimpleNamespace(address="fd7a:115c:a1e0::1")]}) is None


def test_trusted_hosts_include_magicdns_name():
    settings = network.Settings(tailscale_host="vexa.tail1234.ts.net")
    hosts = network.trusted_hosts(settings, [("127.0.0.1", 5000)])
    assert {"vexa.tail1234.ts.net", "vexa", "localhost", "127.0.0.1"} <= set(hosts)
