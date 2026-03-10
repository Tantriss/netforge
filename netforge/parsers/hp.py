"""
netforge.parsers.hp
---------------------
HP Comware → UniversalConfig parser.

Architecture mirrors the JS HPParser (v3.1): the main ``parse()`` loop
dispatches to dedicated sub-methods for each block type.  Every sub-method
returns the index of the *last line it consumed* (``j - 1``), so the main
``while`` loop can unconditionally do ``i += 1`` after each dispatch.

Indentation convention: HP Comware uses exactly one space of indent for
sub-commands inside a block.  A line with indent == 0 always starts a new
top-level statement and terminates the previous block.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from netforge.models import (
    AAADomain,
    InterfaceEntry,
    LocalUser,
    NtpServer,
    RadiusScheme,
    StaticRoute,
    TacacsScheme,
    UniversalConfig,
    VlanEntry,
    VtyLine,
)

# Pre-compiled patterns used in _parse_global_line for readability.
_RE_ROUTE = re.compile(r"^ip route-static\s+(\S+)\s+(\S+)\s+(\S+)")
_RE_NTP = re.compile(r"^ntp-service unicast-server\s+(\S+)")
_RE_DOT1X_METHOD = re.compile(r"authentication-method\s+(\w+)")
_RE_DOT1X_QUIET = re.compile(r"timer quiet-period\s+(\d+)")
_RE_DOT1X_REAUTH = re.compile(r"timer reauth-period\s+(\d+)")
_RE_MAC_DOMAIN = re.compile(r"domain\s+(\S+)")
_RE_MAC_OFFLINE = re.compile(r"timer offline-detect\s+(\d+)")
_RE_MAC_QUIET = re.compile(r"timer quiet\s+(\d+)")

# Pre-compiled patterns used inside block sub-methods.
_RE_IP_ADDR = re.compile(r"ip address\s+(\S+)\s+(\S+)")
_RE_ACCESS_VLAN = re.compile(r"port access vlan\s+(\d+)")
_RE_PVID = re.compile(r"port trunk pvid vlan\s+(\d+)")
_RE_PERMIT = re.compile(r"port trunk permit vlan\s+(.+)")
_RE_DOT1X_MAX = re.compile(r"dot1x max-user\s+(\d+)")
_RE_DOT1X_GUEST = re.compile(r"dot1x guest-vlan\s+(\d+)")
_RE_MAC_MAX = re.compile(r"mac-authentication max-user\s+(\d+)")
_RE_MAC_GUEST = re.compile(r"mac-authentication guest-vlan\s+(\d+)")
_RE_BC_SUPP = re.compile(r"broadcast-suppression kbps\s+(\d+)")
_RE_TIMER_RESP = re.compile(r"timer response-timeout\s+(\d+)")
_RE_RETRY = re.compile(r"retry\s+(\d+)")
_RE_AUTH_MODE = re.compile(r"authentication-mode\s+(\w+)")
_RE_ROLE = re.compile(r"user-role\s+(\S+)")
_RE_IDLE = re.compile(r"idle-timeout\s+(\d+)")
_RE_CLASS = re.compile(r"\bclass\s+(\w+)")
_RE_SVC_TYPE = re.compile(r"service-type\s+(\S+)")
_RE_VTY = re.compile(r"^line vty\s+(\d+)\s+(\d+)")
_RE_LOCAL_USER = re.compile(r"^local-user\s+(\S+)")
_RE_CLOCK = re.compile(r"^clock timezone (.+)")


def _indent(line: str) -> int:
    """Return the number of leading spaces on *line*."""
    return len(line) - len(line.lstrip(" "))


def _is_block_end(line: str) -> bool:
    """Return True when *line* unambiguously closes a block."""
    t = line.strip()
    return t in ("#", "return", "quit", "")


class HPParser:
    """Parses HP Comware config text into a ``UniversalConfig`` IR.

    Usage::

        model = HPParser().parse(config_text)
    """

    # ── Public entry point ────────────────────────────────────────────────────

    def parse(self, config: str) -> UniversalConfig:
        """Parse *config* and return a populated ``UniversalConfig``.

        The parser is line-oriented: it iterates over ``config.splitlines()``,
        skipping blank lines and HP comments (``#``), then dispatches to a
        sub-method for each recognised top-level keyword.  Sub-methods consume
        their entire indented block and return the index of the last line they
        processed; the main loop advances past that index with ``i += 1``.
        """
        model = UniversalConfig(
            source_vendor="hp",
            parsed_at=datetime.now(timezone.utc).isoformat(),
        )

        lines = config.splitlines()
        i = 0

        while i < len(lines):
            raw = lines[i]
            t = raw.strip()

            # Skip blanks, HP comments, and terminator keywords.
            if not t or t.startswith("#") or t in ("return", "quit"):
                i += 1
                continue

            # Only dispatch on top-level (indent == 0) lines.
            if _indent(raw) != 0:
                i += 1
                continue

            if re.match(r"^vlan\s+\d+$", t):
                i = self._parse_vlan(lines, i, model)
            elif t.startswith("interface "):
                i = self._parse_interface(lines, i, model)
            elif t.startswith("radius scheme "):
                i = self._parse_radius(lines, i, model)
            elif t.startswith("hwtacacs scheme "):
                i = self._parse_tacacs(lines, i, model)
            elif t.startswith("domain "):
                i = self._parse_domain(lines, i, model)
            elif _RE_VTY.match(t):
                i = self._parse_vty(lines, i, model)
            elif _RE_LOCAL_USER.match(t):
                i = self._parse_local_user(lines, i, model)
            else:
                self._parse_global_line(t, model)

            i += 1

        return model

    # ── Block sub-methods ─────────────────────────────────────────────────────

    def _parse_vlan(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume a ``vlan N`` block and append a ``VlanEntry`` to *model*.

        Returns the index of the last consumed line (``j - 1``).
        """
        vlan_id = int(lines[i].strip().split()[1])
        entry = VlanEntry(id=vlan_id)
        j = i + 1

        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()
            if sub.startswith("name "):
                entry.name = sub[5:].strip()
            j += 1

        model.vlans.append(entry)
        return j - 1

    def _parse_interface(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume an ``interface`` block (SVI or physical port).

        SVIs (``Vlan-interface<N>``) populate ``ip`` / ``mask``.
        Physical interfaces populate mode, VLAN, dot1x, and security fields.
        Returns ``j - 1``.
        """
        name = lines[i].strip()[len("interface "):].strip()
        is_svi = name.startswith("Vlan-interface")

        entry = InterfaceEntry(
            name=name,
            type="svi" if is_svi else "physical",
        )

        j = i + 1
        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()

            if is_svi:
                m = _RE_IP_ADDR.search(sub)
                if m:
                    entry.ip = m.group(1)
                    entry.mask = m.group(2)
            else:
                self._apply_interface_sub(sub, entry)

            j += 1

        if is_svi:
            model.interfaces.append(entry)
        else:
            model.interfaces.append(entry)

        return j - 1

    @staticmethod
    def _apply_interface_sub(sub: str, entry: InterfaceEntry) -> None:
        """Apply a single indented sub-command to *entry* (physical ports)."""
        if sub.startswith("description "):
            entry.description = sub[12:].strip()
        elif sub == "port link-type access":
            entry.mode = "access"
        elif sub == "port link-type trunk":
            entry.mode = "trunk"
        elif m := _RE_ACCESS_VLAN.search(sub):
            entry.mode = "access"          # implied by 'port access vlan'
            entry.access_vlan = int(m.group(1))
        elif m := _RE_PVID.search(sub):
            entry.trunk_native = int(m.group(1))
        elif m := _RE_PERMIT.search(sub):
            entry.trunk_allowed = m.group(1).strip()
        elif sub == "dot1x" or sub.startswith("dot1x "):
            entry.dot1x = True
        elif m := _RE_DOT1X_MAX.search(sub):
            entry.dot1x_max = int(m.group(1))
        elif m := _RE_DOT1X_GUEST.search(sub):
            entry.guest_vlan = int(m.group(1))
        elif sub == "mac-authentication" or sub.startswith("mac-authentication "):
            entry.mac_auth = True
        elif m := _RE_MAC_MAX.search(sub):
            entry.mac_auth_max = int(m.group(1))
        elif m := _RE_MAC_GUEST.search(sub):
            entry.guest_vlan = int(m.group(1))
        elif "stp edged-port" in sub:
            entry.stp_edge = True
        elif m := _RE_BC_SUPP.search(sub):
            entry.broadcast_suppression = int(m.group(1))
        elif sub.startswith("port-security "):
            entry.port_security = sub

    def _parse_radius(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume a ``radius scheme`` block and append a ``RadiusScheme``.

        Returns ``j - 1``.
        """
        name = lines[i].strip()[len("radius scheme "):].strip()
        scheme = RadiusScheme(name=name)
        j = i + 1

        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()

            if sub.startswith("primary authentication "):
                scheme.primary_auth = sub.split()[2]
            elif sub.startswith("secondary authentication "):
                scheme.secondary_auth.append(sub.split()[2])
            elif "key authentication" in sub:
                scheme.key_auth = "ENCRYPTED"
            elif sub.startswith("nas-ip "):
                scheme.nas_ip = sub.split()[1]
            elif m := _RE_TIMER_RESP.search(sub):
                scheme.timeout = int(m.group(1))
            elif m := _RE_RETRY.search(sub):
                scheme.retransmit = int(m.group(1))

            j += 1

        model.radius_schemes.append(scheme)
        return j - 1

    def _parse_tacacs(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume an ``hwtacacs scheme`` block and append a ``TacacsScheme``.

        Returns ``j - 1``.
        """
        name = lines[i].strip()[len("hwtacacs scheme "):].strip()
        scheme = TacacsScheme(name=name)
        j = i + 1

        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()

            if sub.startswith("primary authentication "):
                scheme.primary_auth = sub.split()[2]
            elif sub.startswith("primary authorization "):
                scheme.primary_author = sub.split()[2]
            elif sub.startswith("primary accounting "):
                scheme.primary_acct = sub.split()[2]
            elif sub.startswith("secondary authentication "):
                scheme.secondary_auth = sub.split()[2]
            elif sub.startswith("secondary authorization "):
                scheme.secondary_author = sub.split()[2]
            elif sub.startswith("secondary accounting "):
                scheme.secondary_acct = sub.split()[2]
            elif "key authentication" in sub:
                scheme.key_auth = "ENCRYPTED"
            elif sub.startswith("nas-ip "):
                scheme.nas_ip = sub.split()[1]

            j += 1

        model.tacacs_schemes.append(scheme)
        return j - 1

    def _parse_domain(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume a ``domain`` block and append an ``AAADomain``.

        Returns ``j - 1``.
        """
        name = lines[i].strip()[len("domain "):].strip()
        domain = AAADomain(name=name)
        j = i + 1

        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()

            if sub.startswith("authentication login "):
                domain.auth_login.append(sub[len("authentication login "):].strip())
            elif sub.startswith("authorization login "):
                domain.author_login.append(sub[len("authorization login "):].strip())
            elif sub.startswith("accounting login "):
                domain.acct_login.append(sub[len("accounting login "):].strip())
            elif sub.startswith("authentication lan-access "):
                domain.auth_lan.append(sub[len("authentication lan-access "):].strip())
            elif sub.startswith("authentication enable "):
                domain.auth_enable.append(sub[len("authentication enable "):].strip())
            elif sub.startswith("authorization enable "):
                domain.author_enable.append(sub[len("authorization enable "):].strip())

            j += 1

        model.domains.append(domain)
        return j - 1

    def _parse_vty(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume a ``line vty`` block and append a ``VtyLine``.

        Returns ``j - 1``.
        """
        m = _RE_VTY.match(lines[i].strip())
        vty = VtyLine(start=int(m.group(1)), end=int(m.group(2)))
        j = i + 1

        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()

            if am := _RE_AUTH_MODE.search(sub):
                vty.auth_mode = am.group(1)
            elif im := _RE_IDLE.search(sub):
                vty.idle_timeout = int(im.group(1))
            elif "protocol inbound ssh" in sub:
                vty.protocol = "ssh"

            j += 1

        model.vty_lines.append(vty)
        return j - 1

    def _parse_local_user(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume a ``local-user`` block and append a ``LocalUser``.

        Returns ``j - 1``.
        """
        m = _RE_LOCAL_USER.match(lines[i].strip())
        user = LocalUser(name=m.group(1))
        j = i + 1

        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()

            if "password hash" in sub:
                user.password_hash = "ENCRYPTED"
            elif sm := _RE_SVC_TYPE.search(sub):
                user.service_type = sm.group(1)
            elif rm := _RE_ROLE.search(sub):
                user.role = rm.group(1)

            j += 1

        model.local_users.append(user)
        return j - 1

    # ── Global (indent-0) single-line statements ──────────────────────────────

    def _parse_global_line(self, line: str, model: UniversalConfig) -> None:
        """Handle a top-level statement that does not open an indented block.

        All assignments are direct mutations on *model*; no return value.
        """
        # Hostname
        if line.startswith("sysname "):
            model.hostname = line[8:].strip()
            return

        # Static route
        if m := _RE_ROUTE.match(line):
            model.static_routes.append(
                StaticRoute(dest=m.group(1), mask=m.group(2), gateway=m.group(3))
            )
            return

        # NTP
        if m := _RE_NTP.match(line):
            ip = m.group(1)
            prefer = "priority" in line
            model.ntp_servers.append(NtpServer(ip=ip, prefer=prefer))
            return

        # DNS
        if line.startswith("dns server "):
            model.dns_servers.append(line[11:].strip())
            return
        if line.startswith("dns domain "):
            model.dns_domain = line[11:].strip()
            return

        # Syslog
        if line.startswith("info-center loghost "):
            # Take the IP (second token); ignore optional 'source' qualifier.
            parts = line.split()
            if len(parts) >= 3 and parts[2] != "source":
                model.syslog_hosts.append(parts[2])
            return

        # Services (flags)
        if line == "ssh server enable":
            model.ssh_enabled = True
            return
        if line == "lldp global enable":
            model.lldp_enabled = True
            return
        if line == "snmp-agent":
            model.snmp_enabled = True
            return
        if line.startswith("snmp-agent sys-info contact "):
            model.snmp_contact = line[len("snmp-agent sys-info contact "):].strip()
            return
        if line.startswith("snmp-agent sys-info location "):
            model.snmp_location = line[len("snmp-agent sys-info location "):].strip()
            return
        if line.startswith("snmp-agent sys-info version "):
            model.snmp_version = line.split()[-1]
            return

        # Port-security global enable
        if line == "port-security enable":
            return  # not stored in UniversalConfig for now

        # dot1x global (informational, no IR field beyond warnings)
        if line.startswith("dot1x "):
            return

        # mac-authentication global
        if line.startswith("mac-authentication "):
            return
