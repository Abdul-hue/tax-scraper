import logging
import os
import re
import platform
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from .models import (
    ChildMaintenanceQuery,
    ChildMaintenanceResult,
    ChildOvernightStay,
    ReceivingParent,
)
from .parser import parse_final_result
from ..common.browser import get_browser_args
from app.core.s3 import upload_screenshot_to_s3_sync

logger = logging.getLogger(__name__)

TARGET_URL = "https://child-maintenance.dwp.gov.uk/calculate/details/will-you-be-paying-or-receiving-child-maintenance-payments"
PROFILE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "chrome_profile", "child_maintenance")
)

# Internal key → exact GOV.UK radio label
OVERNIGHT_LABELS = {
    "never": "Never",
    "up-to-52": "Up to 1 night a week (fewer than 52 nights a year)",
    "52-103": "1 to 2 nights a week (52 to 103 nights a year)",
    "104-155": "2 to 3 nights a week (104 to 155 nights a year)",
    "156-174": "More than 3 nights a week - but not half the time (156 to 174 nights a year)",
    "175-182": "Half the time (175 to 182 nights a year)",
}

# All benefit strings the frontend may send
BENEFIT_LABELS = {
    "Universal Credit",
    "Armed Forces Compensation Scheme payments",
    "Bereavement Allowance",
    "Carers Allowance/Carers Support Payment",
    "Incapacity Benefit",
    "Income Support",
    "Income-related Employment and Support Allowance",
    "Industrial Injuries Disablement Benefit",
    "Jobseeker’s Allowance – contribution-based",
    "Jobseeker’s Allowance – income-based",
    "Maternity Allowance",
    "Pension Credit",
    "Personal Independence Payment (PIP)",
    "Severe Disablement Allowance",
    "Skillseekers training",
    "State Pension",
    "Training Allowance",
    "War Disablement Pension",
    "War Widow’s, Widower’s or Surviving Civil Partner’s Pension",
    "Widow’s Pension",
    "Widowed Parent’s Allowance",
}

# Map frontend other_children_in_home string → label for the GOV.UK form radio buttons
OTHER_CHILDREN_MAP = {
    "none": "None",
    "0": "None",
    "1": "1",
    "2": "2",
    "3": "3 or more",
    "3 or more": "3 or more",
}


class ChildMaintenanceScraper:
    def __init__(self, config=None, headless: bool = None):
        from dotenv import load_dotenv
        load_dotenv()
        self.config = config
        self.headless = False if headless is None else headless

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    # ─────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────

    def scrape(self, query: ChildMaintenanceQuery) -> ChildMaintenanceResult:
        result = ChildMaintenanceResult(
            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        try:
            normalized = self._normalize_query(query)
            parsed, screenshot_url, full_text, pdf_url = self._run_flow(normalized)
            result.result = parsed[0]
            result.reason = parsed[1]
            result.screenshot_url = screenshot_url
            result.pdf_url = pdf_url
            setattr(result, "full_calculation_text", full_text)
            if not result.result:
                result.error = "Could not parse final result page"
        except Exception as e:
            logger.error("Child maintenance scrape failed: %s", e, exc_info=True)
            result.error = str(e)
        return result

    # ─────────────────────────────────────────────────────────────────
    # Normalisation
    # ─────────────────────────────────────────────────────────────────

    def _normalize_query(self, query: ChildMaintenanceQuery) -> ChildMaintenanceQuery:
        logger.info(f"Normalization Input: {query}")
        role = (query.role or "paying").strip().lower()
        if role not in {"paying", "receiving"}:
            raise ValueError("role must be 'paying' or 'receiving'")

        frequency = (query.income_frequency or "monthly").strip().lower()
        if frequency not in {"weekly", "monthly", "yearly"}:
            raise ValueError("income_frequency must be weekly/monthly/yearly")

        # ── receiving_parents ────────────────────────────────────────
        parents_input = query.receiving_parents or []
        if not parents_input:
            raise ValueError("At least one receiving parent is required")
        if len(parents_input) > 9:
            raise ValueError("receiving_parents supports up to 9 parents")

        clean_parents: list[ReceivingParent] = []
        for i, p in enumerate(parents_input):
            # Helper to get value from p (which could be a dict or a dataclass/object)
            def get_val(obj, key, default=None):
                if isinstance(obj, dict):
                    return obj.get(key, default)
                return getattr(obj, key, default)

            # Try new flattened structure fields
            children_count = int(get_val(p, "children_count", 0))
            children_names = get_val(p, "children_names", [])
            overnight_stays = (get_val(p, "overnight_stays", "never") or "never").strip().lower()
            logger.debug(f"Normalizing parent {i+1}: children_count={children_count}, names={children_names}, overnight={overnight_stays}")
            
            # Try old nested list field
            nested_children = get_val(p, "children", [])

            children: list[ChildOvernightStay] = []

            # 1. Prefer old nested children list if populated
            if nested_children:
                for j, c in enumerate(nested_children):
                    c_name = (get_val(c, "name", "") or "").strip()
                    c_stay = (get_val(c, "overnight_stays", "never") or "never").strip().lower()
                    if c_stay not in OVERNIGHT_LABELS:
                        c_stay = "never"
                    if not c_name and j == 0 and getattr(query, "child_name", ""):
                        c_name = str(query.child_name).strip()
                    children.append(
                        ChildOvernightStay(
                            name=c_name or f"Child {len(children) + 1}",
                            overnight_stays=c_stay
                        )
                    )
            
            # 2. Otherwise use new flattened structure
            elif children_count > 0:
                for j in range(children_count):
                    name = ""
                    if j < len(children_names):
                        name = str(children_names[j]).strip()
                    if not name and j == 0 and getattr(query, "child_name", ""):
                        name = str(query.child_name).strip()
                    if not name:
                        name = f"Child {j + 1}"
                    
                    stay = overnight_stays
                    if stay not in OVERNIGHT_LABELS:
                        stay = "never"
                    
                    children.append(ChildOvernightStay(name=name, overnight_stays=stay))
            
            # Validation: form requires at least one child
            if not children:
                raise ValueError(f"Each receiving parent must have at least one child (Parent {i+1})")

            clean_parents.append(ReceivingParent(children=children))

        # ── benefits ─────────────────────────────────────────────────
        raw_benefits = query.benefits or []
        accepted: list[str] = []
        for b in raw_benefits:
            b = b.strip()
            if b in BENEFIT_LABELS:
                accepted.append(b)
            else:
                norm_b = self._normalize_text(b)
                match = next(
                    (lbl for lbl in BENEFIT_LABELS if norm_b in self._normalize_text(lbl)),
                    None,
                )
                if match:
                    accepted.append(match)
                else:
                    logger.warning("Unrecognised benefit '%s' — skipping", b)

        # ── other_children_in_home (string or int) ───────────────────
        oic_raw = str(query.other_children_in_home or "0").strip().lower()
        oic_label = OTHER_CHILDREN_MAP.get(oic_raw, "None")

        return ChildMaintenanceQuery(
            role=role,
            multiple_receiving_parents=bool(getattr(query, "multiple_receiving_parents", False)),
            benefits=accepted,
            income=float(query.income or 0.0),
            income_frequency=frequency,
            add_parent_names=bool(getattr(query, "add_parent_names", False)),
            paying_parent_name=str(getattr(query, "paying_parent_name", "") or "Parent").strip(),
            receiving_parent_name=str(getattr(query, "receiving_parent_name", "") or "Parent").strip(),
            child_name=str(getattr(query, "child_name", "") or "Child").strip(),
            other_children_in_home=oic_label,  # now "None", "1", "2", or "3 or more"
            receiving_parents=clean_parents,
        )

    # ─────────────────────────────────────────────────────────────────
    # Main browser flow
    # ─────────────────────────────────────────────────────────────────

    def _run_flow(self, query: ChildMaintenanceQuery) -> tuple[tuple[str, str], str | None, str, str | None]:
        # Create a unique profile dir for this run to avoid "TargetClosedError" lock issues on Windows
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        temp_profile = Path(PROFILE_DIR).resolve() / f"run_{run_id}"
        temp_profile.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            launch_args = {
                "user_data_dir": str(temp_profile),
                "headless": self.headless,
                "args": get_browser_args(),
                "ignore_default_args": ["--enable-automation"],
                "viewport": {"width": 1440, "height": 900},
            }
            context = p.chromium.launch_persistent_context(**launch_args)
            page = context.pages[0] if context.pages else context.new_page()

            try:
                # ── 1. Open start page ───────────────────────────────
                page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
                self._accept_cookies_if_present(page)

                # ── Robust Navigation Loop ─────────────────────────────
                # Loop until we reach the final calculation page
                _last_url = ""
                _loop_count = 0
                personalisation_child_idx = 0
                while True:
                    page.wait_for_load_state("domcontentloaded", timeout=60000)
                    page.wait_for_timeout(1000)
                    self._accept_cookies_if_present(page)  
                    
                    url = page.url.lower()
                    heading = page.locator("h1").first.inner_text().lower().strip() if page.locator("h1").count() > 0 else ""
                    logger.debug(f">> Evaluating Page | URL: {url} | Heading: {heading}")
                    
                    if url == _last_url:
                        _loop_count += 1
                        if _loop_count > 4:
                            raise RuntimeError(f"Stuck in a loop on url: {url} | heading: {heading}")
                    else:
                        _last_url = url
                        _loop_count = 0
                    
                    # Result page -> Exit loop
                    if (
                        "your child maintenance calculation" in heading
                        or "your-calculation" in url
                        or "complete" in url
                        or "result" in url
                        or "estimated" in heading
                        or "download" in url
                    ) and "do you want to add" not in heading:
                        logger.info("Reached final calculation page.")
                        break
                        
                    # 1. Role Selection
                    if "paying-or-receiving" in url or "paying or receiving" in heading:
                        self._answer_role(page, query.role)
                        continue
                        
                    # 2. More than one parent (Paying)
                    if "payments-to-more-than-one" in url or "more than one other parent" in heading:
                        self._answer_yes_no(page, "will-you-be-making-payments", query.multiple_receiving_parents)
                        continue
                        
                    # 2a. How many people will you be paying (Paying)
                    if "how-many-people-will-you-be-paying" in url or "how many people" in heading:
                        parent_count = len(query.receiving_parents)
                        input_l = page.locator("input[type='text'], input[type='number']").first
                        if input_l.count() > 0:
                            input_l.fill(str(parent_count))
                            self._continue(page)
                        continue
                        
                    # 3. Benefits Gate (Yes/No)
                    # This page asks "Do you get any benefits?" before showing the list.
                    if ("get-any-benefits" in url or "get any benefits" in heading) and "of these" not in heading and "which" not in heading:
                        has_benefits = len(query.benefits) > 0
                        self._answer_yes_no(page, "benefits", has_benefits)
                        continue
                        
                    # 3a. Benefits Multi-Checkbox List
                    # This page asks "Do you get any of these benefits..." and has a list of checkboxes.
                    if "which-benefits" in url or "which benefits" in heading or "any of these benefits" in heading or "state pension" in heading:
                        self._select_benefits(page, query.benefits)
                        continue
                        
                    # 4. Income Yes/No (Paying & Receiving)
                    if "any-income" in url or "any income" in heading:
                        has_income = float(query.income or 0) > 0
                        # Receiving can have Yes, No, I don't know
                        if self._click_label(page, "Yes" if has_income else "No"):
                            self._continue(page)
                        else:
                            self._answer_yes_no(page, "income", has_income)
                        continue
                        
                    # 4b. "Do you know the other parent's income?" (Receiving)
                    if "know-the-other-parents-income" in url or "know the other parent" in heading:
                        has_income = float(query.income or 0) > 0
                        self._answer_yes_no(page, "know-income", has_income)
                        continue
                        
                    # 4c. Enter Income Amount
                    if "enter-income" in url or "taxable-income" in url or "how much" in heading or "income amount" in heading or "taxable income" in heading:
                        input_l = page.locator("input[type='text'], input[type='number'], input.govuk-input").first
                        if input_l.count() > 0:
                            # Fill amount
                            input_l.fill(f"{float(query.income):.2f}")
                            
                            # On some GOV.UK iterations, the frequency is on the exact same page as amount
                            # We can just attempt to click the matching label if present
                            try:
                                freq = query.income_frequency.lower()
                                self._click_radio_by_value(page, freq)
                            except Exception:
                                pass
                                    
                            self._continue(page)
                        continue
                        
                    # 4d. Income Frequency
                    if "how-often" in url and "paid" in heading:
                        self._select_frequency(page, query.income_frequency)
                        continue
                        
                    # 5. How many children will you be paying/receiving for?
                    if "how-many-children" in url or "how many children" in heading:
                        total_children = sum(len(p.children) for p in query.receiving_parents)
                        input_l = page.locator("input[type='text'], input[type='number']").first
                        if input_l.count() > 0:
                            input_l.fill(str(total_children))
                            self._continue(page)
                        continue
                        
                    # 6. Child Names page (Receiving)
                    if "what-are-the-names" in url or "names of your children" in heading or "name of child" in heading:
                        logger.info("Names page detected.")
                        all_children = [c for p in query.receiving_parents for c in p.children]
                        self._fill_all_child_names(page, all_children, query)
                        continue
                        
                    # 7. Do any children stay overnight? (gate)
                    if "stay-overnight" in url and "how often" not in heading:
                        any_overnight = False
                        for p in query.receiving_parents:
                            if any(c.overnight_stays != "never" for c in p.children):
                                any_overnight = True
                                break
                        self._answer_yes_no(page, "stay-overnight", any_overnight, allow_skip=True)
                        continue

                    # 8. How often does [Child Name] stay overnight? (Per child)
                    if "overnight" in url and "how often" in heading:
                        chosen_stay = "never"
                        all_children = [c for p in query.receiving_parents for c in p.children]
                        
                        if all_children:
                            chosen_stay = all_children[0].overnight_stays
                            for c in all_children:
                                if c.name and c.name.lower() in heading:
                                    chosen_stay = c.overnight_stays
                                    break
                                    
                        self._select_overnight(page, chosen_stay)
                        continue
                        
                    # 9. Other children in home
                    if "other-children" in url or "other children " in heading:
                        oic_label = str(query.other_children_in_home)
                        if not self._click_label(page, oic_label):
                            input_l = page.locator("input[type='text'], input[type='number']").first
                            if input_l.count() > 0:
                                input_l.fill(oic_label)
                        self._continue(page)
                        continue
                        
                    # 10. Check your answers / Summary
                    if "check-your-answers" in url or "summary" in url or "review" in url:
                        logger.info("Found 'Check your answers', clicking continue...")
                        self._continue(page)
                        continue
                        
                    # 11. Add names of each parent
                    if "add-the-names-of-each-parent" in url or "names of each parent" in heading:
                        want_yes = bool(getattr(query, "add_parent_names", False))
                        label_for = "f-addParentsNames" if want_yes else "f-addParentsNames-2"

                        label = page.locator(f"label[for='{label_for}']")

                        logger.info(f"=== ADD NAMES DEBUG ===")
                        logger.info(f"want_yes={want_yes}, label_for={label_for}")
                        logger.info(f"label.count()={label.count()}")
                        logger.info(f"label.is_visible()={label.is_visible()}")
                        logger.info(f"label.bounding_box()={label.bounding_box()}")
                        logger.info(f"cookie banner visible={page.locator('.casa-cookie-banner').is_visible()}")
                        logger.info(f"page viewport size={page.viewport_size}")
                        logger.info(f"all labels on page={[l.inner_text() for l in page.locator('label').all()]}")

                        label.dispatch_event("click")
                        page.wait_for_timeout(1000)

                        logger.info(f"after click — url={page.url}")
                        logger.info(f"after click — heading={page.locator('h1').first.inner_text() if page.locator('h1').count() > 0 else ''}")

                        self._continue(page)
                        continue

                    # 11a. "What is your name?" — paying parent name
                    if "parent-name" in url and "your name" in heading:
                        name = str(getattr(query, "paying_parent_name", "") or "Alex").strip()
                        logger.info(f"Entering paying parent name: {name}")
                        
                        selectors = ["input[name='name']", "input#f-name", "input.govuk-input", "input[type='text']"]
                        inp = None
                        for selector in selectors:
                            loc = page.locator(selector).first
                            if loc.count() > 0 and loc.is_visible():
                                inp = loc
                                break
                        
                        if inp:
                            inp.fill(name)
                            # Verify fill
                            if inp.input_value() != name:
                                logger.warning("Fill failed or partially failed, trying type...")
                                inp.click()
                                page.keyboard.press("Control+A")
                                page.keyboard.press("Backspace")
                                inp.type(name)
                            page.wait_for_timeout(500)
                        else:
                            logger.error("Could not find paying parent name input field!")
                            
                        self._continue(page)
                        continue

                    # 11b. "What is the other parent's name?" — receiving parent name
                    if ("other-parent" in url or "other parent" in heading) and "name" in heading:
                        name = str(getattr(query, "receiving_parent_name", "") or "Sam").strip()
                        logger.info(f"Entering receiving parent name: {name}")
                        
                        selectors = ["input[name='name']", "input#f-name", "input.govuk-input", "input[type='text']"]
                        inp = None
                        for selector in selectors:
                            loc = page.locator(selector).first
                            if loc.count() > 0 and loc.is_visible():
                                inp = loc
                                break
                        
                        if inp:
                            inp.fill(name)
                            # Verify fill
                            if inp.input_value() != name:
                                logger.warning("Fill failed or partially failed, trying type...")
                                inp.click()
                                page.keyboard.press("Control+A")
                                page.keyboard.press("Backspace")
                                inp.type(name)
                            page.wait_for_timeout(500)
                        else:
                            logger.error("Could not find receiving parent name input field!")

                        self._continue(page)
                        continue

                    # 11c. "What is your child's name?" — per child name (personalisation flow)
                    if "child-name" in url or ("child" in url and "name" in heading and "personalisation" in url):
                        all_children = []
                        for p in query.receiving_parents:
                            for c in p.children:
                                all_children.append(c)
                        
                        if personalisation_child_idx == 0 and getattr(query, "child_name", ""):
                            name = query.child_name
                        elif personalisation_child_idx < len(all_children):
                            name = all_children[personalisation_child_idx].name
                        else:
                            name = f"Child {personalisation_child_idx + 1}"
                            
                        logger.info(f"Entering child name {personalisation_child_idx + 1} (personalisation): {name}")
                        
                        # Robust input selection
                        selectors = ["input[name='name']", "input#f-name", "input.govuk-input", "input[type='text']"]
                        inp = None
                        for selector in selectors:
                            loc = page.locator(selector).first
                            if loc.count() > 0 and loc.is_visible():
                                inp = loc
                                break
                        
                        if inp:
                            inp.fill(name)
                            # Verify fill
                            if inp.input_value() != name:
                                logger.warning("Fill failed or partially failed, trying type...")
                                inp.click()
                                page.keyboard.press("Control+A")
                                page.keyboard.press("Backspace")
                                inp.type(name)
                            page.wait_for_timeout(500)
                        else:
                            logger.error("Could not find child name input field!")
                        
                        prev_url = page.url
                        self._continue(page)
                        
                        # Only increment index if we actually moved away from this page
                        # (Wait a bit for navigation)
                        try:
                            page.wait_for_url(lambda u: u != prev_url, timeout=3000)
                            personalisation_child_idx += 1
                        except:
                            logger.warning("URL did not change after entering child name. May be a validation error or multi-step same-URL form.")
                        
                        continue
                        
                    # Fallback
                    if page.locator("button:has-text('Continue')").count() > 0 or page.locator("a:has-text('Continue')").count() > 0:
                        logger.warning(f"Unhandled page: {url}. Clicking continue.")
                        self._continue(page)
                        continue
                        
                    raise RuntimeError(f"Scraper stuck. URL: {url} | Heading: {heading}")

                page.wait_for_load_state("networkidle", timeout=60000)
                page.wait_for_timeout(2000)
                html = page.content()

                # ── 9. Screenshot ────────────────────────────────────
                screenshot_url = None
                try:
                    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    screenshot_bytes = page.screenshot(full_page=True)
                    screenshot_url = upload_screenshot_to_s3_sync(
                        screenshot_bytes,
                        f"child_maintenance_{ts}.png",
                    )
                except Exception as e:
                    logger.warning("Screenshot upload failed: %s", e)

                # Cookie check on final page
                try:
                    reject_btn = page.locator("button:has-text('Reject additional cookies')").first
                    if reject_btn.count() > 0 and reject_btn.is_visible(timeout=1500):
                        reject_btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Dismiss cookie banner before extracting
                self._accept_cookies_if_present(page)
                page.wait_for_timeout(1000)

                result_text = "Could not find result calculation."
                reason_text = "Could not determine reason."
                pdf_url = None

                # Extract result paragraphs — skip cookie text
                all_paragraphs = page.locator("div.govuk-grid-column-two-thirds p.govuk-body")
                clean = []
                for i in range(all_paragraphs.count()):
                    txt = all_paragraphs.nth(i).inner_text().strip()
                    if txt and "cookie" not in txt.lower() and len(txt) > 10:
                        clean.append(txt)

                if len(clean) >= 1:
                    result_text = clean[0]
                if len(clean) >= 2:
                    reason_text = clean[1]

                # Download PDF using browser's native download (inherits full session/cookies)
                pdf_url = None
                try:
                    pdf_link = page.locator("a[href*='download']").first
                    if pdf_link.count() > 0:
                        with page.expect_download(timeout=30000) as download_info:
                            pdf_link.click()
                        download = download_info.value
                        
                        # Read the downloaded file bytes
                        import tempfile, os
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp_path = tmp.name
                        
                        download.save_as(tmp_path)
                        
                        with open(tmp_path, "rb") as f:
                            pdf_bytes = f.read()
                        
                        os.unlink(tmp_path)
                        
                        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                        pdf_url = upload_screenshot_to_s3_sync(
                            pdf_bytes,
                            f"child_maintenance_{ts}.pdf",
                            content_type="application/pdf",
                        )
                        logger.info(f"PDF uploaded to S3: {pdf_url}")
                except Exception as e:
                    logger.warning("PDF download failed: %s", e)

                parsed = (result_text, reason_text)
                
                # Add optional full_calculation_text dynamically if present
                full_text = ""
                main_content = page.locator("main, #content, .govuk-main-wrapper").first
                if main_content.count() > 0:
                    full_text = main_content.inner_text().strip()
                
                return parsed, screenshot_url, full_text, pdf_url

            finally:
                context.close()

    # ─────────────────────────────────────────────────────────────────
    # Helper methods
    # ─────────────────────────────────────────────────────────────────

    def _click_radio_by_value(self, page, value: str) -> bool:
        radio = page.locator(f"input[type='radio'][value='{value}']").first
        if radio.count() == 0:
            return False
        input_id = radio.get_attribute("id")
        label = page.locator(f"label[for='{input_id}']").first
        if label.count() > 0:
            try:
                label.click(timeout=2000)
            except:
                logger.warning(f"Regular click failed on radio label for '{value}', using dispatch_event")
                label.dispatch_event("click")
            return True
        
        # fallback to clicking label text (e.g. "Yes", "No")
        capitalized = value.capitalize()
        logger.info(f"Radio value '{value}' not found by selector, trying label text '{capitalized}'")
        return self._click_label(page, capitalized)

    def _accept_cookies_if_present(self, page):
        for selector in [
            "#cookies-accept",
            "#accept-cookies",
            "button:has-text('Accept additional cookies')",
            "button:has-text('Accept all cookies')",
            "button:has-text('Reject additional cookies')",
        ]:
            try:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=1200):
                    btn.click()
                    page.wait_for_timeout(500)
                    break
            except Exception:
                continue

    def _current_slug(self, page) -> str:
        try:
            return page.url.rstrip("/").split("/")[-1]
        except Exception:
            return ""

    def _continue(self, page):
        """Click the submit/continue button and wait for next page."""
        # Try multiple common selectors for the continue button
        selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Continue')",
            ".govuk-button:has-text('Continue')",
            "a.govuk-button:has-text('Continue')",
            "button.govuk-button",
            "input.govuk-button"
        ]
        
        btn = None
        for sel in selectors:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                btn = loc
                break
        
        if btn:
            try:
                btn.click(timeout=5000)
            except Exception as e:
                logger.warning(f"Regular click failed on continue button ({e}), trying dispatch_event...")
                btn.dispatch_event("click")
        else:
            # Last resort fallback
            logger.warning("No continue button found by specific selectors, trying generic button click...")
            page.locator("button.govuk-button, input.govuk-button").first.dispatch_event("click")

        page.wait_for_timeout(1000)  # Wait for navigation to trigger
        page.wait_for_load_state("domcontentloaded", timeout=60000)
        # Wait for any heading to appear to ensure new page content is loaded
        try:
            page.wait_for_selector("h1, h2, .govuk-heading-xl, .govuk-heading-l", timeout=15000)
        except Exception:
            pass

    def _answer_yes_no(self, page, slug_hint: str, yes: bool, allow_skip: bool = False):
        if allow_skip and slug_hint not in page.url:
            return
        if slug_hint and slug_hint not in page.url and not allow_skip:
            logger.debug(
                "Question page mismatch. expected=%s, got=%s", slug_hint, self._current_slug(page)
            )
        val = "yes" if yes else "no"
        logger.info(f"Answering Yes/No for '{slug_hint}': {val} (bool={yes})")
        self._click_radio_by_value(page, val)
        self._continue(page)

    def _answer_role(self, page, role: str):
        val = "paying" if role == "paying" else "receiving"
        self._click_radio_by_value(page, val)
        self._continue(page)

    def _fill_text_and_continue(self, page, field_name: str, value: str):
        field = page.locator(f"input[name='{field_name}']").first
        if field.count() == 0:
            field = page.locator("input[type='text'], input[type='number']").first
        field.fill("")
        field.fill(value)
        self._continue(page)

    def _select_benefits(self, page, benefits: list[str]):
        # Some journeys show an intermediate yes/no before the checkbox list.
        if benefits and not self._has_matching_label(page, benefits[0]):
            yes_no_labels = {
                t.strip().lower()
                for t in page.locator("label").all_inner_texts()
                if t.strip()
            }
            if "yes" in yes_no_labels and "no" in yes_no_labels:
                self._click_label(page, "Yes")
                self._continue(page)

        if not benefits:
            # If no benefits provided, we must select "None of these" to continue
            none_labels = ["None of these", "None of the above", "No, I do not get any of these"]
            found_none = False
            for nl in none_labels:
                if self._click_label(page, nl):
                    found_none = True
                    break
            
            if not found_none:
                logger.warning("Could not find a 'None of these' option on the benefits page.")
        else:
            for benefit in benefits:
                if not self._click_label(page, benefit):
                    labels = [t.strip() for t in page.locator("label").all_inner_texts() if t.strip()]
                    raise RuntimeError(
                        f"Could not locate benefit option: '{benefit}'. "
                        f"url={page.url} labels={labels[:14]}"
                    )
        self._continue(page)

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (text or "").lower())

    def _click_label(self, page, label_text: str) -> bool:
        """Try exact label click, fall back to normalised fuzzy match."""
        try:
            target = page.get_by_label(label_text, exact=True).first
            if target.count() > 0:
                target.click()
                return True
        except Exception:
            pass

        want = self._normalize_text(label_text)
        labels = page.locator("label")
        for idx in range(labels.count()):
            lbl = labels.nth(idx)
            txt = lbl.inner_text().strip()
            norm = self._normalize_text(txt)
            if norm == want or want in norm or norm in want:
                lbl.click()
                return True
        return False

    def _has_matching_label(self, page, label_text: str) -> bool:
        want = self._normalize_text(label_text)
        labels = page.locator("label")
        for idx in range(labels.count()):
            txt = labels.nth(idx).inner_text().strip()
            norm = self._normalize_text(txt)
            if norm == want or want in norm or norm in want:
                return True
        return False

    def _select_frequency(self, page, frequency: str):
        self._click_radio_by_value(page, frequency)
        self._continue(page)

    def _fill_all_child_names(self, page, children: list[ChildOvernightStay], query: ChildMaintenanceQuery = None):
        """
        Fill children's names on the dedicated names page.
        Supports both a single page with multiple inputs and sequential one-name-per-page flows.
        """
        selector = "input[type='text'], input.govuk-input"
        page.wait_for_selector(selector, state="visible", timeout=15000)

        selector = "input[type='text']:visible, input[type='search']:visible, input:not([type]):visible"
        
        # Determine if we are on a multi-input page or a sequential flow
        inputs = page.locator(selector)
        input_count = inputs.count()
        
        logger.debug(
            "Names page: found %d visible input(s) for %d child(ren). url=%s",
            input_count, len(children), page.url
        )

        if input_count > 1:
            # Case 1: Multiple inputs on one page
            for i in range(input_count):
                if i == 0 and getattr(query, "child_name", ""):
                    name = query.child_name
                else:
                    name = children[i].name if i < len(children) else f"Child {i + 1}"
                inputs.nth(i).fill(name)
            self._continue(page)
        elif input_count == 1:
            # Case 2: One input per page (sequential flow)
            for i in range(len(children)):
                # Ensure input is ready
                page.wait_for_selector(selector, state="visible", timeout=10000)
                inp = page.locator(selector).first
                
                if i == 0 and getattr(query, "child_name", ""):
                    name = query.child_name
                else:
                    name = children[i].name if i < len(children) else f"Child {i + 1}"
                inp.fill(name)
                self._continue(page)
                
                # If there are more children, wait for the next page/input
                if i < len(children) - 1:
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    # Break if we navigated away from a name-entry style page
                    if not page.locator(selector).first.is_visible(timeout=2000):
                        logger.warning("Expected another name input but page changed. url=%s", page.url)
                        break
        else:
            # Case 3: No inputs found (unexpected)
            logger.warning("No name inputs found on %s. Continuing anyway.", page.url)
            self._continue(page)

    def _select_overnight(self, page, overnight_key: str):
        """
        Select the overnight-stays radio for the current parent.
        Uses the internal key (e.g. '52-103') to look up the GOV.UK label.
        """
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        label_text = OVERNIGHT_LABELS.get(overnight_key, OVERNIGHT_LABELS["never"])
        if not self._click_label(page, label_text):
            available = [
                t.strip() for t in page.locator("label").all_inner_texts() if t.strip()
            ]
            raise RuntimeError(
                f"Could not find overnight option '{label_text}'. "
                f"url={page.url} labels={available[:12]}"
            )
        self._continue(page)
