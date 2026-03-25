from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from datetime import datetime, timezone
import os, random, time as _time, logging
from pathlib import Path
from scrapers.landregistry.models import LandRegistryQuery, LandRegistryResult
from scrapers.common.browser import get_browser_args
from scrapers.landregistry.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)

BASE = "https://eservices.landregistry.gov.uk"
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "downloads", "landregistry"))
PROFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chrome_profile", "landregistry"))


class LandRegistryScraper:
    def __init__(self, config=None, headless: bool = None):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        if headless is None:
            self.headless = os.getenv("HEADLESS", "true").lower() == "true"
        else:
            self.headless = headless

    def _cleanup_profile(self, profile_path: Path):
        """Delete stale lock files from the profile directory."""
        lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
        for lock_file in lock_files:
            file_path = profile_path / lock_file
            if file_path.exists():
                try:
                    file_path.unlink()
                    logger.info(f"Deleted stale lock file: {lock_file}")
                except Exception as e:
                    logger.warning(f"Could not delete lock file {lock_file}: {e}")

    def scrape(self, query: LandRegistryQuery) -> LandRegistryResult:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        username = os.getenv("LAND_REGISTRY_USERNAME")
        password = os.getenv("LAND_REGISTRY_PASSWORD")
        
        result = LandRegistryResult(
            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)

        try:
            # 1. Clean Postcode — guard against None
            postcode = (query.postcode or "").strip().upper()
            
            # 2. Combine Flat and House if both present — guard against None
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

            with sync_playwright() as p:
                launch_args = {
                "user_data_dir": str(user_data_path),
                "headless": getattr(self, "headless", False),
                "args": [
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--start-maximized",
                ],
                "ignore_default_args": ["--enable-automation", "--no-sandbox"],
                "accept_downloads": True,
            }
                import sys
                if sys.platform == "win32":
                    launch_args["channel"] = "chrome"

                try:
                    logger.info(f"Launching browser with profile: {user_data_path}")
                    context = p.chromium.launch_persistent_context(**launch_args)
                except Exception as e:
                    # If it fails, the lock might be deeper. Try one more time with a full cleanup.
                    logger.warning(f"Browser launch failed: {e}. Performing deep cleanup and retrying...")
                    _time.sleep(2)
                    self._cleanup_profile(user_data_path)
                    context = p.chromium.launch_persistent_context(**launch_args)

                if len(context.pages) > 0:
                    page = context.pages[0]
                else:
                    page = context.new_page()
                Stealth().apply_stealth_sync(page)

                # STEP 1: Navigate to eservices root
                page.goto(f"{BASE}/eservices/", wait_until="domcontentloaded", timeout=60000)
                page.mouse.move(random.randint(100, 800), random.randint(100, 400))
                page.wait_for_timeout(random.randint(1000, 2000))
                page.mouse.wheel(0, random.randint(100, 300))
                page.wait_for_timeout(random.randint(500, 1500))

                def _do_login(pg):
                    """Perform PKMS login if the login form is currently visible."""
                    try:
                        pg.wait_for_selector("input#username", timeout=5000)
                    except Exception:
                        logger.info("No login form present — already authenticated")
                        return  # already logged in

                    logger.info("Login form detected — logging in...")
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
                    sign_in.click()
                    pg.wait_for_load_state("domcontentloaded")
                    pg.wait_for_timeout(5000)

                    # Handle "already signed in somewhere else"
                    if "pkmsdisplace" in pg.content() or "already signed in" in pg.content().lower():
                        try:
                            pg.click("a[href='/pkmsdisplace']", timeout=5000)
                            pg.wait_for_load_state("domcontentloaded")
                            pg.wait_for_timeout(4000)
                        except Exception as e:
                            logger.warning(f"pkmsdisplace redirect failed: {e}")

                    # Verify we left the login page
                    try:
                        pg.wait_for_function(
                            "() => !window.location.href.includes('pkmslogin')",
                            timeout=30000
                        )
                        logger.info("Login successful")
                    except Exception:
                        self._take_error_screenshot(pg, "landregistry_login_captcha_or_error")
                        raise Exception("Login failed — check username and password")

                # STEP 2: Login at homepage if session has expired
                _do_login(page)
                page.wait_for_timeout(2000)

                # STEP 4: Navigate to Request Official Copies
                page.goto(
                    f"{BASE}/eservices/ECOCS_OfficialCopies/ocs/init.do?id=oc_link",
                    wait_until="domcontentloaded",
                    timeout=60000
                )
                page.wait_for_timeout(2000)

                # The ECOCS URL may redirect back to PKMS login if the session expired
                # mid-flight — detect and re-login on demand
                if "pkmslogin" in page.url or page.locator("input#username").is_visible():
                    logger.warning("Redirected to login after ECOCS navigation — re-logging in")
                    _do_login(page)
                    page.goto(
                        f"{BASE}/eservices/ECOCS_OfficialCopies/ocs/init.do?id=oc_link",
                        wait_until="domcontentloaded",
                        timeout=60000
                    )
                    page.wait_for_timeout(2000)

                # Now the OC form should be visible
                try:
                    page.wait_for_selector("form[name='OCForm']", timeout=120000)
                except Exception:
                    self._take_error_screenshot(page, "landregistry_ocform_missing")
                    raise Exception(
                        f"OCForm not found after login. Current URL: {page.url}. "
                        "The ECOCS service may be down or the credentials invalid."
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
                    # No results found for this address / postcode
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

                # STEP 8: Select OC1 → Next
                page.check("input[value='OC1']")
                page.click("input[name='btnNext']")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)

                # STEP 9: Check Register and/or Title Plan → Next
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

                # STEP 11: Get both PDF hrefs
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

                # STEP 12: Click each PDF link and capture the download using expect_download()
                # The links trigger a direct file download (not a page navigation), so we must
                # use expect_download() — page.goto() throws "Download is starting" on these URLs.

                # Download Register PDF by clicking the link on the page
                if result.register_url:
                    try:
                        fname = f"{title_safe}_register_{timestamp}.pdf"
                        file_save_path = os.path.join(DOWNLOAD_DIR, fname)
                        with page.expect_download(timeout=60000) as dl:
                            page.locator("a[href*='ImageServlet'][href*='OC1REG']").first.click()
                        dl.value.save_as(file_save_path)
                        result.register_local_path = f"/api/files/landregistry/{fname}"
                        
                        # Immediately parse the register PDF
                        if result.register_local_path:
                            register_disk_path = os.path.join(DOWNLOAD_DIR, result.register_local_path.split("/")[-1])

                            try:
                                result.register_data = parse_pdf(register_disk_path, doc_type="register")
                            except Exception as e:
                                result.register_data = {"parse_error": str(e)}
                    except Exception as e:
                        result.error = f"Register PDF download error: {e}"

                # Download Title Plan PDF by clicking the link on the page
                if result.title_plan_url:
                    try:
                        fname = f"{title_safe}_title_plan_{timestamp}.pdf"
                        file_save_path = os.path.join(DOWNLOAD_DIR, fname)
                        with page.expect_download(timeout=60000) as dl:
                            page.locator("a[href*='ImageServlet'][href*='OC1TP']").first.click()
                        dl.value.save_as(file_save_path)
                        result.title_plan_local_path = f"/api/files/landregistry/{fname}"
                        
                        # Immediately parse the title plan PDF
                        if result.title_plan_local_path:
                            title_plan_disk_path = os.path.join(DOWNLOAD_DIR, result.title_plan_local_path.split("/")[-1])

                            try:
                                result.title_plan_data = parse_pdf(title_plan_disk_path, doc_type="title_plan")
                            except Exception as e:
                                result.title_plan_data = {"parse_error": str(e)}
                    except Exception as e:
                        existing = result.error or ""
                        result.error = (existing + " | " if existing else "") + f"Title plan PDF download error: {e}"

                # Screenshot capture
                _backend_dir = Path(__file__).parent.parent.parent
                _ss_dir = _backend_dir / "static" / "screenshots"
                _ss_dir.mkdir(parents=True, exist_ok=True)
                _ts = _time.strftime("%Y%m%d_%H%M%S")
                _ss_name = f"landregistry_{_ts}.png"
                _ss_path = str(_ss_dir / _ss_name)
                try:
                    page.screenshot(path=_ss_path, full_page=True)
                    result.screenshot_url = f"/api/files/screenshots/{_ss_name}"
                    logger.info(f"Screenshot saved to: {_ss_path}")
                except Exception as e:
                    logger.warning(f"Failed to capture screenshot: {e}")
                    result.screenshot_url = None

                result.customer_reference = query.customer_reference
                context.close()

        except Exception as e:
            result.error = str(e)
        return result

    def _take_error_screenshot(self, page, name_prefix: str):
        """Save a debug screenshot when an error occurs."""
        try:
            _ss_dir = Path(__file__).parent.parent.parent / "static" / "screenshots"
            _ss_dir.mkdir(parents=True, exist_ok=True)
            _ts = _time.strftime("%Y%m%d_%H%M%S")
            _ss_name = f"{name_prefix}_{_ts}.png"
            _ss_path = str(_ss_dir / _ss_name)
            page.screenshot(path=_ss_path, full_page=True)
            logger.info(f"Error screenshot saved to: {_ss_path}")
        except Exception as e:
            logger.warning(f"Could not save error screenshot: {e}")
