import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright
from .models import NationwideQuery, NationwideResult
from .parser import parse_results
from ..common.browser import get_browser_args
from app.core.s3 import upload_screenshot_to_s3_sync

logger = logging.getLogger(__name__)

TARGET_URL = "https://www.nationwide.co.uk/house-price-index"

# Dedicated worker pool so Playwright's browser subprocess is always launched
# from a fresh thread (with its own event loop), never from the main FastAPI/
# uvicorn event loop. On Windows the main loop is not guaranteed to be a
# Proactor loop (uvicorn's --reload supervisor can hand workers a Selector
# loop), and subprocess creation then fails with NotImplementedError. Every
# other scraper in this codebase (app/scrapers/base.py) uses this same
# sync_playwright + executor pattern for that reason.
_executor = ThreadPoolExecutor(max_workers=4)


def _select_location(page, option_value, field_selector, timeout_ms=15000):
    """Pick a location radio and confirm the form actually switched to it.

    Two things silently swallow a plain Playwright click here, leaving the radio
    on Region so the postcode field never appears:
      - a click before React hydrates the form is discarded;
      - OneTrust's banner / dark filter (which can inject after we removed it)
        sits on top of the form, and even force=True clicks by coordinates.
    So clear the overlay and click the element itself via JS, and keep going
    until the radio stays checked and its dependent field (if any) is visible.
    """
    radio = f'input[type="radio"][value="{option_value}"]'
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        page.evaluate(
            """(sel) => {
                const sdk = document.getElementById('onetrust-consent-sdk');
                if (sdk) sdk.remove();
                document.querySelectorAll('.onetrust-pc-dark-filter').forEach(el => el.remove());
                const r = document.querySelector(sel);
                if (r) r.click();
            }""",
            radio,
        )
        try:
            if field_selector:
                page.wait_for_selector(field_selector, state="visible", timeout=1500)
            else:
                page.wait_for_timeout(750)
            if page.is_checked(radio):
                return
        except Exception:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"Nationwide form did not switch to '{option_value}' "
                f"within {timeout_ms // 1000}s (page not responding to the location choice)"
            )
        logger.info(f"Location '{option_value}' did not stick yet; retrying click")


class NationwideScraper:
    def __init__(self, config=None, headless=True):
        self.config = config
        self.headless = headless

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def scrape(self, query: NationwideQuery) -> NationwideResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._sync_scrape, query)

    def _sync_scrape(self, query: NationwideQuery) -> NationwideResult:
        logger.info(
            f"Starting Nationwide HPI scrape for region='{query.region}', "
            f"value={query.property_value}, from={query.from_year}Q{query.from_quarter}, "
            f"to={query.to_year}Q{query.to_quarter}"
        )

        result = NationwideResult(
            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        try:
            with sync_playwright() as p:
                # Use common browser arguments for stability
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=get_browser_args()
                )
                try:
                    context = browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/122.0.0.0 Safari/537.36"
                        ),
                        viewport={"width": 1440, "height": 900},
                    )
                    page = context.new_page()

                    logger.info(f"Navigating to {TARGET_URL}")
                    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=45000)
                    # The form is server-rendered then hydrated by React. Clicks made
                    # before hydration are discarded (the radio snaps back to Region),
                    # so give the page its full load before touching the form.
                    try:
                        page.wait_for_load_state("load", timeout=20000)
                    except Exception:
                        logger.debug("Page 'load' event slow; relying on location retry")

                    # Dismiss cookie consent if present
                    try:
                        page.wait_for_selector("#onetrust-accept-btn-handler", timeout=10000)
                        page.click("#onetrust-accept-btn-handler")
                        page.wait_for_selector(".onetrust-pc-dark-filter", state="hidden", timeout=8000)
                        logger.info("Dismissed cookie banner and overlay cleared")
                    except Exception:
                        logger.debug("No cookie banner or overlay already gone")

                    # Force-remove OneTrust SDK from DOM in case overlay persists
                    page.evaluate("""
                        const sdk = document.getElementById('onetrust-consent-sdk');
                        if (sdk) sdk.remove();
                        const filter = document.querySelector('.onetrust-pc-dark-filter');
                        if (filter) filter.remove();
                    """)

                    # Location selection: postcode, region, or UK average
                    if query.postcode:
                        _select_location(page, "optionPostcode", 'input[name="postcode"]')
                        page.fill('input[name="postcode"]', query.postcode)
                        page.wait_for_timeout(500)
                    elif query.region and query.region != 'UK':
                        _select_location(page, "optionRegion", 'select[name="region"]')
                        page.select_option('select[name="region"]', label=query.region)
                        page.wait_for_timeout(500)
                    else:
                        _select_location(page, "optionUk", None)

                    # Fill form fields
                    page.fill('input[name="lastValuation"]', str(query.property_value))
                    page.select_option('select[name="lastValuedDate.year"]', str(query.from_year))
                    page.select_option('select[name="lastValuedDate.quarter"]', str(query.from_quarter))
                    page.select_option('select[name="newValueDate.year"]', str(query.to_year))
                    page.select_option('select[name="newValueDate.quarter"]', str(query.to_quarter))

                    # Nuke OneTrust from the DOM and block it from re-injecting,
                    # then fire the submit via JS — this is the only reliable way
                    # to click through OneTrust's persistent dark-filter overlay.
                    page.evaluate("""
                        // Remove existing overlay nodes
                        const sdk = document.getElementById('onetrust-consent-sdk');
                        if (sdk) sdk.remove();
                        document.querySelectorAll('.onetrust-pc-dark-filter').forEach(el => el.remove());

                        // Poison the MutationObserver / re-injection by overriding appendChild
                        // so OneTrust cannot re-add the overlay after we remove it.
                        const _origAppend = Element.prototype.appendChild;
                        Element.prototype.appendChild = function(child) {
                            if (child && child.id === 'onetrust-consent-sdk') return child;
                            if (child && child.classList && child.classList.contains('onetrust-pc-dark-filter')) return child;
                            return _origAppend.call(this, child);
                        };

                        // Click the button directly via JS — bypasses all Playwright intercept checks
                        const btn = document.querySelector('button[data-ref="getResults.button"]');
                        if (btn) btn.click();
                    """)

                    # Wait for results
                    page.wait_for_selector('div[role="alert"] dl', timeout=15000)

                    alert = page.query_selector('div[role="alert"]')
                    if not alert:
                        result.error = "Results container not found"
                        return result

                    description_el = alert.query_selector("p")
                    description = description_el.inner_text().strip() if description_el else ""

                    dl = alert.query_selector("dl")
                    if not dl:
                        result.error = "Results list not found"
                        return result

                    dt_elements = dl.query_selector_all("dt")
                    dd_elements = dl.query_selector_all("dd")
                    dts = [dt.inner_text() for dt in dt_elements]
                    dds = [dd.inner_text() for dd in dd_elements]

                    parsed = parse_results(dts, dds, description)
                    parsed.scraped_at = result.scraped_at

                    # Screenshot capture
                    _ts = time.strftime("%Y%m%d_%H%M%S")
                    _ss_name = f"nationwide_{_ts}.png"
                    try:
                        screenshot_bytes = page.screenshot(full_page=True)
                        parsed.screenshot_url = upload_screenshot_to_s3_sync(screenshot_bytes, _ss_name)
                    except Exception:
                        parsed.screenshot_url = None

                    return parsed

                finally:
                    browser.close()

        except Exception as e:
            logger.error(f"Nationwide scrape failed: {e}", exc_info=True)
            result.error = str(e)

        return result
