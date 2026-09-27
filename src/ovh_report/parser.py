from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from pypdf import PdfReader


MONEY_RE = re.compile(r"^€\s*(-?[\d,.]+)$")
DATE_RE = r"\d{2}[-/]\d{2}[-/]\d{4}"
RESOURCE_RE = re.compile(r"ns\d+\.ip-(?:\d+-)+\d+\.eu", re.I)
IP_RE = re.compile(r"ip-(\d{1,3}(?:\.\d{1,3}){3})", re.I)
VRACK_RE = re.compile(r"pn-\d+", re.I)
HOST_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\.?(?=\s|$)", re.I)
KNOWN_CATEGORIES = {
    "Other GIFT",
    "Other DEDICATED-OPTION",
    "Other IP",
    "Other VRACK",
    "Other",
    "Dedicated Server(s)",
}
KNOWN_ACTIONS = {"Subscription", "Solutions", "Setup", "Special"}


class ParseError(RuntimeError):
    def __init__(self, path: Path, message: str, *, page: int | None = None, context: str = ""):
        location = path.name
        if page is not None:
            location += f", sivu {page}"
        detail = f"{location}: {message}"
        if context:
            detail += f"\n  Konteksti: {context}"
        super().__init__(detail)
        self.path = path
        self.page = page


@dataclass
class LineItem:
    description: str
    category: str
    action: str
    quantity: int
    unit_price: Decimal
    amount_excl_vat: Decimal
    service_start: date | None
    service_end: date | None
    resource_id: str | None
    hostname: str | None
    commitment: str | None
    page: int
    source_context: str = field(repr=False)


@dataclass
class Invoice:
    source_file: str
    invoice_id: str
    bill_type: str
    issue_date: date
    order_number: str
    customer_id: str
    currency: str
    total_excl_vat: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total_incl_vat: Decimal
    items: list[LineItem]


def _money(value: str) -> Decimal:
    try:
        return Decimal(value.replace("€", "").replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"virheellinen rahamäärä {value!r}") from exc


def _date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"virheellinen päivämäärä {value!r}")


def _search(pattern: str, text: str, path: Path, label: str, flags: int = 0) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    if not match:
        raise ParseError(path, f"pakollinen kenttä puuttuu: {label}")
    return match


def _is_footer(line: str) -> bool:
    return bool(
        line.startswith((
            "OVH HOSTING LIMITED",
            "Registration number:",
            "Tel:",
            "Website:",
            "Invoice IE",
            "Invoice ie",
            "Page ",
        ))
        or line.startswith("- VAT number")
    )


def _is_category(line: str) -> bool:
    return line == "Dedicated Server(s)" or line == "Other" or line.startswith("Other ")


def _header_events(
    path: Path,
    lines: list[str],
    pages: list[int],
) -> dict[int, tuple[str | None, str]]:
    events: dict[int, tuple[str | None, str]] = {}
    for idx, line in enumerate(lines):
        if line != "Description" or idx + 1 >= len(lines) or lines[idx + 1] != "Quantity":
            continue
        action = lines[idx - 1] if idx else ""
        if action not in KNOWN_ACTIONS:
            raise ParseError(
                path,
                f"tuntematon laskurivin toiminto: {action or '<tyhjä>'}",
                page=pages[idx],
                context=" | ".join(lines[max(0, idx - 3):idx + 4]),
            )
        candidate = lines[idx - 2] if idx >= 2 else ""
        category: str | None = None
        if candidate in KNOWN_CATEGORIES:
            category = candidate
        elif _is_category(candidate):
            raise ParseError(
                path,
                f"tuntematon laskuosio: {candidate}",
                page=pages[idx],
                context=" | ".join(lines[max(0, idx - 3):idx + 4]),
            )
        elif not (MONEY_RE.match(candidate) or _is_footer(candidate)):
            raise ParseError(
                path,
                f"laskutaulukon osiota ei tunnistettu: {candidate or '<tyhjä>'}",
                page=pages[idx],
                context=" | ".join(lines[max(0, idx - 3):idx + 4]),
            )
        events[idx] = (category, action)
    return events


def _clean_description(parts: list[str]) -> str:
    ignored = {
        "Description", "Quantity", "Unit", "price", "Price", "excl.", "VAT", "(vat", "excl.)",
        "SUB", "-", "TOTAL", "Subscription", "Solutions", "Setup", "Special",
    }
    cleaned: list[str] = []
    for part in parts:
        if part in ignored or _is_footer(part) or _is_category(part) or MONEY_RE.match(part):
            continue
        if part.startswith(("From ", "Commitment end date", "No commitment")):
            break
        if cleaned and cleaned[-1].endswith("-") and re.match(r"[A-Z0-9]", part):
            cleaned[-1] += part
        else:
            cleaned.append(part)
    value = " ".join(cleaned)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _extract_hostname(block: list[str], resource: str | None) -> str | None:
    candidates: list[str] = []
    for line in block:
        for match in HOST_RE.findall(line):
            value = match.rstrip(".")
            if resource and value.lower() in resource.lower():
                continue
            if value.lower().endswith(("ovhcloud.com", "ovh.ie")):
                continue
            candidates.append(value)
    return candidates[-1] if candidates else None


def _validate_item_metadata(path: Path, page: int, parts: list[str]) -> None:
    known_patterns = (
        re.compile(rf"^From\s+{DATE_RE}\s+to\s+{DATE_RE}$", re.I),
        re.compile(r"^No commitment$", re.I),
        re.compile(rf"^Commitment end date\s*:\s*{DATE_RE}$", re.I),
        re.compile(r"^ns\d+\.ip-[\d-]*$", re.I),
        re.compile(r"^[\d-]+\.eu$", re.I),
        re.compile(r"^ip-\d{1,3}(?:\.\d{1,3}){3}$", re.I),
        re.compile(r"^pn-\d+$", re.I),
    )
    for part in parts:
        if _is_footer(part) or HOST_RE.fullmatch(part) or any(pattern.fullmatch(part) for pattern in known_patterns):
            continue
        raise ParseError(
            path,
            f"tuntematon laskurivin kenttä tai metadata: {part}",
            page=page,
            context=" | ".join(parts),
        )


def _parse_items(path: Path, page_lines: list[list[str]]) -> list[LineItem]:
    lines: list[str] = []
    pages: list[int] = []
    for page_number, page in enumerate(page_lines, start=1):
        for line in page:
            lines.append(line)
            pages.append(page_number)

    events = _header_events(path, lines, pages)
    current_category: str | None = None
    current_action: str | None = None
    last_row_end = 0
    last_header = 0
    items: list[LineItem] = []

    idx = 0
    while idx < len(lines):
        if idx in events:
            category, action = events[idx]
            if category is not None:
                current_category = category
            current_action = action
            last_header = idx + 1

        if (
            re.fullmatch(r"\d+", lines[idx])
            and idx + 2 < len(lines)
            and MONEY_RE.match(lines[idx + 1])
            and MONEY_RE.match(lines[idx + 2])
        ):
            start = max(last_row_end, last_header)
            block = lines[start:idx]
            # Remove subtotal material which can precede a fresh table header.
            if "TOTAL" in block:
                pos = len(block) - 1 - block[::-1].index("TOTAL")
                if pos + 1 < len(block) and MONEY_RE.match(block[pos + 1]):
                    block = block[pos + 2:]

            compact = "".join(block)
            spaced = " ".join(block)
            resource_match = RESOURCE_RE.search(compact)
            resource = resource_match.group(0).lower() if resource_match else None
            ip_matches = IP_RE.findall(spaced)
            if resource is None and ip_matches:
                resource = f"ip-{ip_matches[-1]}".lower()
            vrack_match = VRACK_RE.search(spaced)
            if resource is None and vrack_match:
                resource = vrack_match.group(0).lower()

            period = re.search(rf"From\s+({DATE_RE})\s+to\s+({DATE_RE})", spaced, re.I)
            service_start = _date(period.group(1)) if period else None
            service_end = _date(period.group(2)) if period else None
            commitment_match = re.search(r"Commitment end date\s*:\s*([^\s]+)|\bNo commitment\b", spaced, re.I)
            commitment = commitment_match.group(0) if commitment_match else None

            # The item description always precedes its period/resource metadata.
            desc_parts: list[str] = []
            metadata_start = len(block)
            for position, part in enumerate(block):
                joined_so_far = "".join(desc_parts + [part])
                if part.startswith(("From ", "Commitment end date", "No commitment")):
                    metadata_start = position
                    break
                if (
                    RESOURCE_RE.search(joined_so_far)
                    or IP_RE.search(part)
                    or VRACK_RE.search(part)
                    or re.match(r"^(?:ns\d+\.ip-|ip-\d|pn-\d)", part, re.I)
                ):
                    metadata_start = position
                    break
                desc_parts.append(part)
            description = _clean_description(desc_parts)
            if not description:
                context = " | ".join(block[-12:] + lines[idx:idx + 3])
                raise ParseError(path, "laskurivin kuvausta ei voitu tunnistaa", page=pages[idx], context=context)
            if current_category is None or current_action is None:
                context = " | ".join(block[-12:] + lines[idx:idx + 3])
                raise ParseError(path, "laskurivin osiota ei voitu tunnistaa", page=pages[idx], context=context)
            _validate_item_metadata(path, pages[idx], block[metadata_start:])
            if resource is None:
                context = " | ".join(block[-12:] + lines[idx:idx + 3])
                raise ParseError(
                    path,
                    "laskurivin resurssityyppiä tai resurssitunnusta ei tunnistettu",
                    page=pages[idx],
                    context=context,
                )

            quantity = int(lines[idx])
            unit_price = _money(lines[idx + 1])
            amount = _money(lines[idx + 2])
            if unit_price * quantity != amount:
                raise ParseError(
                    path,
                    f"määrä × yksikköhinta ei vastaa rivisummaa ({quantity} × {unit_price} ≠ {amount})",
                    page=pages[idx],
                    context=description,
                )
            if service_start and service_end and service_end < service_start:
                raise ParseError(path, "palvelujakson loppu on ennen alkua", page=pages[idx], context=description)

            items.append(LineItem(
                description=description,
                category=current_category,
                action=current_action,
                quantity=quantity,
                unit_price=unit_price,
                amount_excl_vat=amount,
                service_start=service_start,
                service_end=service_end,
                resource_id=resource,
                hostname=_extract_hostname(block, resource),
                commitment=commitment,
                page=pages[idx],
                source_context=" | ".join(block),
            ))
            last_row_end = idx + 3
            idx += 3
            continue
        idx += 1
    return items


def parse_invoice(path: Path) -> Invoice:
    try:
        reader = PdfReader(path)
    except Exception as exc:
        raise ParseError(path, f"PDF-tiedostoa ei voitu avata: {exc}") from exc
    if reader.is_encrypted:
        raise ParseError(path, "PDF on salattu")

    page_texts: list[str] = []
    page_lines: list[list[str]] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise ParseError(path, f"tekstikerroksen lukeminen epäonnistui: {exc}", page=number) from exc
        if not text.strip():
            raise ParseError(path, "PDF-sivulla ei ole luettavaa tekstikerrosta", page=number)
        page_texts.append(text)
        page_lines.append([line.strip() for line in text.splitlines() if line.strip()])
    text = "\n".join(page_texts)

    invoice_id = _search(
        r"(?:Bill reference|Paid Invoice Reference):\s*\n?\s*(IE\d+)",
        text,
        path,
        "laskutunnus",
        re.I,
    ).group(1).upper()
    bill_type = _search(r"Bill type:\s*\n?\s*([^\n]+)", text, path, "laskutyyppi", re.I).group(1).strip()
    issue_raw = _search(rf"Issue date\s*:?\s*\n?\s*({DATE_RE})", text, path, "laskun päivä", re.I).group(1)
    order_number = _search(r"Order Number:\s*\n?\s*(\d+)", text, path, "tilausnumero", re.I).group(1)
    customer_id = _search(r"Customer ID:\s*\n?\s*([^\n]+)", text, path, "asiakastunnus", re.I).group(1).strip()
    total_excl = _money(_search(r"Invoice total ex\. VAT\s*\n?\s*(€\s*-?[\d,.]+)", text, path, "veroton summa", re.I).group(1))
    vat_match = _search(r"(?:VAT|TVA)\s*\((\d+(?:\.\d+)?)%+\)\s*\n?\s*(€\s*-?[\d,.]+)", text, path, "ALV", re.I)
    vat_rate = Decimal(vat_match.group(1))
    vat_amount = _money(vat_match.group(2))
    total_incl = _money(_search(r"Total Incl\. VAT\s*\n?\s*(€\s*-?[\d,.]+)", text, path, "verollinen summa", re.I).group(1))

    items = _parse_items(path, page_lines)
    if not items and total_excl != 0:
        raise ParseError(path, "PDF:stä ei löytynyt laskurivejä")
    item_total = sum((item.amount_excl_vat for item in items), Decimal("0"))
    if item_total != total_excl:
        raise ParseError(
            path,
            f"laskurivien veroton summa ei täsmää (rivit {item_total:.2f} €, lasku {total_excl:.2f} €)",
        )
    if total_excl + vat_amount != total_incl:
        raise ParseError(
            path,
            f"loppusumma ei täsmää ({total_excl:.2f} € + {vat_amount:.2f} € ≠ {total_incl:.2f} €)",
        )

    return Invoice(
        source_file=path.name,
        invoice_id=invoice_id,
        bill_type=bill_type,
        issue_date=_date(issue_raw),
        order_number=order_number,
        customer_id=customer_id,
        currency="EUR",
        total_excl_vat=total_excl,
        vat_rate=vat_rate,
        vat_amount=vat_amount,
        total_incl_vat=total_incl,
        items=items,
    )


INVOICE_COMPARE_FIELDS = (
    "invoice_id", "bill_type", "issue_date", "order_number", "customer_id", "currency",
    "total_excl_vat", "vat_rate", "vat_amount", "total_incl_vat",
)
ITEM_COMPARE_FIELDS = (
    "description", "category", "action", "quantity", "unit_price", "amount_excl_vat",
    "service_start", "service_end", "resource_id", "hostname", "commitment",
)


def _invoice_signature(invoice: Invoice) -> tuple:
    header = tuple(getattr(invoice, field) for field in INVOICE_COMPARE_FIELDS)
    items = tuple(tuple(getattr(item, field) for field in ITEM_COMPARE_FIELDS) for item in invoice.items)
    return header, items


def _invoice_differences(first: Invoice, second: Invoice) -> list[str]:
    differences: list[str] = []
    for field in INVOICE_COMPARE_FIELDS:
        left, right = getattr(first, field), getattr(second, field)
        if left != right:
            differences.append(f"{field}: {left!s} ≠ {right!s}")
    if len(first.items) != len(second.items):
        differences.append(f"laskurivien määrä: {len(first.items)} ≠ {len(second.items)}")
    for index, (left_item, right_item) in enumerate(zip(first.items, second.items), start=1):
        for field in ITEM_COMPARE_FIELDS:
            left, right = getattr(left_item, field), getattr(right_item, field)
            if left != right:
                differences.append(f"rivi {index}, {field}: {left!s} ≠ {right!s}")
                if len(differences) >= 8:
                    return differences
    return differences


def parse_directory(input_dir: Path, on_warning: Callable[[str], None] | None = None) -> list[Invoice]:
    paths = sorted(
        (path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: path.relative_to(input_dir).as_posix().lower(),
    )
    if not paths:
        raise RuntimeError(f"Hakemistosta {input_dir} ei löytynyt PDF-tiedostoja.")
    invoices_by_id: dict[str, Invoice] = {}
    for path in paths:
        invoice = parse_invoice(path)
        invoice.source_file = path.relative_to(input_dir).as_posix()
        previous = invoices_by_id.get(invoice.invoice_id)
        if previous is None:
            invoices_by_id[invoice.invoice_id] = invoice
            continue
        if _invoice_signature(previous) == _invoice_signature(invoice):
            if on_warning is not None:
                on_warning(
                    f"lasku {invoice.invoice_id} on sisällöltään sama tiedostoissa "
                    f"{previous.source_file} ja {invoice.source_file}; {invoice.source_file} ohitetaan"
                )
            continue
        differences = _invoice_differences(previous, invoice)
        difference_text = "; ".join(differences) if differences else "tuntematon sisältöero"
        raise RuntimeError(
            f"Laskunumerolla {invoice.invoice_id} löytyi eri sisältöiset PDF:t "
            f"{previous.source_file} ja {invoice.source_file}. Erot: {difference_text}"
        )
    return sorted(invoices_by_id.values(), key=lambda invoice: (invoice.issue_date, invoice.invoice_id))
