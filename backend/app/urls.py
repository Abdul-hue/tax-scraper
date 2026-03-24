from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
import os
from app.auth.router import router as auth_router
from app.core.router import router as core_router
from app.scrapers.service import (
    run_tax_scraper,
    run_counciltax_scraper,
    run_parkers_scraper,
    run_nationwide_scraper,
    run_landregistry_scraper,
)

api_router = APIRouter()

# Include existing routers
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(core_router, prefix="/core", tags=["core"])

# Scraper Endpoints
@api_router.get("/scrapers/taxman", tags=["scrapers"])
async def get_tax_valuation(
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
    Get a tax valuation by providing salary and various tax configuration parameters.
    """
    import urllib.parse
    tax_year = urllib.parse.unquote(tax_year)
    age = urllib.parse.unquote(age)
    pension_type = urllib.parse.unquote(pension_type)
    period = urllib.parse.unquote(period)
    region = urllib.parse.unquote(region)
    student_loan = urllib.parse.unquote(student_loan)
    tax_code = urllib.parse.unquote(tax_code)

    return await run_tax_scraper(
        salary=salary,
        period=period,
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


@api_router.get("/scrapers/counciltax", tags=["scrapers"])
async def get_council_tax(postcode: str):
    """
    Get council tax bands and amounts for a given postcode.
    """
    return await run_counciltax_scraper(postcode=postcode)


@api_router.get("/scrapers/parkers", tags=["scrapers"])
async def get_car_valuation(plate: str):
    """
    Get car valuation from Parkers by registration plate.
    """
    return await run_parkers_scraper(plate=plate)


@api_router.get("/scrapers/nationwide", tags=["scrapers"])
async def get_house_price_index(
    region: str = "Greater London",
    postcode: str = "",
    property_value: int = 0,
    from_year: int = 0,
    from_quarter: int = 1,
    to_year: int = 0,
    to_quarter: int = 1,
):
    """
    Get Nationwide House Price Index valuation change for a property.
    """
    return await run_nationwide_scraper(
        region=region,
        postcode=postcode,
        property_value=property_value,
        from_year=from_year,
        from_quarter=from_quarter,
        to_year=to_year,
        to_quarter=to_quarter,
    )


@api_router.get("/scrapers/lps", tags=["scrapers"])
async def get_lps_valuation(
    search_type: str = "postcode",
    postcode: str = "",
    property_number: str = "",
    adv_property_number: str = "",
    street: str = "",
    town: str = "",
    district_council: str = "",
    property_id: str = "",
    max_pages: int = 3,
):
    from app.scrapers.service import run_lps_scraper

    return await run_lps_scraper(
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


@api_router.get("/scrapers/landregistry", tags=["scrapers"])
async def landregistry_scraper(
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
    return await run_landregistry_scraper(
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


@api_router.get("/scrapers/idu", tags=["scrapers"])
async def get_idu(
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
    from app.scrapers.service import run_idu_scraper

    return await run_idu_scraper(
        username=username,
        password=password,
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


@api_router.post("/scrapers/idu/start", tags=["scrapers"])
async def start_idu(
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
    from app.scrapers.service import run_idu_scraper_start

    return await run_idu_scraper_start(
        username=username,
        password=password,
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


@api_router.post("/scrapers/idu/submit-otp", tags=["scrapers"])
async def submit_idu_otp(session_id: str, otp: str):
    from app.scrapers.service import run_idu_scraper_submit_otp
    return await run_idu_scraper_submit_otp(session_id=session_id, otp=otp)


@api_router.get("/scrapers/idu/result/{session_id}", tags=["scrapers"])
async def get_idu_result(session_id: str):
    from app.scrapers.service import run_idu_scraper_get_result
    return await run_idu_scraper_get_result(session_id=session_id)


@api_router.get("/files/landregistry/{filename}")
@api_router.get("/files/landregistry/{filename}")
async def serve_landregistry_file(filename: str):
    # __file__ is backend/app/urls.py
    # go up 2 levels to reach backend/
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(backend_dir, "downloads", "landregistry", filename)
    
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )

@api_router.get("/files/screenshots/{filename}")
async def serve_screenshot(filename: str):
    path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "static", "screenshots", filename
    ))
    if not os.path.exists(path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )


