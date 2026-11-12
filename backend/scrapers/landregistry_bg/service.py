"""Business Gateway flow: address -> title number -> official copies (register / title plan).

Returns the same keys as LandRegistryResult.to_dict() (so the API and frontend treat both
methods alike) plus Business Gateway extras:
  source, bg_env, title_matches, pending, price, hmlr_reference
"""
import io
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from scrapers.landregistry_bg.client import BGError, BusinessGatewayClient

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "downloads", "landregistry"))
SCREENSHOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static", "screenshots"))


def _empty_result(customer_reference: str, env: str = "") -> dict:
    return {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "title_number": "", "address": "", "tenure": "", "administered_by": "",
        "customer_reference": customer_reference,
        "register_url": "", "title_plan_url": "",
        "register_local_path": "", "title_plan_local_path": "",
        "register_data": {}, "title_plan_data": {},
        "screenshot_url": None, "error": None,
        "source": "business_gateway", "bg_env": env,
        "title_matches": [], "pending": None, "price": "", "hmlr_reference": "",
    }


def _address_fields(flat: str, house: str) -> tuple:
    """Map the form's flat/house to BG BuildingNumber / BuildingName."""
    flat, house = (flat or "").strip(), (house or "").strip()
    number = name = ""
    if re.fullmatch(r"\d+[A-Za-z]?(-\d+[A-Za-z]?)?", house) and len(house) <= 5:
        number = house
    else:
        name = house
    if flat:
        flat_label = flat if flat.lower().startswith(("flat", "apartment", "unit")) else f"Flat {flat}"
        name = f"{flat_label} {name}".strip()
    return number, name[:50]


def _format_address(t: dict) -> str:
    line1 = " ".join(x for x in (t.get("building_number"), t.get("street")) if x)
    parts = [t.get("sub_building_name"), t.get("building_name"), line1, t.get("city"), t.get("postcode")]
    return ", ".join(p for p in parts if p)


def _rejection_text(r: dict) -> str:
    rej = r.get("rejection") or {}
    msg = rej.get("reason") or rej.get("other") or "Request rejected by Land Registry"
    errs = "; ".join(v["description"] for v in rej.get("validation_errors") or [] if v.get("description"))
    return f"{msg}{' — ' + errs if errs else ''} ({rej.get('code') or 'no code'})"


def _pending(service: str, r: dict) -> dict:
    ack = r.get("acknowledgement") or {}
    return {
        "service": service,
        "message_id": r["message_id"],
        "message": ack.get("message") or "Request queued by Land Registry",
        "expected_response": ack.get("expected_response", ""),
        "hmlr_reference": ack.get("hmlr_reference", ""),
    }


def _parse(path: str, doc_type: str) -> dict:
    try:
        from scrapers.landregistry.pdf_parser import parse_pdf
        return parse_pdf(path, doc_type=doc_type)
    except Exception as e:  # parsing is best-effort; the PDF is still available
        logger.warning("PDF parse failed for %s: %s", path, e)
        return {"parse_error": str(e)}


def _render_preview(pdf_path: str, title_number: str) -> Optional[str]:
    """Render the first content page of an official copy to PNG; return its URL.

    Business Gateway has no web page to screenshot, so this stands in for the portal
    scraper's screenshot_url. Uploads to S3 like the portal; falls back to local static files.
    """
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            idx = 0
            # Skip HMLR's leading notes page ("...official copy of the register follows this message").
            first_text = (pdf.pages[0].extract_text() or "").lower()
            if len(pdf.pages) > 1 and "follows this message" in first_text:
                idx = 1
            img = pdf.pages[idx].to_image(resolution=110).original
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            png = buf.getvalue()
    except Exception as e:
        logger.warning("Could not render preview for %s: %s", pdf_path, e)
        return None

    name = f"landregistry_bg_{re.sub(r'[^A-Z0-9]', '', title_number)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        from app.core.s3 import upload_screenshot_to_s3_sync
        return upload_screenshot_to_s3_sync(png, name)
    except Exception as e:
        logger.info("S3 upload unavailable (%s); saving preview locally", e)
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    with open(os.path.join(SCREENSHOT_DIR, name), "wb") as f:
        f.write(png)
    return f"/api/files/screenshots/{name}"


def _save_documents(res: dict, docs: list, title_number: str, register: bool, title_plan: bool) -> None:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    saved = {}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    only_one_type = register != title_plan
    for i, doc in enumerate(docs):
        if only_one_type:
            kind = "register" if register else "title_plan"
        else:
            kind = "title_plan" if "plan" in doc["name"].lower() else "register"
        fname = f"BG_{re.sub(r'[^A-Z0-9]', '', title_number)}_{kind}_{ts}{'_' + str(i) if i else ''}.pdf"
        path = os.path.join(DOWNLOAD_DIR, fname)
        with open(path, "wb") as f:
            f.write(doc["content"])
        url = f"/api/files/landregistry/{fname}"
        logger.info("BG saved %s (%d bytes) from %r", fname, len(doc["content"]), doc["name"])
        if kind == "register" and not res["register_local_path"]:
            res["register_local_path"] = res["register_url"] = url
            res["register_data"] = _parse(path, "register")
            saved["register"] = path
        elif kind == "title_plan" and not res["title_plan_local_path"]:
            res["title_plan_local_path"] = res["title_plan_url"] = url
            res["title_plan_data"] = _parse(path, "title_plan")
            saved["title_plan"] = path
    preview_src = saved.get("register") or saved.get("title_plan")
    if preview_src:
        res["screenshot_url"] = _render_preview(preview_src, title_number)


def _apply_oc1(res: dict, oc: dict, title_number: str, register: bool, title_plan: bool) -> dict:
    res["price"] = oc.get("price", "")
    res["hmlr_reference"] = oc.get("hmlr_reference") or (oc.get("acknowledgement") or {}).get("hmlr_reference", "")
    if oc["status"] == "rejection":
        res["error"] = _rejection_text(oc)
    elif oc["status"] == "acknowledgement":
        res["pending"] = _pending("oc1", oc)
    elif oc["status"] == "success":
        if oc["documents"]:
            _save_documents(res, oc["documents"], title_number, register, title_plan)
        else:
            res["error"] = oc.get("message") or "Order accepted but no electronic document was returned"
    else:
        res["error"] = f"Unexpected response type {oc.get('type_code')!r}"
    return res


def _order_copies(client, res: dict, title_number: str, register: bool, title_plan: bool) -> dict:
    res["title_number"] = title_number
    if not (register or title_plan):
        return res  # title lookup only
    cfg = client.cfg
    oc = client.official_copy_title_known(
        title_number=title_number,
        customer_reference=res["customer_reference"],
        register=register,
        title_plan=title_plan,
        property_description=res["address"],
        expected_price=cfg.price_both if (register and title_plan) else cfg.price_single,
        continue_if_fee_exceeds=cfg.continue_if_fee_exceeds,
    )
    return _apply_oc1(res, oc, title_number, register, title_plan)


def _apply_epd(client, res: dict, epd: dict, register: bool, title_plan: bool) -> dict:
    if epd["status"] == "rejection":
        res["error"] = _rejection_text(epd)
        return res
    if epd["status"] == "acknowledgement":
        res["pending"] = _pending("epd", epd)
        return res
    titles = epd.get("titles") or []
    for t in titles:
        t["address"] = _format_address(t)
    res["title_matches"] = titles
    if not titles:
        res["error"] = "No title found for that address"
        return res
    if len(titles) > 1:
        res["error"] = f"{len(titles)} titles match this address — choose the correct one"
        return res
    t = titles[0]
    res["address"], res["tenure"] = t["address"], t["tenure"]
    return _order_copies(client, res, t["title_number"], register, title_plan)


def order(
    customer_reference: str,
    title_number: str = "",
    flat: str = "",
    house: str = "",
    street: str = "",
    town: str = "",
    postcode: str = "",
    order_register: bool = True,
    order_title_plan: bool = True,
    client: Optional[BusinessGatewayClient] = None,
) -> dict:
    res = _empty_result(customer_reference)
    try:
        client = client or BusinessGatewayClient()
        res["bg_env"] = client.cfg.env
        if not customer_reference.strip():
            raise ValueError("Customer reference is required")
        title_number = title_number.strip().upper()
        if title_number:
            return _order_copies(client, res, title_number, order_register, order_title_plan)
        number, name = _address_fields(flat, house)
        epd = client.enquiry_by_property_description(
            customer_reference=customer_reference,
            building_number=number, building_name=name,
            street=street, city=town, postcode=postcode,
        )
        return _apply_epd(client, res, epd, order_register, order_title_plan)
    except (BGError, ValueError, FileNotFoundError) as e:
        logger.error("Business Gateway error: %s", e)
        res["error"] = str(e)
        return res


def poll(
    service: str,
    message_id: str,
    customer_reference: str,
    title_number: str = "",
    order_register: bool = True,
    order_title_plan: bool = True,
    client: Optional[BusinessGatewayClient] = None,
) -> dict:
    """Collect a queued response (out-of-hours / manual processing) using the original MessageID."""
    res = _empty_result(customer_reference)
    try:
        client = client or BusinessGatewayClient()
        res["bg_env"] = client.cfg.env
        if service == "epd":
            return _apply_epd(client, res, client.poll_property_description(message_id),
                              order_register, order_title_plan)
        if service == "oc1":
            res["title_number"] = title_number.strip().upper()
            return _apply_oc1(res, client.poll_official_copy(message_id),
                              res["title_number"], order_register, order_title_plan)
        raise ValueError("service must be 'epd' or 'oc1'")
    except (BGError, ValueError, FileNotFoundError) as e:
        logger.error("Business Gateway poll error: %s", e)
        res["error"] = str(e)
        return res
