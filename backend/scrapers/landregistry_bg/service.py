"""Business Gateway flow: address -> title number -> official copies (register / title plan).

Returns the same keys as LandRegistryResult.to_dict() (so the API and frontend treat both
methods alike) plus Business Gateway extras:
  source, bg_env, title_matches, pending, price, hmlr_reference, code, stage, message_ids

`code` is the machine-readable outcome, so a caller never has to parse `error`:

  ok               the official copy (or copies) came back and were saved
  title_only       a title was found and nothing was ordered (no copy requested)
  pending          HMLR queued the request -- collect it later by `pending.message_id`
  multiple_titles  the address matches several titles -- see `title_matches`, then
                   order again with the chosen `title_number`
  no_title         no title matches the address
  rejected         HMLR rejected the request (`error` has its reason)
  no_document      HMLR accepted the order but returned no electronic copy
  wrong_document   a register was ordered but the reply held none (e.g. only the title
                   plan). The order may have been charged; nothing is offered as the register
  invalid          the input cannot be sent (bad postcode, title number, message id)
  transport        no answer from HMLR. If `stage` is "oc1" the ORDER may have been
                   placed and charged: collect it by `message_ids["oc1"]`, never re-order
  fault            HMLR answered with a SOAP fault
  config           certificates / credentials missing on this server
  unexpected       a response type this code does not know

`stage` is the step the outcome belongs to: "epd" (address search, Enquiry by Property
Description) or "oc1" (the official copy order, the step that is charged).
"""
import io
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from scrapers.landregistry_bg.client import (
    BGError,
    BGTransportError,
    BusinessGatewayClient,
    normalise_postcode,
)

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "downloads", "landregistry"))
SCREENSHOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static", "screenshots"))

# Field limits and patterns from the BG request schemas (wsdl/*.xsd).
POSTCODE_RE = re.compile(r"[A-Z]{1,2}[0-9R][0-9A-Z]? [0-9][ABD-HJLNP-UW-Z]{2}")
TITLE_NUMBER_RE = re.compile(r"[A-Z]{0,3}[0-9]{1,6}[ZT]?")
MESSAGE_ID_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]*")
MAX_BUILDING_NUMBER, MAX_BUILDING_NAME, MAX_STREET, MAX_CITY = 5, 50, 80, 35
# A caller's message id gets "-EPD" / "-OC1" appended; MessageID is 5-50 characters.
MAX_BASE_MESSAGE_ID = 46


class InvalidInput(ValueError):
    """The request cannot be sent as given."""


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
        "code": "", "stage": "", "message_ids": {"epd": "", "oc1": ""},
    }


def _fail(res: dict, code: str, error: str) -> dict:
    res["code"], res["error"] = code, error
    return res


def _message_ids(base: str) -> dict:
    """The EPD and OC1 MessageIDs for one order, from the caller's `base` (or fresh ones).

    A caller that supplies `base` can collect a reply it never saw -- after a timeout --
    by polling these ids, instead of placing (and paying for) a second order.
    """
    from scrapers.landregistry_bg.client import new_message_id
    base = (base or "").strip()
    if not base:
        return {"epd": new_message_id(), "oc1": new_message_id()}
    if len(base) > MAX_BASE_MESSAGE_ID or not MESSAGE_ID_RE.fullmatch(base) or len(base) < 1:
        raise InvalidInput(f"message_id must be 1-{MAX_BASE_MESSAGE_ID} letters, digits or hyphens")
    return {"epd": f"{base}-EPD", "oc1": f"{base}-OC1"}


def _valid_postcode(postcode: str) -> str:
    """The postcode in the schema's form ("SW1A 1AA"), or raise InvalidInput."""
    pc = normalise_postcode(postcode)
    if not POSTCODE_RE.fullmatch(pc):
        raise InvalidInput(f"'{postcode}' is not a valid UK postcode")
    return pc


def _address_fields(flat: str, house: str) -> tuple:
    """Map the form's flat/house to BG BuildingNumber / BuildingName.

    A range ("15-17") is sent as its LOWER number -- the schema's own rule for a
    building that occupies several numbers. A number too long for BuildingNumber
    (5 characters) goes into BuildingName instead.
    """
    flat, house = (flat or "").strip(), (house or "").strip()
    number = name = ""
    m = re.fullmatch(r"(\d+[A-Za-z]?)(?:\s*-\s*\d+[A-Za-z]?)?", house)
    if m and len(m.group(1)) <= MAX_BUILDING_NUMBER:
        number = m.group(1).upper()
    else:
        name = house
    if flat:
        # "Flat 7", "Apartment 7", "Ground Floor Flat" are kept as written; a bare
        # "7" or "A" becomes "Flat 7" / "Flat A".
        has_word = re.search(r"\b(flat|apartment|apt|unit|maisonette)\b", flat, re.IGNORECASE)
        flat_label = flat if has_word else f"Flat {flat}"
        name = f"{flat_label} {name}".strip()
    return number, name[:MAX_BUILDING_NAME]


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


def _pdf_text(content: bytes, pages: int = 2) -> str:
    """The first pages' text of a PDF, lower-cased; "" when it cannot be read."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return " ".join((p.extract_text() or "") for p in pdf.pages[:pages]).lower()
    except Exception as e:  # not a PDF, or unreadable -- the name decides then
        logger.info("Could not read text from a returned document: %s", e)
        return ""


#: What HMLR's covering notes page says follows it, and what each document prints.
_REGISTER_CUES = ("official copy of the register follows", "a: property register",
                  "b: proprietorship register", "proprietorship register", "charges register")
_PLAN_CUES = ("official copy of the title plan follows", "copy of the title plan follows")


def _doc_kind(doc: dict) -> str:
    """"register", "title_plan" or "" -- from what the document SAYS, then its name.

    ⚠️ NEVER FROM WHAT WAS ASKED FOR (2026-11-13). This used to label every file
    with the requested type whenever only one was requested, so a title plan sent
    back for a register order (bgtest's sample for title DN100) was saved -- and
    filed by the caller -- as the register. HMLR's covering notes page names the
    copy that follows it; a register also prints its A/B/C register headings.
    """
    text = _pdf_text(doc.get("content") or b"")
    if any(cue in text for cue in _PLAN_CUES) and not any(cue in text for cue in _REGISTER_CUES[1:]):
        return "title_plan"
    if any(cue in text for cue in _REGISTER_CUES):
        return "register"
    name = str(doc.get("name") or "").lower()
    if "plan" in name:
        return "title_plan"
    if "register" in name:
        return "register"
    return ""


def _save_documents(res: dict, docs: list, title_number: str, register: bool, title_plan: bool) -> None:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    saved = {}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    only_one_type = register != title_plan
    for i, doc in enumerate(docs):
        # What the file is, by its content; only a file that says nothing either
        # way takes the type that was asked for.
        kind = _doc_kind(doc) or (("register" if register else "title_plan") if only_one_type else "register")
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
    res["stage"] = "oc1"
    res["price"] = oc.get("price", "")
    res["hmlr_reference"] = oc.get("hmlr_reference") or (oc.get("acknowledgement") or {}).get("hmlr_reference", "")
    if oc["status"] == "rejection":
        return _fail(res, "rejected", _rejection_text(oc))
    if oc["status"] == "acknowledgement":
        res["pending"] = _pending("oc1", oc)
        res["code"] = "pending"
        return res
    if oc["status"] == "success":
        if not oc["documents"]:
            return _fail(res, "no_document",
                         oc.get("message") or "Order accepted but no electronic document was returned")
        _save_documents(res, oc["documents"], title_number, register, title_plan)
        # ⚠️ A REGISTER WAS ORDERED AND NONE CAME BACK -- e.g. only the title
        # plan. Not "ok": the caller would file the plan as the register. The
        # plan is still saved (`title_plan_url`); it was paid for.
        if register and not res["register_local_path"]:
            return _fail(res, "wrong_document",
                         "HM Land Registry sent the title plan, not the register"
                         if res["title_plan_local_path"] else
                         "HM Land Registry's reply did not contain the register")
        res["code"] = "ok"
        return res
    return _fail(res, "unexpected", f"Unexpected response type {oc.get('type_code')!r}")


def _order_copies(client, res: dict, title_number: str, register: bool, title_plan: bool) -> dict:
    res["title_number"] = title_number
    if not (register or title_plan):
        res["code"] = "title_only"
        return res  # title lookup only
    cfg = client.cfg
    # Set BEFORE the call: a transport error from here on means the order may
    # have been placed (and charged) -- see `order`'s except clause.
    res["stage"] = "oc1"
    oc = client.official_copy_title_known(
        title_number=title_number,
        customer_reference=res["customer_reference"],
        register=register,
        title_plan=title_plan,
        property_description=res["address"],
        expected_price=cfg.price_both if (register and title_plan) else cfg.price_single,
        continue_if_fee_exceeds=cfg.continue_if_fee_exceeds,
        message_id=res["message_ids"]["oc1"],
    )
    return _apply_oc1(res, oc, title_number, register, title_plan)


def _apply_epd(client, res: dict, epd: dict, register: bool, title_plan: bool) -> dict:
    res["stage"] = "epd"
    if epd["status"] == "rejection":
        return _fail(res, "rejected", _rejection_text(epd))
    if epd["status"] == "acknowledgement":
        res["pending"] = _pending("epd", epd)
        res["code"] = "pending"
        return res
    titles = epd.get("titles") or []
    for t in titles:
        t["address"] = _format_address(t)
    res["title_matches"] = titles
    if not titles:
        return _fail(res, "no_title", "No title found for that address")
    if len(titles) > 1:
        return _fail(res, "multiple_titles", f"{len(titles)} titles match this address — choose the correct one")
    t = titles[0]
    res["address"], res["tenure"] = t["address"], t["tenure"]
    return _order_copies(client, res, t["title_number"], register, title_plan)


RESULTS_DIR = os.path.join(DOWNLOAD_DIR, "results")


def _result_path(message_id: str) -> Optional[str]:
    base = (message_id or "").strip()
    if not base or len(base) > MAX_BASE_MESSAGE_ID or not MESSAGE_ID_RE.fullmatch(base):
        return None
    return os.path.join(RESULTS_DIR, f"{base}.json")


def _store_result(message_id: str, res: dict) -> None:
    """Keep this order's outcome under the caller's message id. Best effort.

    ⚠️ WHY. The caller (CAT) waits a fixed time for the reply. When it gives up,
    this process carries on -- the order still completes, and HMLR still charges
    -- but the reply is lost. `stored_result` lets the caller collect the real
    outcome later instead of ordering, and paying, a second time.
    """
    path = _result_path(message_id)
    if not path:
        return
    try:
        import json
        os.makedirs(RESULTS_DIR, exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(res, f)
        os.replace(tmp, path)
    except Exception as e:  # never lose the reply over its copy
        logger.warning("Could not store the result for %s: %s", message_id, e)


def stored_result(message_id: str) -> dict:
    """The outcome stored for an order placed with `message_id`.

    `code` is "in_progress" while that order is still running here, and
    "not_found" when this server never saw the id (or it is malformed).
    """
    path = _result_path(message_id)
    if not path or not os.path.isfile(path):
        return {"code": "not_found", "error": "No order with that message id on this server"}
    try:
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"code": "not_found", "error": f"Stored result unreadable: {e}"}


def order(
    customer_reference: str,
    title_number: str = "",
    flat: str = "",
    house: str = "",
    street: str = "",
    town: str = "",
    postcode: str = "",
    order_register: bool = True,
    order_title_plan: bool = False,
    message_id: str = "",
    client: Optional[BusinessGatewayClient] = None,
) -> dict:
    """Find the title for an address (or take `title_number`) and order its official copy.

    `order_title_plan` defaults to False: the register (owners, charges, price paid)
    is what callers read; the plan is a boundary map and costs a second fee.

    With a caller's `message_id`, the outcome is also kept under it
    (`stored_result`), marked "in_progress" while the order runs.
    """
    if _result_path(message_id):
        _store_result(message_id, {**_empty_result(customer_reference), "code": "in_progress"})
    res = _order(customer_reference, title_number, flat, house, street, town, postcode,
                 order_register, order_title_plan, message_id, client)
    if _result_path(message_id):
        _store_result(message_id, res)
    return res


def _order(customer_reference, title_number, flat, house, street, town, postcode,
           order_register, order_title_plan, message_id, client) -> dict:
    res = _empty_result(customer_reference)
    try:
        if not (customer_reference or "").strip():
            raise InvalidInput("Customer reference is required")
        res["message_ids"] = _message_ids(message_id)
        title_number = re.sub(r"\s+", "", title_number or "").upper()
        if title_number and not TITLE_NUMBER_RE.fullmatch(title_number):
            raise InvalidInput(f"'{title_number}' is not a valid title number")
        if not title_number:
            if not (postcode or "").strip():
                raise InvalidInput("A postcode (or a title number) is required")
            postcode = _valid_postcode(postcode)
            number, name = _address_fields(flat, house)
            if not (number or name or (street or "").strip()):
                raise InvalidInput("A house number, house name or street is required with the postcode")
        client = client or BusinessGatewayClient()
        res["bg_env"] = client.cfg.env
        if title_number:
            return _order_copies(client, res, title_number, order_register, order_title_plan)
        res["stage"] = "epd"
        epd = client.enquiry_by_property_description(
            customer_reference=customer_reference,
            building_number=number, building_name=name,
            street=(street or "").strip()[:MAX_STREET],
            city=(town or "").strip()[:MAX_CITY],
            postcode=postcode,
            message_id=res["message_ids"]["epd"],
        )
        return _apply_epd(client, res, epd, order_register, order_title_plan)
    except InvalidInput as e:
        return _fail(res, "invalid", str(e))
    except BGTransportError as e:
        logger.error("Business Gateway transport error at %s: %s", res["stage"] or "setup", e)
        return _fail(res, "transport", str(e))
    except BGError as e:
        logger.error("Business Gateway error at %s: %s", res["stage"] or "setup", e)
        return _fail(res, "fault", str(e))
    except (ValueError, FileNotFoundError) as e:
        logger.error("Business Gateway configuration error: %s", e)
        return _fail(res, "config", str(e))


def poll(
    service: str,
    message_id: str,
    customer_reference: str,
    title_number: str = "",
    order_register: bool = True,
    order_title_plan: bool = False,
    client: Optional[BusinessGatewayClient] = None,
) -> dict:
    """Collect a queued response (out-of-hours / manual processing) using the original MessageID.

    ⚠️ An EPD reply that resolves to ONE title goes straight on to order its copy. For an
    order placed with a caller's message id ("<base>-EPD"), that order is "<base>-OC1" and
    the outcome is stored under <base> -- so polling the same EPD again returns what was
    stored instead of ordering (and paying) a second time.
    """
    base = message_id[:-4] if (message_id or "").endswith(("-EPD", "-OC1")) else ""
    if not _result_path(base):
        base = ""
    if service == "epd" and base:
        prior = stored_result(base)
        if prior.get("stage") == "oc1" or prior.get("code") in ("ok", "no_document", "in_progress"):
            return prior
    if base:
        _store_result(base, {**_empty_result(customer_reference), "code": "in_progress"})
    res = _poll(service, message_id, customer_reference, title_number, order_register,
                order_title_plan, client, base)
    if base:
        _store_result(base, res)
    return res


def _poll(service, message_id, customer_reference, title_number, order_register,
          order_title_plan, client, base) -> dict:
    res = _empty_result(customer_reference)
    try:
        if not MESSAGE_ID_RE.fullmatch(message_id or "") or len(message_id) > 50:
            raise InvalidInput("message_id is not a Business Gateway message id")
        client = client or BusinessGatewayClient()
        res["bg_env"] = client.cfg.env
        if service == "epd":
            res["stage"] = "epd"
            oc1 = f"{base}-OC1" if base else _message_ids("")["oc1"]
            res["message_ids"] = {"epd": message_id, "oc1": oc1}
            return _apply_epd(client, res, client.poll_property_description(message_id),
                              order_register, order_title_plan)
        if service == "oc1":
            res["stage"] = "oc1"
            res["message_ids"]["oc1"] = message_id
            res["title_number"] = re.sub(r"\s+", "", title_number or "").upper()
            return _apply_oc1(res, client.poll_official_copy(message_id),
                              res["title_number"], order_register, order_title_plan)
        raise InvalidInput("service must be 'epd' or 'oc1'")
    except InvalidInput as e:
        return _fail(res, "invalid", str(e))
    except BGTransportError as e:
        logger.error("Business Gateway poll transport error: %s", e)
        return _fail(res, "transport", str(e))
    except BGError as e:
        logger.error("Business Gateway poll error: %s", e)
        return _fail(res, "fault", str(e))
    except (ValueError, FileNotFoundError) as e:
        logger.error("Business Gateway configuration error: %s", e)
        return _fail(res, "config", str(e))
