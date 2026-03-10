"""
netforge.renderers.hp
-----------------------
UniversalConfig → HP Comware config text renderer.

Pattern: build a ``lines`` list, return ``'\\n'.join(lines)``.
No parsing logic lives here — the renderer reads only from the IR fields.

Rendering order
---------------
1.  Header comment block
2.  ``sysname``
3.  ``hwtacacs scheme`` blocks
4.  ``radius scheme`` blocks
5.  ``domain`` blocks (AAA)
6.  VLAN blocks
7.  SVI interfaces (``Vlan-interface<N>``)
8.  Physical interfaces
9.  Static routes
10. Services: SSH, NTP, DNS, syslog, SNMP, LLDP
11. ``local-user`` blocks
12. ``line vty`` blocks
13. ``return``
"""
from __future__ import annotations

from datetime import datetime, timezone

from netforge.models import (
    AAADomain,
    InterfaceEntry,
    LocalUser,
    RadiusScheme,
    TacacsScheme,
    UniversalConfig,
    VtyLine,
)


class HPRenderer:
    """Renders a ``UniversalConfig`` IR to HP Comware config text.

    Usage::

        text = HPRenderer().render(model)
    """

    # ── Public entry point ────────────────────────────────────────────────────

    def render(self, model: UniversalConfig) -> str:
        """Return the HP Comware configuration string for *model*."""
        lines: list[str] = []

        self._render_header(lines, model)
        self._render_hostname(lines, model)
        self._render_tacacs(lines, model)
        self._render_radius(lines, model)
        self._render_domains(lines, model)
        self._render_vlans(lines, model)
        self._render_svis(lines, model)
        self._render_interfaces(lines, model)
        self._render_static_routes(lines, model)
        self._render_services(lines, model)
        self._render_local_users(lines, model)
        self._render_vty(lines, model)
        lines.append("return")

        return "\n".join(lines)

    # ── Section renderers ─────────────────────────────────────────────────────

    @staticmethod
    def _render_header(lines: list[str], model: UniversalConfig) -> None:
        """Emit the top-of-file comment block."""
        from netforge.detector import VendorDetector
        source = VendorDetector().get_vendor_name(model.source_vendor or "unknown")
        now = datetime.now(timezone.utc).isoformat()
        lines += [
            "#",
            "# HP Comware Configuration",
            f"# Generated from: {source}",
            f"# Date: {now}",
            "#",
            "",
        ]

    @staticmethod
    def _render_hostname(lines: list[str], model: UniversalConfig) -> None:
        if model.hostname:
            lines += [f"sysname {model.hostname}", "#", ""]

    @staticmethod
    def _render_tacacs(lines: list[str], model: UniversalConfig) -> None:
        """Emit one ``hwtacacs scheme`` block per scheme."""
        for scheme in model.tacacs_schemes:
            lines.append(f"hwtacacs scheme {scheme.name}")
            if scheme.primary_auth:
                lines.append(f" primary authentication {scheme.primary_auth}")
            if scheme.primary_author:
                lines.append(f" primary authorization {scheme.primary_author}")
            if scheme.primary_acct:
                lines.append(f" primary accounting {scheme.primary_acct}")
            if scheme.secondary_auth:
                lines.append(f" secondary authentication {scheme.secondary_auth}")
            if scheme.secondary_author:
                lines.append(f" secondary authorization {scheme.secondary_author}")
            if scheme.secondary_acct:
                lines.append(f" secondary accounting {scheme.secondary_acct}")
            if scheme.key_auth:
                lines.append(" key authentication cipher <REPLACE_KEY>")
            if scheme.nas_ip:
                lines.append(f" nas-ip {scheme.nas_ip}")
            lines += ["#", ""]

    @staticmethod
    def _render_radius(lines: list[str], model: UniversalConfig) -> None:
        """Emit one ``radius scheme`` block per scheme."""
        for scheme in model.radius_schemes:
            lines.append(f"radius scheme {scheme.name}")
            if scheme.primary_auth:
                lines.append(f" primary authentication {scheme.primary_auth}")
            for sec in scheme.secondary_auth:
                lines.append(f" secondary authentication {sec}")
            if scheme.key_auth:
                lines.append(" key authentication cipher <REPLACE_KEY>")
            if scheme.timeout is not None:
                lines.append(f" timer response-timeout {scheme.timeout}")
            if scheme.retransmit is not None:
                lines.append(f" retry {scheme.retransmit}")
            if scheme.nas_ip:
                lines.append(f" nas-ip {scheme.nas_ip}")
            lines += ["#", ""]

    @staticmethod
    def _render_domains(lines: list[str], model: UniversalConfig) -> None:
        """Emit one ``domain`` block per AAA domain."""
        for domain in model.domains:
            lines.append(f"domain {domain.name}")
            for m in domain.auth_login:
                lines.append(f" authentication login {m}")
            for m in domain.author_login:
                lines.append(f" authorization login {m}")
            for m in domain.acct_login:
                lines.append(f" accounting login {m}")
            for m in domain.auth_lan:
                lines.append(f" authentication lan-access {m}")
            for m in domain.auth_enable:
                lines.append(f" authentication enable {m}")
            for m in domain.author_enable:
                lines.append(f" authorization enable {m}")
            lines += ["#", ""]

    @staticmethod
    def _render_vlans(lines: list[str], model: UniversalConfig) -> None:
        """Emit one ``vlan N`` block per VLAN entry."""
        for vlan in model.vlans:
            lines.append(f"vlan {vlan.id}")
            if vlan.name:
                lines.append(f" name {vlan.name}")
            lines += ["#", ""]

    @staticmethod
    def _render_svis(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``interface Vlan-interface<N>`` blocks for SVI entries."""
        svis = [iface for iface in model.interfaces if iface.type == "svi"]
        for svi in svis:
            if svi.ip and svi.mask:
                lines += [
                    f"interface {svi.name}",
                    f" ip address {svi.ip} {svi.mask}",
                    "#",
                    "",
                ]

    @staticmethod
    def _render_interfaces(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``interface GigabitEthernet…`` blocks for physical ports."""
        physical = [iface for iface in model.interfaces if iface.type == "physical"]
        for iface in physical:
            lines.append(f"interface {iface.name}")
            if iface.description:
                lines.append(f" description {iface.description}")
            if iface.mode == "access":
                lines.append(" port link-type access")
                if iface.access_vlan:
                    lines.append(f" port access vlan {iface.access_vlan}")
            elif iface.mode == "trunk":
                lines.append(" port link-type trunk")
                if iface.trunk_native:
                    lines.append(f" port trunk pvid vlan {iface.trunk_native}")
                if iface.trunk_allowed:
                    lines.append(f" port trunk permit vlan {iface.trunk_allowed}")
            if iface.dot1x:
                lines.append(" dot1x")
            if iface.dot1x_max is not None:
                lines.append(f" dot1x max-user {iface.dot1x_max}")
            if iface.mac_auth:
                lines.append(" mac-authentication")
            if iface.mac_auth_max is not None:
                lines.append(f" mac-authentication max-user {iface.mac_auth_max}")
            if iface.guest_vlan is not None:
                lines.append(f" dot1x guest-vlan {iface.guest_vlan}")
                lines.append(f" mac-authentication guest-vlan {iface.guest_vlan}")
            if iface.stp_edge:
                lines.append(" stp edged-port")
            if iface.broadcast_suppression is not None:
                lines.append(f" broadcast-suppression kbps {iface.broadcast_suppression}")
            if iface.port_security:
                lines.append(f" {iface.port_security}")
            lines += ["#", ""]

    @staticmethod
    def _render_static_routes(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``ip route-static`` lines."""
        if not model.static_routes:
            return
        for route in model.static_routes:
            lines.append(f"ip route-static {route.dest} {route.mask} {route.gateway}")
        lines += ["#", ""]

    @staticmethod
    def _render_services(lines: list[str], model: UniversalConfig) -> None:
        """Emit SSH, NTP, DNS, syslog, SNMP, and LLDP statements."""
        if model.ssh_enabled:
            lines += ["ssh server enable", "#", ""]

        if model.ntp_servers:
            for srv in model.ntp_servers:
                suffix = " priority" if srv.prefer else ""
                lines.append(f"ntp-service unicast-server {srv.ip}{suffix}")
            lines += ["#", ""]

        if model.dns_domain or model.dns_servers:
            if model.dns_domain:
                lines.append(f"dns domain {model.dns_domain}")
            for srv in model.dns_servers:
                lines.append(f"dns server {srv}")
            lines += ["#", ""]

        if model.syslog_hosts:
            for host in model.syslog_hosts:
                lines.append(f"info-center loghost {host}")
            lines += ["#", ""]

        if model.snmp_enabled:
            lines.append("snmp-agent")
            if model.snmp_contact:
                lines.append(f"snmp-agent sys-info contact {model.snmp_contact}")
            if model.snmp_location:
                lines.append(f"snmp-agent sys-info location {model.snmp_location}")
            if model.snmp_version:
                lines.append(f"snmp-agent sys-info version {model.snmp_version}")
            lines += ["#", ""]

        if model.lldp_enabled:
            lines += ["lldp global enable", "#", ""]

    @staticmethod
    def _render_local_users(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``local-user`` blocks."""
        for user in model.local_users:
            lines.append(f"local-user {user.name} class manage")
            lines.append(f" password hash <REPLACE_PASSWORD_{user.name}>")
            if user.service_type:
                lines.append(f" service-type {user.service_type}")
            if user.role:
                lines.append(f" authorization-attribute user-role {user.role}")
            lines += ["#", ""]

    @staticmethod
    def _render_vty(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``line vty`` blocks."""
        for vty in model.vty_lines:
            lines.append(f"line vty {vty.start} {vty.end}")
            if vty.auth_mode:
                lines.append(f" authentication-mode {vty.auth_mode}")
            if vty.idle_timeout is not None:
                lines.append(f" idle-timeout {vty.idle_timeout}")
            if vty.protocol == "ssh":
                lines.append(" protocol inbound ssh")
            lines += ["#", ""]

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _mask_to_prefix(mask: str) -> int:
        """Convert a dotted-decimal subnet mask to a CIDR prefix length.

        Examples::

            HPRenderer._mask_to_prefix('255.255.255.0')  # 24
            HPRenderer._mask_to_prefix('255.255.0.0')    # 16
            HPRenderer._mask_to_prefix('0.0.0.0')        # 0
        """
        return sum(
            bin(int(octet)).count("1")
            for octet in mask.split(".")
        )

    @staticmethod
    def _prefix_to_mask(prefix: int) -> str:
        """Convert a CIDR prefix length to a dotted-decimal subnet mask.

        Examples::

            HPRenderer._prefix_to_mask(24)  # '255.255.255.0'
            HPRenderer._prefix_to_mask(0)   # '0.0.0.0'
        """
        if prefix == 0:
            return "0.0.0.0"
        mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        return ".".join(str((mask >> shift) & 0xFF) for shift in (24, 16, 8, 0))
