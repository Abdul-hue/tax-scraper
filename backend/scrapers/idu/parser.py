from __future__ import annotations

import re

from bs4 import BeautifulSoup
from typing import List, Dict, Tuple
from .models import SummaryItem, PEPEntry
import logging

logger = logging.getLogger(__name__)


def parse_verdict(soup: BeautifulSoup) -> Tuple[str, str]:
    """Return (verdict, score)."""
    verdict_el = soup.select_one("#result-summary-status")
    score_el = soup.select_one("#result-score")
    verdict = verdict_el.get_text(strip=True) if verdict_el else ""
    score = score_el.get_text(strip=True) if score_el else ""
    return verdict, score


def parse_summary_table(soup: BeautifulSoup) -> List[SummaryItem]:
    """Parse the three summary columns into SummaryItem list."""
    cols = [
        ("Address/Identity", ".res-summary-column-left"),
        ("Alerts", ".res-summary-column-middle"),
        ("Financial", ".res-summary-column-right"),
    ]
    items: List[SummaryItem] = []
    for category, sel in cols:
        col = soup.select_one(sel)
        if not col:
            continue
        for div in col.select("div"):
            classes = " ".join(div.get("class", []))
            status = "not_checked"
            if "button-30px-green" in classes:
                status = "pass"
            elif "button-30px-red" in classes:
                status = "alert"
            elif "button-30px-pink" in classes:
                status = "not_checked"
            elif "button-30px-amber" in classes:
                status = "alert"
            # extract label text without icon characters
            label = div.get_text(" ", strip=True)
            label = label.replace("✔", "").replace("✗", "").replace("⚠", "").strip()
            if label:
                items.append(SummaryItem(category=category, label=label, status=status))
    return items


def _parse_rows(container) -> Dict[str, object]:
    out: Dict[str, object] = {}
    if not container:
        return out
    for row in container.select(".res-profile-row"):
        label_el = row.select_one(".res-profile-item")
        val_el = row.select_one(".res-profile-val-norm")
        if not label_el or not val_el:
            continue
        label = label_el.get_text(strip=True).rstrip(":")
        # detect icon
        icon = row.select_one(".res-profile-val-icon .icon-verified")
        status = "verified" if icon else "not_verified"
        # handle lists inside
        if val_el.find_all("li"):
            vals = [li.get_text(strip=True) for li in val_el.select("li")]
            value = vals
        else:
            text = val_el.get_text(" ", strip=True)
            # LexisNexis phone match may be comma-separated
            if "," in text and any(ch.isdigit() for ch in text):
                value = [p.strip() for p in text.split(",") if p.strip()]
            else:
                value = text
        out[label] = {"value": value, "status": status}
    return out


def parse_address_section(soup: BeautifulSoup) -> Dict:
    container = soup.select_one("#res-address-body")
    return _parse_rows(container)


def parse_credit_active(soup: BeautifulSoup) -> Dict:
    container = soup.select_one("#res-creditactive-body")
    return _parse_rows(container)


def parse_dob_verification(soup: BeautifulSoup) -> Dict:
    container = soup.select_one("#res-dob-body")
    return _parse_rows(container)


#: The two sub-headings inside TraceSmart's "PEP & Sanction" section.
_PEP_SUBSECTIONS = {"pep": "pep", "peps": "pep", "sanction list": "sanction",
                    "sanctions list": "sanction", "sanctions": "sanction"}
#: A match block's labels -> PEPEntry fields.
_PEP_LABELS = {
    "match score": "match_score", "score": "match_score", "name": "name",
    "aliases": "aliases", "alias": "aliases", "last updated": "last_updated",
    "addresses": "addresses", "address": "addresses", "country": "country",
    "countries": "country", "position": "position", "positions": "position",
    "reason": "reason", "reasons": "reason",
}
_PEP_LIST_FIELDS = {"aliases", "addresses"}
#: Footer / navigation lines inside the section, never part of a match.
_PEP_NOISE = ("powered by", "back to top", "lexisnexis")


def _pep_norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9& ]+", " ", text.lower())).strip()


def parse_pep_sanctions(soup: BeautifulSoup):
    """(entries, sanction_result) from the "PEP & Sanction" section.

    ⚠️ TWO SUB-SECTIONS, EACH WITH ITS OWN WorldCompliance LINE:

        PEP            WorldCompliance(tm): No matches found | the match blocks
        Sanction List  WorldCompliance(tm): No matches found | the match blocks

    Read in page order from the section's TEXT, split at those sub-headings,
    so the result does not hang on CSS classes. The class-based reader
    (`_parse_pep_sanctions_by_class`) dropped every match on a real PEP hit
    and took `sanction_result` from the FIRST WorldCompliance line -- the PEP
    one -- so a sanctions hit behind a clean PEP line read as "No matches
    found". It is kept only for a layout with neither sub-heading.

    Each entry carries `list_type` ("pep" / "sanction"). `sanction_result` is
    the Sanction List's own WorldCompliance line, or a summary of its matches.
    """
    container = _pep_section(soup)
    if container is None:
        return [], ""
    lines = []
    for ln in (x.strip() for x in container.get_text("\n").split("\n")):
        if not ln:
            continue
        # "WorldCompliance" + "™" + ":" arrive as separate text nodes when the
        # mark is its own element -- a line of symbols only joins the last one.
        if lines and not _pep_norm(ln):
            lines[-1] += ln
        else:
            lines.append(ln)
    if not any(_pep_norm(ln) in _PEP_SUBSECTIONS for ln in lines):
        return _parse_pep_sanctions_by_class(container)

    entries: List[PEPEntry] = []
    status: Dict[str, str] = {}
    section = None
    entry = None
    pending = None          # the field the next value line belongs to

    def flush():
        nonlocal entry
        if entry is not None and (entry.name or entry.match_score or entry.reason or entry.position):
            entries.append(entry)
        entry = None

    for line in lines:
        norm = _pep_norm(line)
        if norm in _PEP_SUBSECTIONS:
            flush()
            section, pending = _PEP_SUBSECTIONS[norm], None
            continue
        # The footer's bare "WorldCompliance(tm)" -- the LABEL has a colon.
        footer_mark = ":" not in line and norm in ("worldcompliance", "worldcompliance tm")
        if section is None or norm.startswith(_PEP_NOISE) or footer_mark:
            continue
        label, _, rest = line.partition(":")
        key = _pep_norm(label) if _ else ""
        if key.startswith("worldcompliance"):
            pending = "__status__"
            if rest.strip():
                status[section] = rest.strip()
                pending = None
            continue
        if key in _PEP_LABELS:
            field_name = _PEP_LABELS[key]
            if entry is None or (field_name in ("match_score", "name") and getattr(entry, field_name)):
                flush()
                entry = PEPEntry(list_type=section)
            pending = field_name
            line = rest.strip()
            if not line:
                continue
        elif _ and not rest.strip() and len(key) < 40:
            pending = None                      # a label this reader doesn't know
            continue
        if pending == "__status__":
            status[section] = line
            pending = None
        elif pending and entry is not None:
            if pending in _PEP_LIST_FIELDS:
                getattr(entry, pending).append(line)
            else:
                current = getattr(entry, pending)
                setattr(entry, pending, f"{current} {line}".strip())
    flush()

    sanctions = [e for e in entries if e.list_type == "sanction"]
    if sanctions:
        sanction_result = f"{len(sanctions)} match(es): " + "; ".join(
            f"{e.name or 'unnamed'}" + (f" ({e.reason})" if e.reason else "") for e in sanctions)
    else:
        sanction_result = status.get("sanction", "")
    return entries, sanction_result


def _pep_section(soup: BeautifulSoup):
    """The PEP & Sanction section body: `#res-sanction-body`, or the block
    that follows a "PEP & Sanction" heading."""
    container = soup.select_one("#res-sanction-body")
    if container is not None:
        return container
    for heading in soup.find_all(string=re.compile(r"PEP\s*&\s*Sanction", re.I)):
        parent = heading.find_parent(class_=re.compile("heading"))
        if parent is not None:
            body = parent.find_next_sibling()
            if body is not None:
                return body
    return None


def _parse_pep_sanctions_by_class(container):
    """The original class-based reader -- only for a layout without the PEP /
    Sanction List sub-headings."""
    entries: List[PEPEntry] = []
    sanction_result = ""
    rows = [r for r in container.select(".res-profile-row")]
    for row in rows:
        # skip bottom-row if present
        if "bottom-row" in " ".join(row.get("class", [])):
            continue
        score_el = row.select_one(".res-sanction-row-score .res-profile-val-norm")
        name_el = row.select_one(".res-sanction-item-name .res-profile-val-norm")
        aliases = [li.get_text(strip=True) for li in row.select(".res-sanction-item-aliases .res-profile-val-norm li")]
        last_updated = (row.select_one(".res-sanction-item-lastupdated .res-profile-val-norm") or type('',(),{"get_text":lambda*self,strip=True:''})()).get_text(strip=True)
        addresses = [li.get_text(strip=True) for li in row.select(".res-sanction-item-addresses .res-profile-val-norm li")]
        country = (row.select_one(".res-sanction-item-country .res-profile-val-norm") or type('',(),{"get_text":lambda*self,strip=True:''})()).get_text(strip=True)
        position = " ".join([li.get_text(strip=True) for li in row.select(".res-sanction-item-position .res-profile-val-norm li")])
        reason = (row.select_one(".res-sanction-item-reason .res-profile-val-norm") or type('',(),{"get_text":lambda*self,strip=True:''})()).get_text(strip=True)
        entry = PEPEntry(
            match_score = score_el.get_text(strip=True) if score_el else "",
            name = name_el.get_text(strip=True) if name_el else "",
            aliases = aliases,
            last_updated = last_updated,
            addresses = addresses,
            country = country,
            position = position,
            reason = reason,
        )
        entries.append(entry)

    # find sanction result in bottom rows
    bottom = container.select_one(".res-profile-bottom-row")
    if bottom:
        for label_el, val_el in zip(bottom.select(".res-profile-item"), bottom.select(".res-profile-val-norm")):
            label = label_el.get_text(strip=True)
            if "WorldCompliance" in label or "WorldCompliance" in val_el.get_text(" ", strip=True):
                sanction_result = val_el.get_text(strip=True)
                break

    return entries, sanction_result


def parse_section_by_id(soup: BeautifulSoup, body_id: str) -> Dict:
    container = soup.select_one(f"#{body_id}")
    if not container:
        return {}
    data: Dict = {}
    # multi-blocks
    multi_blocks = container.select(".res-profile-multi-block")
    if multi_blocks:
        for block in multi_blocks:
            vals = [v.get_text(strip=True) for v in block.select(".res-profile-multi-val")]
            key = (block.select_one(".res-profile-item") or type('',(),{"get_text":lambda*self,strip=True:''})()).get_text(strip=True)
            data[key] = vals
        return data

    # standard rows
    for row in container.select(".res-profile-row"):
        label_el = row.select_one(".res-profile-item")
        val_el = row.select_one(".res-profile-val-norm")
        if not label_el or not val_el:
            continue
        label = label_el.get_text(strip=True).rstrip(":")
        value = val_el.get_text(" ", strip=True)
        data[label] = value
    return data


def parse_address_links(soup: BeautifulSoup) -> List[Dict]:
    container = soup.select_one("#res-addresslinks-body")
    out: List[Dict] = []
    if not container:
        return out
    rows = container.select(".addl tbody tr")
    for tr in rows:
        if "top" in tr.get("class", []):
            continue
        tds = tr.select("td")
        if len(tds) < 4:
            continue
        address_cell = tds[0]
        bold = address_cell.find("b")
        name = bold.get_text(strip=True) if bold else ""
        address_text = address_cell.get_text(" ", strip=True).replace(name, "").strip()
        out.append({
            "name": name,
            "address": address_text,
            "source": tds[1].get_text(strip=True),
            "recency": tds[2].get_text(strip=True),
            "residency": tds[3].get_text(strip=True),
        })
    return out


def parse_property(soup: BeautifulSoup) -> Dict:
    container = soup.select_one("#res-property-body")
    if not container:
        return {}
    data = _parse_rows(container)
    toggle = container.select_one(".res-profile-val-toggle")
    if toggle:
        data["neighbourhood"] = toggle.get_text(" ", strip=True)
    return data
