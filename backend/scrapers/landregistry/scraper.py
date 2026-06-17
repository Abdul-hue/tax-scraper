from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from datetime import datetime, timezone
import os, random, time as _time, logging, sys
from pathlib import Path
from typing import Optional, List, Dict
from scrapers.landregistry.models import LandRegistryQuery, LandRegistryResult
from scrapers.common.browser import get_browser_args
from scrapers.landregistry.pdf_parser import parse_pdf
from app.core.s3 import upload_screenshot_to_s3_sync
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

BASE = "https://eservices.landregistry.gov.uk"
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "downloads", "landregistry"))
PROFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chrome_profile", "landregistry"))


class LandRegistryScraper:
    def __init__(self, config=None, headless: bool = None, proxy_file: Optional[str] = None):
        if headless is None:
            # Default to .env setting, fallback to True if not set
            env_val = os.getenv("HEADLESS", "True").lower()
            self.headless = (env_val == "true")
        else:
            self.headless = headless
            
        logger.info("Running land registry scraper in direct (no-proxy) mode.")

    def _cleanup_profile(self, profile_path: Path):
        """Delete the entire profile directory to ensure a fresh session and bypass sticky Cloudflare blocks."""
        import shutil
        if profile_path.exists():
            try:
                shutil.rmtree(profile_path)
                logger.info(f"Deep cleaned browser profile: {profile_path.name}")
            except Exception as e:
                logger.warning(f"Could not deep clean profile {profile_path}: {e}")

    def _wait_for_cloudflare(self, page, max_wait: int = 180):
        """Wait for Cloudflare challenge to resolve, with Turnstile handling."""
        print("[LR-DEBUG] Checking for Cloudflare challenge...", flush=True)

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

            # --- HUMAN INTERACTION & TURSTILE SOLVING ---
            # Random mouse movements
            if i % 3 == 0:
                page.mouse.move(
                    random.randint(100, 1800),
                    random.randint(100, 900),
                    steps=random.randint(5, 20)
                )
                if i % 6 == 0:
                    page.mouse.wheel(0, random.randint(-300, 300))

            # Try solving Turnstile every 5 seconds
            if i % 5 == 0:
                self._solve_turnstile(page)

            page.wait_for_timeout(1000)

        print(f"[LR-DEBUG] Cloudflare did NOT resolve after {max_wait}s!", flush=True)
        return False

    def _solve_turnstile(self, page):
        """Attempt to solve Cloudflare Turnstile challenge."""
        try:
            # First, look for any Turnstile widget
            turnstile_widget = page.locator("[class*='cf-turnstile'], [data-sitekey]")
            
            if turnstile_widget.count() == 0:
                return
            
            # Locate Turnstile iframe(s)
            turnstile_iframes = page.locator("iframe[src*='challenges.cloudflare.com']")
            iframe_count = turnstile_iframes.count()
            if iframe_count == 0:
                return
                
            print(f"[LR-DEBUG] Found {iframe_count} Turnstile iframe(s)", flush=True)
            
            # Try each iframe
            for i in range(iframe_count):
                try:
                    iframe = turnstile_iframes.nth(i)
                    frame_locator = page.frame_locator(f"iframe[src*='challenges.cloudflare.com'] >> nth={i}")
                    
                    # Try multiple selectors for the checkbox
                    checkbox_selectors = [
                        "input[type='checkbox']",
                        ".cf-turnstile-checkbox",
                        ".ctp-checkbox",
                        "[class*='checkbox']",
                        "[role='checkbox']"
                    ]
                    
                    for selector in checkbox_selectors:
                        try:
                            checkbox = frame_locator.locator(selector)
                            if checkbox.is_visible(timeout=1000):
                                print(f"[LR-DEBUG] Found Turnstile checkbox with selector: {selector}", flush=True)
                                
                                # Hover and click like a human
                                checkbox.hover(timeout=2000)
                                page.wait_for_timeout(random.randint(300, 800))
                                checkbox.click()
                                print("[LR-DEBUG] Clicked Turnstile checkbox", flush=True)
                                page.wait_for_timeout(random.randint(3000, 7000))
                                return
                        except Exception:
                            continue
                            
                    # If no checkbox, try waiting for the widget to auto-solve
                    print("[LR-DEBUG] No checkbox found, waiting for Turnstile to auto-solve...", flush=True)
                    page.wait_for_timeout(random.randint(5000, 12000))
                    return
                    
                except Exception as e:
                    print(f"[LR-DEBUG] Error with iframe {i}: {str(e)}", flush=True)
                    continue

        except Exception as e:
            print(f"[LR-DEBUG] Error solving Turnstile: {str(e)}", flush=True)

    def scrape(self, query: LandRegistryQuery) -> LandRegistryResult:
        print(f"[LR-DEBUG] scrape() called. headless={self.headless}", flush=True)
        username = query.username or os.getenv("LAND_REGISTRY_USERNAME", "")
        password = query.password or os.getenv("LAND_REGISTRY_PASSWORD", "")
        
        # Strip whitespace just in case
        username = username.strip()
        password = password.strip()
        
        print(f"[LR-DEBUG] Credentials: user='{username}', pass_len={len(password) if password else 0}", flush=True)
        print(f"[LR-DEBUG] Username from query: '{query.username}', Username from env: '{os.getenv('LAND_REGISTRY_USERNAME', '')}'", flush=True)
        print(f"[LR-DEBUG] Password from query length: {len(query.password) if query.password else 0}, Password from env length: {len(os.getenv('LAND_REGISTRY_PASSWORD', ''))}", flush=True)

        if not username or not password:
            raise Exception("Land Registry Username and Password are required. Set LAND_REGISTRY_USERNAME/PASSWORD in .env or provide them in the request.")

        result = LandRegistryResult(
            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)

        # Generate realistic desktop Chrome user agent
        ua = UserAgent(browsers=['chrome'], os=['windows', 'macos'])
        try:
            user_agent = ua.random
            # Verify it's a desktop UA
            if 'Mobile' in user_agent or 'Android' in user_agent or 'iPhone' in user_agent:
                user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        except:
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        print(f"[LR-DEBUG] Using user agent: {user_agent}", flush=True)

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

            print(f"[LR-DEBUG] Using fresh browser session", flush=True)

            with sync_playwright() as p:
                # Use normal headless mode for compatibility
                headless_mode = self.headless
                
                # Base launch args
                launch_args = {
                    "headless": headless_mode,
                    "args": get_browser_args(),
                    "ignore_default_args": ["--enable-automation"],
                }

                # Use real Chrome only on Windows (Docker/Linux only has Chromium)
                if sys.platform == "win32":
                    launch_args["channel"] = "chrome"

                print(f"[LR-DEBUG] Launching browser. headless={headless_mode}, platform={sys.platform}", flush=True)

                # Log launch args
                print(f"[LR-DEBUG] Launch args: {launch_args}", flush=True)
                
                try:
                    browser = p.chromium.launch(**launch_args)
                    context = browser.new_context(
                        accept_downloads=True,
                        user_agent=user_agent,
                        viewport={"width": 1920, "height": 1080},
                        locale="en-GB",
                        timezone_id="Europe/London",
                        device_scale_factor=1,
                        has_touch=False,
                        is_mobile=False,
                        color_scheme="light",
                        permissions=["geolocation"],  # Not used, but matches real browser
                        extra_http_headers={
                            "Accept-Language": "en-GB,en;q=0.9",
                        }
                    )
                    print(f"[LR-DEBUG] Browser launched successfully! Context options: {context}", flush=True)
                except Exception as e:
                    print(f"[LR-DEBUG] Browser launch FAILED: {e}. Retrying...", flush=True)
                    _time.sleep(2)
                    browser = p.chromium.launch(**launch_args)
                    context = browser.new_context(
                        accept_downloads=True,
                        user_agent=user_agent,
                        viewport={"width": 1920, "height": 1080},
                        locale="en-GB",
                        timezone_id="Europe/London",
                        device_scale_factor=1,
                        has_touch=False,
                        is_mobile=False,
                        color_scheme="light",
                        permissions=["geolocation"],
                        extra_http_headers={
                            "Accept-Language": "en-GB,en;q=0.9",
                        }
                    )
                    print(f"[LR-DEBUG] Browser launched on retry! Context options: {context}", flush=True)

                page = context.new_page()

                # Apply stealth BEFORE any navigation
                print("[LR-DEBUG] Applying stealth...", flush=True)
                Stealth().apply_stealth_sync(page)
                print("[LR-DEBUG] Stealth applied successfully.", flush=True)

                # STEP 1: Navigate to eservices root
                print(f"[LR-DEBUG] STEP 1: Navigating to {BASE}/eservices/", flush=True)
                page.goto(f"{BASE}/eservices/", wait_until="networkidle", timeout=120000)
                page.wait_for_timeout(5000)
                print(f"[LR-DEBUG] STEP 1: Loaded. URL={page.url}, title={page.title()}", flush=True)
                
                # Take screenshot of initial page
                try:
                    self._take_error_screenshot(page, "landregistry_initial_page")
                except Exception as e:
                    print(f"[LR-DEBUG] Could not take initial page screenshot: {e}", flush=True)

                # Handle Cloudflare
                if 'just a moment' in page.title().lower() or '__cf_chl' in page.url or 'challenge' in page.title().lower():
                    resolved = self._wait_for_cloudflare(page, max_wait=180)
                    if not resolved:
                        self._take_error_screenshot(page, "landregistry_cloudflare_blocked")
                        raise Exception("Cloudflare challenge did not resolve. Try using a UK residential proxy.")

                # Human-like behaviour
                page.mouse.move(random.randint(100, 800), random.randint(100, 400))
                page.wait_for_timeout(random.randint(1000, 2000))
                page.mouse.wheel(0, random.randint(100, 300))
                page.wait_for_timeout(random.randint(500, 1500))
                print(f"[LR-DEBUG] STEP 1: After human sim. URL={page.url}", flush=True)
                
                # Take screenshot after human sim
                try:
                    self._take_error_screenshot(page, "landregistry_after_human_sim")
                except Exception as e:
                    print(f"[LR-DEBUG] Could not take after human sim screenshot: {e}", flush=True)

                def _do_login(pg):
                    """Perform PKMS login if the login form is currently visible."""
                    print(f"[LR-DEBUG] LOGIN: Checking for login form. URL={pg.url}", flush=True)
                    
                    # Debug: list all forms/inputs on page
                    try:
                        all_inputs = pg.locator("input").all()
                        print(f"[LR-DEBUG] LOGIN: Found {len(all_inputs)} inputs on page", flush=True)
                        for inp in all_inputs:
                            inp_id = inp.get_attribute("id")
                            inp_name = inp.get_attribute("name")
                            inp_type = inp.get_attribute("type")
                            print(f"  - Input: id={inp_id}, name={inp_name}, type={inp_type}", flush=True)
                            
                        all_buttons = pg.locator("input[type='submit'], button").all()
                        print(f"[LR-DEBUG] LOGIN: Found {len(all_buttons)} buttons on page", flush=True)
                        for btn in all_buttons:
                            btn_value = btn.get_attribute("value")
                            btn_text = btn.inner_text()
                            print(f"  - Button: value={btn_value}, text={btn_text}", flush=True)
                    except Exception as e:
                        print(f"[LR-DEBUG] LOGIN: Could not list page elements: {e}", flush=True)
                    
                    try:
                        pg.wait_for_selector("input#username, input[name='username']", timeout=15000)
                    except Exception as e:
                        print(f"[LR-DEBUG] LOGIN: No login form found: {e}. URL={pg.url}", flush=True)
                        self._take_error_screenshot(pg, "landregistry_no_login_form")
                        return

                    print("[LR-DEBUG] LOGIN: Login form detected — typing credentials...", flush=True)
                    pg.wait_for_timeout(random.randint(500, 1500))
                    
                    # Try multiple selectors for username
                    username_selectors = ["input#username", "input[name='username']"]
                    username_filled = False
                    for sel in username_selectors:
                        try:
                            if pg.locator(sel).count() > 0:
                                pg.fill(sel, "")  # Clear first
                                for char in username:
                                    pg.type(sel, char, delay=random.randint(50, 150))
                                username_filled = True
                                print(f"[LR-DEBUG] LOGIN: Filled username with selector: {sel}", flush=True)
                                break
                        except Exception as e:
                            continue
                    if not username_filled:
                        raise Exception("Could not fill username field")
                        
                    pg.wait_for_timeout(random.randint(300, 700))
                    
                    # Try multiple selectors for password
                    password_selectors = ["input#password", "input[name='password']", "input[type='password']"]
                    password_filled = False
                    for sel in password_selectors:
                        try:
                            if pg.locator(sel).count() > 0:
                                pg.fill(sel, "")  # Clear first
                                for char in password:
                                    pg.type(sel, char, delay=random.randint(50, 150))
                                password_filled = True
                                print(f"[LR-DEBUG] LOGIN: Filled password with selector: {sel}", flush=True)
                                break
                        except Exception as e:
                            continue
                    if not password_filled:
                        raise Exception("Could not fill password field")
                        
                    pg.wait_for_timeout(random.randint(500, 1000))
                    
                    # Try multiple selectors for sign-in button
                    signin_selectors = [
                        "input[value='Sign in']",
                        "input[type='submit']",
                        "button[type='submit']",
                        "button:has-text('Sign in')",
                        "input:has-text('Sign in')"
                    ]
                    signin_clicked = False
                    
                    # Take screenshot before clicking
                    self._take_error_screenshot(pg, "landregistry_before_login_click")
                    
                    for sel in signin_selectors:
                        try:
                            btn = pg.locator(sel)
                            if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                                print(f"[LR-DEBUG] LOGIN: Found sign-in button with selector: {sel}", flush=True)
                                btn.first.hover()
                                pg.wait_for_timeout(random.randint(200, 500))
                                print("[LR-DEBUG] LOGIN: Clicking Sign In...", flush=True)
                                btn.first.click()
                                signin_clicked = True
                                break
                        except Exception as e:
                            continue
                    if not signin_clicked:
                        raise Exception("Could not find or click sign-in button")
                    
                    # Wait for navigation
                    pg.wait_for_timeout(10000)
                    
                    # Try to get URL/title, but don't crash if it fails
                    try:
                        current_url = pg.url
                        print(f"[LR-DEBUG] LOGIN: After sign in. URL={current_url}", flush=True)
                    except Exception as e:
                        print(f"[LR-DEBUG] LOGIN: Could not get URL: {e}", flush=True)
                    
                    # Take a debug screenshot to see what the page looks like
                    try:
                        print("[LR-DEBUG] LOGIN: Taking debug screenshot...", flush=True)
                        self._take_error_screenshot(pg, "landregistry_after_login_click")
                    except Exception as e:
                        print(f"[LR-DEBUG] LOGIN: Could not take screenshot: {e}", flush=True)

                    # Check for Cloudflare challenge after login too!
                    try:
                        print("[LR-DEBUG] LOGIN: Checking for Cloudflare after login...", flush=True)
                        current_title = pg.title().lower()
                        current_url = pg.url
                        if 'just a moment' in current_title or '__cf_chl' in current_url or 'challenge' in current_title:
                            print("[LR-DEBUG] LOGIN: Cloudflare challenge detected after login!", flush=True)
                            self._wait_for_cloudflare(pg, max_wait=180)
                    except Exception as e:
                        print(f"[LR-DEBUG] LOGIN: Cloudflare check failed: {e}", flush=True)

                    # Handle "already signed in somewhere else" - simplified version
                    try:
                        print("[LR-DEBUG] LOGIN: Checking for pkmsdisplace link...", flush=True)
                        # Check if the link exists without getting full page content
                        if pg.locator("a[href='/pkmsdisplace']").is_visible(timeout=3000):
                            print("[LR-DEBUG] LOGIN: Found 'already signed in' prompt — clicking pkmsdisplace", flush=True)
                            pg.click("a[href='/pkmsdisplace']", timeout=5000)
                            pg.wait_for_load_state("domcontentloaded")
                            pg.wait_for_timeout(4000)
                            print(f"[LR-DEBUG] LOGIN: After pkmsdisplace. URL={pg.url}", flush=True)
                    except Exception as e:
                        logger.warning(f"pkmsdisplace redirect failed: {e}")
                        print(f"[LR-DEBUG] LOGIN: pkmsdisplace failed but continuing: {e}", flush=True)

                    # Verify login succeeded - with more debugging and robustness
                    print("[LR-DEBUG] LOGIN: Waiting for login to complete...", flush=True)
                    login_success = False
                    for i in range(90):
                        try:
                            current_url = pg.url
                            current_title = pg.title().lower()
                            print(f"[LR-DEBUG] LOGIN: Wait {i+1}s - URL={current_url}, title={current_title}", flush=True)
                            
                            if "pkmslogin" not in current_url and ("/eservices/" in current_url or "portal" in current_title):
                                login_success = True
                                break
                        except Exception as e:
                            print(f"[LR-DEBUG] LOGIN: Error checking URL/title: {e}", flush=True)
                        
                        pg.wait_for_timeout(1000)

                    if not login_success:
                        print(f"[LR-DEBUG] LOGIN: Login failed - still on pkmslogin URL after 90s", flush=True)
                        try:
                            self._take_error_screenshot(pg, "landregistry_login_failed")
                        except Exception as e:
                            print(f"[LR-DEBUG] LOGIN: Could not take error screenshot: {e}", flush=True)
                        raise Exception("Login failed — check username and password or IP address")

                    print("[LR-DEBUG] LOGIN: Login successful!", flush=True)

                # STEP 2: Login
                print("[LR-DEBUG] STEP 2: Calling _do_login()...", flush=True)
                _do_login(page)
                page.wait_for_timeout(2000)
                print(f"[LR-DEBUG] STEP 2: Login done. URL={page.url}", flush=True)
                print(f"[LR-DEBUG] STEP 2: Page title={page.title()}", flush=True)

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
                        with page.expect_download(timeout=120000) as dl:
                            page.locator("a[href*='ImageServlet'][href*='OC1REG']").first.click()
                        dl.value.save_as(file_save_path)
                        result.register_local_path = f"/api/files/landregistry/{fname}"
                        try:
                            result.register_data = parse_pdf(file_save_path, doc_type="register")
                        except Exception as e:
                            result.register_data = {"parse_error": str(e)}
                    except Exception as e:
                        result.error = f"Register PDF download error: {e}"

                # Wait a bit after register download before trying title plan
                page.wait_for_timeout(2000)

                # Download Title Plan PDF
                if result.title_plan_url:
                    try:
                        fname = f"{title_safe}_title_plan_{timestamp}.pdf"
                        file_save_path = os.path.join(DOWNLOAD_DIR, fname)
                        with page.expect_download(timeout=120000) as dl:
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