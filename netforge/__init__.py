"""
netforge
----------
Bidirectional converter between HP Comware and AlliedWare Plus switch
configurations.

Public API::

    from netforge import convert, detect_vendor

    vendor = detect_vendor(raw_text)           # 'hp' or 'allied'
    output = convert(raw_text, to='allied')    # auto-detects source
    output = convert(raw_text, to='hp', from_vendor='allied')
"""
from __future__ import annotations

from typing import Optional

from netforge.detector import VendorDetector
from netforge.parsers.hp import HPParser
from netforge.parsers.allied import AlliedParser
from netforge.renderers.hp import HPRenderer
from netforge.renderers.allied import AlliedRenderer

__all__ = [
    "convert",
    "detect_vendor",
    "VendorDetector",
    "HPParser",
    "AlliedParser",
    "HPRenderer",
    "AlliedRenderer",
]

__version__ = "1.0.0"


def detect_vendor(config: str) -> str:
    """Auto-detect the vendor of *config*.

    Returns 'hp' or 'allied'.
    Raises ValueError if the vendor cannot be determined.
    """
    return VendorDetector().detect(config)


def convert(
    config: str,
    to: str,
    from_vendor: Optional[str] = None,
) -> str:
    """Convert *config* to the *to* vendor format.

    Args:
        config:      Raw configuration text.
        to:          Target vendor -- 'hp' or 'allied'.
        from_vendor: Source vendor -- 'hp' or 'allied'.
                     Auto-detected from *config* when None.

    Returns:
        The converted configuration as a string.

    Raises:
        ValueError: If *to* or the detected source vendor is invalid,
                    or if auto-detection fails (ambiguous / unknown config).
    """
    if to not in ("hp", "allied"):
        raise ValueError(f"Unknown target vendor: {to!r}. Expected 'hp' or 'allied'.")

    source = from_vendor if from_vendor is not None else VendorDetector().detect(config)

    parsers = {"hp": HPParser, "allied": AlliedParser}
    renderers = {"hp": HPRenderer, "allied": AlliedRenderer}

    if source not in parsers:
        raise ValueError(f"Unknown source vendor: {source!r}. Expected 'hp' or 'allied'.")

    model = parsers[source]().parse(config)
    return renderers[to]().render(model)
