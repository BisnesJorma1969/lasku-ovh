from copy import deepcopy
from decimal import Decimal
import hashlib
from pathlib import Path
import shutil

import pytest

import ovh_report.parser as parser_module
from ovh_report.parser import ParseError, _header_events, _validate_item_metadata, parse_directory, parse_invoice
from ovh_report.report import _signed_apportion, build_report, to_cents


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "input"


def test_signed_apportion_is_exact_for_positive_and_negative_components():
    result = _signed_apportion(598, {"server": 4699, "discount": -2209, "free": 0})
    assert sum(result.values()) == 598
    assert result["server"] > 0
    assert result["discount"] < 0
    assert result["free"] == 0


def test_to_cents_rejects_subcent_values():
    assert to_cents(Decimal("12.34")) == 1234
    with pytest.raises(ValueError, match="senttiä pienempi"):
        to_cents(Decimal("0.001"))


@pytest.mark.skipif(not list(DATA_DIR.rglob("*.pdf")), reason="PDF-aineisto ei ole saatavilla")
def test_recursive_discovery_does_not_depend_on_pdf_filename(tmp_path):
    source = next(DATA_DIR.rglob("*.pdf"))
    nested = tmp_path / "vapaamuotoinen" / "hakemistorakenne"
    nested.mkdir(parents=True)
    renamed = nested / "mika-tahansa-nimi.PDF"
    shutil.copy2(source, renamed)

    invoices = parse_directory(tmp_path)

    assert len(invoices) == 1
    assert invoices[0].source_file == "vapaamuotoinen/hakemistorakenne/mika-tahansa-nimi.PDF"
    assert invoices[0].invoice_id.startswith("IE")


@pytest.mark.skipif(not list(DATA_DIR.rglob("*.pdf")), reason="PDF-aineisto ei ole saatavilla")
def test_semantically_identical_invoice_with_different_hash_is_skipped(tmp_path):
    source = next(DATA_DIR.rglob("*.pdf"))
    first = tmp_path / "a" / "ensimmainen.pdf"
    second = tmp_path / "b" / "toinen.pdf"
    first.parent.mkdir()
    second.parent.mkdir()
    shutil.copy2(source, first)
    second.write_bytes(source.read_bytes() + b"\n% container-level difference\n")
    assert hashlib.sha256(first.read_bytes()).digest() != hashlib.sha256(second.read_bytes()).digest()
    warnings: list[str] = []

    invoices = parse_directory(tmp_path, on_warning=warnings.append)

    assert len(invoices) == 1
    assert len(warnings) == 1
    assert "ohitetaan" in warnings[0]


@pytest.mark.skipif(not list(DATA_DIR.rglob("*.pdf")), reason="PDF-aineisto ei ole saatavilla")
def test_same_invoice_number_with_different_content_fails(tmp_path, monkeypatch):
    source = next(DATA_DIR.rglob("*.pdf"))
    original = parse_invoice(source)
    (tmp_path / "ensimmainen.pdf").write_bytes(b"test fixture")
    (tmp_path / "toinen.pdf").write_bytes(b"test fixture")

    def fake_parse(path):
        invoice = deepcopy(original)
        if path.name == "toinen.pdf":
            invoice.total_incl_vat += Decimal("0.01")
        return invoice

    monkeypatch.setattr(parser_module, "parse_invoice", fake_parse)
    with pytest.raises(RuntimeError, match="eri sisältöiset PDF:t.*total_incl_vat"):
        parse_directory(tmp_path)


def test_unknown_invoice_section_fails_closed(tmp_path):
    lines = ["Future Service", "Subscription", "Description", "Quantity", "Unit", "price"]
    with pytest.raises(ParseError, match="laskutaulukon osiota ei tunnistettu"):
        _header_events(tmp_path / "unknown.pdf", lines, [1] * len(lines))


def test_unknown_line_item_field_fails_closed(tmp_path):
    metadata = [
        "From 01-01-2026 to 31-01-2026",
        "Unexpected billing field: value",
        "ip-192.0.2.1",
    ]
    with pytest.raises(ParseError, match="tuntematon laskurivin kenttä tai metadata"):
        _validate_item_metadata(tmp_path / "unknown.pdf", 1, metadata)


@pytest.mark.skipif(not list(DATA_DIR.rglob("Invoice_*.pdf")), reason="PDF-aineisto ei ole saatavilla")
def test_complete_invoice_corpus_reconciles():
    invoices = parse_directory(DATA_DIR)
    report = build_report(invoices, str(DATA_DIR))

    assert len(invoices) == len([path for path in DATA_DIR.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"])
    assert report["summary"]["line_item_count"] == sum(len(invoice.items) for invoice in invoices)
    assert sum(month["incl_vat_cents"] for month in report["months"]) == report["summary"]["total_incl_vat_cents"]
    assert sum(month["excl_vat_cents"] for month in report["months"]) == report["summary"]["total_excl_vat_cents"]
    assert {service["kind"] for service in report["services"]} >= {"server", "ip", "vrack"}
    server_services = [service for service in report["services"] if service["kind"] == "server"]
    assert len(server_services) == 3
    assert all(service["id"] == f"server:{service['ovh_resource_id']}" for service in server_services)
    assert report["vat"]["standard_rate_change"] == {
        "date": "2024-09-01",
        "before_percent": "24",
        "after_percent": "25.5",
    }
    expected_warnings = {
        invoice.invoice_id
        for invoice in invoices
        if invoice.issue_date.isoformat() >= "2024-09-01" and invoice.vat_rate == Decimal("24")
    }
    assert {warning["invoice_id"] for warning in report["vat"]["warnings"]} == expected_warnings


@pytest.mark.skipif(not list(DATA_DIR.rglob("Invoice_*.pdf")), reason="PDF-aineisto ei ole saatavilla")
def test_every_priced_item_has_a_specific_service_group():
    report = build_report(parse_directory(DATA_DIR), str(DATA_DIR))
    priced = [
        item
        for invoice in report["invoices"]
        for item in invoice["items"]
        if item["amount_excl_vat_cents"]
    ]
    assert priced
    assert all(item["group_id"] != "other" for item in priced)
