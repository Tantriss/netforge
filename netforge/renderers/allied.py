"""
netforge.renderers.allied
---------------------------
UniversalConfig → AlliedWare Plus config text renderer.

Pattern: build a ``lines`` list, return ``'\\n'.join(lines)``.
No parsing logic lives here — the renderer reads only from the IR fields.

Name conversions
----------------
HP Comware interface names stored in the IR are converted back to Allied
format on the fly:

* ``GigabitEthernet1/0/3`` → ``port1.0.3``
* ``Vlan-interface10``      → ``vlan10``

AAA method strings stored in HP canonical form are mapped to Allied
``group tacacs+`` / ``group radius`` tokens:

* ``hwtacacs-scheme <NAME>`` → ``group tacacs+``   (scheme name discarded)
* ``radius-scheme <NAME>``   → ``group radius``    (scheme name discarded)
* ``local``, ``none``, …     → kept verbatim

Rendering order
---------------
1.  ``hostname``
2.  ``vlan database`` block
3.  ``tacacs-server host`` inline lines
4.  ``radius-server host`` inline lines
5.  ``aaa`` inline lines
6.  SVI interfaces (``interface vlan<N>``)
7.  Physical interfaces (``interface port<X>.<Y>.<Z>``)
8.  Static routes (``ip route``)
9.  Services: SSH, NTP, LLDP, DNS, syslog, SNMP
10. ``username`` local users
11. ``line vty`` blocks
12. ``end``
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from netforge.models import UniversalConfig


class AlliedRenderer:
    """Renders a ``UniversalConfig`` IR to AlliedWare Plus config text.

    Usage::

        text = AlliedRenderer().render(model)
    """

    # ── Public entry point ────────────────────────────────────────────────────

    def render(self, model: UniversalConfig) -> str:
        """Return the AlliedWare Plus configuration string for *model*."""
        lines: list[str] = []

        self._render_header(lines, model)
        self._render_hostname(lines, model)
        self._render_vlans(lines, model)
        self._render_tacacs(lines, model)
        self._render_radius(lines, model)
        self._render_aaa(lines, model)
        self._render_svis(lines, model)
        self._render_interfaces(lines, model)
        self._render_static_routes(lines, model)
        self._render_services(lines, model)
        self._render_local_users(lines, model)
        self._render_vty(lines, model)
        lines.append("end")

        return "\n".join(lines)

    # ── Section renderers ─────────────────────────────────────────────────────

    @staticmethod
    def _render_header(lines: list[str], model: UniversalConfig) -> None:
        """Emit the top-of-file comment block."""
        from netforge.detector import VendorDetector
        source = VendorDetector().get_vendor_name(model.source_vendor or "unknown")
        now = datetime.now(timezone.utc).isoformat()
        lines += [
            "!",
            "! AlliedWare Plus Configuration",
            f"! Generated from: {source}",
            f"! Date: {now}",
            "!",
            "",
        ]

    @staticmethod
    def _render_hostname(lines: list[str], model: UniversalConfig) -> None:
        if model.hostname:
            lines += [f"hostname {model.hostname}", ""]

    @staticmethod
    def _render_vlans(lines: list[str], model: UniversalConfig) -> None:
        """Emit a ``vlan database`` block containing all VLAN definitions.

        VLAN names are lowercased and sanitised (spaces / hyphens / special
        characters replaced by underscores, truncated to 32 characters) to
        comply with AlliedWare Plus naming rules.
        """
        if not model.vlans:
            return
        lines += ["!", "! VLANs", "!", "vlan database"]
        for vlan in model.vlans:
            raw_name = vlan.name or f"vlan{vlan.id}"
            name = re.sub(r"[\s\-&:*\"]+", "_", raw_name).lower()[:32]
            lines.append(f" vlan {vlan.id} name {name}")
        lines += ["exit", ""]

    @staticmethod
    def _render_tacacs(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``tacacs-server host`` inline lines.

        The primary server is always emitted.  The secondary server (if any)
        becomes a second ``tacacs-server host`` line — Allied does not use
        named scheme blocks.  Each key is an IP-specific placeholder so the
        Key Manager can replace it independently.
        """
        if not model.tacacs_schemes:
            return
        lines += ["!", "! TACACS+", "!"]
        for scheme in model.tacacs_schemes:
            if scheme.primary_auth:
                key_ph = _key_placeholder(scheme.primary_auth)
                lines.append(f"tacacs-server host {scheme.primary_auth} key 8 {key_ph}")
            if scheme.secondary_auth:
                key_ph = _key_placeholder(scheme.secondary_auth)
                lines.append(f"tacacs-server host {scheme.secondary_auth} key 8 {key_ph}")
        lines.append("")

    @staticmethod
    def _render_radius(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``radius-server host`` inline lines.

        Timeout and retransmit values fall back to ``1`` when absent so the
        line is always syntactically complete.
        """
        if not model.radius_schemes:
            return
        lines += ["!", "! RADIUS", "!"]
        for scheme in model.radius_schemes:
            if scheme.primary_auth:
                t = scheme.timeout if scheme.timeout is not None else 1
                r = scheme.retransmit if scheme.retransmit is not None else 1
                key_ph = _key_placeholder(scheme.primary_auth)
                lines.append(
                    f"radius-server host {scheme.primary_auth}"
                    f" timeout {t} retransmit {r} key {key_ph}"
                )
            for sec in scheme.secondary_auth:
                t = scheme.timeout if scheme.timeout is not None else 1
                r = scheme.retransmit if scheme.retransmit is not None else 1
                key_ph = _key_placeholder(sec)
                lines.append(
                    f"radius-server host {sec}"
                    f" timeout {t} retransmit {r} key {key_ph}"
                )
        lines.append("")

    @staticmethod
    def _render_aaa(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``aaa`` inline configuration lines for each domain.

        HP canonical method strings (``hwtacacs-scheme NAME local``) are
        converted to Allied ``group tacacs+``/``group radius`` form.
        Order: enable → login → authorization (1,7,15) → accounting → dot1x → auth-mac.
        The built-in "system" domain is silently skipped.
        """
        if not model.domains:
            return
        has_tacacs = bool(model.tacacs_schemes)
        lines += ["!", "! AAA", "!"]
        enable_emitted = False
        for domain in model.domains:
            if domain.name == "system":
                continue
            if domain.auth_login:
                methods = _methods_to_allied(domain.auth_login)
                lines.append(f"aaa authentication login default {methods}")
            if has_tacacs and not enable_emitted:
                lines.append("aaa authentication enable default group tacacs+ none")
                enable_emitted = True
            if domain.author_login:
                methods = " ".join(
                    t for t in _methods_to_allied(domain.author_login).split()
                    if t != "local"
                )
                for level in (1, 7, 15):
                    lines.append(f"aaa authorization commands {level} default {methods} none")
            if domain.acct_login:
                methods = " ".join(
                    t for t in _methods_to_allied(domain.acct_login).split()
                    if t != "local"
                )
                lines.append(f"aaa accounting login default start-stop {methods}")
            if domain.auth_lan:
                methods = _methods_to_allied(domain.auth_lan)
                lines.append(f"aaa authentication dot1x default {methods}")
                lines.append(f"aaa authentication auth-mac default {methods}")
        lines.append("")

    @staticmethod
    def _render_svis(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``interface vlan<N>`` blocks for SVI entries."""
        svis = [iface for iface in model.interfaces if iface.type == "svi"]
        if not svis:
            return
        lines += ["!", "! VLAN Interfaces (SVIs)", "!"]
        for svi in svis:
            allied_name = _hp_name_to_allied(svi.name)
            lines.append(f"interface {allied_name}")
            if svi.ip and svi.mask:
                prefix = _mask_to_prefix(svi.mask)
                lines.append(f" ip address {svi.ip}/{prefix}")
            lines += ["exit", ""]

    @staticmethod
    def _render_interfaces(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``interface port<X>.<Y>.<Z>`` blocks for physical ports.

        Order per port: switchport → mode/vlan → auth-mac → dot1x →
        auth dynamic-vlan-creation (when both auth active) → stp edge.
        storm-control and port-security are intentionally omitted.
        """
        physical = [iface for iface in model.interfaces if iface.type == "physical"]
        if not physical:
            return
        lines += ["!", "! Interfaces", "!"]
        for iface in physical:
            allied_name = _hp_name_to_allied(iface.name)
            lines.append(f"interface {allied_name}")
            if iface.description:
                lines.append(f" description {iface.description}")
            lines.append(" switchport")
            if iface.mode == "access":
                lines.append(" switchport mode access")
                if iface.access_vlan:
                    lines.append(f" switchport access vlan {iface.access_vlan}")
            elif iface.mode == "trunk":
                lines.append(" switchport mode trunk")
                if iface.trunk_native:
                    lines.append(f" switchport trunk native vlan {iface.trunk_native}")
                if iface.trunk_allowed:
                    allowed = iface.trunk_allowed.replace(" ", ",")
                    lines.append(f" switchport trunk allowed vlan {allowed}")
            if iface.mac_auth:
                lines.append(" auth-mac enable")
            if iface.dot1x:
                lines.append(" dot1x port-control auto")
            if iface.dot1x and iface.mac_auth:
                lines.append(" auth dynamic-vlan-creation")
            if iface.guest_vlan is not None:
                lines.append(f" auth-mac guest-vlan {iface.guest_vlan}")
            if iface.stp_edge:
                lines.append(" spanning-tree edgeport")
            lines += ["exit", ""]

    @staticmethod
    def _render_static_routes(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``ip route DST/PREFIX GW`` lines."""
        if not model.static_routes:
            return
        lines += ["!", "! Static Routes", "!"]
        for route in model.static_routes:
            prefix = _mask_to_prefix(route.mask)
            lines.append(f"ip route {route.dest}/{prefix} {route.gateway}")
        lines.append("")

    @staticmethod
    def _render_services(lines: list[str], model: UniversalConfig) -> None:
        """Emit SSH, NTP, LLDP, DNS, syslog, SNMP, and security service statements.

        ``no service http`` and ``no service telnet`` are always emitted as
        security best-practice regardless of the source config.
        """
        if model.ssh_enabled:
            lines += [
                "!",
                "! SSH",
                "!",
                "ssh server session-timeout 600 login-timeout 600",
                "ssh server allow-users *",
                "service ssh",
                "",
            ]

        if model.ntp_servers:
            lines += ["!", "! NTP", "!"]
            for srv in model.ntp_servers:
                suffix = " prefer" if srv.prefer else ""
                lines.append(f"ntp server {srv.ip}{suffix}")
            lines.append("")

        if model.lldp_enabled:
            lines += ["!", "! LLDP", "!", "lldp run", ""]

        if model.dns_domain or model.dns_servers:
            lines += ["!", "! DNS", "!"]
            if model.dns_domain:
                lines.append(f"ip domain-name {model.dns_domain}")
            for srv in model.dns_servers:
                lines.append(f"ip name-server {srv}")
            if model.dns_servers:
                lines.append("ip domain-lookup")
            lines.append("")

        if model.syslog_hosts:
            lines += ["!", "! Syslog", "!"]
            for host in model.syslog_hosts:
                lines.append(f"log host {host}")
                lines.append(f"log host {host} level notices")
            lines.append("")

        if model.snmp_enabled:
            lines += ["!", "! SNMP", "!"]
            lines.append("no snmp-server ipv6")
            if model.snmp_contact:
                lines.append(f"snmp-server contact {model.snmp_contact}")
            if model.snmp_location:
                lines.append(f"snmp-server location {model.snmp_location}")
            lines.append("snmp-server enable trap lldp")
            for group in model.snmp_groups:
                parts = [f"snmp-server group {group.name} {group.security_level}"]
                if group.read_view:
                    parts.append(f"read {group.read_view}")
                if group.write_view:
                    parts.append(f"write {group.write_view}")
                if group.notify_view:
                    parts.append(f"notify {group.notify_view}")
                lines.append(" ".join(parts))
            for view in model.snmp_views:
                incl = "included" if view.included else "excluded"
                lines.append(f"snmp-server view {view.name} {view.oid} {incl}")
            for user in model.snmp_users:
                u_line = f"snmp-server user {user.name} {user.group}"
                if user.encrypted:
                    u_line += " encrypted"
                if user.auth_protocol and user.auth_key:
                    u_line += f" auth {user.auth_protocol} {user.auth_key}"
                if user.priv_protocol and user.priv_key:
                    u_line += f" priv {user.priv_protocol} {user.priv_key}"
                lines.append(u_line)
            lines.append("")

        # Security best-practice — always emitted
        lines += ["!", "! Security", "!", "no service http", "no service telnet", ""]

    @staticmethod
    def _render_local_users(lines: list[str], model: UniversalConfig) -> None:
        """Emit ``username`` inline lines.

        Allied uses a single-line format; the password is always a placeholder
        because HP hashes are incompatible with AlliedWare Plus.
        """
        if not model.local_users:
            return
        lines += ["!", "! Local Users", "!"]
        for user in model.local_users:
            lines.append(
                f"username {user.name} privilege 15"
                f" password 8 <REPLACE_PASSWORD_{user.name}>"
            )
        lines.append("")

    @staticmethod
    def _render_vty(lines: list[str], model: UniversalConfig) -> None:
        """Emit console and VTY line blocks.

        ``line con 0`` is always emitted before VTY lines.
        exec-timeout uses the ``X 0`` format (minutes seconds).
        VTY end index is capped at 15 (Allied limit).
        """
        if not model.vty_lines:
            return
        lines += ["!", "! VTY Lines", "!"]
        # Console line — always present
        lines += ["line con 0", " exec-timeout 5 0", "exit", ""]
        for vty in model.vty_lines:
            end = min(vty.end, 15)
            lines.append(f"line vty {vty.start} {end}")
            if vty.idle_timeout is not None:
                lines.append(f" exec-timeout {vty.idle_timeout} 0")
            if vty.protocol == "ssh":
                lines.append(" transport input ssh")
            lines += ["exit", ""]


# ── Module-level helpers (pure functions, no instance state) ──────────────────


def _key_placeholder(ip: str) -> str:
    """Return the Key Manager placeholder for *ip*.

    Example: ``'10.0.0.10'`` → ``'<REPLACE_KEY_10_0_0_10>'``.
    """
    return f"<REPLACE_KEY_{ip.replace('.', '_')}>"


def _hp_name_to_allied(name: str) -> str:
    """Convert an HP Comware interface name to AlliedWare Plus format.

    Examples::

        _hp_name_to_allied('GigabitEthernet1/0/3')  # 'port1.0.3'
        _hp_name_to_allied('Vlan-interface10')        # 'vlan10'
        _hp_name_to_allied('unknown')                 # 'unknown'
    """
    if m := re.match(r"^GigabitEthernet(\d+)/(\d+)/(\d+)$", name):
        return f"port{m.group(1)}.{m.group(2)}.{m.group(3)}"
    if m := re.match(r"^Vlan-interface(\d+)$", name):
        return f"vlan{m.group(1)}"
    return name


def _mask_to_prefix(mask: str) -> int:
    """Convert a dotted-decimal mask to a CIDR prefix length.

    Example: ``'255.255.255.0'`` → ``24``.
    """
    return sum(bin(int(octet)).count("1") for octet in mask.split("."))


def _methods_to_allied(method_list: list[str]) -> str:
    """Convert a list of HP canonical AAA method strings to Allied tokens.

    Each entry in *method_list* may itself be a multi-token string such as
    ``'hwtacacs-scheme CORP-TACACS local'``.  The function:

    * replaces ``hwtacacs-scheme <name>`` with ``group tacacs+``
    * replaces ``radius-scheme <name>`` with ``group radius``
    * passes ``local``, ``none``, and other tokens through unchanged
    * skips accounting sub-keywords (``start-stop``, ``stop-only``)

    Example::

        _methods_to_allied(['hwtacacs-scheme CORP local'])
        # 'group tacacs+ local'
    """
    _ACCT_KEYWORDS = frozenset({"start-stop", "stop-only"})
    out: list[str] = []
    for entry in method_list:
        tokens = entry.split()
        idx = 0
        while idx < len(tokens):
            tok = tokens[idx]
            if tok == "hwtacacs-scheme":
                out.append("group tacacs+")
                idx += 2        # skip the scheme name
            elif tok == "radius-scheme":
                out.append("group radius")
                idx += 2        # skip the scheme name
            elif tok in _ACCT_KEYWORDS:
                idx += 1        # skip accounting sub-keywords
            else:
                out.append(tok)
                idx += 1
    return " ".join(out)
