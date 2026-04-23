from scrapers.nationwide.models import NationwideQuery
from scrapers.nationwide.scraper import NationwideScraper
from scrapers.parkers.scraper import ParkersScraper
from scrapers.parkers.models import ParkersConfig
from scrapers.listentotaxman import ListenToTaxmanScraper, ScrapeConfig as TaxScrapeConfig
import asyncio
import threading
import uuid
import logging
import json
import os
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── IDU background session keeper ─────────────────────────────────────────────
# Started once at module-import time so the session is always warm.
# No human intervention ever required.
def _start_idu_keeper():
    try:
        from scrapers.idu.session_keeper import start_session_keeper
        _u = os.getenv("IDU_USERNAME", "")
        _p = os.getenv("IDU_PASSWORD", "")
        if _u and _p:
            # Disabled: do not auto-start IDU session keeper on startup.
            # start_session_keeper(username=_u, password=_p)
            pass
        else:
            logger.warning(
                "IDU_USERNAME / IDU_PASSWORD not set in .env — "
                "session keeper not started. Set them to enable full automation."
            )
    except Exception as exc:
        logger.warning("Could not start IDU session keeper: %s", exc)

# Run in a short-lived thread so it doesn't block module import
threading.Thread(target=_start_idu_keeper, daemon=True, name="IDUKeeperStarter").start()
# ──────────────────────────────────────────────────────────────────────────────

# Global session storage for IDU OTP flow
# active_idu_sessions remains in-memory because it holds live Playwright/Browser objects 
# which cannot be serialized to disk. However, active_idu_results is now file-based.
active_idu_sessions = {}  # session_id -> IDUScraper instance


# ── IDU Threading Lock ───────────────────────────────────────────────────────
# Used to ensure only one thread at a time performs core IDU browser operations.
# Playwright's sync_api is strictly bound to the thread that created it.
# We no longer use a singleton IDUScraper object; instead, we create a fresh 
# instance per request, which is 100% thread-safe.
_idu_operation_lock = threading.Lock()

def _run_idu_task(user: str, pwd: str, task_fn):
    """
    Safely execute an IDU task in a dedicated Playwright instance.
    The instance loads the shared session file maintained by the background keeper.
    """
    from scrapers.idu.scraper import IDUScraper
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    username = user or os.getenv("IDU_USERNAME", "")
    password = pwd or os.getenv("IDU_PASSWORD", "")

    # We use a lock mainly to prevent two threads from trying to 
    # update the session file simultaneously if it ever expires.
    with _idu_operation_lock:
        scraper = IDUScraper(username=username, password=password, headless=None)
        try:
            return task_fn(scraper)
        finally:
            scraper.close()


# File-based result storage
SESSION_RESULT_DIR = Path("backend/output/sessions/results")
SESSION_RESULT_DIR.mkdir(parents=True, exist_ok=True)

def _get_result_path(session_id: str) -> Path:
    return SESSION_RESULT_DIR / f"{session_id}.json"

def _save_idu_result(session_id: str, data: dict):
    path = _get_result_path(session_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _load_idu_result(session_id: str) -> dict:
    path = _get_result_path(session_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _cleanup_old_sessions(max_age_seconds: int = 3600):
    """Delete session result files older than max_age_seconds."""
    now = time.time()
    for file in SESSION_RESULT_DIR.glob("*.json"):
        if now - file.stat().st_mtime > max_age_seconds:
            try:
                file.unlink()
                logger.info(f"Cleaned up expired session result: {file.name}")
            except Exception as e:
                logger.warning(f"Failed to delete expired session file {file}: {e}")

async def run_tax_scraper(
    salary: int,
    period: str = "month",
    tax_year: str = "2025/26",
    region: str = "UK",
    age: str = "under 65",
    student_loan: str = "No",
    pension_amount: float = 0,
    pension_type: str = "£",
    allowances: float = 0,
    tax_code: str = "",
    married: bool = False,
    blind: bool = False,
    no_ni: bool = False,
):
    """
    Service function to bootstrap the tax scraping process.
    """
    loop = asyncio.get_running_loop()

    def _run_sync():
        config = TaxScrapeConfig(
            salary=salary,
            salary_period=period,
            tax_year=tax_year,
            region=region,
            age=age,
            student_loan=student_loan,
            pension_amount=pension_amount,
            pension_type=pension_type,
            allowances=allowances,
            tax_code=tax_code,
            married=married,
            blind=blind,
            no_ni=no_ni,
        )
        headless_mode = os.getenv("HEADLESS", "true").lower() == "true"
        with ListenToTaxmanScraper(headless=headless_mode) as scraper:
            return scraper.scrape(config, screenshot=True)

    result = await loop.run_in_executor(None, _run_sync)
    return result.to_dict() if hasattr(result, 'to_dict') else result


async def run_counciltax_scraper(postcode: str):
    """
    Service function to bootstrap the council tax scraping process.
    """
    from scrapers.counciltax.scraper import CouncilTaxScraper
    
    loop = asyncio.get_running_loop()

    def _run_sync():
        with CouncilTaxScraper() as scraper:
            return scraper.lookup(postcode)

    result = await loop.run_in_executor(None, _run_sync)
    return result.to_dict() if hasattr(result, 'to_dict') else result


async def run_parkers_scraper(plate: str):
    """
    Service function to bootstrap the Parkers scraping process.
    """
    loop = asyncio.get_running_loop()

    def _run_sync():
        headless_mode = os.getenv("HEADLESS", "true").lower() == "true"
        scraper = ParkersScraper(headless=headless_mode)
        return scraper.valuate_by_reg(plate)

    result = await loop.run_in_executor(None, _run_sync)
    return result.to_dict() if hasattr(result, 'to_dict') else result


async def run_mouseprice_scraper(postcode: str):
    """
    Service function to bootstrap the Mouseprice scraping process.
    """
    import asyncio
    from scrapers.mouseprice_scraper import MousePriceScraper

    loop = asyncio.get_running_loop()

    def _run_sync():
        headless_mode = os.getenv("HEADLESS", "true").lower() == "true"
        scraper = MousePriceScraper(headless=headless_mode)
        return scraper.scrape_postcode(postcode)

    result = await loop.run_in_executor(None, _run_sync)
    return result


async def run_nationwide_scraper(
    region: str = "Greater London",
    postcode: str = "",
    property_value: int = 0,
    from_year: int = 0,
    from_quarter: int = 1,
    to_year: int = 0,
    to_quarter: int = 1,
) -> dict:
    """
    Service function to bootstrap the Nationwide HPI scraping process.
    """
    query = NationwideQuery(
        region=region,
        postcode=postcode,
        property_value=property_value,
        from_year=from_year,
        from_quarter=from_quarter,
        to_year=to_year,
        to_quarter=to_quarter,
    )

    loop = asyncio.get_running_loop()

    def _run_sync():
        headless_mode = os.getenv("HEADLESS", "true").lower() == "true"
        with NationwideScraper(headless=headless_mode) as scraper:
            return scraper.scrape(query)

    result = await loop.run_in_executor(None, _run_sync)
    return result.to_dict() if hasattr(result, 'to_dict') else result


async def run_lps_scraper(
    search_type: str = "postcode",
    postcode: str = "",
    property_number: str = "",
    adv_property_number: str = "",
    street: str = "",
    town: str = "",
    district_council: str = "",
    property_id: str = "",
    max_pages: int = 3,
    fetch_details: bool = True,
) -> dict:
    from scrapers.lps.scraper import LpsScraper
    from scrapers.lps.models import LpsQuery

    query = LpsQuery(
        search_type=search_type,
        postcode=postcode,
        property_number=property_number,
        adv_property_number=adv_property_number,
        street=street,
        town=town,
        district_council=district_council,
        property_id=property_id,
        max_pages=max_pages,
    )

    try:
        loop = asyncio.get_event_loop()
        scraper = LpsScraper()
        result = await loop.run_in_executor(None, scraper.scrape, query)
        return result.to_dict() if hasattr(result, 'to_dict') else result
    except Exception as e:
        # Assuming 'logger' is available or imported elsewhere, otherwise use print
        return {"error": str(e), "results": []}


async def run_landregistry_scraper(
    customer_reference: str,
    username: str = None,
    password: str = None,
    title_number: str = "",
    flat: str = "",
    house: str = "",
    street: str = "",
    town: str = "",
    postcode: str = "",
    order_register: bool = True,
    order_title_plan: bool = True,
):
    """
    Service function to bootstrap the Land Registry scraping process.
    """
    from scrapers.landregistry.models import LandRegistryQuery
    from scrapers.landregistry.scraper import LandRegistryScraper
    import asyncio

    query = LandRegistryQuery(
        username=username,
        password=password,
        customer_reference=customer_reference,
        title_number=title_number,
        flat=flat,
        house=house,
        street=street,
        town=town,
        postcode=postcode,
        order_register=order_register,
        order_title_plan=order_title_plan,
    )

    try:
        loop = asyncio.get_event_loop()
        print("[LR-SERVICE] Starting LandRegistryScraper...", flush=True)
        result = await loop.run_in_executor(None, LandRegistryScraper().scrape, query)
        print("[LR-SERVICE] Scraper completed successfully!", flush=True)
        return result.to_dict() if hasattr(result, 'to_dict') else result
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[LR-SERVICE] ERROR: {e}", flush=True)
        print(f"[LR-SERVICE] TRACEBACK:\n{tb}", flush=True)
        logger.error(f"Land Registry scraper service error: {e}", exc_info=True)
            
        return {
            "error": str(e),
            "traceback": tb,
            "register_data": {},
            "title_plan_data": {}
        }


async def run_child_maintenance_scraper(
    role: str,
    multiple_receiving_parents: bool,
    benefits: list[str],
    income: float,
    income_frequency: str,
    add_parent_names: bool,
    paying_parent_name: str,
    receiving_parent_name: str,
    child_name: str,
    other_children_in_home,  # str ("None","1","2","3 or more") or int
    receiving_parents: list[dict],
    headless: bool = True
):
    """
    Service function to bootstrap the GOV.UK child maintenance scraper.

    Accepts the new frontend payload shape where each receiving parent has:
        { children_count: int, children_names: [str, ...], overnight_stays: str }
    Also supports the legacy shape: { children: [{name, overnight_stays}, ...] }
    """
    from scrapers.child_maintenance.models import (
        ChildMaintenanceQuery,
        ReceivingParent,
        ChildOvernightStay,
    )
    from scrapers.child_maintenance.scraper import ChildMaintenanceScraper

    parsed_receiving_parents = []
    for parent in receiving_parents or []:
        children: list[ChildOvernightStay] = []

        # ── NEW shape: { children_count, children_names, overnight_stays } ──
        if "children_count" in parent or "children_names" in parent:
            count = max(1, int(parent.get("children_count") or 1))
            names: list[str] = list(parent.get("children_names") or [])
            # Pad with placeholders if names list is shorter than count
            while len(names) < count:
                names.append(f"Child {len(names) + 1}")
            # Use parent-level overnight_stays for every child
            overnight = parent.get("overnight_stays", "never") or "never"
            for j, name in enumerate(names[:count]):
                clean_name = name.strip()
                if not clean_name and j == 0 and child_name:
                    clean_name = child_name.strip()
                if not clean_name:
                    clean_name = f"Child {j + 1}"
                    
                children.append(
                    ChildOvernightStay(
                        name=clean_name,
                        overnight_stays=overnight,
                    )
                )

        # ── LEGACY shape: { children: [{name, overnight_stays}, ...] } ──
        else:
            for child in parent.get("children", []):
                children.append(
                    ChildOvernightStay(
                        name=child.get("name", ""),
                        overnight_stays=child.get("overnight_stays", "never"),
                    )
                )

        # Ensure at least one child entry
        if not children:
            children.append(ChildOvernightStay(name="Child 1", overnight_stays="never"))

        parsed_receiving_parents.append(ReceivingParent(children=children))

    query = ChildMaintenanceQuery(
        role=role,
        multiple_receiving_parents=multiple_receiving_parents,
        benefits=benefits or [],
        income=float(income or 0),
        income_frequency=income_frequency,
        add_parent_names=add_parent_names,
        paying_parent_name=paying_parent_name,
        receiving_parent_name=receiving_parent_name,
        child_name=child_name,
        other_children_in_home=other_children_in_home,  # passed as-is; scraper normalises
        receiving_parents=parsed_receiving_parents,
    )

    loop = asyncio.get_running_loop()

    def _run_sync():
        with ChildMaintenanceScraper(headless=headless) as scraper:
            return scraper.scrape(query)

    result = await loop.run_in_executor(None, _run_sync)
    return result.to_dict() if hasattr(result, "to_dict") else result


async def run_idu_scraper_start(
    forename: str,
    surname: str,
    username: str = None,
    password: str = None,
    dd: str = "",
    mm: str = "",
    yyyy: str = "",
    gender: str = "",
    middlename: str = "",
    reference: str = "",
    house: str = "",
    street: str = "",
    town: str = "",
    postcode: str = "",
    email: str = "",
    email2: str = "",
    mobile: str = "",
    mobile2: str = "",
    landline: str = "",
    landline2: str = "",
):
    """
    Step 1: Start IDU scraper in background, wait for OTP.
    """
    from scrapers.idu.models import IDUConfig

    session_id = str(uuid.uuid4())
    
    config = IDUConfig(
        forename=forename,
        surname=surname,
        dd=dd,
        mm=mm,
        yyyy=yyyy,
        gender=gender,
        middlename=middlename,
        reference=reference,
        house=house,
        street=street,
        town=town,
        postcode=postcode,
        email=email,
        email2=email2,
        mobile=mobile,
        mobile2=mobile2,
        landline=landline,
        landline2=landline2,
    )

    def _background_worker(sid, user, pwd, conf):
        try:
            _cleanup_old_sessions()
            _save_idu_result(sid, {"status": "processing"})

            def _logic(scraper):
                # Attach OTP sync for Step 1-2 flow
                scraper.otp_event = threading.Event()
                scraper.otp_value = {"code": ""}
                scraper.session_id = sid
                active_idu_sessions[sid] = scraper
                # The browser will load the background-keeper's session file automatically
                return scraper.search(conf, screenshot=True)

            result = _run_idu_task(user, pwd, _logic)

            _save_idu_result(sid, {
                "status": "complete",
                "result": result.to_dict() if hasattr(result, 'to_dict') else result
            })
        except Exception as e:
            _save_idu_result(sid, {
                "status": "error",
                "message": str(e)
            })
        finally:
            if sid in active_idu_sessions:
                del active_idu_sessions[sid]


    # Run in background thread
    thread = threading.Thread(
        target=_background_worker, 
        args=(session_id, username, password, config),
        daemon=True
    )
    thread.start()
    
    return {"session_id": session_id, "status": "processing"}


async def run_idu_scraper_submit_otp(session_id: str, otp: str):
    """
    Step 2: Submit OTP to unblock the background scraper.
    """
    return {"status": "error", "message": "Manual OTP submission is deprecated. The system is fully automated via email."}


async def run_idu_scraper_get_result(session_id: str):
    """
    Step 3: Poll for IDU result.
    """
    _cleanup_old_sessions()
    result = _load_idu_result(session_id)
    if not result:
        return {"status": "error", "message": "Session not found"}
    
    return result


async def run_idu_scraper(
    forename: str,
    surname: str,
    username: str = None,
    password: str = None,
    dd: str = "",
    mm: str = "",
    yyyy: str = "",
    gender: str = "",
    middlename: str = "",
    reference: str = "",
    house: str = "",
    street: str = "",
    town: str = "",
    postcode: str = "",
    email: str = "",
    email2: str = "",
    mobile: str = "",
    mobile2: str = "",
    landline: str = "",
    landline2: str = "",
):
    """
    Service function to bootstrap the IDU (Tracesmart) scraping process.
    """
    from scrapers.idu.models import IDUConfig
    from scrapers.idu.scraper import IDUScraper
    import asyncio

    config = IDUConfig(
        forename=forename,
        surname=surname,
        dd=dd,
        mm=mm,
        yyyy=yyyy,
        gender=gender,
        middlename=middlename,
        reference=reference,
        house=house,
        street=street,
        town=town,
        postcode=postcode,
        email=email,
        email2=email2,
        mobile=mobile,
        mobile2=mobile2,
        landline=landline,
        landline2=landline2,
    )

    try:
        def _run_idu_sync(user, pwd, conf):
            try:
                def _safe_task(s):
                    res = s.search(conf)
                    # If res is already a dict (e.g. error or No Match), don't call to_dict()
                    if hasattr(res, 'to_dict'):
                        return res.to_dict()
                    return res
                return _run_idu_task(user, pwd, _safe_task)
            except Exception as e:
                import traceback
                logger.error(f"IDU Internal Sync Error: {e}\n{traceback.format_exc()}")
                return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run_idu_sync, username, password, config)
    except Exception as outer_e:
        import traceback
        return {"status": "error", "error": str(outer_e), "traceback": traceback.format_exc()}

