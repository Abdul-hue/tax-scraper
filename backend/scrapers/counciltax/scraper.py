import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from .models import CouncilTaxQuery, CouncilTaxResult, PropertyRecord
from ..common.browser import get_browser_args

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.mycounciltax.org.uk/content/index"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.mycounciltax.org.uk/content/index",
    "Origin": "https://www.mycounciltax.org.uk",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class CouncilTaxScraper:
    def __init__(self, config=None, headless: bool = None):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        self.config = config
        if headless is None:
            self.headless = os.getenv("HEADLESS", "true").lower() == "true"
        else:
            self.headless = headless

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def lookup(self, postcode: str) -> CouncilTaxResult:
        """Alias for search() — called by counciltax_main.py"""
        query = CouncilTaxQuery(postcode=postcode)
        return self.search(query)

    def lookup(self, postcode: str) -> CouncilTaxResult:
        """Entry point for the council tax scraper."""
        logger.info(f"Looking up council tax for postcode: {postcode}")
        
        try:
            # Use Playwright to handle JS-rendered pages
            html, screenshot_url = self._fetch_council_tax_html(postcode, headless=True)

            from .parser import parse_properties, parse_error_message
            properties = parse_properties(html, postcode)

            if not properties:
                error_msg = parse_error_message(html)
                logger.warning(f"No properties found. Page message: {error_msg}")
                return CouncilTaxResult(
                    postcode=postcode,
                    scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    properties=[],
                    screenshot_url=screenshot_url,
                    error=error_msg or "No properties found - check debug/counciltax_last.html",
                )

            return CouncilTaxResult(
                postcode=postcode,
                scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                properties=properties,
                screenshot_url=screenshot_url,
                error=None,
            )

        except Exception as e:
            logger.error(f"Council tax search failed: {e}", exc_info=True)
            return CouncilTaxResult(
                postcode=postcode,
                scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                properties=[],
                screenshot_url=None,
                error=str(e),
            )

    def _fetch_council_tax_html(self, postcode: str, headless: bool = True) -> tuple[str, Optional[str]]:
        """Use Playwright to submit the council tax form and return (HTML, screenshot_url)."""
        with sync_playwright() as p:
            # Use common browser arguments for stability
            browser = p.chromium.launch(
                headless=headless,
                args=get_browser_args()
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            try:
                # Step 1: Navigate to the search page with retry and longer timeout
                logger.info(f"Navigating to {SEARCH_URL}")
                
                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        # Using 'commit' is faster and more robust against slow sub-resources
                        page.goto(SEARCH_URL, wait_until="commit", timeout=45000)
                        # Now wait for the actual input element to be ready
                        page.wait_for_selector("input[name='postcode']", timeout=30000)
                        break
                    except Exception as e:
                        if attempt == max_retries:
                            logger.error(f"Navigation to {SEARCH_URL} failed after {max_retries + 1} attempts")
                            raise
                        logger.warning(f"Navigation attempt {attempt + 1} failed: {e}. Retrying in 2s...")
                        time.sleep(2)

                time.sleep(1)

                # Step 1.5: Dismiss cookie consent if present
                try:
                    if page.locator(".fc-consent-root").is_visible(timeout=3000):
                        logger.info("Cookie consent banner detected")
                        # Try clicking the accept button first
                        accept_btn = page.locator(".fc-cta-consent")
                        if accept_btn.is_visible(timeout=2000):
                            accept_btn.click()
                            logger.info("Clicked cookie consent accept button")
                        else:
                            # Fallback: remove the overlay elements directly
                            page.evaluate("""() => {
                                const elements = document.querySelectorAll('.fc-consent-root, .fc-dialog-overlay');
                                elements.forEach(el => el.remove());
                                document.body.style.overflow = 'auto';
                            }""")
                            logger.info("Removed cookie consent overlays via JS fallback")
                except Exception as e:
                    logger.debug(f"Cookie consent dismissal skipped or failed: {e}")

                # Step 2: Fill postcode input
                logger.info(f"Filling postcode: {postcode}")
                page.fill("input[name='postcode']", postcode)
                time.sleep(0.5)

                # Step 3: Click the Search button
                logger.info("Submitting form")
                # Use JavaScript-based click to bypass pointer-event blocking from any remaining overlays
                page.eval_on_selector(
                    "input[name='search'], input[type='submit'], button[type='submit']",
                    "el => el.click()"
                )

                # Step 4: Wait for results to load
                logger.info("Waiting for results page to load")
                # Increased timeout for networkidle as well
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    logger.warning("Network did not go idle, proceeding anyway")
                
                time.sleep(2)

                # Wait for the results table to be present before parsing
                try:
                    # Increased timeout to 30s for the results table
                    page.wait_for_selector("table tr td", timeout=30000)
                    logger.info("Results table found")
                except Exception:
                    logger.warning("Timed out waiting for results table — parsing anyway")

                html = page.content()

                # Save debug HTML
                os.makedirs("debug", exist_ok=True)
                with open("debug/counciltax_last.html", "w", encoding="utf-8") as f:
                    f.write(html)

                logger.info(f"Saved results HTML to debug/counciltax_last.html")
                
                # Screenshot capture
                import time as _time
                from pathlib import Path
                 
                 # backend/scrapers/counciltax/scraper.py -> backend/static/screenshots
                _backend_dir = Path(__file__).parent.parent.parent
                _ss_dir = _backend_dir / "static" / "screenshots"
                _ss_dir.mkdir(parents=True, exist_ok=True)
                _ts = _time.strftime("%Y%m%d_%H%M%S")
                 
                _ss_name = f"counciltax_{_ts}.png"
                _ss_path = str(_ss_dir / _ss_name)
                
                screenshot_url = None
                try:
                    page.screenshot(path=_ss_path, full_page=True)
                    screenshot_url = f"/api/files/screenshots/{_ss_name}"
                    logger.info(f"Screenshot saved to: {_ss_path}")
                except Exception as e:
                    logger.warning(f"Failed to capture screenshot: {e}")
 
                return html, screenshot_url

            except Exception as e:
                # Save whatever we have for debugging
                try:
                    html = page.content()
                    os.makedirs("debug", exist_ok=True)
                    with open("debug/counciltax_last.html", "w", encoding="utf-8") as f:
                        f.write(html)
                except Exception:
                    pass
                raise RuntimeError(f"Council tax fetch failed: {e}") from e

            finally:
                browser.close()


