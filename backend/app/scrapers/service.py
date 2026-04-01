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
            start_session_keeper(username=_u, password=_p)
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


# --- Singleton IDU scraper (avoids re-login on every request) ---
_idu_singleton: "IDUScraper | None" = None  # type: ignore[name-defined]
_idu_singleton_lock = threading.Lock()
_idu_singleton_creds: tuple = (None, None)  # (username, password)


def _get_idu_singleton(username: str, password: str):
    """Return the shared IDUScraper instance, creating it if needed.

    Credentials fall back to IDU_USERNAME / IDU_PASSWORD env vars if the
    caller does not supply them, so the API payload doesn't need to include
    credentials on every single request.

    If credentials change, the old instance is closed and a fresh one is
    created (which will attempt to restore from the saved session cookie).
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()
    username = username or os.getenv("IDU_USERNAME", "")
    password = password or os.getenv("IDU_PASSWORD", "")

    global _idu_singleton, _idu_singleton_creds
    with _idu_singleton_lock:
        if _idu_singleton is not None and _idu_singleton_creds != (username, password):
            # Credentials changed — close old instance
            try:
                _idu_singleton.close()
            except Exception:
                pass
            _idu_singleton = None

        if _idu_singleton is None:
            from scrapers.idu.scraper import IDUScraper
            logger.info("Creating new IDUScraper singleton instance")
            _idu_singleton = IDUScraper(username=username, password=password, headless=True)
            _idu_singleton_creds = (username, password)

        return _idu_singleton


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
        with ListenToTaxmanScraper(headless=True) as scraper:
            return scraper.scrape(config, screenshot=True)

    result = await loop.run_in_executor(None, _run_sync)
    return result.to_dict()


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
    return result.to_dict()


async def run_parkers_scraper(plate: str):
    """
    Service function to bootstrap the Parkers scraping process.
    """
    loop = asyncio.get_running_loop()

    def _run_sync():
        scraper = ParkersScraper(headless=True)
        return scraper.valuate_by_reg(plate)

    result = await loop.run_in_executor(None, _run_sync)
    return result.to_dict()


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
        with NationwideScraper(headless=True) as scraper:
            return scraper.scrape(query)

    result = await loop.run_in_executor(None, _run_sync)
    return result.to_dict()


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
        return result.to_dict()
    except Exception as e:
        # Assuming 'logger' is available or imported elsewhere, otherwise use print
        return {"error": str(e), "results": []}


async def run_landregistry_scraper(
    username: str,
    password: str,
    customer_reference: str,
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
        return result.to_dict()
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


async def run_idu_scraper_start(
    username: str,
    password: str,
    forename: str,
    surname: str,
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

            # Use the singleton — no new browser/login if already authenticated
            scraper = _get_idu_singleton(user, pwd)

            # Attach OTP sync mechanism to the singleton for this request
            scraper.otp_event = threading.Event()
            scraper.otp_value = {"code": ""}
            scraper.session_id = sid  # for status communication
            active_idu_sessions[sid] = scraper

            # Start search (calls _ensure_logged_in which skips if session valid)
            result = scraper.search(conf, screenshot=True)

            _save_idu_result(sid, {
                "status": "complete",
                "result": result.to_dict()
            })
        except Exception as e:
            _save_idu_result(sid, {
                "status": "error",
                "message": str(e)
            })
        finally:
            # Only remove from active_idu_sessions; do NOT close the singleton browser
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
    if session_id not in active_idu_sessions:
        return {"error": "Session not found or already closed"}
    
    scraper = active_idu_sessions[session_id]
    scraper.otp_value["code"] = otp
    scraper.otp_event.set()
    
    return {"status": "processing"}


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
    username: str,
    password: str,
    forename: str,
    surname: str,
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

    def _run_idu_sync(user, pwd, conf):
        try:
            # Use the singleton — no re-login if the session is still alive
            scraper = _get_idu_singleton(user, pwd)
            result = scraper.search(conf)
            return result.to_dict()
        except Exception as e:
            return {"error": str(e)}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_idu_sync, username, password, config)

