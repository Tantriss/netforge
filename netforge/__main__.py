"""
netforge.__main__
-------------------
CLI entry point for the netforge package.

Usage examples::

    netforge config.txt --to allied
    netforge config.txt --to hp --output out.txt
    netforge configs/ --to allied --output converted/
    cat config.txt | netforge --to allied
    netforge config.txt --detect
    netforge config.txt --to allied --report

Exit codes
----------
0  success
1  conversion / parsing error
2  bad arguments / usage error
3  vendor detection ambiguous or failed
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

import netforge
from netforge.detector import VendorDetector
from netforge.models import UniversalConfig
from netforge.parsers.hp import HPParser
from netforge.parsers.allied import AlliedParser
from netforge.renderers.hp import HPRenderer
from netforge.renderers.allied import AlliedRenderer


# ── Helpers ───────────────────────────────────────────────────────────────────


def _safe_detect(config: str) -> Optional[str]:
    """Return detected vendor string or None on failure."""
    try:
        return VendorDetector().detect(config)
    except ValueError:
        return None


def _parse_model(config: str, from_vendor: Optional[str]) -> tuple[UniversalConfig, str]:
    """Parse *config* and return (model, source_vendor).

    Raises SystemExit(3) if detection fails and *from_vendor* is not given.
    """
    source = from_vendor
    if source is None:
        source = _safe_detect(config)
        if source is None:
            click.echo(
                "error: could not auto-detect vendor -- use --from hp|allied",
                err=True,
            )
            sys.exit(3)

    parsers = {"hp": HPParser, "allied": AlliedParser}
    if source not in parsers:
        click.echo(f"error: unknown vendor '{source}'", err=True)
        sys.exit(2)

    try:
        model = parsers[source]().parse(config)
    except Exception as exc:
        click.echo(f"error: parse failed -- {exc}", err=True)
        sys.exit(1)

    return model, source


def _convert_model(model: UniversalConfig, to_vendor: str) -> str:
    """Render *model* to *to_vendor* format."""
    renderers = {"hp": HPRenderer, "allied": AlliedRenderer}
    if to_vendor not in renderers:
        click.echo(f"error: unknown target vendor '{to_vendor}'", err=True)
        sys.exit(2)

    try:
        return renderers[to_vendor]().render(model)
    except Exception as exc:
        click.echo(f"error: render failed -- {exc}", err=True)
        sys.exit(1)


def _print_detect(config: str, label: str) -> None:
    """Print detection result for *label* to stderr."""
    vendor = _safe_detect(config)
    if vendor is None:
        click.echo(f"{label}: unknown (detection ambiguous)", err=True)
    else:
        name = VendorDetector().get_vendor_name(vendor)
        click.echo(f"{label}: {name} ({vendor})", err=True)


def _print_report(model: UniversalConfig, label: str) -> None:
    """Print a human-readable summary of *model* to stderr."""
    lines = [
        f"=== Report: {label} ===",
        f"  hostname    : {model.hostname or '(none)'}",
        f"  vlans       : {len(model.vlans)}",
        f"  interfaces  : {len(model.interfaces)}",
        f"  tacacs      : {len(model.tacacs_schemes)} scheme(s)",
        f"  radius      : {len(model.radius_schemes)} scheme(s)",
        f"  local users : {len(model.local_users)}",
        f"  ntp servers : {len(model.ntp_servers)}",
        f"  static routes: {len(model.static_routes)}",
        f"  ssh enabled : {model.ssh_enabled}",
        f"  lldp enabled: {model.lldp_enabled}",
        f"  snmp enabled: {model.snmp_enabled}",
    ]
    if model.warnings:
        lines.append(f"  warnings ({len(model.warnings)}):")
        for w in model.warnings:
            lines.append(f"    - {w}")
    click.echo("\n".join(lines), err=True)


def _process(
    config: str,
    to_vendor: str,
    from_vendor: Optional[str],
    report: bool,
    label: str,
) -> str:
    """Parse, optionally report, then render.  Returns output text."""
    model, _source = _parse_model(config, from_vendor)
    if report:
        _print_report(model, label)
    return _convert_model(model, to_vendor)


def _write_output(text: str, output_path: Optional[Path]) -> None:
    """Write *text* to *output_path* or stdout."""
    if output_path is None:
        click.echo(text, nl=False)
    else:
        output_path.write_text(text, encoding="utf-8")


# ── CLI definition ────────────────────────────────────────────────────────────


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("input_path", metavar="INPUT", required=False)
@click.option(
    "--to",
    "to_vendor",
    type=click.Choice(["hp", "allied"]),
    default=None,
    help="Target vendor format.",
)
@click.option(
    "--from",
    "from_vendor",
    type=click.Choice(["hp", "allied"]),
    default=None,
    help="Source vendor format (overrides auto-detection).",
)
@click.option(
    "--output",
    "-o",
    "output",
    default=None,
    help="Output file or directory (default: stdout).",
)
@click.option(
    "--detect",
    is_flag=True,
    default=False,
    help="Detect vendor and exit -- no conversion performed.",
)
@click.option(
    "--report",
    is_flag=True,
    default=False,
    help="Print IR summary to stderr after parsing.",
)
@click.version_option(netforge.__version__, prog_name="netforge")
def cli(
    input_path: Optional[str],
    to_vendor: Optional[str],
    from_vendor: Optional[str],
    output: Optional[str],
    detect: bool,
    report: bool,
) -> None:
    """Convert network switch configurations between HP Comware and AlliedWare Plus.

    INPUT may be a file path, a directory (batch mode), or omitted to read from stdin.
    """
    # ── Validate arguments ────────────────────────────────────────────────────
    if not detect and to_vendor is None:
        click.echo("error: --to is required unless --detect is used", err=True)
        sys.exit(2)

    output_path = Path(output) if output else None

    # ── stdin mode ────────────────────────────────────────────────────────────
    if input_path is None:
        if sys.stdin.isatty():
            click.echo("error: provide INPUT or pipe config via stdin", err=True)
            sys.exit(2)
        config = sys.stdin.read()
        if detect:
            _print_detect(config, "stdin")
            return
        text = _process(config, to_vendor, from_vendor, report, "stdin")
        _write_output(text, output_path)
        return

    src = Path(input_path)

    # ── directory / batch mode ────────────────────────────────────────────────
    if src.is_dir():
        if output_path is None:
            click.echo("error: --output directory is required in batch mode", err=True)
            sys.exit(2)
        output_path.mkdir(parents=True, exist_ok=True)
        files = [
            p for p in src.iterdir()
            if p.is_file() and p.suffix in {".txt", ".cfg", ""}
        ]
        if not files:
            click.echo(f"warning: no .txt/.cfg files found in {src}", err=True)
            return
        errors = 0
        for fpath in sorted(files):
            try:
                config = fpath.read_text(encoding="utf-8", errors="replace")
                if detect:
                    _print_detect(config, fpath.name)
                    continue
                text = _process(config, to_vendor, from_vendor, report, fpath.name)
                dest = output_path / fpath.name
                dest.write_text(text, encoding="utf-8")
                click.echo(f"converted: {fpath.name} -> {dest}", err=True)
            except SystemExit as exc:
                errors += 1
                click.echo(f"skipped {fpath.name} (exit {exc.code})", err=True)
        if errors:
            sys.exit(1)
        return

    # ── single file mode ──────────────────────────────────────────────────────
    if not src.is_file():
        click.echo(f"error: '{src}' is not a file or directory", err=True)
        sys.exit(2)

    config = src.read_text(encoding="utf-8", errors="replace")

    if detect:
        _print_detect(config, src.name)
        return

    text = _process(config, to_vendor, from_vendor, report, src.name)
    _write_output(text, output_path)


if __name__ == "__main__":
    cli()
