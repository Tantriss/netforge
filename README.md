# netforge

![Version](https://img.shields.io/badge/version-1.1.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)

Bidirectional converter between **HP Comware** and **AlliedWare Plus** network switch configurations.

---

## Installation

```bash
pip install netforge
```

---

## CLI usage

### Single file

```bash
# HP Comware -> AlliedWare Plus
netforge switch.txt --to allied

# AlliedWare Plus -> HP Comware, write to file
netforge switch.txt --to hp --output out.txt

# Override auto-detection
netforge switch.txt --from hp --to allied
```

### Batch (directory)

```bash
netforge configs/ --to allied --output converted/
```

All `.txt` and `.cfg` files in `configs/` are converted. Results land in `converted/`.

### stdin

```bash
cat switch.txt | netforge --to allied
ssh admin@switch "display current-configuration" | netforge --from hp --to allied
```

### Detect vendor

```bash
netforge switch.txt --detect
# switch.txt: HP Comware (hp)
```

### Report

```bash
netforge switch.txt --to allied --report
# prints IR summary (hostname, VLANs, interfaces, AAA schemes) to stderr
# converted config goes to stdout
```

### Version

```bash
netforge --version
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Conversion / parsing error |
| 2 | Bad arguments / usage error |
| 3 | Vendor detection ambiguous or failed |

---

## Python library

```python
import netforge

# Auto-detect source vendor and convert
allied_config = netforge.convert(hp_config_text, to="allied")
hp_config     = netforge.convert(allied_config_text, to="hp")

# Force source vendor
allied_config = netforge.convert(text, to="allied", from_vendor="hp")

# Detect only
vendor = netforge.detect_vendor(text)   # "hp" or "allied"
```

### Lower-level API

```python
from netforge.parsers.hp import HPParser
from netforge.renderers.allied import AlliedRenderer

model = HPParser().parse(raw_text)        # UniversalConfig (dataclass IR)
print(model.hostname, model.vlans)

output = AlliedRenderer().render(model)
```

---

## Supported features

| Feature | HP Comware | AlliedWare Plus |
|---------|-----------|----------------|
| Hostname | `sysname` | `hostname` |
| VLANs | `vlan <id>` + `name` block | `vlan database` |
| Access port | `port access vlan <id>` | `switchport access vlan <id>` |
| Trunk port | `port link-type trunk` | `switchport mode trunk` |
| SVI | `interface Vlan-interface<id>` | `interface vlan<id>` |
| Interface name | `GigabitEthernet1/0/1` | `port1.0.1` |
| Static routes | `ip route-static` | `ip route` |
| RADIUS | named scheme block | `radius-server host` inline |
| TACACS+ | named scheme block | `tacacs-server host` inline |
| SSH | `ssh server enable` | `service ssh` |
| NTP | `ntp-service unicast-server` | `ntp server` |
| Syslog | `info-center loghost` | `log host` |
| dot1x | `dot1x` per interface | `dot1x port-control auto` |
| MAC auth | `mac-authentication` | `auth-mac enable` |
| STP edge | `stp edged-port` | `spanning-tree edgeport` |
| LLDP | `lldp global enable` | `lldp run` |
| SNMP | `snmp-agent` | `snmp-server enable` |
| DNS | `dns server` + `dns domain` | `ip name-server` + `ip domain-name` |
| VTY lines | `line vty` + `authentication-mode` | `line vty` + `transport input` |
| Local users | `local-user` + `password hash` | `username` + `password 8` |

### Key placeholders

Encrypted secrets are never carried across vendors. The converter emits human-readable
placeholders that the Key Manager can replace:

- TACACS / RADIUS keys: `<REPLACE_KEY_10_0_0_10>`
- User passwords: `<REPLACE_PASSWORD_admin>`

---

## Contributing

1. Fork the repository and create a feature branch.
2. Add your feature to the IR (`models.py`), both parsers, both renderers.
3. Add fixture lines to `tests/fixtures/hp_sample.txt` and `allied_sample.txt`.
4. Write tests in `tests/test_hp_parser.py`, `test_allied_parser.py`, `test_renderers.py`.
5. Run `pytest tests/ -v` — all tests must pass.
6. Open a pull request.

```bash
pip install -e ".[dev]"
pytest tests/ -v --tb=short
```

---

## Changelog

See [GitHub Releases](https://github.com/Tantriss/netforge/releases) for full history.

### v1.1.0

- Fix hostname parsing on indented HP Comware configs
- Fix SSH, SNMP v3, static routes not converted
- Fix AAA duplicates and wrong suffixes
- Fix VTY lines format
- Add `no service http` / `no service telnet` systematically
- Fix UnicodeEncodeError on Windows

---

## License

MIT
