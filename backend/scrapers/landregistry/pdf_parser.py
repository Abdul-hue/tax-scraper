"""
Land Registry PDF Parser — built against real OC1REG and OC1TP PDF output.
pip install pdfplumber
"""
from __future__ import annotations
import re
from typing import List


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_text(pdf_path: str) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("Run: pip install pdfplumber")
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts)


def _clean(s: str) -> str:
    """Collapse whitespace."""
    return re.sub(r"\s+", " ", s or "").strip()


def _clean_b_body(raw: str) -> str:
    """Remove page-break artefacts that Land Registry injects into the B register."""
    s = re.sub(r"\d+ of \d+", "", raw)
    s = re.sub(r"Title number [A-Z0-9]+", "", s)
    s = re.sub(r"B: Proprietorship Register continued", "", s)
    return s


# ── section splitters ─────────────────────────────────────────────────────────

def _split_sections(text: str):
    """Return (a_body, b_body, c_body) raw strings."""
    a_m = re.search(r"A: Property Register", text)
    b_m = re.search(r"B: Proprietorship Register", text)
    c_m = re.search(r"C: Charges Register", text)
    end_m = re.search(r"End of register", text)

    if not (a_m and b_m and c_m):
        return "", "", ""

    a_body = text[a_m.end(): b_m.start()]
    b_body = text[b_m.end(): c_m.start()]
    c_body = text[c_m.end(): end_m.start()] if end_m else text[c_m.end():]
    return a_body, b_body, c_body


# ── A register ────────────────────────────────────────────────────────────────

def _parse_a(body: str) -> dict:
    result = {}

    # County : District  e.g. "MERSEYSIDE : LIVERPOOL"
    m = re.search(r"([A-Z][A-Z\s]+?)\s*:\s*([A-Z][A-Z\s]+?)(?:\n|$)", body)
    result["county"]   = _clean(m.group(1)) if m else ""
    result["district"] = _clean(m.group(2)) if m else ""

    # Tenure
    m = re.search(r"\b(Freehold|Leasehold)\b", body, re.IGNORECASE)
    result["tenure"] = m.group(1).capitalize() if m else ""

    # Property address  — "being <address> (<postcode>)"
    m = re.search(r"being\s+(.+?(?:\([A-Z0-9 ]+\)|\w{2,4}\s*\d[A-Z0-9]{2}[A-Z]?))\.", body, re.DOTALL)
    if m:
        result["property_address"] = _clean(m.group(1))
    else:
        # fallback: first numbered entry line
        m2 = re.search(r"1\s+\(\d{2}\.\d{2}\.\d{4}\)\s+(.+?)(?=\n2\s+\(|\Z)", body, re.DOTALL)
        result["property_address"] = _clean(m2.group(1)) if m2 else ""

    # Lease details
    result["lease_date"]    = ""
    result["lease_term"]    = ""
    result["lease_rent"]    = ""
    result["lease_parties"] = []

    date_m = re.search(r"Date\s*:\s*(.+)", body)
    if date_m:
        result["lease_date"] = _clean(date_m.group(1))

    term_m = re.search(r"Term\s*:\s*(.+)", body)
    if term_m:
        result["lease_term"] = _clean(term_m.group(1))

    rent_m = re.search(r"Rent\s*:\s*(.+)", body)
    if rent_m:
        result["lease_rent"] = _clean(rent_m.group(1))

    result["lease_parties"] = re.findall(r"\(\d+\)\s+(.+)", body)
    result["raw"] = _clean(body)
    return result


# ── B register ────────────────────────────────────────────────────────────────

def _parse_b(body: str) -> dict:
    body = _clean_b_body(body)
    result = {}

    # Title class  e.g. "Title absolute"
    m = re.search(r"(Title absolute|Title good leasehold|Qualified title|Possessory title)", body, re.IGNORECASE)
    result["title_class"] = _clean(m.group(1)) if m else ""

    # Proprietor(s) — stop at next numbered entry
    m = re.search(r"PROPRIETOR:\s+(.+?)(?=\n\d+\s+\(|\Z)", body, re.DOTALL)
    result["proprietor"] = _clean(m.group(1)) if m else ""

    # Price paid + date
    m = re.search(r"price stated to have been paid on (.+?) was\s+(£[\d,]+)", body)
    result["price_paid"]      = m.group(2) if m else ""
    result["price_paid_date"] = _clean(m.group(1)) if m else ""

    # All RESTRICTIONs
    restrictions: List[str] = []
    for rm in re.finditer(r"RESTRICTION:\s+(.+?)(?=\n\d+\s+\(|\Z)", body, re.DOTALL):
        restrictions.append(_clean(rm.group(1)))
    result["restrictions"] = restrictions

    result["raw"] = _clean(body)
    return result


# ── C register ────────────────────────────────────────────────────────────────

def _parse_c(body: str) -> dict:
    """
    Each charge spans two numbered entries:
      Entry N   — "REGISTERED CHARGE dated DD Month YYYY."
      Entry N+1 — "Proprietor: LENDER NAME ... of ADDRESS"
    We pair them up.
    """
    entries = re.findall(
        r"\d+\s+\(\d{2}\.\d{2}\.\d{4}\)\s+(.+?)(?=\n\d+\s+\(|\Z)",
        body,
        re.DOTALL,
    )
    entries = [_clean(e) for e in entries]

    charges = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        charge_m = re.search(r"REGISTERED CHARGE dated (\d+\s+\w+\s+\d{4})", entry)
        if charge_m:
            charge = {"charge_date": charge_m.group(1), "lender": "", "lender_address": "", "company_reg": ""}
            # next entry has the lender
            if i + 1 < len(entries):
                next_e = entries[i + 1]
                lender_m  = re.search(r"Proprietor:\s+(.+?)(?:\s+\(Co\.|\s+of\b)", next_e)
                reg_m     = re.search(r"Co\. Regn\. No\.\s+([\d]+)", next_e)
                addr_m    = re.search(r"\bof\s+(.+)", next_e)
                charge["lender"]         = lender_m.group(1).strip() if lender_m else ""
                charge["company_reg"]    = reg_m.group(1) if reg_m else ""
                charge["lender_address"] = addr_m.group(1).strip() if addr_m else ""
                i += 2
            else:
                i += 1
            charges.append(charge)
        else:
            i += 1

    return {
        "charge_count": len(charges),
        "charges": charges,
        "raw": _clean(body),
    }


# ── public API ────────────────────────────────────────────────────────────────

def parse_register_pdf(pdf_path: str) -> dict:
    """Parse an OC1REG (Register) PDF into structured JSON."""
    try:
        text = _get_text(pdf_path)
    except Exception as e:
        return {"parse_error": str(e)}

    try:
        # Top-level fields
        tn_m = re.search(r"Title number\s+([A-Z]{1,3}\d+)", text)
        ed_m = re.search(r"Edition date\s+([\d\.]+)", text)
        issued_m = re.search(r"Issued on\s+(.+?)\.", text)
        search_date_m = re.search(r"entries on the register of title on\s+(.+?)\.", text, re.DOTALL)

        a_body, b_body, c_body = _split_sections(text)

        return {
            "document_type":   "register",
            "title_number":    tn_m.group(1) if tn_m else "",
            "edition_date":    ed_m.group(1) if ed_m else "",
            "issued_on":       _clean(issued_m.group(1)) if issued_m else "",
            "search_date":     _clean(search_date_m.group(1)) if search_date_m else "",
            "a_register":      _parse_a(a_body),
            "b_register":      _parse_b(b_body),
            "c_register":      _parse_c(c_body),
            "raw_text":        text,
            "parse_error":     None,
        }
    except Exception as e:
        return {"parse_error": str(e), "raw_text": text}


def parse_title_plan_pdf(pdf_path: str) -> dict:
    """Parse an OC1TP (Title Plan) PDF. The map itself is a raster image — only metadata is extractable."""
    try:
        text = _get_text(pdf_path)
    except Exception as e:
        return {"parse_error": str(e)}

    try:
        tn_m      = re.search(r"Title number\s+([A-Z]{1,3}\d+)", text)
        issued_m  = re.search(r"issued on\s+(.+?)\s+shows", text, re.IGNORECASE)
        office_m  = re.search(r"dealt with by\s+(.+?)\s*\.", text, re.IGNORECASE)

        # Page 2 is the map image — we cannot extract coordinates or boundaries from it
        return {
            "document_type":     "title_plan",
            "title_number":      tn_m.group(1) if tn_m else "",
            "issued_on":         _clean(issued_m.group(1)) if issued_m else "",
            "land_registry_office": _clean(office_m.group(1)) if office_m else "",
            "map_note":          "Title Plan page 2 is a raster image. Boundary coordinates are not extractable via PDF text parsing.",
            "raw_text":          text,
            "parse_error":       None,
        }
    except Exception as e:
        return {"parse_error": str(e), "raw_text": text}


def parse_pdf(pdf_path: str, doc_type: str = "register") -> dict:
    """Main entrypoint. doc_type: 'register' or 'title_plan'"""
    if doc_type == "title_plan":
        return parse_title_plan_pdf(pdf_path)
    return parse_register_pdf(pdf_path)