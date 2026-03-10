"""
netforge.models
-----------------
Vendor-agnostic intermediate representation (IR) of a switch configuration.

All parsers produce a ``UniversalConfig``; all renderers consume one.
No vendor-specific logic lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Leaf dataclasses ──────────────────────────────────────────────────────────


@dataclass
class VlanEntry:
    """A single VLAN definition with its numeric ID and optional name."""

    id: int
    name: Optional[str] = None


@dataclass
class InterfaceEntry:
    """A physical switch port or a VLAN SVI (Switched Virtual Interface).

    SVI entries (``type='svi'``) populate ``ip`` and ``mask``.
    Physical port entries populate ``mode``, ``access_vlan``, ``trunk_*``,
    dot1x/MAC-auth/STP fields, etc.
    Both types may carry ``description``.
    """

    name: str
    type: str = "physical"                      # "physical" | "svi"
    description: Optional[str] = None
    mode: Optional[str] = None                  # "access" | "trunk"
    access_vlan: Optional[int] = None
    trunk_native: Optional[int] = None
    trunk_allowed: Optional[str] = None         # space-separated VLAN list
    dot1x: bool = False
    dot1x_max: Optional[int] = None
    mac_auth: bool = False
    mac_auth_max: Optional[int] = None
    guest_vlan: Optional[int] = None
    stp_edge: bool = False
    broadcast_suppression: Optional[int] = None  # kbps
    port_security: Optional[str] = None          # raw command string
    ip: Optional[str] = None                     # SVI only
    mask: Optional[str] = None                   # SVI only — dotted-decimal


@dataclass
class RadiusScheme:
    """A RADIUS authentication scheme (named on HP; synthetic on Allied).

    ``secondary_auth`` is a list because HP allows multiple fallback servers.
    ``key_auth`` is set to ``'ENCRYPTED'`` when the source config had a cipher
    key; the Key Manager is responsible for injecting the real value.
    """

    name: str
    primary_auth: Optional[str] = None
    secondary_auth: list[str] = field(default_factory=list)
    key_auth: Optional[str] = None              # 'ENCRYPTED' or None
    timeout: Optional[int] = None
    retransmit: Optional[int] = None
    nas_ip: Optional[str] = None


@dataclass
class TacacsScheme:
    """A TACACS+ scheme covering authentication, authorization, and accounting.

    HP uses a single named block; Allied uses inline ``tacacs-server host``
    lines synthesised into the ``'TACACS_SCHEME'`` sentinel name.
    ``key_auth`` follows the same 'ENCRYPTED' convention as ``RadiusScheme``.
    """

    name: str
    primary_auth: Optional[str] = None
    primary_author: Optional[str] = None
    primary_acct: Optional[str] = None
    secondary_auth: Optional[str] = None
    secondary_author: Optional[str] = None
    secondary_acct: Optional[str] = None
    key_auth: Optional[str] = None              # 'ENCRYPTED' or None
    nas_ip: Optional[str] = None


@dataclass
class AAADomain:
    """An AAA domain that maps service types to authentication method lists.

    Each list entry is a method string such as ``'hwtacacs-scheme CORP local'``
    or ``'radius-scheme WIRELESS local'`` (HP format used as canonical form).
    """

    name: str
    auth_login: list[str] = field(default_factory=list)
    author_login: list[str] = field(default_factory=list)
    acct_login: list[str] = field(default_factory=list)
    auth_lan: list[str] = field(default_factory=list)
    auth_enable: list[str] = field(default_factory=list)
    author_enable: list[str] = field(default_factory=list)


@dataclass
class VtyLine:
    """A VTY (virtual terminal) line block for remote management access."""

    start: int
    end: int
    auth_mode: Optional[str] = None             # e.g. 'scheme', 'password'
    idle_timeout: Optional[int] = None          # minutes
    protocol: Optional[str] = None              # 'ssh' | None


@dataclass
class LocalUser:
    """A locally-defined user account.

    ``password_hash`` is set to ``'ENCRYPTED'`` when the source config
    contained a hashed/ciphered password; plaintext passwords are never stored.
    """

    name: str
    password_hash: Optional[str] = None         # 'ENCRYPTED' or None
    service_type: Optional[str] = None          # e.g. 'ssh', 'terminal'
    role: Optional[str] = None                  # e.g. 'network-admin'


# ── Root IR ───────────────────────────────────────────────────────────────────


@dataclass
class StaticRoute:
    """An IPv4 static route entry."""

    dest: str
    mask: str                                   # dotted-decimal
    gateway: str


@dataclass
class NtpServer:
    """A single NTP server reference."""

    ip: str
    prefer: bool = False


@dataclass
class UniversalConfig:
    """Vendor-agnostic intermediate representation of a switch configuration.

    Produced by ``HPParser`` or ``AlliedParser``; consumed by ``HPRenderer``
    or ``AlliedRenderer``. The ``source_vendor`` field records which parser
    created this object; the renderer's caller is responsible for tracking
    the target vendor.

    All collection fields default to empty lists so callers never need to
    guard against ``None`` when iterating.
    """

    # Metadata
    source_vendor: Optional[str] = None         # 'hp' | 'allied'
    parsed_at: Optional[str] = None             # ISO-8601 timestamp

    # Global
    hostname: Optional[str] = None

    # Layer 2
    vlans: list[VlanEntry] = field(default_factory=list)
    interfaces: list[InterfaceEntry] = field(default_factory=list)

    # Routing
    static_routes: list[StaticRoute] = field(default_factory=list)

    # AAA
    radius_schemes: list[RadiusScheme] = field(default_factory=list)
    tacacs_schemes: list[TacacsScheme] = field(default_factory=list)
    domains: list[AAADomain] = field(default_factory=list)

    # Services
    ssh_enabled: bool = False
    ntp_servers: list[NtpServer] = field(default_factory=list)
    dns_servers: list[str] = field(default_factory=list)
    dns_domain: Optional[str] = None
    syslog_hosts: list[str] = field(default_factory=list)
    lldp_enabled: bool = False
    snmp_enabled: bool = False
    snmp_contact: Optional[str] = None
    snmp_location: Optional[str] = None
    snmp_version: Optional[str] = None

    # Management
    vty_lines: list[VtyLine] = field(default_factory=list)
    local_users: list[LocalUser] = field(default_factory=list)

    # Diagnostics
    warnings: list[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        """Append a freeform warning string (e.g. from a parser)."""
        self.warnings.append(message)
