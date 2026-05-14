import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from .models import EiirQuery, EiirResult, EiirRecord
from .parser import parse_results, parse_detail, parse_no_results_message
from ..common.browser import get_browser_args
from app.core.s3 import upload_screenshot_to_s3_sync

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.insolvencydirect.bis.gov.uk/eiir/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


class EiirScraper:
    """
    Scraper for the UK Individual Insolvency Register.

    Drives the search form at insolvencydirect.bis.gov.uk/eiir/search with
    Playwright (the site sits behind a WAF and rejects plain HTTP clients),
    parses the result table, and optionally follows each result into its
    detail page to capture the full set of fields.
    """

    def __init__(self, config=None, headless: bool = True):
        self.config = config
        self.headless = headless

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def lookup(self, forename: str, surname: str, follow_details: bool = True) -> EiirResult:
        query = EiirQuery(forename=forename, surname=surname, follow_details=follow_details)
        return self.search(query)

    def search(self, query: EiirQuery) -> EiirResult:
        search_term = f"{query.forename} {query.surname}".strip()
        result = EiirResult(
            search_term=search_term,
            forename=query.forename,
            surname=query.surname,
            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        if not search_term:
            result.error = "search_term is empty — provide a forename and/or surname"
            return result

        logger.info("Starting EIIR search for '%s'", search_term)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless, args=get_browser_args())
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1440, "height": 900},
                )
                page = context.new_page()

                try:
                    page.goto(SEARCH_URL, wait_until="commit", timeout=45000)
                    page.wait_for_selector("input#searchTerm", timeout=20000)

                    page.fill("input#searchTerm", search_term)
                    page.click("button#searchButton")

                    try:
                        page.wait_for_load_state("networkidle", timeout=20000)
                    except PlaywrightTimeoutError:
                        logger.warning("Network did not go idle after search submit — continuing")

                    html = page.content()

                    os.makedirs("debug", exist_ok=True)
                    with open("debug/eiir_last.html", "w", encoding="utf-8") as f:
                        f.write(html)

                    records = parse_results(html)

                    if not records:
                        result.error = parse_no_results_message(html) or "No EIIR records found"
                    else:
                        if query.follow_details:
                            self._enrich_with_details(page, records)
                        result.records = records

                    try:
                        screenshot_bytes = page.screenshot(full_page=True)
                        ts = time.strftime("%Y%m%d_%H%M%S")
                        ss_name = f"eiir_{ts}.png"
                        result.screenshot_url = upload_screenshot_to_s3_sync(screenshot_bytes, ss_name)
                    except Exception as e:
                        logger.warning("EIIR screenshot upload failed: %s", e)

                    return result

                finally:
                    browser.close()

        except Exception as e:
            logger.error("EIIR scrape failed: %s", e, exc_info=True)
            result.error = str(e)
            return result

    def _enrich_with_details(self, page, records: list[EiirRecord]) -> None:
        """
        For each record with a detail_url, navigate to that page, parse the
        summary list, and populate the record's detail fields. Errors on
        individual records are logged but do not abort the batch.
        """
        for record in records:
            if not record.detail_url:
                continue
            try:
                page.goto(record.detail_url, wait_until="domcontentloaded", timeout=20000)
                try:
                    page.wait_for_selector("dl, table", timeout=10000)
                except PlaywrightTimeoutError:
                    pass

                detail_html = page.content()
                fields = parse_detail(detail_html)
                record.detail_fields = fields

                for key, value in fields.items():
                    k = key.lower()
                    if "birth" in k:
                        record.date_of_birth = value
                    elif "address" in k:
                        record.last_known_address = value
                    elif "practitioner" in k or "trustee" in k:
                        record.insolvency_practitioner = value
                    elif "court" in k and not record.court:
                        record.court = value
                    elif ("case" in k or "number" in k) and not record.case_number:
                        record.case_number = value
                    elif "type" in k and not record.insolvency_type:
                        record.insolvency_type = value
                    elif "status" in k and not record.status:
                        record.status = value
            except Exception as e:
                logger.warning("Failed to load EIIR detail page %s: %s", record.detail_url, e)
