"""
netforge.detector
-------------------
Vendor detection via pattern scoring.

Mirrors the ``VendorDetector`` class from the JS transpiler exactly:
same patterns, same scoring algorithm (one point per line that matches
*any* pattern of a given vendor), same tie-breaking — except that an
undecidable result raises ``ValueError`` instead of returning ``'unknown'``.
"""
from __future__ import annotations

import re
from typing import Optional


class VendorDetector:
    """Detects HP Comware vs AlliedWare Plus by scoring config lines.

    Scoring: for each non-empty, non-comment line, +1 to ``hp_score`` if
    *any* HP pattern matches, +1 to ``allied_score`` if *any* Allied pattern
    matches.  The vendor with the higher score wins.
    """

    # Patterns compiled once at class definition time.
    # Order mirrors the JS source (VendorDetector.hpPatterns / alliedPatterns).

    HP_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"^sysname\s+"),
        re.compile(r"^interface\s+(GigabitEthernet|Ten-GigabitEthernet)"),
        re.compile(r"^port\s+(access|link-type|trunk)"),
        re.compile(r"^dot1x$"),
        re.compile(r"^mac-authentication$"),
        re.compile(r"^hwtacacs\s+scheme"),
        re.compile(r"^radius\s+scheme"),
        re.compile(r"^info-center"),
        re.compile(r"^undo\s+"),
        re.compile(r"^Vlan-interface\d+$"),
        re.compile(r"^ntp-service\s+unicast-server"),
    ]

    ALLIED_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"^hostname\s+"),
        re.compile(r"^interface\s+port\d+\.\d+\.\d+"),
        re.compile(r"^switchport\s+(mode|access)"),
        re.compile(r"^auth-mac\s+enable"),
        re.compile(r"^dot1x\s+port-control"),
        re.compile(r"^spanning-tree\s+edgeport"),
        re.compile(r"^vlan\s+database"),
        re.compile(r"^radius-server\s+host"),
        re.compile(r"^tacacs-server\s+host"),
        re.compile(r"^log\s+host"),
        re.compile(r"^snmp-server"),
        re.compile(r"^ntp\s+server"),
    ]

    _VENDOR_NAMES: dict[str, str] = {
        "hp": "HP Comware",
        "allied": "AlliedWare Plus",
    }

    def detect(self, config: str) -> str:
        """Return ``'hp'`` or ``'allied'``.

        Raises ``ValueError`` when the scores are equal (tie) or both zero,
        so the caller can prompt the user to supply ``--vendor`` explicitly.
        """
        lines = [
            stripped
            for raw in config.splitlines()
            if (stripped := raw.strip())
            and not stripped.startswith("#")
            and not stripped.startswith("!")
        ]

        hp_score = 0
        allied_score = 0

        for line in lines:
            if any(p.search(line) for p in self.HP_PATTERNS):
                hp_score += 1
            if any(p.search(line) for p in self.ALLIED_PATTERNS):
                allied_score += 1

        if hp_score > allied_score:
            return "hp"
        if allied_score > hp_score:
            return "allied"

        raise ValueError(
            f"Vendor undecidable (hp_score={hp_score}, allied_score={allied_score}). "
            "Use --vendor hp|allied to override."
        )

    def get_vendor_name(self, vendor: str) -> str:
        """Return the human-readable vendor label.

        Raises ``ValueError`` for unknown vendor strings.
        """
        try:
            return self._VENDOR_NAMES[vendor]
        except KeyError:
            raise ValueError(
                f"Unknown vendor: {vendor!r}. Expected 'hp' or 'allied'."
            ) from None
