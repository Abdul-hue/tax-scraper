import logging
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright
from .models import NationwideQuery, NationwideResult
from .parser import parse_results
from ..common.browser import get_browser_args
from app.core.s3 import upload_screenshot_to_s3_sync

logger = logging.getLogger(__name__)

TARGET_URL = "https://www.nationwide.co.uk/house-price-index"


class NationwideScraper:
    def __init__(self, config=None, headless=True):
        self.config = config
        self.headless = headless

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def scrape(self, query: NationwideQuery) -> NationwideResult:
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
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1440, "height": 900},
                )
                page = context.new_page()

                try:
                    logger.info(f"Navigating to {TARGET_URL}")
                    page.goto(TARGET_URL, wait_until="commit", timeout=45000)

                    # Dismiss cookie consent if present
                    try:
                        page.wait_for_selector("#onetrust-accept-btn-handler", timeout=5000)
                        page.click("#onetrust-accept-btn-handler")
                        logger.info("Dismissed cookie banner")
                    except Exception:
                        logger.debug("No cookie banner found or already dismissed")

                    # Location selection: postcode, region, or UK average
                    if query.postcode:
                        # Select Postcode radio
                        page.click('input[type="radio"][value="optionPostcode"]')
                        page.wait_for_timeout(500)
                        # Fill postcode input - wait for it to appear after radio click
                        page.wait_for_selector('input[name="postcode"]', timeout=5000)
                        page.fill('input[name="postcode"]', query.postcode)
                        page.wait_for_timeout(500)
                    elif query.region and query.region != 'UK':
                        # Select Region radio
                        page.click('input[type="radio"][value="optionRegion"]')
                        page.wait_for_timeout(500)
                        page.wait_for_selector('select[name="region"]', timeout=5000)
                        page.select_option('select[name="region"]', label=query.region)
                        page.wait_for_timeout(500)
                    else:
                        # Select UK average radio
                        page.click('input[type="radio"][value="optionUk"]')
                        page.wait_for_timeout(500)

                    # Fill form fields
                    page.fill('input[name="lastValuation"]', str(query.property_value))
                    page.select_option('select[name="lastValuedDate.year"]', str(query.from_year))
                    page.select_option('select[name="lastValuedDate.quarter"]', str(query.from_quarter))
                    page.select_option('select[name="newValueDate.year"]', str(query.to_year))
                    page.select_option('select[name="newValueDate.quarter"]', str(query.to_quarter))

                    # Submit
                    page.click('button[data-ref="getResults.button"]')

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

                    dts = [dt.inner_text() for dt in dl.query_selector_all("dt")]
                    dds = [dd.inner_text() for dd in dl.query_selector_all("dd")]

                    parsed = parse_results(dts, dds, description)
                    parsed.scraped_at = result.scraped_at

                    # Screenshot capture
                    import time as _time
                    _ts = _time.strftime("%Y%m%d_%H%M%S")
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
