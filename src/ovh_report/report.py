from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from typing import Any

from . import __version__
from .parser import Invoice, LineItem


COLORS = [
    "#4e79a7", "#e15759", "#59a14f", "#8f63a8", "#d59628",
    "#76b7b2", "#b55a84", "#ed8b4f", "#6b8eac", "#9c755f",
]


def to_cents(value: Decimal) -> int:
    cents = value * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"Rahamäärässä on senttiä pienempi osa: {value}")
    return int(cents)


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _month_label(key: str) -> str:
    year, month = key.split("-")
    names = [
        "tammi", "helmi", "maalis", "huhti", "touko", "kesä",
        "heinä", "elo", "syys", "loka", "marras", "joulu",
    ]
    return f"{names[int(month) - 1]} {year}"


def _month_range(first: str, last: str) -> list[str]:
    year, month = map(int, first.split("-"))
    end_year, end_month = map(int, last.split("-"))
    result: list[str] = []
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def _signed_apportion(total: int, weights: dict[Any, int]) -> dict[Any, int]:
    """Split an integer exactly, allowing negative weights and allocations."""
    if not weights:
        return {}
    denominator = sum(weights.values())
    if denominator == 0:
        if total != 0:
            raise ValueError("Nollapainolle ei voi jakaa nollasta poikkeavaa summaa")
        return {key: 0 for key in weights}
    exact = {key: Decimal(total) * Decimal(weight) / Decimal(denominator) for key, weight in weights.items()}
    result = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in exact.items()}
    missing = total - sum(result.values())
    order = sorted(weights, key=lambda key: (-(exact[key] - result[key]), str(key)))
    for key in order[:missing]:
        result[key] += 1
    return result


def _item_months(item: LineItem, issue_date: date) -> dict[str, int]:
    amount = to_cents(item.amount_excl_vat)
    if item.service_start is None or item.service_end is None:
        return {_month_key(issue_date): amount}
    day_counts: dict[str, int] = defaultdict(int)
    current = item.service_start
    while current <= item.service_end:
        day_counts[_month_key(current)] += 1
        current += timedelta(days=1)
    return _signed_apportion(amount, dict(day_counts))


def _service_info(invoices: list[Invoice]) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    hostnames: dict[str, str] = {}
    resources: set[str] = set()
    for invoice in invoices:
        for item in invoice.items:
            if item.resource_id:
                resources.add(item.resource_id)
                if item.resource_id.startswith("ns") and item.hostname:
                    hostnames[item.resource_id] = item.hostname

    services: dict[str, dict[str, str]] = {}
    resource_groups: dict[str, str] = {}
    for resource in sorted(resources):
        if resource.startswith("ns"):
            group_id = f"server:{resource}"
            label = hostnames.get(resource, resource)
            kind = "server"
        elif resource.startswith("ip-"):
            group_id = "ip"
            label = "IP-osoitteet"
            kind = "ip"
        elif resource.startswith("pn-"):
            group_id = "vrack"
            label = "vRack"
            kind = "vrack"
        else:
            raise ValueError(f"Tuntematon resurssityyppi: {resource}")
        resource_groups[resource] = group_id
        service = {"id": group_id, "label": label, "kind": kind}
        if kind == "server":
            service["ovh_resource_id"] = resource
        services.setdefault(group_id, service)
    ordered = sorted(
        services.values(),
        key=lambda service: ({"server": 0, "ip": 1, "vrack": 2}[service["kind"]], service["label"]),
    )
    for index, service in enumerate(ordered):
        service["color"] = COLORS[index % len(COLORS)]
    return {service["id"]: service for service in ordered}, resource_groups


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def build_report(invoices: list[Invoice], source_directory: str) -> dict[str, Any]:
    services, resource_groups = _service_info(invoices)
    invoice_item_refs: dict[tuple[int, int], list[dict[str, int | str]]] = defaultdict(list)

    for invoice_index, invoice in enumerate(invoices):
        ex_weights: dict[tuple[int, str], int] = {}
        for item_index, item in enumerate(invoice.items):
            allocations = _item_months(item, invoice.issue_date)
            for month, cents in allocations.items():
                key = (item_index, month)
                ex_weights[key] = cents
        vat_allocations = _signed_apportion(to_cents(invoice.vat_amount), ex_weights)
        for (item_index, month), excl in ex_weights.items():
            vat = vat_allocations[(item_index, month)]
            invoice_item_refs[(invoice_index, item_index)].append({
                "month": month, "excl_vat_cents": excl, "vat_cents": vat, "incl_vat_cents": excl + vat,
            })

    month_groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    invoice_json: list[dict[str, Any]] = []
    for invoice_index, invoice in enumerate(invoices):
        items_json: list[dict[str, Any]] = []
        for item_index, item in enumerate(invoice.items):
            if item.resource_id not in resource_groups:
                raise ValueError(
                    f"Laskun {invoice.invoice_id} rivin resurssia ei voitu ryhmitellä: {item.resource_id or '<puuttuu>'}"
                )
            group_id = resource_groups[item.resource_id]
            allocations = sorted(invoice_item_refs[(invoice_index, item_index)], key=lambda row: row["month"])
            item_record = {
                "description": item.description,
                "category": item.category,
                "action": item.action,
                "quantity": item.quantity,
                "unit_price_excl_vat_cents": to_cents(item.unit_price),
                "amount_excl_vat_cents": to_cents(item.amount_excl_vat),
                "service_start": _iso(item.service_start),
                "service_end": _iso(item.service_end),
                "resource_id": item.resource_id,
                "hostname": item.hostname,
                "commitment": item.commitment,
                "page": item.page,
                "group_id": group_id,
                "allocations": allocations,
            }
            items_json.append(item_record)
            for allocation in allocations:
                month = str(allocation["month"])
                group = month_groups[month].setdefault(group_id, {
                    "id": group_id,
                    "label": services[group_id]["label"],
                    "kind": services[group_id]["kind"],
                    "color": services[group_id]["color"],
                    "excl_vat_cents": 0,
                    "vat_cents": 0,
                    "incl_vat_cents": 0,
                    "items": [],
                })
                group["excl_vat_cents"] += int(allocation["excl_vat_cents"])
                group["vat_cents"] += int(allocation["vat_cents"])
                group["incl_vat_cents"] += int(allocation["incl_vat_cents"])
                group["items"].append({
                    "invoice_id": invoice.invoice_id,
                    "source_file": invoice.source_file,
                    "description": item.description,
                    "category": item.category,
                    "action": item.action,
                    "resource_id": item.resource_id,
                    "service_start": _iso(item.service_start),
                    "service_end": _iso(item.service_end),
                    "excl_vat_cents": allocation["excl_vat_cents"],
                    "vat_cents": allocation["vat_cents"],
                    "incl_vat_cents": allocation["incl_vat_cents"],
                })
        invoice_json.append({
            "source_file": invoice.source_file,
            "pdf_path": f"pdfs/{invoice.issue_date.year:04d}/{invoice.invoice_id}.pdf",
            "invoice_id": invoice.invoice_id,
            "bill_type": invoice.bill_type,
            "issue_date": invoice.issue_date.isoformat(),
            "order_number": invoice.order_number,
            "currency": invoice.currency,
            "total_excl_vat_cents": to_cents(invoice.total_excl_vat),
            "vat_rate_percent": str(invoice.vat_rate),
            "vat_cents": to_cents(invoice.vat_amount),
            "total_incl_vat_cents": to_cents(invoice.total_incl_vat),
            "items": items_json,
        })

    all_month_keys = sorted(month_groups)
    months_json: list[dict[str, Any]] = []
    if all_month_keys:
        for month in _month_range(all_month_keys[0], all_month_keys[-1]):
            groups = sorted(month_groups.get(month, {}).values(), key=lambda group: list(services).index(group["id"]))
            months_json.append({
                "month": month,
                "label": _month_label(month),
                "excl_vat_cents": sum(group["excl_vat_cents"] for group in groups),
                "vat_cents": sum(group["vat_cents"] for group in groups),
                "incl_vat_cents": sum(group["incl_vat_cents"] for group in groups),
                "groups": groups,
            })

    summary = {
        "invoice_count": len(invoices),
        "line_item_count": sum(len(invoice.items) for invoice in invoices),
        "first_month": months_json[0]["month"] if months_json else None,
        "last_month": months_json[-1]["month"] if months_json else None,
        "total_excl_vat_cents": sum(to_cents(invoice.total_excl_vat) for invoice in invoices),
        "vat_cents": sum(to_cents(invoice.vat_amount) for invoice in invoices),
        "total_incl_vat_cents": sum(to_cents(invoice.total_incl_vat) for invoice in invoices),
    }
    if sum(month["excl_vat_cents"] for month in months_json) != summary["total_excl_vat_cents"]:
        raise ValueError("Kuukausien veroton summa ei vastaa laskujen summaa")
    if sum(month["vat_cents"] for month in months_json) != summary["vat_cents"]:
        raise ValueError("Kuukausien ALV-summa ei vastaa laskujen summaa")

    vat_change_date = date(2024, 9, 1)
    rate_stats: dict[str, list[date]] = defaultdict(list)
    vat_warnings: list[dict[str, str]] = []
    for invoice in invoices:
        rate = str(invoice.vat_rate)
        rate_stats[rate].append(invoice.issue_date)
        if invoice.issue_date >= vat_change_date and invoice.vat_rate == Decimal("24"):
            vat_warnings.append({
                "invoice_id": invoice.invoice_id,
                "issue_date": invoice.issue_date.isoformat(),
                "billed_rate_percent": rate,
                "expected_standard_rate_percent": "25.5",
                "message": "Laskulla on 24 % ALV yleisen verokannan muutospäivän jälkeen.",
            })
    vat_info = {
        "calculation": "invoice_actual",
        "standard_rate_change": {
            "date": vat_change_date.isoformat(),
            "before_percent": "24",
            "after_percent": "25.5",
        },
        "invoice_rates": [
            {
                "rate_percent": rate,
                "invoice_count": len(dates),
                "first_invoice_date": min(dates).isoformat(),
                "last_invoice_date": max(dates).isoformat(),
            }
            for rate, dates in sorted(rate_stats.items(), key=lambda item: Decimal(item[0]))
        ],
        "warnings": vat_warnings,
    }

    return {
        "schema_version": 1,
        "generator": {"name": "ovh-invoice-report", "version": __version__},
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {"directory": source_directory, "pdf_count": len(invoices)},
        "currency": "EUR",
        "allocation_method": "service_days",
        "vat": vat_info,
        "summary": summary,
        "services": list(services.values()),
        "months": months_json,
        "invoices": invoice_json,
    }
