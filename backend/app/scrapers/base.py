from __future__ import annotations
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, List

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import asyncio
from concurrent.futures import ThreadPoolExecutor
from app.core.s3 import upload_screenshot_to_s3

_executor = ThreadPoolExecutor(max_workers=4)

logger = logging.getLogger(__name__)

# ── ListenToTaxman Models ──────────────────────────────────────────────────
SalaryPeriod = Literal["year", "month", "4weeks", "2weeks", "week", "day", "hour"]
PensionType  = Literal["£", "%"]
StudentLoan  = Literal["No", "Plan 1", "Plan 2", "Plan 4", "Postgraduate"]
AgeGroup     = Literal["under 65", "65-74", "75 and over"]
Region       = Literal["UK", "Scotland"]

@dataclass
class TaxConfig:
    salary:         int          = 2200
    salary_period:  SalaryPeriod = "month"
    tax_year:       str          = "2025/26"
    region:         Region       = "UK"
    age:            AgeGroup     = "under 65"
    student_loan:   StudentLoan  = "No"
    pension_amount: float        = 0
    pension_type:   PensionType  = "£"
    allowances:     float        = 0
    tax_code:       str          = ""
    married:        bool         = False
    blind:          bool         = False
    no_ni:          bool         = False

@dataclass
class PayslipRow:
    label:   str
    percent: str = ""
    yearly:  str = ""
    monthly: str = ""
    weekly:  str = ""

@dataclass
class TaxResult:
    config:          dict
    scraped_at:      str
    url:             str
    payslip:         list[dict]    = field(default_factory=list)
    summary:         dict          = field(default_factory=dict)
    screenshot_url:  Optional[str] = None
    error:           Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.payslip)

    def to_dict(self) -> dict:
        return asdict(self)

# ── Council Tax Models ──────────────────────────────────────────────────────
@dataclass
class PropertyRecord:
    address:        str
    band:           str
    annual_amount:  float = 0.0
    monthly_amount: float = 0.0
    postcode:       str = ""

@dataclass
class CouncilTaxResult:
    postcode:    str
    scraped_at:  str
    properties:  list[dict] = field(default_factory=list)
    screenshot_url:  Optional[str] = None
    error:       Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and len(self.properties) > 0

    def to_dict(self) -> dict:
        return asdict(self)

# ── Parkers Models ──────────────────────────────────────────────────────────
@dataclass
class ValuationPrices:
    private_low:   str = ""
    private_high:  str = ""
    dealer_low:    str = ""
    dealer_high:   str = ""

@dataclass
class ParkersResult:
    config:          dict
    scraped_at:      str
    reg_plate:       str    = ""
    make:            str    = ""
    model:           str    = ""
    year:            str    = ""
    prices:          ValuationPrices = field(default_factory=ValuationPrices)
    screenshot_url:  Optional[str] = None
    error:           Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and (self.prices.private_low != "" or self.prices.dealer_low != "")

    def to_dict(self) -> dict:
        return asdict(self)

# ── Unified Scraper Engine ──────────────────────────────────────────────────
class ScraperEngine:
    """
    Unified engine for all scraping modules.
    Initialize once with global config, then call specific scrapers.
    """
    def __init__(
        self,
        headless: bool = True,
        output_dir: str | Path = "output",
        timeout_ms: int = 20_000,
    ):
        self.headless = headless
        self.output_dir = Path(output_dir)
        self.timeout_ms = timeout_ms

    async def stop(self):
        return None

    def _capture_and_upload_screenshot(self, page, prefix: str) -> Optional[str]:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.png"
        screenshot_bytes = page.screenshot(full_page=True)
        return asyncio.run(upload_screenshot_to_s3(screenshot_bytes, filename))

    # ── ListenToTaxman Implementation (Ported) ───────────────────────────────
    async def scrape_taxman(
        self,
        config: TaxConfig = None,
        screenshot: bool = False,
    ) -> TaxResult:
        if config is None:
            config = TaxConfig()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._sync_scrape_taxman, config, screenshot)

    def _sync_scrape_taxman(
        self,
        config: TaxConfig,
        screenshot: bool = False,
    ) -> TaxResult:
        url = "https://www.listentotaxman.com"
        result = TaxResult(
            config=asdict(config),
            scraped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            url=url,
        )
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            try:
                logger.info(f"Loading {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=40_000)

                # --- Wait for Form ---
                page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(1500)

                # --- Fill Form ---
                page.select_option('select[name="yr"]', label=config.tax_year)
                page.select_option('select[name="region"]', label=config.region)
                if page.is_checked('input[name="married"]') != config.married:
                    page.click('input[name="married"]')
                if page.is_checked('input[name="blind"]') != config.blind:
                    page.click('input[name="blind"]')
                if page.is_checked('input[name="exNI"]') != config.no_ni:
                    page.click('input[name="exNI"]')
                page.select_option('select[name="plan"]', label=config.student_loan)
                page.select_option('select[name="age"]', label=config.age)
                page.fill('input[name="add"]', str(int(config.allowances)) if config.allowances else "0")
                page.select_option('#pension-prepend', label=config.pension_type)
                page.fill('input[name="pension"]', str(config.pension_amount))
                page.fill('input[name="ingr"]', str(config.salary))
                page.select_option('select[name="time"]', label=config.salary_period)

                # --- Submit ---
                page.evaluate(
                    "() => { const b = document.querySelector('#calculate'); "
                    "if(b){ b.disabled=false; b.removeAttribute('disabled'); b.click(); }}"
                )

                # --- Wait for Results ---
                try:
                    page.wait_for_selector('#row-gross-pay', timeout=20_000)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass

                # --- Parse ---
                html = page.content()
                soup = BeautifulSoup(html, "lxml")

                table = None
                for tbl in soup.find_all("table"):
                    if "Net Wage" in tbl.get_text() or "Gross Pay" in tbl.get_text():
                        table = tbl
                        break

                rows = []
                if table:
                    for tr in table.find_all("tr"):
                        cells = tr.find_all(["td", "th"])
                        if len(cells) >= 2:
                            texts = [c.get_text(" ", strip=True) for c in cells]
                            rows.append(
                                PayslipRow(
                                    label=texts[0],
                                    percent=texts[1] if len(texts) > 1 else "",
                                    yearly=texts[2] if len(texts) > 2 else "",
                                    monthly=texts[3] if len(texts) > 3 else "",
                                    weekly=texts[4] if len(texts) > 4 else "",
                                )
                            )

                result.payslip = [asdict(r) for r in rows]
                result.summary = {r.label: asdict(r) for r in rows if r.label}

                if screenshot:
                    try:
                        result.screenshot_url = self._capture_and_upload_screenshot(page, "taxman")
                    except Exception as e:
                        logger.error("S3 upload failed for Taxman: %s", e)
                        result.screenshot_url = None

            except Exception as e:
                logger.error(f"Scrape failed: {e}")
                result.error = str(e)
            finally:
                context.close()
                browser.close()

        return result

    # ── Council Tax Implementation (Ported) ──────────────────────────────────
    async def scrape_counciltax(self, postcode: str) -> CouncilTaxResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._sync_scrape_counciltax, postcode)

    def _sync_scrape_counciltax(self, postcode: str) -> CouncilTaxResult:
        postcode = postcode.strip().upper()
        url = "https://www.mycounciltax.org.uk/content/index"

        result = CouncilTaxResult(
            postcode=postcode,
            scraped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            try:
                logger.info(f"Navigating to {url}")
                page.goto(url, wait_until="commit", timeout=45_000)
                page.wait_for_selector("input[name='postcode']", timeout=30_000)

                # Fill and Submit
                page.fill("input[name='postcode']", postcode)
                page.click("input[name='search'], input[type='submit'], button[type='submit']")

                # Wait for Results
                try:
                    page.wait_for_selector("table tr td", timeout=30_000)
                except Exception:
                    pass

                html = page.content()
                soup = BeautifulSoup(html, "lxml")

                properties = []
                rows = soup.select("table tr")
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) < 2:
                        continue

                    address = cells[0].get_text(strip=True)
                    band = cells[1].get_text(strip=True)[:1].upper()
                    annual_tax_str = cells[2].get_text(strip=True) if len(cells) >= 3 else "0"

                    amount_str = annual_tax_str.replace("£", "").replace(",", "").strip()
                    try:
                        amount = float(amount_str)
                    except Exception:
                        amount = 0.0

                    properties.append(
                        PropertyRecord(
                            address=address,
                            band=band,
                            annual_amount=amount,
                            monthly_amount=round(amount / 12, 2) if amount else 0.0,
                            postcode=postcode,
                        )
                    )

                result.properties = [asdict(p) for p in properties]

                try:
                    result.screenshot_url = self._capture_and_upload_screenshot(page, "counciltax")
                except Exception as e:
                    logger.error("S3 upload failed for Council Tax: %s", e)
                    result.screenshot_url = None

                if not properties:
                    error_el = soup.select_one(".error, .alert, [class*='error']")
                    if error_el:
                        result.error = error_el.get_text(strip=True)
                    else:
                        result.error = "No properties found for this postcode."

            except Exception as e:
                logger.error(f"Council tax scrape failed: {e}")
                result.error = str(e)
            finally:
                context.close()
                browser.close()

        return result

    # ── Parkers Implementation (Ported) ──────────────────────────────────────
    async def scrape_parkers(self, plate: str) -> ParkersResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._sync_scrape_parkers, plate)

    def _sync_scrape_parkers(self, plate: str) -> ParkersResult:
        plate = plate.strip().upper().replace(" ", "")
        url = "https://www.parkers.co.uk/"

        result = ParkersResult(
            config={"plate": plate},
            scraped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            reg_plate=plate,
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            try:
                logger.info(f"Navigating to Parkers: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=40_000)
                page.wait_for_timeout(2000)

                self._parkers_dismiss_overlays(page)

                try:
                    tab = page.locator("a[data-tabs-target='valuations']")
                    if tab.is_visible(timeout=5000):
                        tab.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

                reg_input = self._parkers_find_reg_input(page)
                if not reg_input:
                    raise RuntimeError("Could not find registration input field")

                reg_input.click()
                reg_input.fill(plate)
                page.wait_for_timeout(500)

                if not self._parkers_submit(page):
                    raise RuntimeError("Could not submit valuation form")

                page.wait_for_timeout(3000)
                self._parkers_dismiss_overlays(page)

                if "/confirm/" in page.url:
                    self._parkers_handle_confirm(page)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    page.wait_for_timeout(2000)

                if "select-a-valuation" in page.url:
                    self._parkers_handle_select_valuation(page)

                if self._parkers_picker_present(page):
                    self._parkers_select_first_vehicle(page)
                    page.wait_for_timeout(3000)

                self._parkers_dismiss_email_gate(page)

                try:
                    page.wait_for_selector("[class*='valuation'], [class*='price']", timeout=15000)
                except Exception:
                    pass

                html = page.content()
                soup = BeautifulSoup(html, "lxml")

                prices = ValuationPrices()
                price_boxes = soup.find_all("div", class_="valuation-price-box__container")
                for box in price_boxes:
                    name_elem = box.find("div", class_="valuation-price-box__price-name")
                    price_elem = box.find("div", class_="valuation-price-box__price")
                    if not name_elem or not price_elem:
                        continue

                    name = name_elem.get_text(strip=True).lower()
                    price_text = price_elem.get_text(strip=True)
                    vals = re.findall(r'£[\d,]+', price_text)

                    if "private" in name:
                        prices.private_low = vals[0] if len(vals) > 0 else ""
                        prices.private_high = vals[1] if len(vals) > 1 else ""
                    elif "dealer" in name or "forecourt" in name:
                        prices.dealer_low = vals[0] if len(vals) > 0 else ""
                        prices.dealer_high = vals[1] if len(vals) > 1 else ""

                result.prices = prices

                details_span = soup.select_one(
                    ".valuation-free-page__container__header-row--vehicle, "
                    ".valuation-option-box__header-row--vehicle"
                )
                if details_span:
                    txt = details_span.get_text(strip=True)
                    parts = txt.split()
                    if len(parts) >= 1:
                        result.make = parts[0]
                    if len(parts) >= 2:
                        result.model = parts[1]
                    if len(parts) >= 3:
                        result.year = parts[-1]

                try:
                    result.screenshot_url = self._capture_and_upload_screenshot(page, "parkers")
                except Exception as e:
                    logger.error("S3 upload failed for Parkers: %s", e)
                    result.screenshot_url = None

            except Exception as e:
                logger.error(f"Parkers scrape failed: {e}")
                result.error = str(e)
            finally:
                context.close()
                browser.close()

        return result

    # ── Parkers Helpers ──────────────────────────────────────────────────────
    def _parkers_dismiss_overlays(self, page):
        selectors = ["#onetrust-accept-btn-handler", ".cc-btn.cc-accept", "button.bm-close-btn", "[class*='close']"]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click()
                    page.wait_for_timeout(500)
            except Exception:
                pass

    def _parkers_find_reg_input(self, page):
        for sel in ["input.vrm-lookup__input", "input[placeholder*='reg' i]", "input[name='vrm']"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    return el
            except Exception:
                pass
        return None

    def _parkers_submit(self, page) -> bool:
        for sel in ["button.vrm-lookup__button", "button:has-text('Value my car')", "button[type='submit']"]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click()
                    return True
            except Exception:
                pass
        return False

    def _parkers_handle_confirm(self, page):
        try:
            radios = page.locator("input[name='valuationPurpose']")
            if radios.count() > 0:
                radios.nth(0).check()
            
            link = page.locator("#valuation-confirmation-link")
            link.scroll_into_view_if_needed()
            href = link.get_attribute("href")
            if href:
                target = "https://www.parkers.co.uk" + href if href.startswith("/") else href
                page.goto(target, wait_until="domcontentloaded")
            else:
                link.click()
        except Exception:
            pass

    def _parkers_handle_select_valuation(self, page):
        try:
            btn = page.locator("a.valuation-primer-page__option__cta__link--free").first
            href = btn.get_attribute("href")
            if href:
                target = "https://www.parkers.co.uk" + href if href.startswith("/") else href
                page.goto(target, wait_until="domcontentloaded")
            else:
                btn.click()
        except Exception:
            derived = page.url.replace("/select-a-valuation/", "/free-valuation/")
            page.goto(derived, wait_until="domcontentloaded")

    def _parkers_picker_present(self, page) -> bool:
        try:
            return page.locator("select[name*='derivative' i]").first.is_visible(timeout=500)
        except Exception:
            return False

    def _parkers_select_first_vehicle(self, page):
        try:
            sel = page.locator("select").first
            sel.select_option(index=1)
            page.wait_for_timeout(1000)
            page.click("button[type='submit'], button:has-text('Continue')")
        except Exception:
            pass

    def _parkers_dismiss_email_gate(self, page):
        for sel in ["button:has-text('Skip')", "button:has-text('No thanks')", "a:has-text('Skip')"]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click()
            except Exception:
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.stop()
