import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import EiirRecord

logger = logging.getLogger(__name__)

BASE_URL = "https://www.insolvencydirect.bis.gov.uk"

IVA_KEYWORDS = ("individual voluntary arrangement", "iva")

DOB_PATTERNS = [
    "%Y-%m-%d",
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %m %Y",
    "%d %B %Y", "%d %b %Y",
    "%B %d %Y", "%b %d %Y",
]


def normalise_dob(raw: str) -> Optional[str]:
    """
    Normalise a DOB string to ISO 'YYYY-MM-DD'. Returns None if no recognised
    date can be extracted. Tolerates extra surrounding text by extracting the
    first date-like substring before parsing.
    """
    if not raw:
        return None
    text = raw.strip()

    # Extract a date-shaped substring if there's surrounding text
    m = re.search(r"\b\d{1,2}[\s/.-]+(?:\d{1,2}|[A-Za-z]+)[\s/.-]+\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b", text)
    if m:
        text = m.group(0)
    text = re.sub(r"\s+", " ", text).strip()

    for fmt in DOB_PATTERNS:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 1900)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def is_iva(insolvency_type: str) -> bool:
    """True if the type string indicates an Individual Voluntary Arrangement."""
    if not insolvency_type:
        return False
    t = insolvency_type.lower()
    return any(k in t for k in IVA_KEYWORDS)


def parse_results(html: str) -> list[EiirRecord]:
    """
    Parse the EIIR search-results page into EiirRecord rows.

    The page uses the GOV.UK Design System, so results typically render as a
    `<table class="govuk-table">`. We try the table first; if no rows are
    found we fall back to scanning for result links so layout tweaks on the
    live site don't silently break the scraper.
    """
    soup = BeautifulSoup(html, "html.parser")
    records: list[EiirRecord] = []

    table = soup.select_one("table.govuk-table") or soup.select_one("table")
    if table:
        headers = [th.get_text(strip=True).lower() for th in table.select("thead th")]
        if not headers:
            first_row = table.select_one("tr")
            if first_row:
                headers = [c.get_text(strip=True).lower() for c in first_row.select("th")]

        body_rows = table.select("tbody tr") or table.select("tr")
        for row in body_rows:
            cells = row.find_all(["td"])
            if not cells:
                continue

            cell_text = [c.get_text(" ", strip=True) for c in cells]
            link_el = row.find("a", href=True)
            detail_url = urljoin(BASE_URL, link_el["href"]) if link_el else ""

            record = _row_to_record(headers, cells, cell_text, detail_url)
            if record.name or record.case_number:
                records.append(record)

    if not records:
        # Fallback: any anchor that points at a detail page
        for a in soup.select("a[href*='/eiir/']"):
            href = a.get("href", "")
            if "search" in href.lower() or "home" in href.lower():
                continue
            text = a.get_text(" ", strip=True)
            if not text:
                continue
            records.append(EiirRecord(name=text, detail_url=urljoin(BASE_URL, href)))

    logger.info("Parsed %d EIIR records", len(records))
    return records


def _row_to_record(headers: list[str], cells, cell_text: list[str], detail_url: str) -> EiirRecord:
    """Map a results-table row to an EiirRecord using header names when available."""
    record = EiirRecord(detail_url=detail_url)

    if headers and len(headers) == len(cell_text):
        for header, value in zip(headers, cell_text):
            _assign_by_header(record, header, value)
    else:
        # Header-less fallback: best-effort positional mapping.
        if cell_text:
            record.name = cell_text[0]
        if len(cell_text) > 1:
            record.insolvency_type = cell_text[1]
        if len(cell_text) > 2:
            record.court = cell_text[2]
        if len(cell_text) > 3:
            record.case_number = cell_text[3]
        if len(cell_text) > 4:
            record.date_of_order = cell_text[4]
        if len(cell_text) > 5:
            record.status = cell_text[5]

    return record


def _assign_by_header(record: EiirRecord, header: str, value: str) -> None:
    h = header.lower()
    if "name" in h:
        record.name = value
    elif "type" in h:
        record.insolvency_type = value
    elif "court" in h:
        record.court = value
    elif "case" in h or "number" in h:
        record.case_number = value
    elif "date" in h:
        record.date_of_order = value
    elif "status" in h:
        record.status = value


def parse_detail(html: str) -> dict:
    """
    Parse an EIIR detail page into a dict of field name -> value.
    Tries dl.govuk-summary-list dt/dd pairs first, falls back to plain
    key/value tables, and finally to a "Label: value" line scan so we
    capture whatever the live page is actually rendering.
    """
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}

    for dl in soup.select("dl.govuk-summary-list, dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            key = dt.get_text(" ", strip=True)
            value = dd.get_text(" ", strip=True)
            if key:
                fields[key] = value

    if not fields:
        for row in soup.select("table tr"):
            row_cells = row.find_all(["th", "td"])
            if len(row_cells) >= 2:
                key = row_cells[0].get_text(" ", strip=True)
                value = row_cells[1].get_text(" ", strip=True)
                if key:
                    fields[key] = value

    if not fields:
        body_text = soup.get_text("\n", strip=True)
        for line in body_text.splitlines():
            m = re.match(r"^([A-Za-z][A-Za-z /()'’-]{2,60})\s*[:\-]\s*(.+)$", line)
            if m:
                key, value = m.group(1).strip(), m.group(2).strip()
                if key and value and key not in fields:
                    fields[key] = value

    return fields


def extract_key_fields(detail_fields: dict) -> dict:
    """
    Reduce a raw detail-page dict to the canonical fields the matcher needs.
    Returns: {dob: str|None (ISO), insolvency_type: str, court: str,
              case_number: str, status: str, last_known_address: str,
              insolvency_practitioner: str}.
    """
    out = {
        "dob": None,
        "insolvency_type": "",
        "court": "",
        "case_number": "",
        "status": "",
        "last_known_address": "",
        "insolvency_practitioner": "",
    }
    for key, value in detail_fields.items():
        k = key.lower()
        if "birth" in k:
            out["dob"] = normalise_dob(value)
        elif "type" in k and "case" not in k:
            out["insolvency_type"] = value
        elif "court" in k:
            out["court"] = value
        elif "case" in k or "number" in k:
            out["case_number"] = value
        elif "status" in k:
            out["status"] = value
        elif "address" in k:
            out["last_known_address"] = value
        elif "practitioner" in k or "trustee" in k or "supervisor" in k:
            out["insolvency_practitioner"] = value
    return out


def parse_no_results_message(html: str) -> Optional[str]:
    """Return the user-facing 'no results' message if present, else None."""
    soup = BeautifulSoup(html, "html.parser")
    for selector in [
        ".govuk-error-summary",
        ".govuk-error-message",
        ".govuk-notification-banner",
        ".govuk-inset-text",
    ]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(" ", strip=True)
            if text:
                return text

    m = re.search(r"(no\s+(matches|results|records)\s+found|no\s+entries)", html, re.IGNORECASE)
    return m.group(0) if m else None
