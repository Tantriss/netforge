# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Single-file HTML application that converts network switch configurations bidirectionally between **HP Comware** and **AlliedWare Plus** formats.
Author: Tantriss | v3.x — 2026

### Version history

| File | Version | Notes |
|---|---|---|
| `transpiler-v2_2-WITH-KEY-MANAGER (1).html` | v2.2 | Original — reference source |
| `transpiler-v3_0-PROFESSIONAL.html` | v3.0 | Full UI/UX redesign, logic identical to v2.2 |
| `demo.html` | v3.1 | AlliedParser implemented, parsers refactored, inline test suite |

**Active file to edit: `demo.html`**

---

## Architecture

One HTML file — three sections: `<style>` / `<body>` / `<script>`. No build system, no external dependencies except Google Fonts.

### Core JS Classes

| Class | Role |
|---|---|
| `UniversalConfig` | Intermediate representation (vendor-agnostic IR) |
| `VendorDetector` | Detects HP vs Allied via pattern scoring |
| `HPParser` | HP Comware → `UniversalConfig` — split into sub-methods (v3.1+) |
| `AlliedParser` | AlliedWare Plus → `UniversalConfig` — fully implemented (v3.1+) |
| `AlliedRenderer` | `UniversalConfig` → AlliedWare Plus text |
| `HPRenderer` | `UniversalConfig` → HP Comware text |

### Parser architecture (v3.1+)

Both parsers follow the same sub-method pattern — the main `parse()` loop dispatches to dedicated methods per block type:

```
HPParser.parse()
├── parseVlan(lines, i, model)        → returns new index
├── parseInterface(lines, i, model)   → returns new index (SVI or physical)
├── parseRadius(lines, i, model)      → returns new index
├── parseTacacs(lines, i, model)      → returns new index
├── parseDomain(lines, i, model)      → returns new index
├── parseVty(lines, i, model)         → returns new index
├── parseLocalUser(lines, i, model)   → returns new index
└── parseGlobalLine(t, model)         → void, handles remaining top-level lines

AlliedParser.parse()
├── parseVlanDatabase(lines, i, model) → returns new index
├── parseInterface(lines, i, model)    → returns new index (vlan<id> or port<x>.<y>.<z>)
├── parseVtySection(lines, i, model)   → returns new index
├── prefixToMask(prefix)               → '255.255.255.0' from 24
└── convertPortName(alliedName)        → 'GigabitEthernet1/0/1' from 'port1.0.1'
```

### Adding a new vendor feature

1. Add the field to `UniversalConfig` constructor
2. Parse it in `HPParser.parseGlobalLine()` or the relevant sub-method
3. Parse it in the relevant `AlliedParser` sub-method
4. Render it in `AlliedRenderer.render()` and `HPRenderer.render()`
5. Update `VendorDetector` patterns if needed
6. Add a test case to `TEST_CASES`

### Adding a new vendor (ex: Cisco IOS)

1. Create `CiscoParser` class with same sub-method pattern
2. Create `CiscoRenderer` class (build `lines[]`, return `lines.join('\n')`)
3. Add detection patterns to `VendorDetector`
4. The `UniversalConfig` IR requires no changes if the feature already exists

### Key Manager

`collectCredentials()` → `buildKeyManagerHTML()` → `applyCredentialsToConfig()`

- Placeholder format: `<REPLACE_KEY_IP_WITH_DOTS_AS_UNDERSCORES>`
- User passwords: `<REPLACE_PASSWORD_username>`
- `buildKeyManagerHTML` uses `data-type="radius|tacacs|user"` on sections for CSS color coding
- Adding a new secret type: add detection in `collectCredentials`, add input in `buildKeyManagerHTML`, placeholder is replaced automatically by `applyCredentialsToConfig` via `data-placeholders` attribute

---

## Code Conventions

### CSS (v3.0+ design system)
- All values via CSS custom properties in `:root` — never raw hex/px
- Key tokens: `--bg-base`, `--bg-surface`, `--bg-raised`, `--cyan`, `--amber`, `--emerald`, `--rose`
- Fonts: `--font-ui` (IBM Plex Sans) for UI, `--font-mono` (JetBrains Mono) for config text
- Section comments: `/* ── Section Name ── */`

### JavaScript
- ES6+ class syntax, `'use strict'`
- Section headers: `// ╔══════════════════╗ // ║  Name  ║ // ╚══════════════════╝`
- Renderer pattern: build `lines[]` array, `return lines.join('\n')`
- User feedback: always `showStatus(message, type)` — types: `'success'` `'error'` `'warning'` `'info'`
- No external libraries

### UniversalConfig structure
```js
{
  metadata: { source_vendor, parsed_at },
  global: { hostname, clock },
  vlans: [{ id, name }],
  interfaces: [{ name, type, description, mode, access_vlan, trunk_native, trunk_allowed,
                 dot1x, dot1x_max, mac_auth, mac_auth_max, guest_vlan, stp_edge,
                 broadcast_suppression, port_security }],
  svis: [{ name, ip, mask }],
  routing: { static_routes: [{ dest, mask, gateway }] },
  aaa: {
    radius_schemes: [{ name, primary_auth, secondary_auth[], key_auth, timeout, retransmit, nas_ip }],
    tacacs_schemes: [{ name, primary_auth, primary_author, primary_acct, key_auth, nas_ip }],
    domains: [{ name, auth_login[], author_login[], acct_login[], auth_lan[], auth_enable[], author_enable[] }]
  },
  services: { ntp, dns, syslog, ssh, lldp, snmp },
  dot1x_global: { enabled, auth_method, timers },
  mac_auth_global: { domain, timers },
  port_security_global: { enabled },
  vty_lines: [{ start, end, auth_mode, role, idle_timeout, protocol }],
  local_users: [{ name, class, password_hash, service_type, role }],
  warnings: [], checklist: []
}
```

---

## Supported Config Features

| Feature | HP Comware | AlliedWare Plus |
|---|---|---|
| Hostname | `sysname` | `hostname` |
| VLANs | `vlan <id>` + `name` block | `vlan database` + `vlan <id> name` |
| Access port | `port access vlan <id>` | `switchport access vlan <id>` |
| Trunk port | `port link-type trunk` + `port trunk permit vlan` | `switchport mode trunk` + `switchport trunk allowed vlan` |
| SVI | `interface Vlan-interface<id>` | `interface vlan<id>` + `ip address <ip>/<prefix>` |
| Interface name | `GigabitEthernet1/0/1` | `port1.0.1` |
| Static route | `ip route-static <dst> <mask> <gw>` | `ip route <dst>/<prefix> <gw>` |
| RADIUS | `radius scheme` block | `radius-server host` inline |
| TACACS+ | `hwtacacs scheme` block | `tacacs-server host` inline |
| SSH | `ssh server enable` | `service ssh` + `no service telnet` |
| NTP | `ntp-service unicast-server` | `ntp server` |
| Syslog | `info-center loghost` | `log host` |
| dot1x | `dot1x` per interface | `dot1x port-control auto` |
| MAC auth | `mac-authentication` | `auth-mac enable` |
| STP edge | `stp edged-port` | `spanning-tree edgeport` |
| LLDP | `lldp global enable` | `lldp run` |
| SNMP | `snmp-agent` + `sys-info` | `snmp-server enable/contact/location` |
| DNS | `dns server` + `dns domain` | `ip name-server` + `ip domain-name` |
| VTY | `line vty` + `authentication-mode scheme` | `line vty` + `transport input ssh` |
| Local users | `local-user` + `password hash` | `username` + `password 8` |

---

## Development Workflow

No build system — edit HTML directly, open in browser (Chrome/Firefox recommended).

### Testing
- **Manual**: Load Sample → Convert → verify output → Reverse → verify round-trip → Apply Keys
- **Inline test suite** (v3.1+): click **Run Tests** button in header → modal shows 12 pass/fail cases covering HP→Allied, Allied→HP, and round-trip

### Adding a test case
Add an entry to the `TEST_CASES` const array in the Constants section:
```js
{
  name: 'Description of test',
  input: 'raw config text',
  forceVendor: 'hp',       // optional, overrides auto-detection
  targetVendor: 'allied',  // optional
  roundTrip: false,        // set true for HP→Allied→HP round-trip test
  expects: ['string that must appear in output', ...]
}
```

---

## Known Limitations

- Encrypted keys (`cipher` / `hash`) become placeholders — require Key Manager to inject real values
- VLAN name sanitization: spaces/hyphens/special chars → underscores, truncated at 32 chars
- Mask-to-prefix conversion uses bit-counting (handles any valid mask)
- Allied VTY lines capped at 0-15 (Allied limit)
- `AlliedParser` AAA mapping is best-effort — complex multi-domain HP configs may not fully round-trip
