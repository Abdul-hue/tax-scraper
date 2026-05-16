import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
import sys
from pathlib import Path

# Add the backend directory to sys.path so 'app' can be imported when run directly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.append(str(backend_dir))

from app.core.s3 import upload_screenshot_to_s3_sync
from playwright_stealth import Stealth

# ── CONFIGURATION & LOGGING ──────────────────────────────────────────────────

logger = logging.getLogger(__name__)

# ── CUSTOM EXCEPTIONS ────────────────────────────────────────────────────────

class TooManyRequestsError(Exception):
    """Raised when the server returns a 429 status code."""
    pass

class ScraperBlockedError(Exception):
    """Raised when the scraper is blocked by Cloudflare or 403."""
    pass

class ProxyFailedError(Exception):
    """Raised when a proxy connection fails or times out."""
    pass

class ProxyAuthError(Exception):
    """Raised when ALL proxies return 407 Proxy Authentication Required."""
    pass

# ── SCRAPER CLASS ────────────────────────────────────────────────────────────

class MousePriceScraper:
    """
    Production-grade scraper for mouseprice.com.
    
    Handles proxy rotation, session warmup, human-like delays, and 
    Cloudflare bypass logic using pure requests and BeautifulSoup.
    """

    def __init__(
        self,
        proxy_file: Optional[str] = None,   # FIXED: was "webshare_proxies.txt" — now optional; proxies only loaded when explicitly provided
        output_dir: str = "scraper_output",
        request_timeout: int = 30,
        min_delay: int = 18,   # FIXED: raised from 12 — Anubis more likely to block rapid requests
        max_delay: int = 40,   # FIXED: raised from 28 — ditto
        max_retries: int = 3,  # FIXED: was 4
        headless: bool = True
    ):
        # Resolve paths relative to this script's directory if they are relative
        base_path = Path(__file__).parent
        # FIXED: proxy_file is now Optional[str]; only resolve path when a value is given
        if proxy_file:
            self.proxy_file: Optional[Path] = base_path / proxy_file if not Path(proxy_file).is_absolute() else Path(proxy_file)
        else:
            self.proxy_file = None  # FIXED: no proxy file — will run direct
        self.output_dir = base_path / output_dir if not Path(output_dir).is_absolute() else Path(output_dir)
        
        self.request_timeout = request_timeout
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.headless = headless
        self.base_url = "https://www.mouseprice.com"
        
        # FIXED: only load proxies if a file path was given
        self.proxy_pool = self._load_proxies() if proxy_file else []
        if not self.proxy_pool:
            logger.info("🚀 No proxies configured — running in direct (no-proxy) mode.")
        self.ua = UserAgent()
        
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── PROXY MANAGEMENT ──────────────────────────────────────────────────────

    def _load_proxies(self) -> List[Dict[str, str]]:
        """Parses the proxy file and returns a list of proxy dictionaries."""
        # FIXED: return [] instead of raising FileNotFoundError when no file is configured or file missing
        if not self.proxy_file or not Path(self.proxy_file).exists():
            logger.info("No proxy file found — skipping proxy loading.")
            return []

        proxies = []
        with open(self.proxy_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                parts = line.split(":")
                if len(parts) != 4:
                    logger.warning(f"Skipping invalid proxy line: {line}")
                    continue
                
                host, port, user, password = parts
                proxy_url = f"http://{user}:{password}@{host}:{port}"
                proxies.append({
                    "http": proxy_url,
                    "https": proxy_url,
                    "_label": f"{host}:{port}"
                })

        if not proxies:
            logger.warning(f"No valid proxies found in {self.proxy_file} — running direct.")  # FIXED: warn instead of raise
            return []
        
        logger.info(f"✅ Successfully loaded {len(proxies)} proxies from {self.proxy_file.name}")
        return proxies

    def _get_random_proxy(self) -> Dict[str, str]:
        """Returns a random proxy dictionary from the pool."""
        proxy = random.choice(self.proxy_pool)
        logger.debug(f"Selected proxy: {proxy['_label']}")
        return proxy

    # ── HEADER & SESSION MANAGEMENT ───────────────────────────────────────────

    def _get_headers(self) -> Dict[str, str]:
        """Generates realistic browser headers."""
        languages = [
            "en-GB,en;q=0.9,en-US;q=0.8",
            "en-US,en;q=0.9",
            "en-GB,en-GB;q=0.9,en;q=0.8"
        ]
        return {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": random.choice(languages),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "DNT": "1"
        }

    # ── CORE FETCH LOGIC ──────────────────────────────────────────────────────

    def _is_anubis_page(self, content: str) -> bool:
        """Returns True if the page content looks like an Anubis challenge page."""
        # FIXED: replaced single-string check with multi-signal detection
        content_lower = content.lower()
        signals = [
            "anubis",
            "proof of work",
            "proof-of-work",
            "making sure you're not a bot",
            "checking your browser",
            "please wait while we verify",
            "window._anubis",
            "anubis_challenge",
        ]
        return any(s in content_lower for s in signals)

    def _wait_for_anubis_to_clear(self, page, timeout_ms: int = 60000) -> bool:
        """
        Wait for Anubis challenge to complete. Polls multiple signals.
        Returns True if real page loaded, False if timed out.
        """
        # FIXED: replaced single #anubis_challenge selector with JS multi-signal poll
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        logger.info("🛡️  Anubis detected — waiting for JS proof-of-work (up to %ds)...", timeout_ms // 1000)
        try:
            # Wait until NONE of the known Anubis signals are present in the page
            page.wait_for_function(
                """() => {
                    const html = document.documentElement.innerHTML.toLowerCase();
                    const signals = [
                        'anubis', 'proof of work', 'proof-of-work',
                        'making sure you', 'checking your browser',
                        'please wait while we verify', 'window._anubis',
                        'anubis_challenge'
                    ];
                    return !signals.some(s => html.includes(s));
                }""",
                timeout=timeout_ms
            )
            # Extra wait for the real page to settle after redirect
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            logger.info("✅ Anubis challenge cleared.")
            return True
        except PlaywrightTimeoutError:
            logger.warning("⏰ Anubis did not clear within %ds.", timeout_ms // 1000)
            return False
        except Exception as e:
            logger.warning("⚠️  Anubis wait error: %s", e)
            return False

    def _fetch_direct_playwright(self, url: str) -> str:
        """
        Fetch a page using Playwright with NO proxy — last resort fallback.
        Warms up on the homepage first to look like a real user, then navigates
        to the target URL. Playwright runs the Anubis JS challenge automatically.
        """
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

        logger.info("🚀 Initiating Direct Playwright fetch (No Proxy) to bypass persistent blocks: %s", url)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent=self.ua.random,
                viewport={"width": 1280, "height": 900},
                locale="en-GB",
                extra_http_headers={
                    "Accept-Language": "en-GB,en;q=0.9",
                    "DNT": "1",
                }
            )
            page = context.new_page()
            # FIXED: Apply stealth to bypass bot detection (Anubis, etc.)
            Stealth().apply_stealth_sync(page)
            try:
                # Step 1: Warm up on the homepage first (mimics a real user)
                if url != self.base_url:
                    logger.info("🏠 Warming up on homepage to mimic human behavior: %s", self.base_url)
                    try:
                        page.goto(self.base_url, wait_until="domcontentloaded", timeout=self.request_timeout * 1000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=15000)
                        except PlaywrightTimeoutError:
                            pass

                        # Handle Anubis on homepage too
                        hp_content = page.content()
                        if self._is_anubis_page(hp_content):  # FIXED: use multi-signal helper
                            self._wait_for_anubis_to_clear(page, timeout_ms=60000)  # FIXED: 60s timeout

                        # Brief human-like pause before navigating to target
                        page.wait_for_timeout(random.randint(1500, 3000))
                    except Exception as warmup_err:
                        logger.warning("Homepage warmup failed (non-fatal): %s", warmup_err)

                # Step 2: Navigate to the actual target URL
                logger.info("🎯 Navigating to target property page: %s", url)
                page.goto(url, wait_until="domcontentloaded", timeout=self.request_timeout * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except PlaywrightTimeoutError:
                    logger.debug("Direct fetch: networkidle timeout — continuing anyway")

                # FIXED: check for Anubis FIRST, then wait for it to clear before confirming SVGs
                content = page.content()
                if self._is_anubis_page(content):  # FIXED: use multi-signal helper
                    cleared = self._wait_for_anubis_to_clear(page, timeout_ms=60000)  # FIXED: 60s timeout
                    if cleared:  # FIXED: human-like pause after challenge clears
                        page.wait_for_timeout(random.randint(1500, 3000))
                    content = page.content()

                # FIXED: confirm real data SVGs are present after Anubis has cleared
                try:
                    page.wait_for_selector("svg.circular-chart", timeout=20000)
                    logger.info("✅ SVG charts confirmed — real page loaded.")
                except Exception:
                    logger.warning("⚠️  SVG charts not found — page may be partial.")

                content = page.content()
                return content
            finally:
                browser.close()


    def _do_fetch_with_proxy(self, url: str) -> str:
        """
        FIXED: Extracted from fetch_page — runs the proxy-based Playwright fetch
        with tenacity retry. Raises on exhaustion so fetch_page can fall back to direct.
        """
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

        proxy_auth_failures = 0

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=5, max=30),
            retry=(
                retry_if_exception_type(ProxyFailedError) |
                retry_if_exception_type(PlaywrightTimeoutError)
            ),
            before_sleep=before_sleep_log(logger, logging.INFO),
            reraise=True
        )
        def _do_fetch():
            nonlocal proxy_auth_failures
            proxy_dict = self._get_random_proxy()

            pw_proxy: dict | None = None
            if "http" in proxy_dict:
                from urllib.parse import urlparse
                parsed = urlparse(proxy_dict["http"])
                pw_proxy = {
                    "server": f"{parsed.hostname}:{parsed.port}",
                    "username": parsed.username or "",
                    "password": parsed.password or "",
                }

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(
                    proxy=pw_proxy,  # type: ignore
                    user_agent=self.ua.random,
                    viewport={"width": 1280, "height": 900}
                )
                page = context.new_page()
                # FIXED: Apply stealth to bypass bot detection
                Stealth().apply_stealth_sync(page)
                try:
                    logger.info("🌐 [Proxy %s] Navigating to %s", proxy_dict['_label'], url)
                    try:
                        response = page.goto(
                            url, wait_until="domcontentloaded",
                            timeout=self.request_timeout * 1000
                        )
                    except Exception as nav_err:
                        err_str = str(nav_err)
                        proxy_auth_failures += 1
                        logger.warning(
                            "Proxy %s navigation failed (total failures: %d): %s",
                            proxy_dict['_label'], proxy_auth_failures, err_str[:150]
                        )
                        raise ProxyFailedError(f"Proxy nav error: {nav_err}")

                    if response and response.status == 429:
                        raise ProxyFailedError("Rate limited via proxy")
                    if response and response.status == 403:
                        raise ProxyFailedError("403 via proxy")

                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except PlaywrightTimeoutError:
                        logger.debug("Networkidle timeout — continuing anyway")

                    content = page.content()

                    if self._is_anubis_page(content):
                        cleared = self._wait_for_anubis_to_clear(page, timeout_ms=60000)
                        if not cleared or self._is_anubis_page(page.content()):
                            raise ProxyFailedError("Anubis persists through proxy — rotating")

                        try:
                            page.wait_for_selector("svg.circular-chart", timeout=15000)
                        except Exception:
                            logger.warning("SVGs not found after Anubis cleared — content may be partial")

                        page.wait_for_timeout(random.randint(800, 2000))
                        content = page.content()

                    if "cf-browser-verification" in content.lower():
                        raise ProxyFailedError("Cloudflare JS challenge via proxy")

                    return content
                finally:
                    browser.close()

        return _do_fetch()

    def fetch_page(self, url: str) -> str:
        """
        FIXED: Direct (no-proxy) mode is now the primary path.
        Proxy mode is only used when self.proxy_pool is non-empty, with direct as fallback.
        """
        if not self.proxy_pool:
            # FIXED: No proxies configured — go direct immediately (was: try proxies first)
            logger.info("📡 Direct mode: fetching %s", url)
            return self._fetch_direct_playwright(url)
        else:
            # FIXED: Proxy mode — try proxies with retry, fall back to direct on total failure
            try:
                return self._do_fetch_with_proxy(url)
            except Exception as exc:
                logger.warning("⚠️  All proxies failed. Falling back to direct. Error: %s", exc)
                return self._fetch_direct_playwright(url)


    # ── PERSISTENCE ──────────────────────────────────────────────────────────────

    def save_html(self, html_content: str, label: str) -> Path:
        """Saves HTML content to the output directory."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{label}_{timestamp}.html"
        file_path = self.output_dir / filename
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        logger.info(f"💾 HTML content persisted to local cache: {file_path}")
        return file_path

    def _save_screenshot(self, html_file_path: Path, label: str) -> Optional[str]:
        """
        Render the locally-saved HTML file via Playwright and upload PNG to S3.
        Uses a local file:// URL so Cloudflare is never involved.
        Returns a public S3 URL, or None on failure.
        """
        try:
            from playwright.sync_api import sync_playwright

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"mouseprice_{label}_{timestamp}.png"

            # Render the local HTML file (no network, no Cloudflare)
            file_url = html_file_path.resolve().as_uri()

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(file_url, wait_until="domcontentloaded")
                screenshot_bytes = page.screenshot(full_page=False)
                browser.close()

            screenshot_url = upload_screenshot_to_s3_sync(screenshot_bytes, screenshot_name)
            logger.info("📸 Page screenshot captured and uploaded to S3: %s", screenshot_url)
            return screenshot_url

        except Exception as e:
            logger.warning(f"Screenshot failed (non-fatal): {e}")
            return None

    def _detect_no_results(self, soup: BeautifulSoup) -> tuple:
        """
        Check if the page shows a 'no results' or redirect-to-homepage condition.
        Returns (no_results: bool, reason: str).
        """
        text = soup.get_text(separator=" ", strip=True).lower()

        # Check for explicit no-results messages from Mouseprice
        no_result_phrases = [
            "no results found for your query",
            "no results found for this location",
            "no properties found",
            "please broaden your search",
        ]
        for phrase in no_result_phrases:
            if phrase in text:
                return True, (
                    "No property sales data was found for this postcode. "
                    "This usually means it is a non-residential address (e.g. government, "
                    "royal, or commercial) with no recorded transactions, or the postcode "
                    "is too new / too rural to have sales history on Mouseprice."
                )

        # Check if we landed back on the homepage (no postcode in title)
        title = (soup.title.string or "").strip().lower() if soup.title else ""
        if "house prices" in title and "in" not in title:
            return True, (
                "The postcode page was not found — Mouseprice redirected to the homepage. "
                "Please verify the postcode is correct and in UK format (e.g. SW10 0AA)."
            )

        return False, ""


    # ── SCRAPERS ──────────────────────────────────────────────────────────────

    def scrape_homepage(self) -> Dict[str, Any]:
        """Scrapes metadata from the homepage."""
        logger.info("Scraping homepage...")
        html_content = self.fetch_page(self.base_url)
        soup = BeautifulSoup(html_content, "html.parser")
        
        title = (soup.title.string or "").strip() if soup.title else "N/A"
        desc = soup.find("meta", attrs={"name": "description"})
        meta_content = desc.get("content", "") if desc else ""
        meta_desc = "".join(meta_content).strip() if isinstance(meta_content, list) else meta_content.strip() if meta_content else ""
        
        html_file = self.save_html(html_content, "homepage")
        return {"title": title, "meta_description": meta_desc, "html_file": str(html_file)}

    # ── PARSING HELPERS ───────────────────────────────────────────────────────

    def debug_chart_svgs(self, soup: BeautifulSoup) -> None:
        """
        Print all circular-chart SVGs and their tspan contents to the logger.
        Call this when parse_success is False to diagnose selector failures.
        """
        svgs = soup.find_all("svg", class_="circular-chart")
        logger.debug(f"[debug_chart_svgs] Found {len(svgs)} .circular-chart SVG(s)")
        for i, svg in enumerate(svgs):
            text_el = svg.find("text")
            if text_el:
                tspans = [ts.get_text(strip=True) for ts in text_el.find_all("tspan")]
                logger.debug(f"  SVG[{i}] tspans: {tspans}")
            else:
                logger.debug(f"  SVG[{i}] has no <text> element")

    def parse_postcode_summary(self, soup: BeautifulSoup) -> dict:
        """
        Extract the three summary stats from the SVG circular charts.

        Strategy:
          1. Find all <svg class="circular-chart"> elements
          2. For each SVG, read all <tspan> children inside the first <text> block
          3. The second tspan is the label (e.g. "avg price", "sold", "avg psqm")
          4. The first tspan is the value
          5. Match label → assign to the correct output field

        Returns dict with keys:
          number_of_sales  (str, e.g. "5")
          average_price    (str, e.g. "£3,825,000")
          avg_psqm         (str, e.g. "£22,859")
          parse_success    (bool) - False if none of the three were found
        """
        # If this breaks, check saved HTML for changes to svg structure
        result = {
            "number_of_sales": "N/A",
            "average_price": "N/A",
            "avg_psqm": "N/A",
            "parse_success": False,
        }

        svgs = soup.find_all("svg", class_="circular-chart")
        logger.debug(f"parse_postcode_summary: found {len(svgs)} .circular-chart SVG(s)")

        for svg in svgs:
            text_el = svg.find("text")
            if not text_el:
                continue

            tspans = text_el.find_all("tspan")
            if len(tspans) < 2:
                continue

            value = tspans[0].get_text(strip=True)
            label = tspans[1].get_text(strip=True).lower()

            if label == "sold":
                result["number_of_sales"] = value
                result["parse_success"] = True
            elif label == "avg price":
                result["average_price"] = value
                result["parse_success"] = True
            elif label == "avg psqm":
                result["avg_psqm"] = value
                result["parse_success"] = True

        if not result["parse_success"]:
            logger.warning(
                "parse_postcode_summary: no data extracted — HTML structure may have changed. "
                "Check saved HTML and run debug_chart_svgs() for details."
            )
            self.debug_chart_svgs(soup)

        return result

    def scrape_postcode(self, postcode: str) -> Dict[str, Any]:
        """Scrapes property metrics for a given postcode from SVG circular charts."""
        clean_pc = postcode.strip().upper()
        # Mouseprice URL format: /house-prices/SW10+0AA/ (space → +, uppercase)
        # The summary section on this page contains the circular SVG charts.
        # /area/SW100AA/ returns HTTP 404 — do not use that format.
        encoded_pc = clean_pc.replace(" ", "+")
        url = f"{self.base_url}/house-prices/{encoded_pc}/"
        
        logger.info(f"🔍 Scraping postcode: {postcode}")
        try:
            html_content = self.fetch_page(url)
            soup = BeautifulSoup(html_content, "html.parser")
            file_label = clean_pc.replace(" ", "")
            html_file = self.save_html(html_content, f"postcode_{file_label}")

            # Take a screenshot of the locally-rendered page (no Cloudflare risk)
            screenshot_url = self._save_screenshot(html_file, file_label)

            # Detect no-results / redirect-to-homepage conditions
            no_results, no_results_reason = self._detect_no_results(soup)

            if no_results:
                logger.warning(f"⚠️  No results for {postcode}: {no_results_reason}")
                return {
                    "postcode": postcode,
                    "number_of_sales": "N/A",
                    "average_price": "N/A",
                    "avg_psqm": "N/A",
                    "parse_success": False,
                    "no_results": True,
                    "no_results_reason": no_results_reason,
                    "url": url,
                    "html_file": str(html_file),
                    "screenshot_url": screenshot_url,
                }

            summary = self.parse_postcode_summary(soup)

            return {
                "postcode": postcode,
                "number_of_sales": summary["number_of_sales"],
                "average_price": summary["average_price"],
                "avg_psqm": summary["avg_psqm"],
                "parse_success": summary["parse_success"],
                "no_results": False,
                "no_results_reason": "",
                "url": url,
                "html_file": str(html_file),
                "screenshot_url": screenshot_url,
            }
        except Exception as e:
            import traceback
            err_msg = f"Error scraping postcode {postcode}: {str(e)}"
            logger.error(f"❌ {err_msg}\n{traceback.format_exc()}")
            return {
                "postcode": postcode,
                "error": str(e),
                "parse_success": False,
                "status": "error",
                "message": err_msg,
                "traceback": traceback.format_exc()
            }

    def scrape_property_detail(self, property_url: str) -> Dict[str, Any]:
        """
        Stub for property detail scraping.
        
        Expected shape: {address: str, last_sold_price: str, ...}
        """
        return {"url": property_url, "status": "todo"}

# ── MAIN TEST BLOCK ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Setup logging for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("mouseprice_scraper.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    
    try:
        scraper = MousePriceScraper(headless=False)  # FIXED: headless=False for visual debugging
        
        print("\n--- Testing Homepage ---")
        hp = scraper.scrape_homepage()
        print(json.dumps(hp, indent=2))
        
        print("\n--- Testing Postcode (LN6 9XY) ---")
        pc = scraper.scrape_postcode("LN6 9XY")
        print(json.dumps(pc, indent=2))
        
    except Exception as e:
        logger.exception("Fatal error")
        print(f"\n[FATAL] {e}")
