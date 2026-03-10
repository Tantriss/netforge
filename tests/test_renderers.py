"""Integration tests for HPRenderer and AlliedRenderer."""
import pytest
from netforge.parsers.hp import HPParser
from netforge.parsers.allied import AlliedParser
from netforge.renderers.hp import HPRenderer
from netforge.renderers.allied import AlliedRenderer


# -- HP -> Allied -------------------------------------------------------------

def test_hp_to_allied_hostname(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "hostname SW-CORE-01" in out


def test_hp_to_allied_vlan(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "vlan database" in out
    assert "vlan 10 name" in out


def test_hp_to_allied_svi(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "interface vlan10" in out
    assert "ip address 10.0.10.1/24" in out


def test_hp_to_allied_trunk(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "switchport mode trunk" in out
    assert "switchport trunk allowed vlan" in out


def test_hp_to_allied_access_dot1x(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "switchport mode access" in out
    assert "dot1x port-control auto" in out
    assert "auth-mac enable" in out
    assert "spanning-tree edgeport" in out


def test_hp_to_allied_tacacs(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "tacacs-server host 10.0.0.10" in out
    assert "tacacs-server host 10.0.0.11" in out


def test_hp_to_allied_radius(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "radius-server host 10.0.0.20" in out


def test_hp_to_allied_aaa(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "aaa authentication login default" in out
    assert "group tacacs+" in out


def test_hp_to_allied_ssh(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "service ssh" in out


def test_hp_to_allied_ntp(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "ntp server 10.0.0.1" in out
    assert "prefer" in out


def test_hp_to_allied_local_user(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "username admin" in out
    assert "<REPLACE_PASSWORD_admin>" in out


def test_hp_to_allied_vty(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "line vty" in out
    assert "transport input ssh" in out


# -- Allied -> HP -------------------------------------------------------------

def test_allied_to_hp_hostname(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "sysname SW-CORE-01" in out


def test_allied_to_hp_vlan(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "vlan 10" in out
    assert "name Management" in out


def test_allied_to_hp_interface(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "GigabitEthernet" in out
    assert "port access vlan" in out


def test_allied_to_hp_trunk(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "port link-type trunk" in out
    assert "port trunk permit vlan" in out


def test_allied_to_hp_tacacs(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "hwtacacs scheme TACACS_SCHEME" in out
    assert "primary authentication 10.0.0.10" in out
    assert "secondary authentication 10.0.0.11" in out


def test_allied_to_hp_radius(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "radius scheme RADIUS_SCHEME" in out
    assert "primary authentication 10.0.0.20" in out


def test_allied_to_hp_domain(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "domain default" in out


def test_allied_to_hp_ssh(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "ssh server enable" in out


def test_allied_to_hp_ntp(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "ntp-service unicast-server 10.0.0.1" in out


def test_allied_to_hp_local_user(allied_config: str) -> None:
    model = AlliedParser().parse(allied_config)
    out = HPRenderer().render(model)
    assert "local-user admin" in out
    assert "<REPLACE_PASSWORD_admin>" in out


# -- Utilities ----------------------------------------------------------------

def test_hp_renderer_mask_to_prefix() -> None:
    r = HPRenderer()
    assert r._mask_to_prefix("255.255.255.0") == 24
    assert r._mask_to_prefix("255.255.0.0")   == 16
    assert r._mask_to_prefix("0.0.0.0")        == 0
    assert r._mask_to_prefix("255.255.255.255") == 32


def test_hp_renderer_prefix_to_mask() -> None:
    r = HPRenderer()
    assert r._prefix_to_mask(24) == "255.255.255.0"
    assert r._prefix_to_mask(16) == "255.255.0.0"
    assert r._prefix_to_mask(0)  == "0.0.0.0"
    assert r._prefix_to_mask(32) == "255.255.255.255"
