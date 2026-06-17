"""
Scraper/parkers/scraper.py

Rewritten Parkers scraper flow to handle every page in order.
"""

import logging
import os
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth
import re
from .models import ParkersConfig, ParkersResult, ValuationPrices
from ..common.browser import get_browser_args
from app.core.s3 import upload_screenshot_to_s3_sync

logger = logging.getLogger(__name__)

VALUATION_URL = "https://www.parkers.co.uk/car-valuation/"
PROFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chrome_profile", "parkers"))


class ParkersScraper:
    def __init__(self, config: Optional[ParkersConfig] = None, headless: bool = None, proxy_file: Optional[str] = None):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        if headless is None:
            env_val = os.getenv("HEADLESS", "True").lower()
            self.headless = (env_val == "true")
        else:
            self.headless = headless
        logger.info(f"ParkersScraper initialized with headless={self.headless}")
        
        self.proxy_file = proxy_file
        self.proxy_pool = self._load_proxies() if proxy_file else []
        if not self.proxy_pool:
            logger.info("No proxies configured — running in direct (no-proxy) mode.")

    def _load_proxies(self) -> List[Dict[str, str]]:
        """Parses the proxy file and returns a list of proxy dictionaries."""
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
            logger.warning(f"No valid proxies found in {self.proxy_file} — running direct.")
            return []
        
        logger.info(f"Successfully loaded {len(proxies)} proxies from {Path(self.proxy_file).name}")
        return proxies

    def _get_random_proxy(self) -> Optional[Dict[str, str]]:
        """Returns a random proxy dictionary from the pool."""
        if not self.proxy_pool:
            return None
        proxy = random.choice(self.proxy_pool)
        logger.debug(f"Selected proxy: {proxy['_label']}")
        return proxy

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

    def valuate_by_reg(self, plate: str) -> ParkersResult:
        plate = plate.strip().upper().replace(" ", "")
        logger.info(f"Valuating by reg plate: {plate}")

        os.makedirs(PROFILE_DIR, exist_ok=True)
        user_data_path = Path(PROFILE_DIR).resolve() / "default"
        self._cleanup_profile(user_data_path)

        # Get proxy config
        pw_proxy = None
        proxy_dict = self._get_random_proxy()
        if proxy_dict:
            logger.info(f"Using proxy: {proxy_dict['_label']}")
            from urllib.parse import urlparse
            parsed = urlparse(proxy_dict["http"])
            pw_proxy = {
                "server": f"{parsed.hostname}:{parsed.port}",
                "username": parsed.username or "",
                "password": parsed.password or "",
            }
        else:
            logger.info("No proxy available — connecting directly")

        with sync_playwright() as pw:
            # Use persistent context to save Cloudflare cookies between runs
            launch_args = {
                "user_data_dir": str(user_data_path),
                "headless": self.headless,
                "args": get_browser_args() + ["--window-size=1920,1080"],
                "ignore_default_args": ["--enable-automation"],
                "accept_downloads": True,
                "viewport": {"width": 1920, "height": 1080},
                "proxy": pw_proxy,
            }

            # Add channel only if on Windows/local (where Chrome is likely installed)
            # Docker (Linux) usually only has Chromium unless explicitly added.
            if not self.headless and os.name == "nt":
                launch_args["channel"] = "chrome"

            try:
                context = pw.chromium.launch_persistent_context(**launch_args)
            except Exception as e:
                logger.warning(f"Browser launch failed: {e}. Retrying after cleanup...")
                time.sleep(2)
                self._cleanup_profile(user_data_path)
                context = pw.chromium.launch_persistent_context(**launch_args)

            page = context.pages[0] if context.pages else context.new_page()

            # Apply stealth BEFORE any navigation
            Stealth().apply_stealth_sync(page)

            try:
                # STEP 1: Navigate and wait for Cloudflare to pass
                logger.info(f"Navigating to {VALUATION_URL}")
                page.goto(VALUATION_URL, wait_until="domcontentloaded", timeout=60000)

                # Wait for Cloudflare to auto-pass (it usually does within 5s)
                page.wait_for_timeout(5000)

                # Dismiss cookies / GDPR consent if present
                try:
                    if page.locator('button[id*="onetrust-accept"]').is_visible(timeout=2000):
                        page.click('button[id*="onetrust-accept"]', timeout=2000)
                        logger.info("OneTrust cookies dismissed")
                except Exception as e:
                    logger.debug(f"OneTrust dismissal skipped: {e}")

                try:
                    consent_container = page.locator('div[id^="sp_message_container"]')
                    if consent_container.is_visible(timeout=4000):
                        logger.info("SourcePoint GDPR consent iframe detected")
                        sp_frame = page.frame_locator('iframe[id^="sp_message_iframe"]')
                        accept_btn = sp_frame.get_by_role("button", name=re.compile(r"Accept|OK|Agree", re.I))
                        try:
                            accept_btn.click(timeout=5000)
                            logger.info("SourcePoint consent dismissed")
                        except Exception as btn_err:
                            logger.warning(f"iframe button click failed: {btn_err}")
                        page.evaluate("""
                            () => {
                                document.querySelectorAll(
                                    'div[id^="sp_message_container"], #sp_message_container_1446475'
                                ).forEach(el => el.remove());
                            }
                        """)
                        page.wait_for_timeout(500)
                except Exception as e:
                    logger.debug(f"SourcePoint consent dismissal skipped: {e}")

                # Wait for the VRM input — try multiple selectors
                logger.info("Waiting for VRM input field...")
                vrm_selector = None
                fallback_selectors = [
                    'input.vrm-lookup__input',
                    'input[placeholder*="reg" i]',
                    'input[placeholder*="registration" i]',
                    'input[name*="vrm" i]',
                    'input[id*="vrm" i]',
                    'input[type="text"]',
                ]
                for selector in fallback_selectors:
                    try:
                        page.wait_for_selector(selector, state='visible', timeout=10000)
                        vrm_selector = selector
                        logger.info(f"VRM input found with selector: {selector}")
                        break
                    except Exception:
                        logger.debug(f"Selector not found: {selector}")
                        continue

                if not vrm_selector:
                    self._take_error_screenshot(page, "parkers_no_vrm_input")
                    return ParkersResult(
                        plate=plate,
                        error="scraper_error",
                        message="Could not find VRM input field — Cloudflare may be blocking or site layout changed"
                    )

                self._dismiss_overlays(page)

                plate_input = page.locator(vrm_selector)
                plate_input.click(force=True)
                plate_input.fill('')
                plate_input.type(plate, delay=50)
                logger.info(f"Typed plate: {plate}")

                logger.info("Clicking submit button...")
                page.locator('button.vrm-lookup__button').click()

                try:
                    page.wait_for_selector(
                        'span.error, .vrm-confirm__heading--version',
                        timeout=15000,
                        state='attached'
                    )
                    if page.locator('span.error').count() > 0:
                        error_text = page.inner_text('span.error').lower()
                        if 'not found' in error_text:
                            logger.info(f"Registration not found: {error_text}")
                            return ParkersResult(
                                plate=plate,
                                reg_plate=plate,
                                error='not_found',
                                message='not_found',
                                scraped_at=datetime.now(timezone.utc).isoformat() + 'Z'
                            )
                except Exception:
                    pass

                try:
                    page.wait_for_selector(".vrm-confirm__image, .vrm-confirm__heading--version", timeout=15000)
                    logger.info("Reached confirmation page")
                except Exception as e:
                    logger.error(f"Failed to reach confirmation page: {str(e)}")
                    self._take_error_screenshot(page, "parkers_error_confirm_page")
                    return ParkersResult(
                        plate=plate,
                        config={"plate": plate},
                        reg_plate=plate,
                        error="navigation_error",
                        message="Could not reach confirmation page after plate submission"
                    )

                if not page.locator(".vrm-confirm__image").count() and not page.locator(".vrm-confirm__heading--version").count():
                    return ParkersResult(
                        plate=plate,
                        config={"plate": plate},
                        reg_plate=plate,
                        error="not_found",
                        message="not_found"
                    )

                # STEP 2: Confirmation page — extract vehicle details and image
                vehicle_image = page.evaluate("""
                    () => {
                        const img = document.querySelector('.vrm-confirm__image')
                        if (!img) return ''
                        const interchange = img.getAttribute('data-interchange')
                        if (interchange) {
                            const matches = interchange.match(/\\[([^\\],]+),\\s*\\(medium\\)\\]/)
                            if (matches) return matches[1].trim()
                            const defaultMatch = interchange.match(/\\[([^\\],]+),\\s*\\(default\\)\\]/)
                            if (defaultMatch) return defaultMatch[1].trim()
                        }
                        const src = img.getAttribute('src') || ''
                        if (src.includes('transparent')) return ''
                        return src
                    }
                """)
                vehicle_version = page.locator("h3.vrm-confirm__heading--version").inner_text().strip()

                vehicle_details = {}
                detail_items = page.locator("ul.vrm-confirm__details-list li").all()
                for item in detail_items:
                    text = item.inner_text().strip()
                    if ":" in text:
                        k, v = text.split(":", 1)
                        vehicle_details[k.strip()] = v.strip()

                # STEP 3: Select valuation purpose
                logger.info("Selecting valuation purpose...")
                self._dismiss_overlays(page)
                page.check('#curious')
                page.click('#valuation-confirmation-link')
                page.wait_for_load_state("domcontentloaded", timeout=15000)

                current_url = page.url
                free_val_url = current_url.replace('select-a-valuation', 'free-valuation')

                logger.info(f"Navigating directly to free valuation: {free_val_url}")
                page.goto(free_val_url, wait_until="domcontentloaded", timeout=30000)

                # STEP 5: Free valuation results page — extract prices
                logger.info("Extracting prices...")
                try:
                    page.wait_for_selector(".valuation-price-box__price", timeout=15000, state='attached')

                    self._dismiss_overlays(page)

                    vehicle_full_name = page.locator("span.valuation-option-box__header-row--vehicle").first.inner_text().strip()
                except Exception as e:
                    logger.error(f"Failed to find vehicle details on result page: {str(e)}")
                    self._take_error_screenshot(page, "parkers_error_result_page")
                    return ParkersResult(
                        plate=plate,
                        config={"plate": plate},
                        reg_plate=plate,
                        error="extraction_error",
                        message="Could not find vehicle details on result page"
                    )

                make = ""
                model = ""
                year = ""
                parts = vehicle_full_name.split(" ")
                if len(parts) > 0: make = parts[0]
                if len(parts) > 1: model = parts[1]
                if len(parts) > 0: year = parts[-1]

                prices_raw = page.evaluate("""
                    () => {
                        const result = {
                            private_low: null, private_high: null,
                            dealer_low: null, dealer_high: null,
                            part_exchange: null
                        }
                        const boxes = document.querySelectorAll(
                            '.valuation-price-box__container__inner, .valuation-price-box__price-summary'
                        )
                        boxes.forEach(box => {
                            const nameEl = box.querySelector('.valuation-price-box__price-name')
                            const priceEl = box.querySelector('.valuation-price-box__price')
                            if (!nameEl || !priceEl) return
                            const name = nameEl.textContent.trim().toLowerCase()
                            const price = priceEl.textContent.trim()
                            const parts = price.split(' - ')
                            if (name.includes('private')) {
                                result.private_low = parts[0] || price
                                result.private_high = parts[1] || null
                            } else if (name.includes('dealer')) {
                                result.dealer_low = parts[0] || price
                                result.dealer_high = parts[1] || null
                            } else if (name.includes('part exchange') || name.includes('part-exchange')) {
                                result.part_exchange = price
                            }
                        })
                        return result
                    }
                """)

                prices = ValuationPrices()
                if prices_raw:
                    prices = ValuationPrices(
                        private_low=prices_raw.get('private_low'),
                        private_high=prices_raw.get('private_high'),
                        dealer_low=prices_raw.get('dealer_low'),
                        dealer_high=prices_raw.get('dealer_high'),
                        part_exchange=prices_raw.get('part_exchange')
                    )

                try:
                    page.wait_for_selector('.valuation-price-box__price', state='visible', timeout=5000)
                except Exception:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(500)

                import time as _time
                _ts = _time.strftime("%Y%m%d_%H%M%S")
                _ss_name = f"parkers_{_ts}.png"
                screenshot_bytes = page.screenshot(full_page=False)
                screenshot_url = upload_screenshot_to_s3_sync(screenshot_bytes, _ss_name)
                logger.info("Screenshot uploaded to S3: %s", screenshot_url)

                return ParkersResult(
                    plate=plate,
                    config={"plate": plate},
                    scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    reg_plate=plate,
                    make=make,
                    model=model,
                    year=year,
                    vehicle_version=vehicle_version,
                    vehicle_full_name=vehicle_full_name,
                    vehicle_image=vehicle_image,
                    vehicle_details=vehicle_details,
                    prices=prices,
                    screenshot_url=screenshot_url
                )

            except Exception as e:
                logger.exception("Parkers scraper error")
                self._take_error_screenshot(page, "parkers_exception")
                return ParkersResult(plate=plate, error="scraper_error", message=str(e))
            finally:
                context.close()

    def valuate(self, config: ParkersConfig, **kwargs) -> ParkersResult:
        return self.valuate_by_reg(config.reg_plate)

    def _take_error_screenshot(self, page, name_prefix):
        import time as _time
        _ts = _time.strftime("%Y%m%d_%H%M%S")
        _ss_name = f"{name_prefix}_{_ts}.png"
        screenshot_bytes = page.screenshot(full_page=True)
        screenshot_url = upload_screenshot_to_s3_sync(screenshot_bytes, _ss_name)
        logger.info("Error screenshot uploaded to S3: %s", screenshot_url)

    def _dismiss_overlays(self, page):
        """Remove popups and overlays that block interactions."""
        try:
            page.evaluate("""
                () => {
                    const selectors = [
                        '#newsletterSignup',
                        '.newsletter-signup',
                        'div[id^="sp_message_container"]',
                        'div[role="dialog"][aria-modal="true"]',
                        '[class*="overlay"]',
                        '[class*="modal"]',
                        '[class*="popup"]',
                        '#onetrust-banner-sdk',
                        '#_vis_opt_path_hides'
                    ];
                    selectors.forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => el.remove());
                    });
                    // Also fix body overflow if it was locked
                    document.body.style.overflow = 'auto';
                    document.documentElement.style.overflow = 'auto';
                }
            """)
        except Exception as e:
            logger.debug(f"Overlay dismissal failed: {e}")