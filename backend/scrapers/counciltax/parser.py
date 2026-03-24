import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_council_tax_results(html: str) -> list[dict]:
    """
    Parse council tax results from mycounciltax.org.uk.

    The results page renders a plain <table border="1"> with no CSS classes.
    Row 0 is a header row using <th> tags — skipped automatically because
    find_all("td") returns nothing for header rows.
    Data rows have 3 <td> cells: address, band, annual tax.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    rows = soup.select("table tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue  # skip header row (uses <th>) and any malformed rows
        address = cells[0].get_text(strip=True)
        band = cells[1].get_text(strip=True)
        annual_tax = cells[2].get_text(strip=True) if len(cells) >= 3 else ""
        if address:
            results.append({
                "address": address,
                "band": band,
                "annual_tax": annual_tax,
            })

    logger.info(f"Parsed {len(results)} properties from council tax results table")

    if not results:
        logger.warning("No properties found — check if the results page HTML was saved correctly")

    return results


def parse_properties(html: str, postcode: str = "") -> list:
    """Parse property records from the mycounciltax.org.uk results page (backwards compatibility wrapper)."""
    from .models import PropertyRecord

    # Use new simplified parser
    raw_results = parse_council_tax_results(html)
    properties = []
    for result in raw_results:
        # Extract band (single letter A-H)
        band = result["band"].strip()[:1].upper()
        # Extract amount from annual_tax string (e.g., "£1448" -> 1448)
        amount_str = result["annual_tax"].replace("£", "").replace(",", "").strip()
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 0.0
        monthly_amount = round(amount / 12, 2) if amount else 0.0
        properties.append(PropertyRecord(
            address=result["address"],
            band=band,
            annual_amount=amount,
            monthly_amount=monthly_amount,
            postcode=postcode,
        ))
    return properties

    # Strategy 4: Look for any list items or divs with "Band" keyword
    for el in soup.find_all(["li", "div", "p", "span"]):
        text = el.get_text(separator=" ", strip=True)
        band_match = re.search(r'\bBand\s*([A-H])\b', text, re.IGNORECASE)
        amount_match = re.search(r'£\s*([\d,]+(?:\.\d{2})?)', text)
        if band_match and amount_match and len(text) < 300:
            properties.append(PropertyRecord(
                address=text[:80],
                band=band_match.group(1).upper(),
                annual_amount=float(amount_match.group(1).replace(",", "")),
                postcode=postcode,
            ))

    if properties:
        seen = set()
        unique = []
        for p in properties:
            key = (p.band, p.annual_amount)
            if key not in seen:
                seen.add(key)
                unique.append(p)
        logger.debug(f"Strategy 4 (div/li scan) found {len(unique)} records")
        return unique

    logger.warning("All parse strategies failed — inspect debug/counciltax_last.html")
    return []


def parse_error_message(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    for selector in [".error", ".alert", ".message", "[class*='error']", "[class*='alert']"]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(strip=True)
            if text:
                return text
    m = re.search(r'(no properties|not found|invalid postcode|please enter|no results)', html, re.IGNORECASE)
    return m.group(0) if m else None


def extract_local_authority(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["h1", "h2", "h3", "p"]):
        text = tag.get_text(strip=True)
        if re.search(r'(council|borough|district|city|county)', text, re.IGNORECASE) and len(text) < 120:
            return text
    return None
