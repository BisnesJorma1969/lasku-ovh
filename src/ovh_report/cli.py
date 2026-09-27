from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .generator import write_output
from .parser import ParseError, parse_directory
from .report import build_report


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ovh-report",
        description="Muodosta OVHcloudin PDF-laskuista kuukausittainen paikallinen raportti.",
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        default=Path("input"),
        help="PDF-laskujen hakemisto (oletus: ./input)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Tuloshakemisto (oletus: ./output)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    input_dir = args.input_dir.resolve()
    output_dir = (args.output or Path("output")).resolve()
    if not input_dir.is_dir():
        print(f"Virhe: syöte ei ole hakemisto: {input_dir}", file=sys.stderr)
        return 2
    if input_dir == output_dir or input_dir.is_relative_to(output_dir) or output_dir.is_relative_to(input_dir):
        print("Virhe: syöte- ja tuloshakemistot eivät saa sijaita sisäkkäin.", file=sys.stderr)
        return 2
    if output_dir.exists() and not output_dir.is_dir():
        print(f"Virhe: tulospolku ei ole hakemisto: {output_dir}", file=sys.stderr)
        return 2
    try:
        invoices = parse_directory(
            input_dir,
            on_warning=lambda message: print(f"Varoitus: {message}", file=sys.stderr),
        )
        report = build_report(invoices, input_dir.name)
        write_output(report, output_dir, input_dir)
    except (ParseError, RuntimeError, ValueError, OSError) as exc:
        print(f"Virhe: {exc}", file=sys.stderr)
        return 1
    print(
        f"Valmis: {len(invoices)} laskua, {report['summary']['line_item_count']} riviä → {output_dir / 'index.html'}"
    )
    return 0
