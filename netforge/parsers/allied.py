"""
netforge.parsers.allied
-------------------------
AlliedWare Plus → UniversalConfig parser.

Architecture mirrors ``HPParser``:

* Main ``parse()`` loop dispatches on top-level (indent-0) keywords.
* Block sub-methods (``_parse_vlan_database``, ``_parse_interface``,
  ``_parse_vty``) return ``j - 1`` so the caller can do ``i += 1``
  unconditionally at the bottom of the loop.
* Allied-specific single-line statements (``hostname``, ``ntp server``,
  ``aaa …``, etc.) are handled inline in ``_parse_global_line``.

Allied block delimiters:  blocks end with an ``exit`` line at indent 0.
These are skipped by the main loop (like ``!``, ``end``), so sub-methods
simply break when they encounter any indent-0 line and let the loop skip
the ``exit`` naturally.

Scheme name conventions
-----------------------
AlliedWare Plus does not use named AAA schemes.  The parsers synthesise
the sentinel names ``'TACACS_SCHEME'`` and ``'RADIUS_SCHEME'`` so that
``HPRenderer`` can produce a valid ``hwtacacs scheme`` / ``radius scheme``
block.  A second ``tacacs-server host`` line populates the ``secondary_*``
fields of the single scheme.
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

# ── Pre-compiled patterns ─────────────────────────────────────────────────────

_RE_VLAN_DB_ENTRY = re.compile(r"^vlan\s+(\d+)\s+name\s+(\S+)")
_RE_VTY = re.compile(r"^line vty\s+(\d+)\s+(\d+)")
_RE_IP_CIDR = re.compile(r"ip address\s+(\S+)/(\d+)")
_RE_ACCESS_VLAN = re.compile(r"switchport access vlan\s+(\d+)")
_RE_NATIVE_VLAN = re.compile(r"switchport trunk native vlan\s+(\d+)")
_RE_ALLOWED_VLAN = re.compile(r"switchport trunk allowed vlan\s+(.+)")
_RE_AUTH_MAC_GUEST = re.compile(r"auth-mac guest-vlan\s+(\d+)")
_RE_STORM = re.compile(r"storm-control broadcast level\s+(\d+)")
_RE_EXEC_TIMEOUT = re.compile(r"exec-timeout\s+(\d+)")
_RE_TACACS_HOST = re.compile(r"^tacacs-server host\s+(\S+)")
_RE_RADIUS_HOST = re.compile(r"^radius-server host\s+(\S+)")
_RE_RADIUS_TIMEOUT = re.compile(r"timeout\s+(\d+)")
_RE_RADIUS_RETRANSMIT = re.compile(r"retransmit\s+(\d+)")
_RE_NTP = re.compile(r"^ntp server\s+(\S+)")
_RE_LOG_HOST = re.compile(r"^log host\s+(\S+)")
_RE_IP_ROUTE = re.compile(r"^ip route\s+(\S+)/(\d+)\s+(\S+)")
_RE_SNMP_CONTACT = re.compile(r"^snmp-server contact\s+(.+)")
_RE_SNMP_LOCATION = re.compile(r"^snmp-server location\s+(.+)")
_RE_IP_NAME_SERVER = re.compile(r"^ip name-server\s+(\S+)")
_RE_IP_DOMAIN = re.compile(r"^ip domain-name\s+(\S+)")
_RE_USERNAME = re.compile(r"^username\s+(\S+)")
_RE_AAA = re.compile(
    r"^aaa (authentication|authorization|accounting) (\S+) default (.+)"
)

# Keywords the main loop skips unconditionally (like '#' in HP).
_SKIP_TOKENS = frozenset({"!", "end", "exit"})

# Allied VTY line count limit.
_ALLIED_VTY_MAX = 15


def _indent(line: str) -> int:
    """Return the number of leading spaces in *line*."""
    return len(line) - len(line.lstrip(" "))


class AlliedParser:
    """Parses AlliedWare Plus config text into a ``UniversalConfig`` IR.

    Usage::

        model = AlliedParser().parse(config_text)
    """

    # ── Public entry point ────────────────────────────────────────────────────

    def parse(self, config: str) -> UniversalConfig:
        """Parse *config* and return a populated ``UniversalConfig``.

        The main loop skips blank lines, ``!`` comments, and the Allied block
        terminators ``exit`` / ``end``.  All other indent-0 lines are either
        dispatched to a block sub-method or handled by ``_parse_global_line``.
        """
        model = UniversalConfig(
            source_vendor="allied",
            parsed_at=datetime.now(timezone.utc).isoformat(),
        )

        lines = config.splitlines()
        i = 0

        while i < len(lines):
            raw = lines[i]
            t = raw.strip()

            # Skip blanks, Allied comments, and block terminators.
            if not t or t in _SKIP_TOKENS:
                i += 1
                continue

            # Only dispatch on top-level (indent == 0) lines.
            if _indent(raw) != 0:
                i += 1
                continue

            if t == "vlan database":
                i = self._parse_vlan_database(lines, i, model)
            elif t.startswith("interface "):
                i = self._parse_interface(lines, i, model)
            elif _RE_VTY.match(t):
                i = self._parse_vty(lines, i, model)
            elif _RE_USERNAME.match(t):
                self._parse_local_user(t, model)
            else:
                self._parse_global_line(t, model)

            i += 1

        return model

    # ── Block sub-methods ─────────────────────────────────────────────────────

    def _parse_vlan_database(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume the ``vlan database`` block; append ``VlanEntry`` objects.

        The block ends at the ``exit`` line (indent 0).  That line is returned
        as ``j - 1`` so the main loop's ``i += 1`` skips past it cleanly
        (the main loop itself will then encounter ``exit`` and skip it).
        Returns ``j - 1``.
        """
        j = i + 1

        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()
            if m := _RE_VLAN_DB_ENTRY.match(sub):
                model.vlans.append(VlanEntry(id=int(m.group(1)), name=m.group(2)))
            j += 1

        return j - 1

    def _parse_interface(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume an ``interface`` block (SVI or physical port).

        Interfaces named ``vlan<N>`` (case-insensitive) are SVIs: their
        ``ip address X/PREFIX`` sub-command is converted to dotted-decimal
        notation via ``prefix_to_mask()``.

        Interfaces named ``port<X>.<Y>.<Z>`` are physical ports: their name
        is converted to ``GigabitEthernet<X>/<Y>/<Z>`` via
        ``convert_port_name()``.

        Returns ``j - 1``.
        """
        name_allied = lines[i].strip()[len("interface "):].strip()
        svi_match = re.match(r"^vlan(\d+)$", name_allied, re.IGNORECASE)

        if svi_match:
            entry = InterfaceEntry(
                name=f"Vlan-interface{svi_match.group(1)}",
                type="svi",
            )
        else:
            entry = InterfaceEntry(
                name=AlliedParser.convert_port_name(name_allied),
                type="physical",
            )

        j = i + 1
        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()

            if svi_match:
                self._apply_svi_sub(sub, entry)
            else:
                self._apply_port_sub(sub, entry)

            j += 1

        model.interfaces.append(entry)
        return j - 1

    def _parse_vty(
        self, lines: list[str], i: int, model: UniversalConfig
    ) -> int:
        """Consume a ``line vty`` block and append a ``VtyLine``.

        Allied supports at most 16 VTY lines (0–15); the ``end`` value is
        capped accordingly.  ``auth_mode`` defaults to ``'scheme'`` because
        Allied VTY lines that reach this parser always require AAA auth.
        Returns ``j - 1``.
        """
        m = _RE_VTY.match(lines[i].strip())
        vty = VtyLine(
            start=int(m.group(1)),
            end=min(int(m.group(2)), _ALLIED_VTY_MAX),
            auth_mode="scheme",
        )
        j = i + 1

        while j < len(lines):
            if _indent(lines[j]) == 0:
                break
            sub = lines[j].strip()

            if em := _RE_EXEC_TIMEOUT.search(sub):
                vty.idle_timeout = int(em.group(1))
            elif sub == "transport input ssh":
                vty.protocol = "ssh"

            j += 1

        model.vty_lines.append(vty)
        return j - 1

    # ── Single-line sub-methods ───────────────────────────────────────────────

    @staticmethod
    def _parse_local_user(line: str, model: UniversalConfig) -> None:
        """Parse a ``username`` line and append a ``LocalUser``.

        Allied inline format::

            username admin privilege 15 password 8 <REPLACE_PASSWORD_admin>

        The password value (encrypted or placeholder) is stored as
        ``'ENCRYPTED'`` — the actual value is never preserved.
        """
        m = _RE_USERNAME.match(line)
        if not m:
            return
        model.local_users.append(
            LocalUser(
                name=m.group(1),
                password_hash="ENCRYPTED",
                service_type="ssh",
            )
        )

    def _parse_global_line(self, line: str, model: UniversalConfig) -> None:
        """Handle a top-level line that does not open an indented block.

        Covers: hostname, SSH, NTP, syslog, SNMP, LLDP, DNS, static routes,
        TACACS+, RADIUS, AAA, and ``username`` inline declarations.
        """
        # Hostname
        if line.startswith("hostname "):
            model.hostname = line[9:].strip()
            return

        # SSH — any of the three Allied SSH enable keywords
        if line in ("service ssh", "ssh server v2only", "no service telnet"):
            model.ssh_enabled = True
            return
        if line.startswith("ssh server "):
            # ssh server session-timeout / allow-users / etc. — ssh is on
            model.ssh_enabled = True
            return

        # NTP
        if m := _RE_NTP.match(line):
            model.ntp_servers.append(
                NtpServer(ip=m.group(1), prefer="prefer" in line)
            )
            return

        # Syslog
        if m := _RE_LOG_HOST.match(line):
            ip = m.group(1)
            if ip not in model.syslog_hosts:
                model.syslog_hosts.append(ip)
            return

        # SNMP
        if line == "snmp-server enable":
            model.snmp_enabled = True
            return
        if m := _RE_SNMP_CONTACT.match(line):
            model.snmp_contact = m.group(1).strip()
            model.snmp_enabled = True
            return
        if m := _RE_SNMP_LOCATION.match(line):
            model.snmp_location = m.group(1).strip()
            model.snmp_enabled = True
            return

        # LLDP
        if line == "lldp run":
            model.lldp_enabled = True
            return

        # DNS
        if m := _RE_IP_NAME_SERVER.match(line):
            model.dns_servers.append(m.group(1))
            return
        if m := _RE_IP_DOMAIN.match(line):
            model.dns_domain = m.group(1)
            return

        # Static routes  — ip route DST/PREFIX GW
        if m := _RE_IP_ROUTE.match(line):
            model.static_routes.append(
                StaticRoute(
                    dest=m.group(1),
                    mask=AlliedParser.prefix_to_mask(int(m.group(2))),
                    gateway=m.group(3),
                )
            )
            return

        # TACACS+ — first host → primary, second → secondary
        if m := _RE_TACACS_HOST.match(line):
            ip = m.group(1)
            if not model.tacacs_schemes:
                model.tacacs_schemes.append(
                    TacacsScheme(
                        name="TACACS_SCHEME",
                        primary_auth=ip,
                        primary_author=ip,
                        primary_acct=ip,
                        key_auth="ENCRYPTED",
                    )
                )
            else:
                scheme = model.tacacs_schemes[0]
                if scheme.secondary_auth is None:
                    scheme.secondary_auth = ip
                    scheme.secondary_author = ip
                    scheme.secondary_acct = ip
            return

        # RADIUS — first host → primary, subsequent → secondary
        if m := _RE_RADIUS_HOST.match(line):
            ip = m.group(1)
            if not model.radius_schemes:
                timeout = int(t.group(1)) if (t := _RE_RADIUS_TIMEOUT.search(line)) else None
                retransmit = int(r.group(1)) if (r := _RE_RADIUS_RETRANSMIT.search(line)) else None
                model.radius_schemes.append(
                    RadiusScheme(
                        name="RADIUS_SCHEME",
                        primary_auth=ip,
                        key_auth="ENCRYPTED",
                        timeout=timeout,
                        retransmit=retransmit,
                    )
                )
            else:
                scheme = model.radius_schemes[0]
                if ip not in scheme.secondary_auth:
                    scheme.secondary_auth.append(ip)
            return

        # AAA
        if line.startswith("aaa "):
            self._parse_aaa_line(line, model)
            return

    # ── AAA helper ────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_aaa_line(line: str, model: UniversalConfig) -> None:
        """Map an ``aaa …`` line onto the single canonical ``AAADomain``.

        Allied uses flat inline ``aaa`` commands rather than named domains.
        All entries are accumulated into one domain named ``'default'``,
        which is created on first use.

        Method name mapping:

        * ``tacacs+`` → ``'hwtacacs-scheme TACACS_SCHEME'``
        * ``radius``  → ``'radius-scheme RADIUS_SCHEME'``
        * everything else (``local``, ``none``, ``start-stop``) → kept as-is

        The ``group`` keyword (Allied prefix before method names) is stripped.
        """
        m = _RE_AAA.match(line)
        if not m:
            return

        action, service, rest = m.group(1), m.group(2), m.group(3)

        # Lazy-create the single default domain.
        if not model.domains:
            model.domains.append(
                AAADomain(name="default")
            )
        domain = model.domains[0]

        def map_method(token: str) -> str:
            if token == "tacacs+":
                return "hwtacacs-scheme TACACS_SCHEME"
            if token == "radius":
                return "radius-scheme RADIUS_SCHEME"
            return token

        methods = [
            map_method(tok)
            for tok in rest.strip().split()
            if tok != "group"
        ]

        if action == "authentication":
            if service == "login":
                domain.auth_login.extend(methods)
            elif service == "dot1x":
                domain.auth_lan.extend(methods)
            elif service == "enable":
                domain.auth_enable.extend(methods)
        elif action == "authorization":
            if service in ("commands", "exec"):
                domain.author_login.extend(methods)
        elif action == "accounting":
            if service in ("login", "exec"):
                domain.acct_login.extend(methods)

    # ── Interface sub-command helpers ─────────────────────────────────────────

    @staticmethod
    def _apply_svi_sub(sub: str, entry: InterfaceEntry) -> None:
        """Apply a single indented sub-command to an SVI ``InterfaceEntry``."""
        if m := _RE_IP_CIDR.search(sub):
            entry.ip = m.group(1)
            entry.mask = AlliedParser.prefix_to_mask(int(m.group(2)))

    @staticmethod
    def _apply_port_sub(sub: str, entry: InterfaceEntry) -> None:
        """Apply a single indented sub-command to a physical ``InterfaceEntry``."""
        if sub.startswith("description "):
            entry.description = sub[12:].strip()
        elif sub == "switchport mode access":
            entry.mode = "access"
        elif sub == "switchport mode trunk":
            entry.mode = "trunk"
        elif m := _RE_ACCESS_VLAN.search(sub):
            entry.access_vlan = int(m.group(1))
        elif m := _RE_NATIVE_VLAN.search(sub):
            entry.trunk_native = int(m.group(1))
        elif m := _RE_ALLOWED_VLAN.search(sub):
            # Normalise Allied comma-list to space-separated HP format.
            entry.trunk_allowed = m.group(1).strip().replace(",", " ")
        elif sub == "dot1x port-control auto":
            entry.dot1x = True
        elif sub == "auth-mac enable":
            entry.mac_auth = True
        elif m := _RE_AUTH_MAC_GUEST.search(sub):
            entry.guest_vlan = int(m.group(1))
        elif sub == "spanning-tree edgeport":
            entry.stp_edge = True
        elif m := _RE_STORM.search(sub):
            entry.broadcast_suppression = int(m.group(1))

    # ── Static utilities ──────────────────────────────────────────────────────

    @staticmethod
    def prefix_to_mask(prefix: int) -> str:
        """Convert a CIDR prefix length to a dotted-decimal subnet mask.

        Examples::

            AlliedParser.prefix_to_mask(24)  # '255.255.255.0'
            AlliedParser.prefix_to_mask(16)  # '255.255.0.0'
            AlliedParser.prefix_to_mask(0)   # '0.0.0.0'
            AlliedParser.prefix_to_mask(32)  # '255.255.255.255'

        Uses a 32-bit left-shift masked to unsigned 32 bits to reproduce the
        JavaScript ``(0xFFFFFFFF << (32 - prefix)) >>> 0`` behaviour exactly.
        """
        if prefix == 0:
            return "0.0.0.0"
        mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        return ".".join(str((mask >> shift) & 0xFF) for shift in (24, 16, 8, 0))

    @staticmethod
    def convert_port_name(name: str) -> str:
        """Convert an Allied port name to HP Comware format.

        Examples::

            AlliedParser.convert_port_name('port1.0.1')   # 'GigabitEthernet1/0/1'
            AlliedParser.convert_port_name('port2.0.10')  # 'GigabitEthernet2/0/10'
            AlliedParser.convert_port_name('unknown')      # 'unknown'  (passthrough)
        """
        m = re.match(r"^port(\d+)\.(\d+)\.(\d+)$", name)
        if m:
            return f"GigabitEthernet{m.group(1)}/{m.group(2)}/{m.group(3)}"
        return name
