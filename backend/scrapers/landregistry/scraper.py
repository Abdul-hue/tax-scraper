from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from datetime import datetime, timezone
import os, random, time as _time, logging
from pathlib import Path
from .models import LandRegistryQuery, LandRegistryResult

logger = logging.getLogger(__name__)

BASE = "https://eservices.landregistry.gov.uk"
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "downloads", "landregistry"))
PROFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chrome_profile", "landregistry"))


class LandRegistryScraper:
    def scrape(self, query: LandRegistryQuery) -> LandRegistryResult:
        # HARDCODED CREDENTIALS
        username = "TWilkinson3093"
        password = "James123."
        
        result = LandRegistryResult(
            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)

        try:
            # 1. Clean Postcode
            postcode = query.postcode.strip().upper()
            
            # 2. Combine Flat and House if both present
            house_field = query.house.strip()
            flat_field = query.flat.strip()
            
            address_line_1 = ""
            if flat_field and house_field:
                address_line_1 = f"{flat_field}, {house_field}"
            elif flat_field:
                address_line_1 = flat_field
            else:
                address_line_1 = house_field

            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=os.path.join(PROFILE_DIR, username),
                    headless=True,
                    channel="chrome",
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                    accept_downloads=True,
                )
                page = context.new_page()
                Stealth().apply_stealth_sync(page)

                # STEP 1: Navigate to eservices root
                page.goto(f"{BASE}/eservices/", wait_until="domcontentloaded", timeout=60000)
                page.mouse.move(random.randint(100, 800), random.randint(100, 400))
                page.wait_for_timeout(random.randint(1000, 2000))
                page.mouse.wheel(0, random.randint(100, 300))
                page.wait_for_timeout(random.randint(500, 1500))

                # STEP 2: Login
                page.wait_for_selector("input#username", timeout=120000)
                page.wait_for_timeout(random.randint(500, 1500))
                for char in username:
                    page.type("input#username", char, delay=random.randint(50, 150))
                page.wait_for_timeout(random.randint(300, 700))
                for char in password:
                    page.type("input#password", char, delay=random.randint(50, 150))
                page.wait_for_timeout(random.randint(500, 1000))
                sign_in = page.locator("input[value='Sign in']")
                sign_in.hover()
                page.wait_for_timeout(random.randint(200, 500))
                sign_in.click()
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(5000)

                # STEP 3: Handle "already signed in somewhere else"
                if "pkmsdisplace" in page.content() or "already signed in" in page.content().lower():
                    page.click("a[href='/pkmsdisplace']")
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(4000)

                try:
                    page.wait_for_function(
                        "() => !window.location.href.includes('pkmslogin')",
                        timeout=30000
                    )
                except:
                    raise Exception("Login failed — check username and password")

                page.wait_for_timeout(2000)

                # STEP 4: Navigate to Request Official Copies
                page.goto(
                    f"{BASE}/eservices/ECOCS_OfficialCopies/ocs/init.do?id=oc_link",
                    wait_until="domcontentloaded",
                    timeout=60000
                )
                page.wait_for_timeout(2000)
                page.wait_for_selector("form[name='OCForm']", timeout=30000)
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
                page.wait_for_selector("a[href*='OCS2205.do']", timeout=30000)
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
                                from .pdf_parser import parse_pdf
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
                                from .pdf_parser import parse_pdf
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