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


# -- v1.1.0 regression tests --------------------------------------------------

def test_hp_to_allied_switchport_first(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("interface port"):
            sub = [l.strip() for l in lines[i + 1:i + 5]
                   if l.strip() and not l.strip().startswith("description")]
            assert sub[0] == "switchport", f"Expected 'switchport' first under {line}, got {sub[0]}"
            break


def test_hp_to_allied_no_storm_control(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "storm-control" not in out


def test_hp_to_allied_no_port_security_comment(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "switchport port-security" not in out
    assert "! HP" not in out


def test_hp_to_allied_auth_dynamic_vlan(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "auth dynamic-vlan-creation" in out


def test_hp_to_allied_vty_con0(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "line con 0" in out
    assert "exec-timeout 5 0" in out


def test_hp_to_allied_vty_timeout_format(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "exec-timeout 10 0" in out


def test_hp_to_allied_no_domain_comment(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "! Domain:" not in out


def test_hp_to_allied_aaa_auth_mac(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "aaa authentication auth-mac default" in out


def test_hp_to_allied_no_service_http(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "no service http" in out


def test_hp_to_allied_no_service_telnet(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "no service telnet" in out


def test_hp_to_allied_ssh_timeout(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "ssh server session-timeout 600 login-timeout 600" in out


def test_hp_to_allied_snmp_no_ipv6(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "no snmp-server ipv6" in out


def test_hp_to_allied_snmp_trap_lldp(hp_config: str) -> None:
    model = HPParser().parse(hp_config)
    out = AlliedRenderer().render(model)
    assert "snmp-server enable trap lldp" in out


def test_hp_parser_sftp_enabled() -> None:
    config = "ssh server enable\nsftp server enable\n"
    from netforge.parsers.hp import HPParser
    model = HPParser().parse(config)
    assert model.ssh_enabled is True
    assert model.sftp_enabled is True


def test_hp_parser_snmp_v3_group() -> None:
    config = (
        "snmp-agent\n"
        "snmp-agent group v3 GP_TEST privacy read-view iso write-view iso notify-view iso\n"
    )
    from netforge.parsers.hp import HPParser
    model = HPParser().parse(config)
    assert model.snmp_groups, "Expected SNMPGroup to be parsed"
    g = model.snmp_groups[0]
    assert g.name == "GP_TEST"
    assert g.security_level == "priv"
    assert g.read_view == "iso"


def test_hp_parser_snmp_v3_user() -> None:
    config = (
        "snmp-agent\n"
        "snmp-agent usm-user v3 TESTUSER GP_TEST cipher authentication-mode sha AUTHKEY privacy-mode aes128 PRIVKEY\n"
    )
    from netforge.parsers.hp import HPParser
    model = HPParser().parse(config)
    assert model.snmp_users, "Expected SNMPUser to be parsed"
    u = model.snmp_users[0]
    assert u.name == "TESTUSER"
    assert u.group == "GP_TEST"
    assert u.auth_protocol == "sha"
    assert u.priv_protocol == "aes"


def test_hp_parser_static_route() -> None:
    config = "ip route-static 0.0.0.0 0.0.0.0 10.0.0.1\n"
    from netforge.parsers.hp import HPParser
    model = HPParser().parse(config)
    assert model.static_routes
    r = model.static_routes[0]
    assert r.dest == "0.0.0.0"
    assert r.gateway == "10.0.0.1"


def test_hp_to_allied_static_route() -> None:
    config = "ip route-static 0.0.0.0 0.0.0.0 10.0.0.1\n"
    from netforge.parsers.hp import HPParser
    from netforge.renderers.allied import AlliedRenderer
    model = HPParser().parse(config)
    out = AlliedRenderer().render(model)
    assert "ip route 0.0.0.0/0 10.0.0.1" in out
