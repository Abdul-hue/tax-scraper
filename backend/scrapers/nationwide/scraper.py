import logging
from datetime import datetime, timezone

from playwright.async_api import async_playwright
from .models import NationwideQuery, NationwideResult
from .parser import parse_results
from ..common.browser import get_browser_args
from app.core.s3 import upload_screenshot_to_s3

logger = logging.getLogger(__name__)

TARGET_URL = "https://www.nationwide.co.uk/house-price-index"


class NationwideScraper:
    def __init__(self, config=None, headless=True):
        self.config = config
        self.headless = headless

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def scrape(self, query: NationwideQuery) -> NationwideResult:
        logger.info(
            f"Starting Nationwide HPI scrape for region='{query.region}', "
            f"value={query.property_value}, from={query.from_year}Q{query.from_quarter}, "
            f"to={query.to_year}Q{query.to_quarter}"
        )

        result = NationwideResult(
            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        try:
            async with async_playwright() as p:
                # Use common browser arguments for stability
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=get_browser_args()
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1440, "height": 900},
                )
                page = await context.new_page()

                try:
                    logger.info(f"Navigating to {TARGET_URL}")
                    await page.goto(TARGET_URL, wait_until="commit", timeout=45000)

                    # Dismiss cookie consent if present
                    try:
                        await page.wait_for_selector("#onetrust-accept-btn-handler", timeout=10000)
                        await page.click("#onetrust-accept-btn-handler")
                        await page.wait_for_selector(".onetrust-pc-dark-filter", state="hidden", timeout=8000)
                        logger.info("Dismissed cookie banner and overlay cleared")
                    except Exception:
                        logger.debug("No cookie banner or overlay already gone")

                    # Force-remove OneTrust SDK from DOM in case overlay persists
                    await page.evaluate("""
                        const sdk = document.getElementById('onetrust-consent-sdk');
                        if (sdk) sdk.remove();
                        const filter = document.querySelector('.onetrust-pc-dark-filter');
                        if (filter) filter.remove();
                    """)

                    # Location selection: postcode, region, or UK average
                    if query.postcode:
                        # Select Postcode radio
                        await page.click('input[type="radio"][value="optionPostcode"]', force=True)
                        await page.wait_for_timeout(500)
                        # Fill postcode input - wait for it to appear after radio click
                        await page.wait_for_selector('input[name="postcode"]', timeout=5000)
                        await page.fill('input[name="postcode"]', query.postcode)
                        await page.wait_for_timeout(500)
                    elif query.region and query.region != 'UK':
                        # Select Region radio
                        await page.click('input[type="radio"][value="optionRegion"]', force=True)
                        await page.wait_for_timeout(500)
                        await page.wait_for_selector('select[name="region"]', timeout=5000)
                        await page.select_option('select[name="region"]', label=query.region)
                        await page.wait_for_timeout(500)
                    else:
                        # Select UK average radio
                        await page.click('input[type="radio"][value="optionUk"]', force=True)
                        await page.wait_for_timeout(500)

                    # Fill form fields
                    await page.fill('input[name="lastValuation"]', str(query.property_value))
                    await page.select_option('select[name="lastValuedDate.year"]', str(query.from_year))
                    await page.select_option('select[name="lastValuedDate.quarter"]', str(query.from_quarter))
                    await page.select_option('select[name="newValueDate.year"]', str(query.to_year))
                    await page.select_option('select[name="newValueDate.quarter"]', str(query.to_quarter))

                    # Nuke OneTrust from the DOM and block it from re-injecting,
                    # then fire the submit via JS — this is the only reliable way
                    # to click through OneTrust's persistent dark-filter overlay.
                    await page.evaluate("""
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
                    await page.wait_for_selector('div[role="alert"] dl', timeout=15000)

                    alert = await page.query_selector('div[role="alert"]')
                    if not alert:
                        result.error = "Results container not found"
                        return result

                    description_el = await alert.query_selector("p")
                    description = (await description_el.inner_text()).strip() if description_el else ""

                    dl = await alert.query_selector("dl")
                    if not dl:
                        result.error = "Results list not found"
                        return result

                    dt_elements = await dl.query_selector_all("dt")
                    dd_elements = await dl.query_selector_all("dd")
                    dts = [await dt.inner_text() for dt in dt_elements]
                    dds = [await dd.inner_text() for dd in dd_elements]

                    parsed = parse_results(dts, dds, description)
                    parsed.scraped_at = result.scraped_at

                    # Screenshot capture
                    import time as _time
                    _ts = _time.strftime("%Y%m%d_%H%M%S")
                    _ss_name = f"nationwide_{_ts}.png"
                    try:
                        screenshot_bytes = await page.screenshot(full_page=True)
                        parsed.screenshot_url = await upload_screenshot_to_s3(screenshot_bytes, _ss_name)
                    except Exception:
                        parsed.screenshot_url = None

                    return parsed

                finally:
                    await browser.close()

        except Exception as e:
            logger.error(f"Nationwide scrape failed: {e}", exc_info=True)
            result.error = str(e)

        return result
