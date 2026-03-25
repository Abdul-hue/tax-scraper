import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
from .models import LpsQuery, LpsResult, LpsProperty, LpsPropertyDetail
from ..common.browser import get_browser_args

logger = logging.getLogger(__name__)

BASE_URL = "https://valuationservices.finance-ni.gov.uk"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": f"{BASE_URL}/Property/Search",
    "Origin": BASE_URL,
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

class LpsScraper:
    def __init__(self, config=None, headless: bool = None):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        if headless is None:
            self.headless = os.getenv("HEADLESS", "true").lower() == "true"
        else:
            self.headless = headless

    def scrape(self, query: LpsQuery) -> LpsResult:
        session = requests.Session()
        session.get(f"{BASE_URL}/Property/Search", headers=HEADERS)

        result = LpsResult(
            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            search_type=query.search_type,
        )
        try:
            all_properties = []

            for page in range(1, query.max_pages + 1):
                if query.search_type == "postcode":
                    # 1. URL Decode and Clean Postcode
                    postcode = query.postcode.strip().upper()
                    payload = {
                        "searchType": "postcode",
                        "postcode": postcode,
                        "propertyNumber": query.property_number.strip(),
                        "page": str(page),
                    }
                    endpoint = f"{BASE_URL}/Property/GetResultsByPostcode"
                else:
                    payload = {
                        "searchType": "advanced",
                        "advPropertyNumber": query.adv_property_number.strip(),
                        "street": query.street.strip(),
                        "town": query.town.strip(),
                        "districtCouncil": query.district_council.strip(),
                        "propertyId": query.property_id.strip(),
                        "page": str(page),
                    }
                    endpoint = f"{BASE_URL}/Property/GetResultsByAdvanced"

                resp = session.post(endpoint, data=payload, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                if not data:
                    break

                for item in data:
                    all_properties.append(LpsProperty(
                        property_id=str(item.get("propertyId", "")),
                        full_address=item.get("fullAddress", ""),
                        capital_value=item.get("capitalValue", "N/A"),
                        total_nav=item.get("totalNAV", ""),
                    ))

                result.pages_scraped = page

                if len(data) < 10:  # last page has fewer than 10 results
                    break

            result.properties = all_properties
            result.total_found = len(all_properties)

            # Fetch detail page for each property
            details = []
            for prop in all_properties:
                try:
                    detail = self._fetch_detail(prop.property_id, session)
                    details.append(detail)
                except Exception as e:
                    details.append(LpsPropertyDetail(property_id=prop.property_id, error=str(e)))
            result.property_details = details

            # Screenshot capture using Playwright
            import time as _time
            from pathlib import Path
            
            # backend/scrapers/lps/scraper.py -> backend/static/screenshots
            _backend_dir = Path(__file__).parent.parent.parent
            _ss_dir = _backend_dir / "static" / "screenshots"
            _ss_dir.mkdir(parents=True, exist_ok=True)
            _ts = _time.strftime("%Y%m%d_%H%M%S")
            _ss_name = f"lps_{_ts}.png"
            _ss_path = str(_ss_dir / _ss_name)
            
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=getattr(self, "headless", True),
                        args=get_browser_args()
                    )
                    context = browser.new_context(viewport={"width": 1280, "height": 1024})
                    page = context.new_page()
                    
                    # Navigate to the search page or last results page if possible
                    # Since LPS is a multi-step search, we'll just capture the search root
                    # as a fallback if the specific result URL isn't easily reachable via GET
                    search_url = f"{BASE_URL}/Property/Search"
                    page.goto(search_url, wait_until="networkidle", timeout=30000)
                    
                    page.screenshot(path=_ss_path, full_page=True)
                    result.screenshot_url = f"/api/files/screenshots/{_ss_name}"
                    logger.info(f"Screenshot saved to: {_ss_path}")
                    browser.close()
            except Exception as e:
                logger.warning(f"Failed to capture screenshot: {e}")
                result.screenshot_url = None

        except Exception as e:
            result.error = str(e)

        return result

    def _fetch_detail(self, property_id: str, session: requests.Session) -> LpsPropertyDetail:
        detail = LpsPropertyDetail(property_id=property_id)
        try:
            url = f"{BASE_URL}/Property/Details?propertyId={property_id}"
            resp = session.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Full address
            addr_tag = soup.select_one("section[aria-labelledby='address-heading'] address")
            if addr_tag:
                detail.full_address = addr_tag.get_text(" ", strip=True)

            # Key details (LPS ID, UPRN, property type)
            for row in soup.select(".govuk-summary-list__row"):
                key = row.select_one(".govuk-summary-list__key")
                val = row.select_one(".govuk-summary-list__value")
                if not key or not val:
                    continue
                k = key.get_text(strip=True).lower()
                v = val.get_text(strip=True)
                if "uprn" in k or "unique property" in k:
                    detail.uprn = v
                elif "property type" in k:
                    detail.property_type = v

            # Non-domestic information table
            for row in soup.select("section[aria-labelledby='nondomestic-info-heading'] tbody tr"):
                th = row.select_one("th")
                td = row.select_one("td")
                if not th or not td:
                    continue
                key = th.get_text(" ", strip=True).lower()
                val = td.get_text(strip=True)
                if "description" in key:
                    detail.description = val
                elif "nav) non" in key:
                    detail.nav_non_exempt = val
                elif "nav) exempt" in key:
                    detail.nav_exempt = val
                elif "ot " in key or key.startswith("ot"):
                    detail.ot_other = val
                elif "in " in key or "industrial" in key:
                    detail.in_industrial = val
                elif "sr " in key or "sports" in key:
                    detail.sr_sports = val
                elif "ft " in key or "freight" in key:
                    detail.ft_freight = val
                elif "ex " in key or "exempt" in key:
                    detail.ex_exempt = val
                elif "estimated" in key and "rate bill" in key:
                    detail.estimated_rate_bill = val

            # Valuation summaries table
            summaries = []
            for row in soup.select("section[aria-labelledby='valuation-summaries-heading'] tbody tr"):
                cells = [td.get_text(strip=True) for td in row.select("td")]
                if len(cells) >= 6:
                    summaries.append({
                        "num": cells[0],
                        "floor": cells[1],
                        "description_use": cells[2],
                        "area": cells[3],
                        "rate": cells[4],
                        "distinguishment": cells[5],
                    })
            detail.valuation_summaries = summaries

        except Exception as e:
            detail.error = str(e)

        return detail

