"""
debug_idu_address.py
Standalone address-lookup debug test for LexisNexis IDU.

Subject: Nkayilu Tuveno  |  DOB: 20/10/1970  |  Postcode: E5 9HD
Expected address: FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON E5 9HD

Run from the backend/ directory:
    python scratch/debug_idu_address.py
"""

import sys
import os
import json
import logging
from pathlib import Path

# Allow imports from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
USERNAME     = os.getenv("IDU_USERNAME", "")
PASSWORD     = os.getenv("IDU_PASSWORD", "")
SESSION_FILE = Path(__file__).resolve().parents[1] / "output" / "sessions" / "idu_session.json"
OUTPUT_DIR   = Path(__file__).resolve().parents[1] / "output" / "debug"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SCREENSHOT_PATH = str(OUTPUT_DIR / "debug_idu_address_failure.png")
HTML_PATH       = str(OUTPUT_DIR / "debug_idu_address_page.html")

SEARCH_URL = "https://idu.tracesmart.co.uk/?page=newSearch&searchtype=1"

# ── Subject details ────────────────────────────────────────────────────────────
FORENAME   = "Nkayilu"
SURNAME    = "Tuveno"
DOB_DD     = "20"
DOB_MM     = "10"
DOB_YYYY   = "1970"
GENDER     = "Male"          # will try multiple value formats
POSTCODE   = "E5 9HD"
REFERENCE  = "359291"
# Expected result — used only for verification comparison
EXPECTED_ADDRESS = "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON E5 9HD"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_session(context, session_file: Path) -> bool:
    if not session_file.exists():
        return False
    try:
        data = json.loads(session_file.read_text())
        if data.get("cookies"):
            context.add_cookies(data["cookies"])
        return True
    except Exception as e:
        logger.warning(f"Session load failed: {e}")
        return False


def _save_session(context, session_file: Path) -> None:
    try:
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text(json.dumps({"cookies": context.cookies()}))
        logger.info(f"Session saved → {session_file}")
    except Exception as e:
        logger.warning(f"Session save failed: {e}")


def _do_login(page, context) -> None:
    """Full login flow — mirrors IDUScraper._ensure_logged_in exactly."""
    if not USERNAME or not PASSWORD:
        raise RuntimeError("IDU_USERNAME / IDU_PASSWORD are not set in .env")

    import time as _time

    logger.info("Starting full login flow…")
    page.goto("https://sso.tracesmart.co.uk/login/idu", timeout=30_000)
    page.wait_for_selector("#username", timeout=20_000)
    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    page.click('input[data-testid="sign-in"]')

    # Step 2 — "Send One Time Password" page
    otp_trigger_time = _time.time()
    try:
        otp_send_btn = page.locator('[data-testid="otp-send"]')
        if otp_send_btn.is_visible(timeout=3_000):
            logger.info("Clicking 'Send One Time Password'…")
            otp_trigger_time = _time.time()
            otp_send_btn.click()
            page.wait_for_load_state("networkidle", timeout=15_000)
        else:
            logger.debug("OTP send button not visible — may not be required")
    except Exception:
        logger.debug("OTP send page not shown, continuing…")

    # Step 3 — OTP code input
    try:
        page.wait_for_selector('[data-testid="otp-code"]', timeout=10_000)
        logger.info("OTP code field visible")

        otp = None
        try:
            from scrapers.idu.otp_email import fetch_otp_from_email
            logger.info("Auto-fetching OTP from email…")
            otp = fetch_otp_from_email(
                poll_interval=5.0,
                timeout=120.0,
                since_timestamp=otp_trigger_time,
            )
            if otp:
                logger.info(f"OTP retrieved from email: {otp}")
        except Exception as e:
            logger.warning(f"Auto OTP fetch error: {e}")

        if not otp:
            otp = input(">>> Enter OTP code manually: ").strip()

        page.fill('[data-testid="otp-code"]', otp)
        page.click('[data-testid="otp-submit"]')
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            logger.debug("Network did not go idle after OTP, proceeding…")

    except PWTimeout:
        logger.info("No OTP code field appeared — login may have proceeded without OTP")

    # Step 4 — Handle /mfa/ intermediate page
    if "/mfa/" in page.url or "/sso/" in page.url:
        logger.warning(f"Still on MFA/SSO page: {page.url}")
        mfa_handled = False
        try:
            for keyword in ("Continue", "Accept", "Confirm", "Proceed"):
                btn = page.get_by_role("button", name=keyword)
                if btn.is_visible(timeout=3_000):
                    logger.info(f"Clicking MFA button: {keyword}")
                    btn.click()
                    page.wait_for_load_state("networkidle", timeout=15_000)
                    mfa_handled = True
                    break
            if not mfa_handled:
                first_btn = page.locator("button, input[type=submit]").first
                if first_btn.is_visible(timeout=3_000):
                    first_btn.click()
                    page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception as e:
            logger.warning(f"MFA handler error: {e}")

    # Step 4b — Conflict / concurrent-session page
    try:
        page.wait_for_selector('[data-testid="accept"]', timeout=8_000)
        logger.info("Conflict page — accepting…")
        page.click('[data-testid="accept"]')
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass

    # Step 5 — Verify dashboard loaded
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass
    try:
        indicator = page.locator("#hd-logout-button, .newSearch").or_(
            page.get_by_text("You are logged in")
        ).first
        indicator.wait_for(state="visible", timeout=20_000)
        logger.info("Dashboard confirmed")
    except Exception as e:
        logger.error(f"Dashboard not detected after login. URL={page.url}  Title={page.title()}")
        raise RuntimeError(f"Login failed — dashboard not detected: {e}")

    _save_session(context, SESSION_FILE)
    logger.info("Login complete — session saved")


def _ensure_on_search_form(page, context) -> None:
    """Load session or log in, then land on the new-search form."""
    _load_session(context, SESSION_FILE)
    page.goto(SEARCH_URL, timeout=40_000)
    try:
        page.wait_for_selector("#forename", timeout=15_000)
        logger.info("Search form loaded — session valid")
        return
    except PWTimeout:
        logger.info("Session invalid or expired — performing fresh login")

    _do_login(page, context)
    page.goto(SEARCH_URL, timeout=40_000)
    page.wait_for_selector("#forename", timeout=20_000)
    logger.info("Search form loaded after login")


def _set_gender(page) -> None:
    """Try several common value formats for the gender select."""
    for val in (GENDER, GENDER.lower(), GENDER[0].upper(), "1"):
        try:
            page.select_option("#gender", val, timeout=2_000)
            logger.info(f"Gender set with value={repr(val)}")
            return
        except Exception:
            continue
    logger.warning("Could not set gender — skipping")


def _read_field(page, selector: str) -> str:
    try:
        return page.input_value(selector, timeout=2_000)
    except Exception:
        return "(error reading)"


# ── Dropdown discovery helpers ────────────────────────────────────────────────

# Candidate selectors for an address <select> dropdown
_SELECT_SELECTORS = [
    "#pafaddress",
    "#addressSelect",
    "#address-select",
    "#addr-select",
    "select[name='address']",
    "select[name='pafaddress']",
    ".address-dropdown select",
    "#addressResults select",
    "select.address-list",
    ".address-select select",
    "#addressDrop",
    "#addressDropdown",
]


def _collect_select_options(page, selector: str) -> list[dict]:
    """Return list of {value, text} dicts for all options in a <select>."""
    return page.eval_on_selector_all(
        f"{selector} option",
        "els => els.map(e => ({value: e.value, text: e.textContent.trim()}))",
    )


def _find_address_select(page, timeout_each: int = 3_000) -> tuple[str | None, list[dict]]:
    """
    Scan known selectors for an address <select>.
    Returns (selector, options) or (None, []).
    """
    for sel in _SELECT_SELECTORS:
        try:
            page.wait_for_selector(sel, timeout=timeout_each)
            opts = _collect_select_options(page, sel)
            if opts:
                return sel, opts
        except PWTimeout:
            continue
    return None, []


def _scan_all_selects(page) -> list[dict]:
    """Return metadata for every <select> currently in the DOM."""
    try:
        return page.eval_on_selector_all(
            "select",
            """els => els.map(s => ({
                id:      s.id,
                name:    s.name,
                cls:     s.className,
                options: Array.from(s.options).map(o => ({
                    value: o.value,
                    text:  o.textContent.trim(),
                }))
            }))""",
        )
    except Exception:
        return []


def _addressmatch_info(page) -> dict:
    """Return inner HTML and all links from #addressmatch."""
    try:
        html = page.inner_html("#addressmatch", timeout=2_000)
        links = page.eval_on_selector_all(
            "#addressmatch a",
            "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))",
        )
        return {"html": html, "links": links}
    except Exception:
        return {"html": "", "links": []}


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    console_msgs: list[str] = []
    network_log:  list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/114.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # Capture all JS console messages from the start
        page.on("console", lambda m: console_msgs.append(f"[{m.type.upper()}] {m.text}"))

        # ── Step 1: Land on search form ────────────────────────────────────
        _ensure_on_search_form(page, context)

        # ── Step 2: Fill subject fields ───────────────────────────────────
        logger.info("Filling subject fields…")
        page.fill("#forename",  FORENAME)
        page.fill("#surname",   SURNAME)
        page.fill("#dd",        DOB_DD)
        page.fill("#mm",        DOB_MM)
        page.fill("#yyyy",      DOB_YYYY)
        page.fill("#reference", REFERENCE)
        _set_gender(page)

        # Enter only the postcode — leave house/street/town blank so
        # the dropdown returns ALL addresses at E5 9HD
        page.fill("#postcode", POSTCODE)

        logger.info(
            f"Fields filled: {FORENAME} {SURNAME}, "
            f"DOB {DOB_DD}/{DOB_MM}/{DOB_YYYY}, "
            f"Postcode {POSTCODE}, Ref {REFERENCE}"
        )

        # ── Step 3: Arm network capture then click Find Address ────────────
        # Record every request/response from this point forward
        page.on("request",  lambda r: network_log.append(f"REQ  [{r.resource_type:<10}] {r.method} {r.url}"))
        page.on("response", lambda r: network_log.append(f"RES  [{r.status}] {r.url}"))

        logger.info("Clicking #addchk (Find Address)…")
        page.click("#addchk")

        # ── Step 4: Discover the address response ──────────────────────────
        # IDU uses #addressmatch containing <a class="pd-addresslink"> items —
        # NOT a <select>.  Check that first; fall back to <select> scanning only
        # if #addressmatch doesn't appear.

        address_options: list[dict] = []   # full list of returned addresses
        found_via: str              = "none"
        am_links: list[dict]        = []   # raw link dicts from #addressmatch

        # 4a — Primary: wait for #addressmatch (the real IDU address list)
        logger.info("Waiting for #addressmatch (up to 12 s)…")
        try:
            page.wait_for_selector("#addressmatch", timeout=12_000)
            am = _addressmatch_info(page)

            if am["links"]:
                am_links = am["links"]
                found_via = f"#addressmatch  ({len(am_links)} link(s))"
                # Build address_options from ALL links — each link IS an address option
                address_options = [
                    {"value": lnk.get("href", ""), "text": lnk.get("text", ""), "href": lnk.get("href", "")}
                    for lnk in am_links
                ]
                logger.info(f"{len(address_options)} address links found in #addressmatch")
                if am["html"]:
                    logger.info(f"#addressmatch inner HTML:\n{am['html']}")

            elif am["html"]:
                found_via = "#addressmatch text-only"
                address_options = [{"value": "text", "text": am["html"].strip()}]
                logger.info(f"Text-only #addressmatch: {am['html'].strip()}")

        except PWTimeout:
            logger.warning("#addressmatch did not appear within 12 s — falling back to <select> scan")

        # 4b — Fallback: check for a <select> dropdown (shorter timeout now)
        if not address_options:
            logger.info("Checking for <select> dropdown (2 s per selector)…")
            used_selector, sel_options = _find_address_select(page, timeout_each=2_000)
            if sel_options:
                address_options = sel_options
                found_via = f"<select>  selector={used_selector}"
                logger.info(f"<select> found: {used_selector} with {len(sel_options)} option(s)")

        # 4c — Last resort: full DOM scan for any address-like <select>
        if not address_options:
            logger.info("Last-resort DOM scan for address <select>…")
            for s in _scan_all_selects(page):
                combined = (s["id"] + s["name"] + s["cls"]).lower()
                if any(kw in combined for kw in ("addr", "paf", "post")):
                    logger.info(f"Candidate <select>: id={s['id']} name={s['name']} opts={len(s['options'])}")
                if len(s["options"]) > 1:
                    kws = ("flat", "road", "street", "house", "lane", "close", "way", "avenue")
                    if any(any(kw in o["text"].lower() for kw in kws) for o in s["options"]):
                        address_options = s["options"]
                        found_via = f"DOM scan  selector=#{s['id']}"
                        logger.info(f"Address <select> found via DOM scan: #{s['id']}")
                        break

        # ── Step 5: Print ALL captured options ────────────────────────────
        # Use am_links as the canonical list when available (IDU's actual links)
        display_options = am_links if am_links else address_options

        print()
        print("=" * 70)
        print("ADDRESS DROPDOWN OPTIONS")
        print("=" * 70)
        print(f"  Found via  : {found_via}")
        print(f"  Count      : {len(display_options)}")
        print()
        if display_options:
            for i, opt in enumerate(display_options):
                text = opt.get("text", "")
                val  = opt.get("href", opt.get("value", ""))
                print(f"  [{i:>3}]  {text}")
        else:
            print("  (no options captured)")
        print("=" * 70)

        # ── Step 6: Failure diagnostics ────────────────────────────────────
        if not address_options:
            print()
            print(">>> ZERO RESULTS — capturing failure diagnostics…")
            print()

            # Network log
            print("─" * 70)
            print("NETWORK REQUESTS/RESPONSES (captured after Find Address click)")
            print("─" * 70)
            if network_log:
                for entry in network_log:
                    print(f"  {entry}")
            else:
                print("  (none captured)")

            # JS console errors/warnings
            print()
            print("─" * 70)
            print("JS CONSOLE MESSAGES")
            print("─" * 70)
            errors_and_warnings = [m for m in console_msgs if m.startswith(("[ERROR]", "[WARNING]"))]
            if errors_and_warnings:
                for msg in errors_and_warnings:
                    print(f"  {msg}")
            elif console_msgs:
                print(f"  (no errors/warnings; {len(console_msgs)} info messages logged)")
            else:
                print("  (none)")

            # Screenshot
            print()
            try:
                page.screenshot(path=SCREENSHOT_PATH, full_page=False)
                print(f"[SCREENSHOT] → {SCREENSHOT_PATH}")
            except Exception as e:
                print(f"[SCREENSHOT] failed: {e}")

            # Full page HTML
            try:
                html_content = page.content()
                with open(HTML_PATH, "w", encoding="utf-8") as fh:
                    fh.write(html_content)
                print(f"[HTML DUMP]  → {HTML_PATH}")

                # Print the #addressmatch section specifically
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html_content, "html.parser")
                    am_el = soup.find(id="addressmatch")
                    addchk_el = soup.find(id="addchk")
                    print()
                    print("─" * 70)
                    print("#addressmatch element in HTML dump:")
                    print("─" * 70)
                    print(am_el.prettify() if am_el else "  (not present in DOM)")
                    print()
                    print("─" * 70)
                    print("#addchk element in HTML dump:")
                    print("─" * 70)
                    print(addchk_el.prettify() if addchk_el else "  (not present in DOM)")
                except ImportError:
                    print("  (BeautifulSoup not available — HTML saved to disk)")
            except Exception as e:
                print(f"[HTML DUMP] failed: {e}")

        # ── Step 7: Click the target address link and confirm ─────────────
        # IDU uses pd-addresslink anchors — find the one matching FLAT 1 and
        # click it, then confirm with #confirm-yes.

        selected_text   = None
        fields_after: dict[str, str] = {}

        if address_options:
            # Find best match for FLAT 1, FERRY HOUSE, HARRINGTON HILL
            target_upper = EXPECTED_ADDRESS.upper()
            flat_opt = None
            for opt in address_options:
                text_up = opt.get("text", "").upper()
                if not text_up or text_up in ("-- SELECT --", "PLEASE SELECT"):
                    continue
                # Exact target first — match the flat number from EXPECTED_ADDRESS
                target_flat = EXPECTED_ADDRESS.upper().split(",")[0].strip()  # e.g. "FLAT 7"
                if target_flat in text_up and "FERRY" in text_up:
                    flat_opt = opt
                    break
            # Fall back: first FLAT option
            if flat_opt is None:
                for opt in address_options:
                    text_up = opt.get("text", "").upper()
                    if "FLAT" in text_up:
                        flat_opt = opt
                        break
            # Last resort: first non-blank
            if flat_opt is None:
                for opt in address_options:
                    if opt.get("text", "").strip():
                        flat_opt = opt
                        break

            if flat_opt:
                selected_text = flat_opt.get("text", "")
                logger.info(f"Target option to click: {repr(selected_text)}")

                # If the addresses came from #addressmatch links, click by visible text
                if am_links:
                    try:
                        link_loc = page.locator(
                            f'a.pd-addresslink:has-text("{selected_text}")'
                        ).first
                        link_loc.click(timeout=5_000)
                        logger.info(f"Clicked pd-addresslink: {repr(selected_text)}")
                    except Exception as e:
                        logger.warning(f"pd-addresslink click failed: {e} — trying #addressmatch a")
                        try:
                            page.click("#addressmatch a", timeout=5_000)
                        except Exception as e2:
                            logger.warning(f"Fallback click also failed: {e2}")
                else:
                    # <select> path
                    used_sel = found_via.split("selector=")[-1].strip() if "selector=" in found_via else None
                    if used_sel:
                        try:
                            page.select_option(used_sel, label=selected_text, timeout=5_000)
                        except Exception as e:
                            logger.warning(f"select_option failed: {e}")

                # Click #confirm-yes if it appears
                confirm_clicked = False
                try:
                    page.wait_for_selector("#confirm-yes", timeout=5_000)
                    logger.info("#confirm-yes appeared — confirming address")
                    try:
                        page.check("#confirm-yes")
                    except Exception:
                        page.click("#confirm-yes")
                    confirm_clicked = True
                except PWTimeout:
                    logger.info("#confirm-yes did not appear (may not be required)")

                # IDU stores the selected address internally by link id — the
                # visible #house/#street/#town fields remain empty after selection.
                fields_after["confirm_clicked"] = str(confirm_clicked)

        # ── Step 8: Summary ────────────────────────────────────────────────
        print()
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"  Subject            : {FORENAME} {SURNAME}, DOB {DOB_DD}/{DOB_MM}/{DOB_YYYY}")
        print(f"  Postcode searched  : {POSTCODE}")
        print(f"  Reference          : {REFERENCE}")
        total_returned = len(am_links) if am_links else len(address_options)
        print(f"  Addresses returned : {total_returned}")
        print(f"  Found via          : {found_via}")
        print(f"  Option selected    : {repr(selected_text)}")

        target_flat = EXPECTED_ADDRESS.upper().split(",")[0].strip()
        clicked_correct = selected_text and target_flat in selected_text.upper()
        confirmed = fields_after.get("confirm_clicked") == "True"

        if clicked_correct and confirmed:
            print(f"  RESULT             : PASS — clicked '{selected_text}' and #confirm-yes completed")
        elif clicked_correct:
            print(f"  RESULT             : PARTIAL — clicked correct link but #confirm-yes did not appear")
        elif address_options:
            print(f"  RESULT             : FAIL — correct link not found (target: {target_flat})")
            print(f"  Screenshot         : {SCREENSHOT_PATH}")
        else:
            print("  RESULT             : FAIL — no addresses returned")
            print(f"  Screenshot         : {SCREENSHOT_PATH}")
            print(f"  HTML dump          : {HTML_PATH}")

        print("=" * 70)

        browser.close()


if __name__ == "__main__":
    main()
