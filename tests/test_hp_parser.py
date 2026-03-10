"""Unit tests for HPParser against hp_sample.txt."""
import pytest
from netforge.parsers.hp import HPParser
from netforge.models import UniversalConfig


@pytest.fixture
def model(hp_config: str) -> UniversalConfig:
    return HPParser().parse(hp_config)


def test_hostname(model: UniversalConfig) -> None:
    assert model.hostname == "SW-CORE-01"


def test_vlans(model: UniversalConfig) -> None:
    ids = {v.id: v for v in model.vlans}
    assert 10 in ids
    assert ids[10].name == "Management"
    assert {10, 20, 100, 999} == set(ids)


def test_svi(model: UniversalConfig) -> None:
    svis = [i for i in model.interfaces if i.type == "svi"]
    assert svis, "Expected at least one SVI"
    svi = next(i for i in svis if "10" in i.name)
    assert svi.ip == "10.0.10.1"
    assert svi.mask == "255.255.255.0"


def test_access_interface(model: UniversalConfig) -> None:
    access = [i for i in model.interfaces if i.type == "physical" and i.mode == "access"]
    assert access, "Expected at least one access-mode interface"
    assert any(i.access_vlan is not None for i in access)


def test_trunk_interface(model: UniversalConfig) -> None:
    trunks = [i for i in model.interfaces if i.type == "physical" and i.mode == "trunk"]
    assert trunks, "Expected at least one trunk-mode interface"
    assert any(i.trunk_allowed is not None for i in trunks)


def test_dot1x_on_access_port(model: UniversalConfig) -> None:
    dot1x_ports = [i for i in model.interfaces if i.type == "physical" and i.dot1x]
    assert dot1x_ports, "Expected at least one dot1x-enabled port"


def test_stp_edge_on_ports(model: UniversalConfig) -> None:
    edge_ports = [i for i in model.interfaces if i.stp_edge]
    assert edge_ports, "Expected at least one stp edged-port"


def test_tacacs(model: UniversalConfig) -> None:
    assert model.tacacs_schemes, "Expected at least one TACACS scheme"
    scheme = model.tacacs_schemes[0]
    assert scheme.primary_auth is not None
    assert scheme.secondary_auth is not None
    assert scheme.key_auth == "ENCRYPTED"


def test_radius(model: UniversalConfig) -> None:
    assert model.radius_schemes, "Expected at least one RADIUS scheme"
    scheme = model.radius_schemes[0]
    assert scheme.primary_auth is not None
    assert scheme.key_auth == "ENCRYPTED"
    assert scheme.timeout == 3
    assert scheme.retransmit == 2


def test_aaa_domain(model: UniversalConfig) -> None:
    assert model.domains, "Expected at least one AAA domain"
    domain = model.domains[0]
    assert domain.auth_login
    assert domain.auth_lan


def test_ssh(model: UniversalConfig) -> None:
    assert model.ssh_enabled is True


def test_ntp(model: UniversalConfig) -> None:
    assert len(model.ntp_servers) >= 1
    assert any(s.prefer for s in model.ntp_servers)


def test_dns(model: UniversalConfig) -> None:
    assert model.dns_domain == "corp.local"
    assert "10.0.0.1" in model.dns_servers


def test_syslog(model: UniversalConfig) -> None:
    assert "10.0.0.50" in model.syslog_hosts


def test_snmp(model: UniversalConfig) -> None:
    assert model.snmp_enabled is True
    assert model.snmp_contact == "NOC-Team"
    assert model.snmp_location == "DataCenter-Row3"


def test_lldp(model: UniversalConfig) -> None:
    assert model.lldp_enabled is True


def test_vty(model: UniversalConfig) -> None:
    assert model.vty_lines, "Expected at least one VTY block"
    vty = model.vty_lines[0]
    assert vty.start == 0
    assert vty.auth_mode == "scheme"
    assert vty.protocol == "ssh"
    assert vty.idle_timeout == 10


def test_local_user(model: UniversalConfig) -> None:
    assert model.local_users, "Expected at least one local user"
    user = next(u for u in model.local_users if u.name == "admin")
    assert user.password_hash == "ENCRYPTED"
