from scrapers.nationwide.models import NationwideQuery
from scrapers.nationwide.scraper import NationwideScraper
from scrapers.parkers.scraper import ParkersScraper
from scrapers.parkers.models import ParkersConfig
from scrapers.listentotaxman import ListenToTaxmanScraper, ScrapeConfig as TaxScrapeConfig
import asyncio
import threading
import uuid

# Global session/result storage for IDU OTP flow
active_idu_sessions = {}  # session_id -> IDUScraper instance
active_idu_results = {}   # session_id -> { "status": "processing" | "complete" | "error", "result": ... }


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
        result = await loop.run_in_executor(None, LandRegistryScraper().scrape, query)
        return result.to_dict()
    except Exception as e:
        import traceback
        # Assuming logger is defined elsewhere or use print if not
        try:
            logger.error(f"Land Registry scraper service error: {e}", exc_info=True)
        except NameError:
            print(f"Land Registry scraper service error: {e}")
            
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
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
    from scrapers.idu.scraper import IDUScraper

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
            active_idu_results[sid] = {"status": "processing"}
            scraper = IDUScraper(username=user, password=pwd, headless=False)
            
            # Setup OTP sync mechanism
            scraper.otp_event = threading.Event()
            scraper.otp_value = {"code": ""}
            active_idu_sessions[sid] = scraper
            
            # Start search (which will call _ensure_logged_in and wait for otp_event)
            result = scraper.search(conf, screenshot=True)
            
            active_idu_results[sid] = {
                "status": "complete",
                "result": result.to_dict()
            }
        except Exception as e:
            active_idu_results[sid] = {
                "status": "error",
                "message": str(e)
            }
        finally:
            # Cleanup session after processing
            if sid in active_idu_sessions:
                try:
                    active_idu_sessions[sid].browser.close()
                    active_idu_sessions[sid].playwright.stop()
                except:
                    pass
                del active_idu_sessions[sid]

    # Run in background thread
    thread = threading.Thread(
        target=_background_worker, 
        args=(session_id, username, password, config),
        daemon=True
    )
    thread.start()
    
    return {"session_id": session_id, "status": "awaiting_otp"}


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
    if session_id not in active_idu_results:
        return {"status": "error", "message": "Session not found"}
    
    return active_idu_results[session_id]


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
            scraper = IDUScraper(username=user, password=pwd, headless=False)
            result = scraper.search(conf)
            return result.to_dict()
        except Exception as e:
            return {"error": str(e)}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_idu_sync, username, password, config)

