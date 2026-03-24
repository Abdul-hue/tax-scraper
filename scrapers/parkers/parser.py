from __future__ import annotations
from bs4 import BeautifulSoup
from .models import ValuationPrices
import logging, re
from typing import List

logger = logging.getLogger(__name__)

def parse_valuation_prices(html: str) -> ValuationPrices:
    """
    Extract price ranges from the Parkers free-valuation page.
    Parses .valuation-price-box__container blocks with full price ranges.
    Example: "£2,995 - £4,185" extracts both values as private_low/private_high.
    """
    # Always parse from string — never call string methods on html directly
    if isinstance(html, str):
        soup = BeautifulSoup(html, "html.parser")
    else:
        soup = html

    # Primary strategy: Extract full price ranges from .valuation-price-box structure
    price_boxes = soup.find_all("div", class_="valuation-price-box__container")
    if price_boxes:
        prices = {}
        for box in price_boxes:
            name_elem = box.find("div", class_="valuation-price-box__price-name")
            price_elem = box.find("div", class_="valuation-price-box__price")
            if not name_elem or not price_elem:
                continue

            name = name_elem.get_text(strip=True).lower()
            price_text = price_elem.get_text(strip=True)  # e.g. "£2,995 - £4,185"

            # Extract all pound values from the range string
            values = re.findall(r'£[\d,]+', price_text)

            if "private" in name:
                prices["private_low"] = values[0] if len(values) > 0 else ""
                prices["private_high"] = values[1] if len(values) > 1 else ""
            elif "dealer" in name or "forecourt" in name:
                prices["dealer_low"] = values[0] if len(values) > 0 else ""
                prices["dealer_high"] = values[1] if len(values) > 1 else ""

        if prices:
            return ValuationPrices(
                private_low=prices.get("private_low", ""),
                private_high=prices.get("private_high", ""),
                dealer_low=prices.get("dealer_low", ""),
                dealer_high=prices.get("dealer_high", ""),
            )

    # Fallback: try keyword-based extraction for compatibility
    price_map = {}
    price_keywords = {
        "private_good": [r"private.*good", r"good.*private", r"private sale.*good"],
        "private_poor": [r"private.*poor", r"poor.*private", r"private sale.*poor"],
        "trade_in":     [r"trade.?in", r"part.?ex"],
        "dealer": [r"dealer", r"forecourt"],
    }

    # Strategy 1: walk up from each £ amount to find its label
    for el in soup.find_all(string=re.compile(r'£\s*[\d,]+')):
        m = re.search(r'£\s*([\d,]+)', str(el))
        if not m:
            continue
        try:
            amount = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if not (500 < amount < 500_000):
            continue
        parent = el.parent
        for _ in range(6):
            if not parent:
                break
            context = parent.get_text(separator=" ", strip=True).lower()
            for key, patterns in price_keywords.items():
                if key not in price_map:
                    for pat in patterns:
                        if re.search(pat, context):
                            price_map[key] = f"£{amount:,}"
                            break
            parent = parent.parent

    if len(price_map) >= 2:
        return _build_prices(price_map)

    # Strategy 2: collect all £ amounts in document order
    seen = set()
    all_amounts = []
    for el in soup.find_all(string=re.compile(r'£\s*[\d,]+')):
        m = re.search(r'£\s*([\d,]+)', str(el))
        if m:
            try:
                v = int(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if 500 < v < 500_000 and v not in seen:
                seen.add(v)
                all_amounts.append(f"£{v:,}")

    if len(all_amounts) >= 2:
        return _build_prices_from_list(all_amounts)

    return ValuationPrices()


def _build_prices(price_map: dict) -> ValuationPrices:
    """Build ValuationPrices from keyword-matched price map (legacy fallback)."""
    return ValuationPrices(
        private_low=price_map.get("private_low", ""),
        private_high=price_map.get("private_high", ""),
        dealer_low=price_map.get("dealer_low", ""),
        dealer_high=price_map.get("dealer_high", ""),
    )


def _build_prices_from_list(amounts: list) -> ValuationPrices:
    """Build ValuationPrices from a list of amounts in order (legacy fallback)."""
    return ValuationPrices(
        private_low=amounts[0] if len(amounts) > 0 else "",
        private_high=amounts[1] if len(amounts) > 1 else "",
        dealer_low=amounts[2] if len(amounts) > 2 else "",
        dealer_high=amounts[3] if len(amounts) > 3 else "",
    )


def parse_vehicle_details(html) -> dict:
    """
    Extract vehicle identity info from the results page:
      - make, range/model name, derivative/trim, year,
        fuel type, transmission

    These appear in a vehicle summary section at the top of results.
    Return a dict with keys: make, range_name, model, year,
                             fuel_type, transmission
    Return empty strings for any fields not found.
    """
    # Always parse from string - never call string methods on html directly
    if isinstance(html, str):
        soup = BeautifulSoup(html, "html.parser")
    else:
        soup = html
    
    # Strategy 0: Try to extract from the free-valuation page vehicle name span
    vehicle_span = soup.select_one(".valuation-free-page__container__header-row--vehicle, .valuation-option-box__header-row--vehicle")
    if vehicle_span:
        full_name = vehicle_span.get_text(strip=True)
        # Parse the full name: e.g. "Vauxhall Astra Hatchback 1.4T 16V SRi 5d 2017/17"
        # This is simplistic but reasonable for the straightforward name format
        details = {k: "" for k in ["make", "range_name", "model", "year", "fuel_type", "transmission"]}
        parts = full_name.split()
        if len(parts) >= 2:
            details["make"] = parts[0]  # e.g. "Vauxhall"
            details["range_name"] = parts[1]  # e.g. "Astra"
            # Remaining parts as model/derivative
            if len(parts) > 2:
                details["model"] = " ".join(parts[2:])
        return details
    
    # Fallback: Use regex patterns for other page structures
    # Always initialise text so it's never unbound
    text = soup.get_text(" ", strip=True)
    details = {k: "" for k in ["make", "range_name", "model", "year", "fuel_type", "transmission"]}
    # naive regex patterns
    lookup = {
        "make": r'Make[:\s]+([A-Za-z0-9 &]+)',
        "range_name": r'Range[:\s]+([A-Za-z0-9 &-]+)',
        "model": r'Model[:\s]+([A-Za-z0-9 &-]+)',
        "year": r'Year[:\s]+(\d{4})',
        "fuel_type": r'Fuel[:\s]+([A-Za-z]+)',
        "transmission": r'Transmission[:\s]+([A-Za-z]+)',
    }
    for key, pat in lookup.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            details[key] = m.group(1).strip()
    return details


def parse_dropdown_options(soup: BeautifulSoup, dropdown_id: str) -> List[str]:
    """
    Extract all option values/text from a <select> dropdown by its id.
    Used to navigate the make/model/year dropdown chain.
    Returns list of option text strings (stripped, non-empty).
    """
    sel = soup.find('select', id=dropdown_id)
    if not sel:
        return []
    options = []
    for opt in sel.find_all('option'):
        txt = opt.get_text(strip=True)
        if txt:
            options.append(txt)
    return options


def is_email_gate_page(soup: BeautifulSoup) -> bool:
    """
    Detect if the current page is the email/registration gate.
    The gate page URL contains '/valuations-access/' and contains
    text like "stay up to date" or a skip/continue link.
    Returns True if on gate page, False otherwise.
    """
    text = soup.get_text(" ", strip=True)
    if re.search(r'stay up to date', text, re.I):
        return True
    if soup.find('a', href=re.compile(r'/valuations-access/')):
        return True
    if re.search(r'skip|continue|no thanks', text, re.I):
        return True
    return False


def is_valuation_results_page(soup: BeautifulSoup) -> bool:
    """
    Detect if the current page is the actual valuation results.
    Look for presence of price elements (£ values in valuation cards).
    Returns True if prices are present, False otherwise.
    """
    text = soup.get_text(" ", strip=True)
    return bool(re.search(r'£[\d,]+', text))
