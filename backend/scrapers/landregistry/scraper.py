from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from datetime import datetime, timezone
import os, random, time as _time, logging, sys
from pathlib import Path
from scrapers.landregistry.models import LandRegistryQuery, LandRegistryResult
from scrapers.common.browser import get_browser_args
from scrapers.landregistry.pdf_parser import parse_pdf
from app.core.s3 import upload_screenshot_to_s3_sync

logger = logging.getLogger(__name__)

BASE = "https://eservices.landregistry.gov.uk"
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "downloads", "landregistry"))
PROFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chrome_profile", "landregistry"))


class LandRegistryScraper:
    def __init__(self, config=None, headless: bool = None):
        if headless is None:
            # Default to .env setting, fallback to True if not set
            env_val = os.getenv("HEADLESS", "True").lower()
            self.headless = (env_val == "true")
        else:
            self.headless = headless

    def _cleanup_profile(self, profile_path: Path):
        """Delete the entire profile directory to ensure a fresh session and bypass sticky Cloudflare blocks."""
        import shutil
        if profile_path.exists():
            try:
                shutil.rmtree(profile_path)
                logger.info(f"Deep cleaned browser profile: {profile_path.name}")
            except Exception as e:
                logger.warning(f"Could not deep clean profile {profile_path}: {e}")

    def _wait_for_cloudflare(self, page, max_wait: int = 60):
        """Wait for Cloudflare challenge to resolve."""
        print("[LR-DEBUG] Checking for Cloudflare challenge...", flush=True)

        # First handle Turnstile iframe if present
        try:
            turnstile = page.locator("iframe[src*='challenges.cloudflare.com']")
            if turnstile.is_visible(timeout=5000):
                print("[LR-DEBUG] Turnstile iframe detected — clicking to trigger verification...", flush=True)
                # Scroll to it
                turnstile.scroll_into_view_if_needed()
                # Use bounding box to click center
                box = turnstile.bounding_box()
                if box:
                    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                page.wait_for_timeout(3000)
        except Exception:
            pass

        # Wait for challenge to clear
        for i in range(max_wait):
            current_title = page.title().lower()
            current_url = page.url

            # If common Cloudflare indicators are gone, we are through
            if (
                'just a moment' not in current_title and 
                '__cf_chl' not in current_url and 
                'challenge' not in current_title and
                'loading' not in current_title
            ):
                print(f"[LR-DEBUG] Cloudflare cleared after {i}s. Title='{page.title()}'", flush=True)
                return True

            if i % 2 == 0:
                print(f"[LR-DEBUG] CF wait {i+1}s - title='{page.title()}', url={current_url[:80]}", flush=True)

            # --- NEW LEVEL 2 STEALTH: ACTIVE HUMAN INTERACTION ---
            # Random mouse movements during the wait to look natural
            if i % 5 == 0:
                page.mouse.move(random.randint(50, 500), random.randint(50, 500))
                if i % 10 == 0:
                    page.mouse.wheel(0, random.choice([100, -100]))

            # Try clicking Turnstile checkbox periodically with more precision
            if i % 8 == 0 and i > 0:
                try:
                    turnstile = page.locator("iframe[src*='challenges.cloudflare.com']")
                    if turnstile.is_visible(timeout=1000):
                        turnstile.scroll_into_view_if_needed()
                        box = turnstile.bounding_box()
                        if box:
                            # Move mouse to box first then click
                            cx, cy = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
                            page.mouse.move(cx, cy, steps=5)
                            page.mouse.click(cx, cy)
                            print(f"[LR-DEBUG] Precise Turnstile click at ({cx}, {cy})", flush=True)
                except Exception:
                    pass
            # -----------------------------------------------------

            page.wait_for_timeout(1000)

        print(f"[LR-DEBUG] Cloudflare did NOT resolve after {max_wait}s!", flush=True)
        return False

    def scrape(self, query: LandRegistryQuery) -> LandRegistryResult:
        print(f"[LR-DEBUG] scrape() called. headless={self.headless}", flush=True)
        username = query.username or os.getenv("LAND_REGISTRY_USERNAME", "")
        password = query.password or os.getenv("LAND_REGISTRY_PASSWORD", "")
        print(f"[LR-DEBUG] Credentials: user='{username}', pass_len={len(password) if password else 0}", flush=True)

        if not username or not password:
            raise Exception("Land Registry Username and Password are required. Set LAND_REGISTRY_USERNAME/PASSWORD in .env or provide them in the request.")

        result = LandRegistryResult(
            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)

        try:
            postcode = (query.postcode or "").strip().upper()
            house_field = (query.house or "").strip()
            flat_field = (query.flat or "").strip()

            address_line_1 = ""
            if flat_field and house_field:
                address_line_1 = f"{flat_field}, {house_field}"
            elif flat_field:
                address_line_1 = flat_field
            else:
                address_line_1 = house_field

            user_data_path = Path(PROFILE_DIR).resolve() / username
            self._cleanup_profile(user_data_path)
            print(f"[LR-DEBUG] Profile path: {user_data_path}", flush=True)

            with sync_playwright() as p:
                # Base launch args — works on both Windows and Linux/Docker
                launch_args = {
                    "user_data_dir": str(user_data_path),
                    "headless": self.headless,
                    "args": [
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--disable-infobars",
                        "--start-maximized",
                        "--flag-switches-begin",
                        "--disable-site-isolation-trials",
                        "--flag-switches-end",
                    ],
                    "ignore_default_args": ["--enable-automation"],
                    "accept_downloads": True,
                    # Match user agent to Windows Chrome to avoid TLS mismatch
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                }

                # Use real Chrome only on Windows (Docker/Linux only has Chromium)
                if sys.platform == "win32":
                    launch_args["channel"] = "chrome"

                print(f"[LR-DEBUG] Launching browser. headless={self.headless}, platform={sys.platform}", flush=True)

                try:
                    context = p.chromium.launch_persistent_context(**launch_args)
                    print("[LR-DEBUG] Browser launched successfully!", flush=True)
                except Exception as e:
                    print(f"[LR-DEBUG] Browser launch FAILED: {e}. Retrying...", flush=True)
                    _time.sleep(2)
                    self._cleanup_profile(user_data_path)
                    context = p.chromium.launch_persistent_context(**launch_args)
                    print("[LR-DEBUG] Browser launched on retry!", flush=True)

                page = context.pages[0] if context.pages else context.new_page()

                # Apply stealth BEFORE any navigation
                Stealth().apply_stealth_sync(page)
                print("[LR-DEBUG] Stealth applied.", flush=True)

                # STEP 1: Navigate to eservices root
                print(f"[LR-DEBUG] STEP 1: Navigating to {BASE}/eservices/", flush=True)
                page.goto(f"{BASE}/eservices/", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                print(f"[LR-DEBUG] STEP 1: Loaded. URL={page.url}, title={page.title()}", flush=True)

                # Handle Cloudflare
                if 'just a moment' in page.title().lower() or '__cf_chl' in page.url or 'challenge' in page.title().lower():
                    resolved = self._wait_for_cloudflare(page, max_wait=60)
                    if not resolved:
                        self._take_error_screenshot(page, "landregistry_cloudflare_blocked")
                        raise Exception("Cloudflare challenge did not resolve. Try using a UK residential proxy.")

                # Human-like behaviour
                page.mouse.move(random.randint(100, 800), random.randint(100, 400))
                page.wait_for_timeout(random.randint(1000, 2000))
                page.mouse.wheel(0, random.randint(100, 300))
                page.wait_for_timeout(random.randint(500, 1500))
                print(f"[LR-DEBUG] STEP 1: After human sim. URL={page.url}", flush=True)

                def _do_login(pg):
                    """Perform PKMS login if the login form is currently visible."""
                    print(f"[LR-DEBUG] LOGIN: Checking for login form. URL={pg.url}", flush=True)
                    try:
                        pg.wait_for_selector("input#username", timeout=10000)
                    except Exception:
                        print(f"[LR-DEBUG] LOGIN: No login form — already authenticated. URL={pg.url}", flush=True)
                        return

                    print("[LR-DEBUG] LOGIN: Login form detected — typing credentials...", flush=True)
                    pg.wait_for_timeout(random.randint(500, 1500))
                    for char in username:
                        pg.type("input#username", char, delay=random.randint(50, 150))
                    pg.wait_for_timeout(random.randint(300, 700))
                    for char in password:
                        pg.type("input#password", char, delay=random.randint(50, 150))
                    pg.wait_for_timeout(random.randint(500, 1000))
                    sign_in = pg.locator("input[value='Sign in']")
                    sign_in.hover()
                    pg.wait_for_timeout(random.randint(200, 500))
                    print("[LR-DEBUG] LOGIN: Clicking Sign In...", flush=True)
                    sign_in.click()
                    pg.wait_for_load_state("domcontentloaded")
                    pg.wait_for_timeout(5000)
                    print(f"[LR-DEBUG] LOGIN: After sign in. URL={pg.url}", flush=True)

                    # Handle "already signed in somewhere else"
                    if "pkmsdisplace" in pg.content() or "already signed in" in pg.content().lower():
                        try:
                            pg.click("a[href='/pkmsdisplace']", timeout=5000)
                            pg.wait_for_load_state("domcontentloaded")
                            pg.wait_for_timeout(4000)
                        except Exception as e:
                            logger.warning(f"pkmsdisplace redirect failed: {e}")

                    # Verify login succeeded
                    try:
                        pg.wait_for_function(
                            "() => !window.location.href.includes('pkmslogin')",
                            timeout=30000
                        )
                        print("[LR-DEBUG] LOGIN: Login successful!", flush=True)
                    except Exception:
                        self._take_error_screenshot(pg, "landregistry_login_failed")
                        raise Exception("Login failed — check username and password")

                # STEP 2: Login
                print("[LR-DEBUG] STEP 2: Calling _do_login()...", flush=True)
                _do_login(page)
                page.wait_for_timeout(2000)
                print(f"[LR-DEBUG] STEP 2: Login done. URL={page.url}", flush=True)

                # STEP 4: Navigate to Request Official Copies
                print("[LR-DEBUG] STEP 4: Navigating to ECOCS...", flush=True)
                page.goto(
                    f"{BASE}/eservices/ECOCS_OfficialCopies/ocs/init.do?id=oc_link",
                    wait_until="domcontentloaded",
                    timeout=60000
                )
                page.wait_for_timeout(2000)
                print(f"[LR-DEBUG] STEP 4: ECOCS loaded. URL={page.url}", flush=True)

                # Re-login if session expired mid-flight
                if "pkmslogin" in page.url or page.locator("input#username").is_visible():
                    print("[LR-DEBUG] STEP 4: Session expired — re-logging in", flush=True)
                    _do_login(page)
                    page.goto(
                        f"{BASE}/eservices/ECOCS_OfficialCopies/ocs/init.do?id=oc_link",
                        wait_until="domcontentloaded",
                        timeout=60000
                    )
                    page.wait_for_timeout(2000)

                # Wait for OC form
                print("[LR-DEBUG] STEP 4: Waiting for OCForm...", flush=True)
                try:
                    page.wait_for_selector("form[name='OCForm']", timeout=120000)
                    print("[LR-DEBUG] STEP 4: OCForm found!", flush=True)
                except Exception:
                    print(f"[LR-DEBUG] STEP 4: OCForm NOT FOUND! URL={page.url}", flush=True)
                    self._take_error_screenshot(page, "landregistry_ocform_missing")
                    raise Exception(
                        f"OCForm not found. URL: {page.url}. "
                        "ECOCS service may be down or credentials invalid."
                    )
                page.wait_for_timeout(1000)

                # STEP 5: Fill property search form
                if query.title_number:
                    page.fill("input[name='titleNumber']", query.title_number)
                if address_line_1:
                    page.fill("input[name='house']", address_line_1)
                if query.street:
                    page.fill("input[name='road']", query.street)
                if query.town:
                    page.fill("input[name='town']", query.town)
                if postcode:
                    page.fill("input[name='postcode']", postcode)
                page.fill("input[name='customerReference']", query.customer_reference)
                page.locator("input[name='btnNext']").last.click()
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)

                # STEP 6: Click first "Order Official Copies"
                try:
                    page.wait_for_selector("a[href*='OCS2205.do']", timeout=30000)
                except Exception:
                    logger.warning("No title results found for the given address/postcode")
                    self._take_error_screenshot(page, "landregistry_no_results")
                    result.error = "no_results"
                    context.close()
                    return result
                page.locator("a[href*='OCS2205.do']").first.click()
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)

                # STEP 7: Extract property details
                try:
                    result.title_number = page.locator("#formSubHeader span").first.inner_text().strip()
                except:
                    pass
                try:
                    subtext = page.locator("#formSubHeader .clearBoth").inner_text()
                    for line in subtext.splitlines():
                        line = line.strip()
                        if line.startswith("Address:"):
                            result.address = line.replace("Address:", "").strip()
                        elif line.startswith("Tenure:"):
                            result.tenure = line.replace("Tenure:", "").strip()
                        elif "administered by:" in line:
                            result.administered_by = line.split("administered by:")[-1].strip()
                except:
                    pass

                # STEP 8: Select OC1
                page.check("input[value='OC1']")
                page.click("input[name='btnNext']")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)

                # STEP 9: Check Register and/or Title Plan
                if query.order_register:
                    try:
                        page.check("input[name='registerChoiceTemp']")
                    except:
                        pass
                if query.order_title_plan:
                    try:
                        page.check("input[name='titlePlanChoiceTemp']")
                    except:
                        pass
                page.click("input[name='btnNext']")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)

                # STEP 10: Fee confirmation → Submit
                page.wait_for_selector("input[name='btnSubmit']", timeout=30000)
                page.click("input[name='btnSubmit']")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(3000)

                # STEP 11: Get PDF hrefs
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                title_safe = (result.title_number or "unknown").replace("/", "_")

                try:
                    reg_href = page.locator("a[href*='ImageServlet'][href*='OC1REG']").first.get_attribute("href")
                    if reg_href:
                        result.register_url = f"{BASE}{reg_href}" if reg_href.startswith("/") else reg_href
                except:
                    pass

                try:
                    tp_href = page.locator("a[href*='ImageServlet'][href*='OC1TP']").first.get_attribute("href")
                    if tp_href:
                        result.title_plan_url = f"{BASE}{tp_href}" if tp_href.startswith("/") else tp_href
                except:
                    pass

                # STEP 12: Download Register PDF
                if result.register_url:
                    try:
                        fname = f"{title_safe}_register_{timestamp}.pdf"
                        file_save_path = os.path.join(DOWNLOAD_DIR, fname)
                        with page.expect_download(timeout=60000) as dl:
                            page.locator("a[href*='ImageServlet'][href*='OC1REG']").first.click()
                        dl.value.save_as(file_save_path)
                        result.register_local_path = f"/api/files/landregistry/{fname}"
                        try:
                            result.register_data = parse_pdf(file_save_path, doc_type="register")
                        except Exception as e:
                            result.register_data = {"parse_error": str(e)}
                    except Exception as e:
                        result.error = f"Register PDF download error: {e}"

                # Download Title Plan PDF
                if result.title_plan_url:
                    try:
                        fname = f"{title_safe}_title_plan_{timestamp}.pdf"
                        file_save_path = os.path.join(DOWNLOAD_DIR, fname)
                        with page.expect_download(timeout=60000) as dl:
                            page.locator("a[href*='ImageServlet'][href*='OC1TP']").first.click()
                        dl.value.save_as(file_save_path)
                        result.title_plan_local_path = f"/api/files/landregistry/{fname}"
                        try:
                            result.title_plan_data = parse_pdf(file_save_path, doc_type="title_plan")
                        except Exception as e:
                            result.title_plan_data = {"parse_error": str(e)}
                    except Exception as e:
                        existing = result.error or ""
                        result.error = (existing + " | " if existing else "") + f"Title plan PDF download error: {e}"

                # Screenshot
                _ts = _time.strftime("%Y%m%d_%H%M%S")
                _ss_name = f"landregistry_{_ts}.png"
                try:
                    screenshot_bytes = page.screenshot(full_page=True)
                    result.screenshot_url = upload_screenshot_to_s3_sync(screenshot_bytes, _ss_name)
                    logger.info("Screenshot uploaded to S3: %s", result.screenshot_url)
                except Exception as e:
                    logger.warning(f"Screenshot failed: {e}")
                    result.screenshot_url = None

                result.customer_reference = query.customer_reference
                context.close()

        except Exception as e:
            result.error = str(e)
        return result

    def _take_error_screenshot(self, page, name_prefix: str):
        """Save a debug screenshot when an error occurs."""
        try:
            _ts = _time.strftime("%Y%m%d_%H%M%S")
            _ss_name = f"{name_prefix}_{_ts}.png"
            screenshot_bytes = page.screenshot(full_page=True)
            screenshot_url = upload_screenshot_to_s3_sync(screenshot_bytes, _ss_name)
            logger.info("Error screenshot uploaded to S3: %s", screenshot_url)
        except Exception as e:
            logger.warning(f"Could not save error screenshot: {e}")