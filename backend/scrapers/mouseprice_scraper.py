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

# ── SCRAPER CLASS ────────────────────────────────────────────────────────────

class MousePriceScraper:
    """
    Production-grade scraper for mouseprice.com.
    
    Handles proxy rotation, session warmup, human-like delays, and 
    Cloudflare bypass logic using pure requests and BeautifulSoup.
    """

    def __init__(
        self,
        proxy_file: str = "webshare_proxies.txt",
        output_dir: str = "scraper_output",
        request_timeout: int = 30,
        min_delay: int = 12,
        max_delay: int = 28,
        max_retries: int = 4
    ):
        # Resolve paths relative to this script's directory if they are relative
        base_path = Path(__file__).parent
        self.proxy_file = base_path / proxy_file if not Path(proxy_file).is_absolute() else Path(proxy_file)
        self.output_dir = base_path / output_dir if not Path(output_dir).is_absolute() else Path(output_dir)
        
        self.request_timeout = request_timeout
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.base_url = "https://www.mouseprice.com"
        
        self.proxy_pool = self._load_proxies()
        self.ua = UserAgent()
        
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── PROXY MANAGEMENT ──────────────────────────────────────────────────────

    def _load_proxies(self) -> List[Dict[str, str]]:
        """Parses the proxy file and returns a list of proxy dictionaries."""
        if not self.proxy_file.exists():
            # Check one level up if not found (common in certain project structures)
            alt_path = self.proxy_file.parent.parent / self.proxy_file.name
            if alt_path.exists():
                self.proxy_file = alt_path
            else:
                raise FileNotFoundError(f"Proxy file not found at {self.proxy_file}")

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
            raise ValueError(f"No valid proxies found in {self.proxy_file}")
        
        logger.info(f"Loaded {len(proxies)} proxies from {self.proxy_file}")
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

    def _build_session(self, proxy: Dict[str, str]) -> requests.Session:
        """
        Creates a requests.Session with the provided proxy and random headers.
        
        WHY SESSIONS:
        1. TCP Connection Reuse: Reusing connections (keep-alive) reduces latency 
           and mimics browser behavior.
        2. Cookie Management: Sessions persist cookies across requests, which is 
           essential for multi-step navigation and bypassing basic anti-bot.
        """
        session = requests.Session()
        session.proxies = {k: v for k, v in proxy.items() if not k.startswith("_")}
        session.headers.update(self._get_headers())
        return session

    # ── CORE FETCH LOGIC ──────────────────────────────────────────────────────

    def fetch_page(self, url: str, session: Optional[requests.Session] = None) -> requests.Response:
        """
        Fetches a page with full retry logic and bot-bypass patterns.
        """
        # We need a wrapper to use tenacity with self
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=2, min=15, max=90),
            retry=(
                retry_if_exception_type(TooManyRequestsError) | 
                retry_if_exception_type(ProxyFailedError) | 
                retry_if_exception_type(requests.Timeout)
            ),
            before_sleep=before_sleep_log(logger, logging.INFO),
            reraise=True
        )
        def _do_fetch():
            proxy = self._get_random_proxy()
            _session = session if session else self._build_session(proxy)

            # 1. Warm up session
            if url != self.base_url:
                try:
                    logger.info(f"Warming up session on homepage for proxy {proxy['_label']}")
                    _session.get(self.base_url, timeout=self.request_timeout)
                    time.sleep(random.uniform(2, 5))
                except Exception as e:
                    raise ProxyFailedError(f"Warmup failed: {e}")

            # 2. Human-like delay
            delay = random.uniform(self.min_delay, self.max_delay)
            logger.info(f"Natural delay: {delay:.2f}s...")
            time.sleep(delay)

            # 3. Main request
            try:
                response = _session.get(url, timeout=self.request_timeout)
            except (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout) as e:
                raise ProxyFailedError(f"Proxy error: {e}")
            except requests.exceptions.RequestException as e:
                raise

            # 4. Status checks
            if response.status_code == 429:
                raise TooManyRequestsError("Rate limited")
            
            if response.status_code == 403:
                raise ScraperBlockedError("403 Blocked")

            content_lower = response.text.lower()
            if "cf-browser-verification" in content_lower or "ray id" in content_lower:
                raise ScraperBlockedError("Cloudflare challenge")

            return response

        return _do_fetch()

    # ── PERSISTENCE ──────────────────────────────────────────────────────────────

    def save_html(self, html_content: str, label: str) -> Path:
        """Saves HTML content to the output directory."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{label}_{timestamp}.html"
        file_path = self.output_dir / filename
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        logger.info(f"HTML saved: {file_path}")
        return file_path

    def _save_screenshot(self, html_file_path: Path, label: str) -> Optional[str]:
        """
        Render the locally-saved HTML file via Playwright and save as PNG.
        Uses a local file:// URL so Cloudflare is never involved.
        Returns a relative URL like /static/screenshots/<filename>, or None on failure.
        """
        try:
            from playwright.sync_api import sync_playwright

            # Resolve the screenshots directory relative to the backend root
            # backend/scrapers/mouseprice_scraper.py -> backend/ -> backend/static/screenshots/
            screenshots_dir = Path(__file__).parent.parent / "static" / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"mouseprice_{label}_{timestamp}.png"
            screenshot_path = screenshots_dir / screenshot_name

            # Render the local HTML file (no network, no Cloudflare)
            file_url = html_file_path.resolve().as_uri()

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(file_url, wait_until="domcontentloaded")
                page.screenshot(path=str(screenshot_path), full_page=False)
                browser.close()

            logger.info(f"Screenshot saved: {screenshot_path}")
            return f"/static/screenshots/{screenshot_name}"

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
        title = soup.title.string.strip().lower() if soup.title else ""
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
        response = self.fetch_page(self.base_url)
        soup = BeautifulSoup(response.text, "html.parser")
        
        title = soup.title.string.strip() if soup.title else "N/A"
        desc = soup.find("meta", attrs={"name": "description"})
        meta_desc = desc.get("content", "").strip() if desc else ""
        
        html_file = self.save_html(response.text, "homepage")
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
        
        logger.info(f"Scraping postcode: {postcode}")
        response = self.fetch_page(url)
        soup = BeautifulSoup(response.text, "html.parser")
        file_label = clean_pc.replace(" ", "")
        html_file = self.save_html(response.text, f"postcode_{file_label}")

        # Take a screenshot of the locally-rendered page (no Cloudflare risk)
        screenshot_url = self._save_screenshot(html_file, file_label)

        # Detect no-results / redirect-to-homepage conditions
        no_results, no_results_reason = self._detect_no_results(soup)

        if no_results:
            logger.warning(f"No results for {postcode}: {no_results_reason}")
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
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("mouseprice_scraper.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    
    try:
        scraper = MousePriceScraper(proxy_file="webshare_proxies.txt")
        
        print("\n--- Testing Homepage ---")
        hp = scraper.scrape_homepage()
        print(json.dumps(hp, indent=2))
        
        print("\n--- Testing Postcode (W1T 4JT) ---")
        pc = scraper.scrape_postcode("W1T 4JT")
        print(json.dumps(pc, indent=2))
        
    except Exception as e:
        logger.exception("Fatal error")
        print(f"\n[FATAL] {e}")
