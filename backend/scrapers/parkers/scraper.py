"""
Scraper/parkers/scraper.py

Rewritten Parkers scraper flow to handle every page in order.
"""

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import re
from .models import ParkersConfig, ParkersResult, ValuationPrices
from ..common.browser import get_browser_args

logger = logging.getLogger(__name__)

VALUATION_URL = "https://www.parkers.co.uk/car-valuation/"

class ParkersScraper:
    def __init__(self, config: Optional[ParkersConfig] = None, headless: bool = True):
        self.headless = headless

    def valuate_by_reg(self, plate: str) -> ParkersResult:
        plate = plate.strip().upper().replace(" ", "")
        logger.info(f"Valuating by reg plate: {plate}")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless,
                args=get_browser_args()
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            try:
                # STEP 1: Enter plate and submit
                logger.info(f"Navigating to {VALUATION_URL}")
                page.goto(VALUATION_URL, wait_until="domcontentloaded", timeout=10000)
                
                # Dismiss cookies / GDPR consent if present
                try:
                    # 1. Check for OneTrust
                    if page.locator('button[id*="onetrust-accept"]').is_visible(timeout=2000):
                        page.click('button[id*="onetrust-accept"]', timeout=1000)
                        logger.info("OneTrust cookies dismissed")
                    
                    # 2. Check for SourcePoint GDPR iframe
                    consent_iframe = page.locator('iframe[id^="sp_message_iframe"]')
                    if consent_iframe.is_visible(timeout=3000):
                        logger.info("SourcePoint GDPR consent iframe detected")
                        # Click the "Accept" or "OK" button inside the iframe
                        # Common selectors for SourcePoint buttons: button[title="Accept"], button.sp_choice_type_11
                        accept_btn = consent_iframe.content_frame.get_by_role("button", name=re.compile("Accept|OK|Agree", re.I))
                        if accept_btn.is_visible(timeout=2000):
                            accept_btn.click()
                            logger.info("SourcePoint consent dismissed via button click")
                        
                        # Wait for overlay to disappear
                        page.locator('div[id^="sp_message_container"]').wait_for(state="hidden", timeout=5000)
                except Exception as e:
                    logger.debug(f"Consent dismissal skipped or failed: {e}")

                # Wait for the VRM input to appear
                logger.info("Waiting for VRM input field...")
                page.wait_for_selector(
                    'input.vrm-lookup__input',
                    state='visible',
                    timeout=15000
                )
                
                # Clear field first then type fast
                plate_input = page.locator('input.vrm-lookup__input')
                plate_input.click()
                plate_input.fill('')
                plate_input.type(plate, delay=50)  # 50ms between keystrokes
                logger.info(f"Typed plate: {plate}")
                
                # Handle potential captcha check before clicking
                captcha_selector = '#recaptcha-v2, iframe[src*="recaptcha"]'
                if page.locator(captcha_selector).count() > 0:
                    logger.info("Captcha detected, waiting 30s for auto-resolve...")
                    page.wait_for_timeout(31000)

                logger.info("Clicking submit button...")
                page.locator('button.vrm-lookup__button').click()
                
                # Now wait for EITHER the error OR navigation away from 
                # the current page (confirmation page loaded) 
                try:
                    # Check for not-found error or confirmation page (fast check)
                    page.wait_for_selector( 
                        'span.error, .vrm-confirm__heading--version', 
                        timeout=10000,
                        state='attached'
                    ) 
                    
                    if page.locator('span.error').count() > 0:
                        # Error appeared — car not in database 
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
                    # No error or confirmation shown yet
                    pass 

                # Wait for confirmation page specifically if not already there
                try:
                    page.wait_for_selector(".vrm-confirm__image, .vrm-confirm__heading--version", timeout=10000)
                    logger.info("Reached confirmation page")
                except Exception as e:
                    logger.error(f"Failed to reach confirmation page: {str(e)}")
                    # Take error screenshot
                    self._take_error_screenshot(page, "error_confirm_page")
                    return ParkersResult(
                        plate=plate,
                        config={"plate": plate},
                        reg_plate=plate,
                        error="navigation_error",
                        message="Could not reach confirmation page after plate submission"
                    )

                # Check if plate found
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
                        
                        // Try data-interchange first (lazy loaded)
                        const interchange = img.getAttribute('data-interchange')
                        if (interchange) {
                            // Format: "[url1, (default)], [url2, (medium)]"
                            // Extract the medium/600x400 URL
                            const matches = interchange.match(
                                /\\[([^\\],]+),\\s*\\(medium\\)\\]/
                            )
                            if (matches) return matches[1].trim()
                            
                            // Fallback to default
                            const defaultMatch = interchange.match(
                                /\\[([^\\],]+),\\s*\\(default\\)\\]/
                            )
                            if (defaultMatch) return defaultMatch[1].trim()
                        }
                        
                        // Fallback to src if not transparent
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
                page.check('#curious')
                page.click('#valuation-confirmation-link')
                page.wait_for_load_state("domcontentloaded", timeout=10000)

                # Get current URL and replace 'select-a-valuation' with 
                # 'free-valuation' directly — skips the primer page entirely 
                current_url = page.url 
                free_val_url = current_url.replace( 
                    'select-a-valuation', 
                    'free-valuation' 
                ) 
                
                # Navigate directly to free valuation page 
                logger.info(f"Navigating directly to free valuation: {free_val_url}")
                page.goto(free_val_url, wait_until="domcontentloaded", timeout=15000)

                # STEP 5: Free valuation results page — extract prices
                logger.info("Extracting prices...")
                try:
                    page.wait_for_selector(".valuation-price-box__price", timeout=10000, state='attached')
                    
                    # STEP 1 — Dismiss all popups using JavaScript:
                    page.evaluate("""
                        () => {
                            const popup = document.getElementById('newsletterSignup')
                            if (popup) popup.remove()
                            
                            // Remove any overlay divs
                            const overlays = document.querySelectorAll(
                                '[class*="overlay"], [class*="modal"], [class*="popup"]'
                            )
                            overlays.forEach(el => el.remove())
                            
                            // Remove vis_hide layer
                            const vis = document.getElementById('_vis_opt_path_hides')
                            if (vis) vis.remove()
                        }
                    """)

                    vehicle_full_name = page.locator("span.valuation-option-box__header-row--vehicle").first.inner_text().strip()
                except Exception as e:
                    logger.error(f"Failed to find vehicle details on result page: {str(e)}")
                    self._take_error_screenshot(page, "error_result_page")
                    return ParkersResult(
                        plate=plate,
                        config={"plate": plate},
                        reg_plate=plate,
                        error="extraction_error",
                        message="Could not find vehicle details on result page"
                    )
                
                # Split vehicle_full_name to get make, model, year
                # e.g. "Ford Fiesta 1.6 TDCi Zetec ECOnetic 5d 2014/14"
                make = ""
                model = ""
                year = ""
                parts = vehicle_full_name.split(" ")
                if len(parts) > 0: make = parts[0]
                if len(parts) > 1: model = parts[1]
                if len(parts) > 0: year = parts[-1]

                # STEP 2 — Extract prices using JavaScript evaluation with the correct selectors:
                prices_raw = page.evaluate("""
                    () => {
                        const result = {
                            private_low: null,
                            private_high: null,
                            dealer_low: null,
                            dealer_high: null,
                            part_exchange: null
                        }
                        
                        // Find all price boxes
                        const boxes = document.querySelectorAll(
                            '.valuation-price-box__container__inner, .valuation-price-box__price-summary'
                        )
                        
                        boxes.forEach(box => {
                            const nameEl = box.querySelector(
                                '.valuation-price-box__price-name'
                            )
                            const priceEl = box.querySelector(
                                '.valuation-price-box__price'
                            )
                            if (!nameEl || !priceEl) return
                            
                            const name = nameEl.textContent.trim().toLowerCase()
                            const price = priceEl.textContent.trim()
                            
                            // Parse range like "£1,090 - £2,010"
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

                # Wait for at least one price to be visible before screenshot 
                try: 
                    page.wait_for_selector( 
                        '.valuation-price-box__price', 
                        state='visible', 
                        timeout=5000 
                    ) 
                except Exception: 
                    # If still not visible, scroll to trigger lazy load 
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)") 
                    page.wait_for_timeout(1000) 
                    page.evaluate("window.scrollTo(0, 0)") 
                    page.wait_for_timeout(500) 
                
                # Take screenshot AFTER content is confirmed visible 
                import time as _time
                _backend_dir = Path(__file__).parent.parent.parent
                _ss_dir = _backend_dir / "static" / "screenshots"
                _ss_dir.mkdir(parents=True, exist_ok=True)
                _ts = _time.strftime("%Y%m%d_%H%M%S")
                _ss_name = f"parkers_{_ts}.png"
                _ss_path = str(_ss_dir / _ss_name)
                page.screenshot(path=_ss_path, full_page=False)  # full_page=False
                screenshot_url = f"/api/files/screenshots/{_ss_name}"
                logger.info(f"Screenshot saved to: {_ss_path}")

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
                return ParkersResult(plate=plate, error="scraper_error", message=str(e))
            finally:
                browser.close()

    def valuate(self, config: ParkersConfig, **kwargs) -> ParkersResult:
        return self.valuate_by_reg(config.reg_plate)

    def _take_error_screenshot(self, page, name_prefix):
        import time as _time
        _ss_dir = Path(__file__).parent.parent.parent / "static" / "screenshots"
        _ss_dir.mkdir(parents=True, exist_ok=True)
        _ts = _time.strftime("%Y%m%d_%H%M%S")
        _ss_name = f"{name_prefix}_{_ts}.png"
        _ss_path = str(_ss_dir / _ss_name)
        page.screenshot(path=_ss_path, full_page=True)
        logger.info(f"Error screenshot saved to: {_ss_path}")
