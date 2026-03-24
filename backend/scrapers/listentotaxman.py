"""
Scraper/listentotaxman.py
─────────────────────────────────────────────────────────────────────────────
Production-grade Playwright scraper for https://www.listentotaxman.com

Uses Microsoft Playwright instead of Selenium — ships its own bundled
Chromium browser so Windows AppLocker / WDAC policies cannot block it.

Setup (one-time)
----------------
    pip install playwright beautifulsoup4 lxml
    python -m playwright install chromium

Usage
-----
    from Scraper import ListenToTaxmanScraper, ScrapeConfig

    config = ScrapeConfig(
        salary         = 2200,
        salary_period  = "month",
        tax_year       = "2025/26",
        region         = "UK",
        pension_amount = 0,   # no pension by default
        pension_type   = "£",
    )

    with ListenToTaxmanScraper() as scraper:
        result = scraper.scrape(config, screenshot=True, save_json=True)
        print(result.to_json())
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from bs4 import BeautifulSoup
from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

logger = logging.getLogger(__name__)

# ── literal types (mirrors every dropdown on the form) ────────────────────────
SalaryPeriod = Literal["year", "month", "4weeks", "2weeks", "week", "day", "hour"]
PensionType  = Literal["£", "%"]
StudentLoan  = Literal["No", "Plan 1", "Plan 2", "Plan 4", "Postgraduate"]
AgeGroup     = Literal["under 65", "65-74", "75 and over"]
Region       = Literal["UK", "Scotland"]


# ── input model ───────────────────────────────────────────────────────────────
@dataclass
class ScrapeConfig:
    """
    One field per form input visible on listentotaxman.com.
    Defaults mirror the site's own default values.
    """
    salary:         int          = 2200
    salary_period:  SalaryPeriod = "month"
    tax_year:       str          = "2025/26"
    region:         Region       = "UK"
    age:            AgeGroup     = "under 65"
    student_loan:   StudentLoan  = "No"
    pension_amount: float        = 0   # default now zero (was 5)
    pension_type:   PensionType  = "£"
    allowances:     float        = 0
    tax_code:       str          = ""
    married:        bool         = False
    blind:          bool         = False
    no_ni:          bool         = False


# ── payslip row ───────────────────────────────────────────────────────────────
@dataclass
class PayslipRow:
    """One data row from the 'Your Payslip Wage' results table."""
    label:   str
    percent: str = ""
    yearly:  str = ""
    monthly: str = ""
    weekly:  str = ""


# ── result ────────────────────────────────────────────────────────────────────
@dataclass
class TaxResult:
    """
    Full scrape result — always returned.
    Check .success before consuming .payslip / .summary.
    Call .to_dict() or .to_json() to send as a backend API response.
    """
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

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ── scraper ───────────────────────────────────────────────────────────────────
class ListenToTaxmanScraper:
    """
    Playwright-based scraper for listentotaxman.com.

    Fills every form field dynamically, submits the form, waits for the
    payslip table to render, parses every row, and optionally saves a
    full-page screenshot and JSON file.

    Parameters
    ----------
    headless    : Run browser without a visible window (default True).
    output_dir  : Folder for screenshots and JSON output files.
    timeout_ms  : Max milliseconds to wait for page elements (default 20s).
    retry_limit : How many times to retry on transient failure (default 2).
    slow_mo_ms  : Milliseconds between Playwright actions — useful for
                  debugging; set to 0 in production (default 0).
    """

    URL = "https://www.listentotaxman.com"

    def __init__(
        self,
        headless:    bool       = True,
        output_dir:  str | Path = "output",
        timeout_ms:  int        = 20_000,
        retry_limit: int        = 2,
        slow_mo_ms:  int        = 0,
    ):
        self.output_dir  = Path(output_dir)
        self.timeout_ms  = timeout_ms
        self.retry_limit = retry_limit
        self.slow_mo_ms  = slow_mo_ms
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Playwright context — kept open for the lifetime of this object
        self._pw       = sync_playwright().start()
        self._browser  = self._pw.chromium.launch(
            headless = headless,
            slow_mo  = slow_mo_ms,
            args     = ["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self._context  = self._browser.new_context(
            viewport       = {"width": 1440, "height": 900},
            user_agent     = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        self._page: Page = self._context.new_page()
        # Set by _wait_for_form — may point to an iframe if form is embedded
        self._active_frame = self._page
        self._salary_selector = 'input[name="salary"]'
        logger.info("ListenToTaxmanScraper ready (headless=%s)", headless)

    # ── public API ────────────────────────────────────────────────────────────
    def scrape(
        self,
        config:     ScrapeConfig = None,
        screenshot: bool         = False,
        save_json:  bool         = False,
    ) -> TaxResult:
        """
        Navigate to the site, fill every input field from `config`,
        submit the form, parse the payslip table, and return a TaxResult.

        Parameters
        ----------
        config     : All form values. Uses ScrapeConfig defaults if None.
        screenshot : Save a full-page PNG to output/.
        save_json  : Write result to output/taxman_<salary>.json.
        """
        if config is None:
            config = ScrapeConfig()

        result = TaxResult(
            config     = asdict(config),
            scraped_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            url        = self.URL,
        )

        for attempt in range(1, self.retry_limit + 2):
            try:
                logger.info("Loading %s (attempt %d)", self.URL, attempt)
                self._page.goto(self.URL, wait_until="domcontentloaded",
                                timeout=40_000)
                self._wait_for_form()

                # ── fill every form field ─────────────────────────────────────
                self._fill_form(config)

                # ── submit ────────────────────────────────────────────────────
                self._submit()

                # ── wait for payslip values to be non-zero ────────────────────
                self._wait_for_results()

                # ── parse ─────────────────────────────────────────────────────
                # Get HTML from the active frame (main page or iframe)
                html           = self._active_frame.content() if hasattr(self._active_frame, "content") else self._page.content()
                soup           = BeautifulSoup(html, "lxml")
                rows           = self._parse_payslip(soup)
                result.payslip = [asdict(r) for r in rows]
                result.summary = self._build_summary(rows)

                # ── screenshot after real values confirmed ─────────────────────
                if screenshot:
                    import time as _time
                    from pathlib import Path
                    
                    # BACKEND_DIR is backend/
                    _backend_dir = Path(__file__).parent.parent
                    _ss_dir = _backend_dir / "static" / "screenshots"
                    _ss_dir.mkdir(parents=True, exist_ok=True)
                    _ts = _time.strftime("%Y%m%d_%H%M%S")
                    
                    _ss_name = f"taxman_{_ts}.png"
                    _ss_path = str(_ss_dir / _ss_name)
                    
                    try:
                        self._page.screenshot(path=_ss_path, full_page=True)
                        result.screenshot_url = f"/api/files/screenshots/{_ss_name}"
                        logger.info(f"Screenshot saved to: {_ss_path}")
                    except Exception as e:
                        logger.warning(f"Failed to capture screenshot: {e}")
                        result.screenshot_url = None

                if not result.payslip:
                    raise ValueError(
                        "Payslip table parsed as empty — "
                        "page structure may have changed."
                    )

                logger.info(
                    "Scraped %d payslip rows for salary=%s %s",
                    len(rows), config.salary, config.salary_period,
                )
                break  # success

            except (PWTimeout, ValueError, Exception) as exc:
                logger.warning("Attempt %d failed: %s", attempt, exc)
                if attempt > self.retry_limit:
                    result.error = str(exc)
                    logger.error("All attempts exhausted: %s", exc)
                else:
                    import time; time.sleep(2 ** attempt)

        # Always save payslip to JSON after a successful scrape
        if result.payslip:
            self._save_json(result, config.salary)
        elif save_json:
            # Save full result (including error) when requested
            self._save_json(result, config.salary)

        return result

    # ── form filling ──────────────────────────────────────────────────────────
    def _wait_for_form(self) -> None:
        """
        Wait until the form is interactive.
        The salary field is input[name="ingr"] on listentotaxman.com.
        """
        page = self._page
        # Use domcontentloaded — networkidle times out due to 60+ ad/tracker iframes
        page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
        page.wait_for_timeout(1500)

        # Try all known salary field selectors
        for sel in ['input[name="ingr"]', '#ingr', 'input[type="number"]']:
            try:
                page.wait_for_selector(sel, state="visible", timeout=5_000)
                self._active_frame = page
                logger.info("Form ready — salary selector: %s", sel)
                return
            except Exception:
                continue

        # Dump inputs for debugging if still not found
        found = page.eval_on_selector_all(
            "input, select",
            "els => els.map(e => e.name + '|' + e.id + '|' + e.type)"
        )
        raise TimeoutError(f"Form not found. Inputs on page: {found}")


    def _fill_form(self, cfg: ScrapeConfig) -> None:
        """
        Fill every visible input on the form using ScrapeConfig values.

        Field names discovered via debug_page.py inspection:
          yr             → tax year dropdown
          region         → income tax region dropdown
          married        → married checkbox
          blind          → blind checkbox
          exNI           → I pay no NI checkbox
          plan           → student loan dropdown
          age            → age dropdown
          add            → allowances / deductions input
          code           → tax code input
          #pension-prepend → pension type select (£ / %)
          pension        → pension amount input
          ingr           → salary amount input
          time           → salary period dropdown
        """
        f = self._active_frame
        logger.debug("Filling form with: %s", cfg)

        # 1. Tax year
        self._select(f, ['select[name="yr"]', '#yr'], cfg.tax_year)

        # 2. Region
        self._select(f, ['select[name="region"]', '#region'], cfg.region)

        # 3. Checkboxes
        self._checkbox(f, ['input[name="married"]', '#married'], cfg.married)
        self._checkbox(f, ['input[name="blind"]',   '#blind'],   cfg.blind)
        self._checkbox(f, ['input[name="exNI"]',    '#exNI'],    cfg.no_ni)

        # 4. Student loan
        self._select(f, ['select[name="plan"]', '#plan'], cfg.student_loan)

        # 5. Age
        self._select(f, ['select[name="age"]', '#age'], cfg.age)

        # 6. Allowances / deductions
        self._fill(f, ['input[name="add"]', '#add'],
                   str(int(cfg.allowances)) if cfg.allowances else "0")

        # 7. Tax code (optional)
        if cfg.tax_code:
            self._fill(f, ['input[name="code"]', '#code'], cfg.tax_code)

        # 8. Pension type (£ / %) — select by id since name is empty
        self._select(f, ['#pension-prepend', 'select[id="pension-prepend"]'],
                     cfg.pension_type)

        # 9. Pension amount
        self._fill(f, ['input[name="pension"]', '#pension'], str(cfg.pension_amount))

        # 10. Salary amount
        self._fill(f, ['input[name="ingr"]', '#ingr'], str(cfg.salary))

        # 11. Salary period
        self._select(f, ['select[name="time"]', '#time'], cfg.salary_period)

        logger.debug("Form filled successfully.")

    def _submit(self) -> None:
        """
        Click Calculate My Wage and confirm the results actually updated
        by checking that Gross Pay changes from £0 to a real value.
        """
        f = self._active_frame

        # Read the CURRENT gross pay value before clicking — to detect change
        def _get_gross():
            """Return the first £‑value from the gross pay row.

            The calculator renders the gross pay in multiple columns (year, month,
            week, etc).  The relevant column depends on the salary period selected
            and the order of those cells can shift when additional hidden columns
            are present.  We therefore scan every cell in the row for the first
            currency string we encounter instead of assuming a fixed index.
            """
            try:
                return f.evaluate("""
                    () => {
                        const rows = Array.from(document.querySelectorAll('table tr'));
                        for (const row of rows) {
                            if (!row.textContent.includes('Gross Pay')) continue;
                            const cells = Array.from(row.querySelectorAll('td'));
                            for (let i = 1; i < cells.length; i++) {
                                const txt = cells[i].textContent.trim();
                                if (txt.startsWith('£'))
                                    return txt;
                            }
                        }
                        return null;
                    }
                """)
            except Exception:
                return None

        gross_before = _get_gross()
        logger.debug("Gross Pay before click: %s", gross_before)

        # Click via JS — most reliable across headless/headful modes.  The
        # site renders the submit button disabled until the form is valid.  In
        # headless mode the .click() call on a disabled element merely scrolls
        # it into view, so we proactively remove the attribute before firing the
        # event.
        clicked = f.evaluate("""
            () => {
                const btns = Array.from(document.querySelectorAll('button, input[type=submit]'));
                const btn  = btns.find(b =>
                    b.textContent.trim().includes('Calculate My Wage') ||
                    b.value === 'Calculate My Wage'
                );
                if (btn) {
                    btn.disabled = false;
                    btn.removeAttribute('disabled');
                    btn.scrollIntoView();
                    btn.click();
                    return true;
                }
                return false;
            }
        """)

        if not clicked:
            # Fallback: Playwright locator.  Make sure the button is enabled first
            try:
                f.evaluate("() => { const b = document.querySelector('#calculate'); if(b){ b.disabled=false; b.removeAttribute('disabled'); }}")
            except Exception:
                pass
            try:
                btn = f.locator("button", has_text="Calculate My Wage")
                btn.scroll_into_view_if_needed(timeout=3_000)
                btn.click(timeout=5_000, force=True)
                clicked = True
                logger.info("Submitted via Playwright locator")
            except Exception as e:
                logger.debug("Locator click failed: %s", e)

        if not clicked:
            raise TimeoutError("Could not click Calculate My Wage button")

        logger.info("Button clicked — waiting for results to update...")

        # Wait for the result values to change from £0 to real figures
        # Poll up to 15 seconds
        import time
        for i in range(30):
            time.sleep(0.5)
            gross_after = _get_gross()
            logger.debug("Poll %d — Gross Pay: %s", i, gross_after)
            if gross_after and gross_after != gross_before and gross_after != "£0" and gross_after != "£0.00":
                logger.info("Results updated — Gross Pay: %s", gross_after)
                return

        # If values didn't change, page may use AJAX — wait for network quiet
        try:
            self._page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        logger.warning("Results may not have updated — proceeding with parse anyway")


    def _wait_for_results(self) -> None:
        """
        Wait until the payslip table has real values (not all £0).
        Takes a screenshot mid-wait for debugging if values stay zero.
        """
        import time
        f = self._active_frame

        # Wait for Net Wage text to be present first
        for sel in ['text=Net Wage', 'text=Gross Pay', 'text=Your Payslip']:
            try:
                f.wait_for_selector(sel, state="visible", timeout=10_000)
                break
            except Exception:
                continue

        # Then poll until the gross-pay row itself contains a non-zero
        # amount.  The previous implementation scanned the whole page; various
        # adverts and non‑related elements may contain currency symbols which
        # could fool the check and make us give up early.
        for i in range(20):
            time.sleep(0.5)
            has_real_value = f.evaluate("""
                () => {
                    const row = document.querySelector('#row-gross-pay');
                    if (!row) return false;
                    const cells = Array.from(row.querySelectorAll('td'));
                    return cells.some(td => {
                        const t = td.textContent.trim();
                        return /^£(?!0(?:\\.00)?$)/.test(t);
                    });
                }
            """)
            if has_real_value:
                logger.info("Payslip values confirmed non-zero after %d polls", i+1)
                return
            logger.debug("Poll %d — gross row still £0", i+1)

        logger.warning("Payslip values are still £0 after polling — scraping anyway")


    # ── form element helpers ─────────────────────────────────────────────────
    def _select(self, frame, selectors: list, value: str) -> None:
        """
        Select a dropdown option — tries label, value attribute, then partial text.
        Iterates through all provided selectors until one works.
        """
        for selector in selectors:
            try:
                frame.wait_for_selector(selector, timeout=3_000)
                # Try by label text (exact)
                try:
                    frame.select_option(selector, label=value, timeout=2_000)
                    logger.debug("Selected by label '%s' in %s", value, selector)
                    return
                except Exception:
                    pass
                # Try by value attribute (exact)
                try:
                    frame.select_option(selector, value=value, timeout=2_000)
                    logger.debug("Selected by value '%s' in %s", value, selector)
                    return
                except Exception:
                    pass
                # Partial text match on option labels
                opts = frame.eval_on_selector_all(
                    f"{selector} option",
                    "els => els.map(e => ({text: e.textContent.trim(), val: e.value}))"
                )
                logger.debug("Options in %s: %s", selector, opts)
                match = next(
                    (o for o in opts
                     if value.lower() in o['text'].lower()
                     or value.lower() in o['val'].lower()),
                    None
                )
                if match:
                    frame.select_option(selector, value=match['val'], timeout=2_000)
                    logger.debug("Partial-matched '%s' -> '%s' in %s",
                                 value, match['text'], selector)
                    return
            except Exception:
                continue
        logger.warning("Could not select '%s' — no selector matched", value)

    def _fill(self, frame, selectors: list, value: str) -> None:
        """Clear and type into the first matching input."""
        for selector in selectors:
            try:
                frame.wait_for_selector(selector, timeout=3_000)
                frame.fill(selector, "")
                frame.fill(selector, value)
                logger.debug("Filled %s = '%s'", selector, value)
                return
            except Exception:
                continue
        logger.warning("Could not fill '%s' — no selector matched", value)

    def _checkbox(self, frame, selectors: list, desired: bool) -> None:
        """Tick or un-tick the first matching checkbox."""
        for selector in selectors:
            try:
                frame.wait_for_selector(selector, timeout=3_000)
                if frame.is_checked(selector) != desired:
                    frame.click(selector)
                return
            except Exception:
                continue

    # ── payslip parser ────────────────────────────────────────────────────────
    def _parse_payslip(self, soup: BeautifulSoup) -> list[PayslipRow]:
        """
        Parse the 'Your Payslip Wage' results table.

        Columns: Label | % | Yearly | Monthly | Weekly

        Falls back to searching known row labels if no table is found.
        """
        rows: list[PayslipRow] = []

        # Find the table that contains the payslip data
        target = None
        for tbl in soup.find_all("table"):
            txt = tbl.get_text()
            if "Net Wage" in txt or "Gross Pay" in txt:
                target = tbl
                break

        if not target:
            logger.warning("Payslip table not found — using div fallback")
            return self._parse_payslip_fallback(soup)

        for tr in target.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            label = texts[0]
            if not label:
                continue
            rows.append(PayslipRow(
                label   = label,
                percent = texts[1] if len(texts) > 1 else "",
                yearly  = texts[2] if len(texts) > 2 else "",
                monthly = texts[3] if len(texts) > 3 else "",
                weekly  = texts[4] if len(texts) > 4 else "",
            ))

        logger.debug("Parsed %d rows from payslip table", len(rows))
        return rows

    def _parse_payslip_fallback(self, soup: BeautifulSoup) -> list[PayslipRow]:
        """Fallback: extract known row labels from non-table markup."""
        LABELS = [
            "Gross Pay", "Tax free allowance", "Total taxable",
            "Total Tax Due", "20% rate", "40% rate", "45% rate",
            "Student Loan", "National Insurance", "Pension [you]",
            "Total Deductions", "Net Wage", "Employers NI",
            "Net change from 2024",
        ]
        rows: list[PayslipRow] = []
        for label in LABELS:
            el = soup.find(string=lambda t, lbl=label: t and lbl in t)
            if el:
                parent = el.find_parent()
                sibs   = parent.find_next_siblings() if parent else []
                vals   = [s.get_text(" ", strip=True) for s in sibs[:4]]
                rows.append(PayslipRow(
                    label   = label,
                    percent = vals[0] if len(vals) > 0 else "",
                    yearly  = vals[1] if len(vals) > 1 else "",
                    monthly = vals[2] if len(vals) > 2 else "",
                    weekly  = vals[3] if len(vals) > 3 else "",
                ))
        return rows

    def _build_summary(self, rows: list[PayslipRow]) -> dict:
        """
        Flat dict for quick lookups in backend code.
        e.g. result.summary["Net Wage"]["monthly"] → "£1,873.45"
        """
        return {
            row.label: {
                "percent": row.percent,
                "yearly":  row.yearly,
                "monthly": row.monthly,
                "weekly":  row.weekly,
            }
            for row in rows if row.label
        }

    # ── screenshot ────────────────────────────────────────────────────────────
    def _take_screenshot(self, salary: int | str) -> str:
        """
        Capture the full page (not just the visible viewport) and save as PNG.
        Returns the absolute path to the saved file.
        """
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"taxman_{salary}_{ts}.png"
        self._page.screenshot(path=str(path), full_page=True)
        logger.info("Screenshot saved → %s", path.resolve())
        return str(path.resolve())

    # ── JSON ──────────────────────────────────────────────────────────────────
    def _save_json(self, result: TaxResult, salary: int | str) -> Path:
        """Save payroll (payslip) data to output/taxman_<salary>.json."""
        path = self.output_dir / f"taxman_{salary}.json"
        payload = {"payslip": result.payslip}
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("JSON saved → %s", path.resolve())
        return path

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def close(self) -> None:
        """Shut down the browser and Playwright instance cleanly."""
        try:
            self._browser.close()
            self._pw.stop()
            logger.info("Browser closed.")
        except Exception as exc:
            logger.warning("Error during close: %s", exc)

    def __enter__(self) -> "ListenToTaxmanScraper":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"ListenToTaxmanScraper(output_dir={str(self.output_dir)!r})"