"""Minimal HM Land Registry Business Gateway SOAP client (stdlib only).

Transport: mutual TLS with our BG client certificate + WS-Security UsernameToken header.
Services: Enquiry by Property Description v2.0 (address -> title numbers),
Official Copy Title Known v2.1 (title number -> register / title plan PDFs), and their polls.
"""
import base64
import io
import logging
import zipfile
import re
import ssl
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from typing import Optional
from xml.sax.saxutils import escape

from scrapers.landregistry_bg.config import BGConfig, load_config

logger = logging.getLogger(__name__)

NS_WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
PASSWORD_TEXT = ("http://docs.oasis-open.org/wss/2004/01/"
                 "oasis-200401-wss-username-token-profile-1.0#PasswordText")
NS_I18N = "http://www.w3.org/2005/09/ws-i18n"
NS_EPD_WS = "http://epdv2_0.ws.bg.lr.gov/"
NS_EPD_REQ = "http://www.oscre.org/ns/eReg-Final/2011/RequestSearchByPropertyDescriptionV2_0"
NS_EPD_POLL = "http://poll.epdv2_0.ws.bg.lr.gov/"
NS_OC1_WS = "http://officialcopyv2_1.ws.bg.lr.gov/"
NS_OC1_REQ = "http://www.oscre.org/ns/eReg-Final/2011/RequestTitleKnownOfficialCopyV2_1"
NS_OC1_POLL = "http://poll.officialcopyv2_1.ws.bg.lr.gov/"
NS_POLL_REQ = "http://www.oscre.org/ns/eReg/MR01-20090605/PollRequest"

EPD_SERVICE = "EnquiryByPropertyDescriptionV2_0WebService"
EPD_POLL_SERVICE = "EnquiryByPropertyDescriptionV2_0PollWebService"
OC1_SERVICE = "OfficialCopyTitleKnownV2_1WebService"
OC1_POLL_SERVICE = "OC1TitleKnownV2_1PollRequestWebService"

# RequestedOfficialCopyCode
OC_REGISTER, OC_TITLE_PLAN, OC_REGISTER_AND_PLAN = "10", "20", "30"

TYPE_CODES = {"10": "acknowledgement", "20": "rejection", "30": "success"}
TENURE_CODES = {"0": "Other", "10": "Freehold", "20": "Leasehold", "30": "Commonhold", "40": "Feuhold"}


class BGError(Exception):
    """Transport error or SOAP fault from Business Gateway."""


class BGTransportError(BGError):
    """No answer from Business Gateway: connection refused, TLS failure, timeout.

    Kept apart from a SOAP fault because it means something different for a PAID
    order: HMLR may have received the request and charged for it even though we
    never saw the reply. Callers treat it as "outcome unknown" and collect the
    reply by MessageID instead of ordering again.
    """


def new_message_id() -> str:
    # Schema: 5-50 chars, [a-zA-Z0-9][a-zA-Z0-9-]*, unique per request.
    return "TIG" + uuid.uuid4().hex


def normalise_postcode(postcode: str) -> str:
    pc = re.sub(r"\s+", "", postcode or "").upper()
    return f"{pc[:-3]} {pc[-3:]}" if len(pc) > 3 else pc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first(el: Optional[ET.Element], name: str) -> Optional[ET.Element]:
    if el is None:
        return None
    return next((e for e in el.iter() if _local(e.tag) == name), None)


def _text(el: Optional[ET.Element], name: str) -> str:
    found = _first(el, name)
    return (found.text or "").strip() if found is not None else ""


class BusinessGatewayClient:
    def __init__(self, config: Optional[BGConfig] = None):
        self.cfg = config or load_config()
        ctx = ssl.create_default_context(cafile=self.cfg.ca_file)
        ctx.load_cert_chain(self.cfg.cert_file, self.cfg.key_file)
        self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    # ── transport ────────────────────────────────────────────────────────
    def _envelope(self, body_xml: str) -> bytes:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Header>
    <wsse:Security xmlns:wsse="{NS_WSSE}">
      <wsse:UsernameToken>
        <wsse:Username>{escape(self.cfg.username)}</wsse:Username>
        <wsse:Password Type="{PASSWORD_TEXT}">{escape(self.cfg.password)}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
    <i18n:international xmlns:i18n="{NS_I18N}">
      <i18n:locale>{escape(self.cfg.locale)}</i18n:locale>
    </i18n:international>
  </soapenv:Header>
  <soapenv:Body>
{body_xml}
  </soapenv:Body>
</soapenv:Envelope>""".encode("utf-8")

    def call(self, service: str, body_xml: str) -> ET.Element:
        """POST a SOAP body to `service`; return the parsed soap Body element."""
        url = f"{self.cfg.base_url}/{service}"
        req = urllib.request.Request(
            url, data=self._envelope(body_xml), method="POST",
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
        )
        logger.info("BG %s -> %s", self.cfg.env, url)
        try:
            with self._opener.open(req, timeout=self.cfg.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()  # SOAP faults arrive as HTTP 500 with a Fault body
            if not raw:
                raise BGTransportError(f"HTTP {e.code} from {url}") from e
        except urllib.error.URLError as e:
            raise BGTransportError(f"Could not reach {url}: {e.reason}") from e
        except (TimeoutError, OSError) as e:
            # A read that times out AFTER the connection opened raises
            # socket.timeout (TimeoutError), not URLError -- it used to escape as
            # an unhandled exception and an HTTP 500 to the caller.
            raise BGTransportError(f"No reply from {url}: {e}") from e

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise BGError(f"Non-XML response from {url}: {raw[:300]!r}") from e

        fault = _first(root, "Fault")
        if fault is not None:
            raise BGError(f"SOAP fault {_text(fault, 'faultcode')}: {_text(fault, 'faultstring')}")
        body = _first(root, "Body")
        if body is None:
            raise BGError(f"No SOAP Body in response from {url}")
        return body

    # ── Enquiry by Property Description v2.0 ─────────────────────────────
    def enquiry_by_property_description(
        self,
        customer_reference: str,
        building_number: str = "",
        building_name: str = "",
        street: str = "",
        city: str = "",
        postcode: str = "",
        message_id: Optional[str] = None,
    ) -> dict:
        message_id = message_id or new_message_id()
        addr = [
            ("BuildingName", building_name),
            ("BuildingNumber", building_number),
            ("StreetName", street),
            ("CityName", city),
            ("PostcodeZone", normalise_postcode(postcode) if postcode else ""),
        ]
        addr_xml = "".join(f"<req:{k}>{escape(v.strip())}</req:{k}>" for k, v in addr if v and v.strip())
        body = f"""<epd:searchProperties xmlns:epd="{NS_EPD_WS}" xmlns:req="{NS_EPD_REQ}">
  <arg0>
    <req:ID><req:MessageID>{escape(message_id)}</req:MessageID></req:ID>
    <req:Product>
      <req:ExternalReference><req:Reference>{escape(message_id[:25])}</req:Reference></req:ExternalReference>
      <req:CustomerReference><req:Reference>{escape(customer_reference[:25])}</req:Reference></req:CustomerReference>
      <req:SubjectProperty><req:Address>{addr_xml}</req:Address></req:SubjectProperty>
    </req:Product>
  </arg0>
</epd:searchProperties>"""
        return self._parse_epd_response(self.call(EPD_SERVICE, body), message_id)

    def poll_property_description(self, message_id: str) -> dict:
        body = self._poll_body(NS_EPD_POLL, message_id)
        return self._parse_epd_response(self.call(EPD_POLL_SERVICE, body), message_id)

    # ── Official Copy Title Known (OC1) v2.1 ─────────────────────────────
    def official_copy_title_known(
        self,
        title_number: str,
        customer_reference: str,
        register: bool = True,
        title_plan: bool = True,
        property_description: str = "",
        expected_price: Optional[float] = None,
        continue_if_fee_exceeds: bool = True,
        message_id: Optional[str] = None,
    ) -> dict:
        """Order official copies. Returns documents as decoded bytes (PDFs; ZIPs are unpacked)."""
        if register and title_plan:
            code = OC_REGISTER_AND_PLAN
        elif register:
            code = OC_REGISTER
        elif title_plan:
            code = OC_TITLE_PLAN
        else:
            raise ValueError("Select at least one of register / title plan")

        message_id = message_id or new_message_id()
        title_number = title_number.strip().upper()
        description = (property_description or f"Title {title_number}").strip()[:130]
        price_xml = (f"<req:ExpectedPrice><req:GrossPriceAmount>{expected_price:.2f}"
                     f"</req:GrossPriceAmount></req:ExpectedPrice>") if expected_price else ""
        body = f"""<oc:performTitleKnownSearch xmlns:oc="{NS_OC1_WS}" xmlns:req="{NS_OC1_REQ}">
  <arg0>
    <req:ID><req:MessageID>{escape(message_id)}</req:MessageID></req:ID>
    <req:Product>
      <req:ExternalReference><req:Reference>{escape(message_id[:25])}</req:Reference></req:ExternalReference>
      <req:CustomerReference><req:Reference>{escape(customer_reference[:25])}</req:Reference></req:CustomerReference>
      <req:SubjectProperty><req:TitleNumber>{escape(title_number)}</req:TitleNumber></req:SubjectProperty>
      {price_xml}
      <req:Contact>
        <req:Name>{escape(self.cfg.contact_name)}</req:Name>
        <req:Communication><req:Telephone>{escape(self.cfg.contact_phone)}</req:Telephone></req:Communication>
      </req:Contact>
      <req:TitleKnownOfficialCopy>
        <req:RequestedOfficialCopyCode>{code}</req:RequestedOfficialCopyCode>
        <req:PropertyDescription>{escape(description)}</req:PropertyDescription>
        <req:OfficialCopyTypeCode>10</req:OfficialCopyTypeCode>
        <req:ContinueIfTitleIsClosedAndContinuedIndicator>false</req:ContinueIfTitleIsClosedAndContinuedIndicator>
        <req:NotifyIfPendingFirstRegistrationIndicator>false</req:NotifyIfPendingFirstRegistrationIndicator>
        <req:NotifyIfPendingApplicationIndicator>false</req:NotifyIfPendingApplicationIndicator>
        <req:SendBackDatedIndicator>false</req:SendBackDatedIndicator>
        <req:ContinueIfActualFeeExceedsExpectedFeeIndicator>{str(continue_if_fee_exceeds).lower()}</req:ContinueIfActualFeeExceedsExpectedFeeIndicator>
      </req:TitleKnownOfficialCopy>
    </req:Product>
  </arg0>
</oc:performTitleKnownSearch>"""
        return self._parse_oc1_response(self.call(OC1_SERVICE, body), message_id)

    def poll_official_copy(self, message_id: str) -> dict:
        body = self._poll_body(NS_OC1_POLL, message_id)
        return self._parse_oc1_response(self.call(OC1_POLL_SERVICE, body), message_id)

    # ── shared helpers ───────────────────────────────────────────────────
    @staticmethod
    def _poll_body(ws_ns: str, message_id: str) -> str:
        # Poll reuses the original request's MessageID.
        return (f'<p:getResponse xmlns:p="{ws_ns}" xmlns:pr="{NS_POLL_REQ}">'
                f'<arg0><pr:ID><pr:MessageID>{escape(message_id)}</pr:MessageID></pr:ID></arg0>'
                f'</p:getResponse>')

    @staticmethod
    def _base_response(body: ET.Element, message_id: str) -> tuple:
        gw = _first(body, "GatewayResponse")
        if gw is None:
            raise BGError("Response has no GatewayResponse element")
        type_code = _text(gw, "TypeCode")
        result = {
            "message_id": message_id,
            "type_code": type_code,
            "status": TYPE_CODES.get(type_code, "unknown"),
            "rejection": None,
            "acknowledgement": None,
        }
        rej = _first(gw, "Rejection")
        if rej is not None:
            rr = _first(rej, "RejectionResponse")
            result["rejection"] = {
                "code": _text(rr, "Code"),
                "reason": _text(rr, "Reason"),
                "other": _text(rr, "OtherDescription"),
                "validation_errors": [
                    {"code": _text(v, "Code"), "description": _text(v, "Description")}
                    for v in (e for e in rej.iter() if _local(e.tag) == "ValidationErrors")
                ],
            }
        ack = _first(gw, "Acknowledgement")
        if ack is not None:
            result["acknowledgement"] = {
                "unique_id": _text(ack, "UniqueID"),
                "expected_response": _text(ack, "ExpectedResponseDateTime"),
                "message": _text(ack, "MessageDescription"),
                "hmlr_reference": _text(_first(ack, "HMLRReference"), "Reference"),
            }
        return gw, result

    @classmethod
    def _parse_oc1_response(cls, body: ET.Element, message_id: str) -> dict:
        gw, result = cls._base_response(body, message_id)
        result.update({"documents": [], "price": "", "hmlr_reference": "",
                       "message": "", "result_type_code": ""})
        results = _first(gw, "Results")
        if results is None:
            return result
        result["price"] = _text(_first(results, "ActualPrice"), "GrossPriceAmount")
        result["hmlr_reference"] = _text(_first(results, "HMLRReference"), "Reference")
        result["message"] = _text(_first(results, "MessageDetails"), "Description")
        result["result_type_code"] = _text(results, "ResultTypeCode")
        for att in (e for e in results.iter() if _local(e.tag) == "Attachment"):
            blob = _first(att, "EmbeddedFileBinaryObject")
            if blob is None or not (blob.text or "").strip():
                continue
            attrs = {_local(k): v for k, v in blob.attrib.items()}
            data = base64.b64decode("".join(blob.text.split()))
            fmt = (attrs.get("format") or attrs.get("mimeCode") or "").upper()
            title = _text(att, "Title")
            if "ZIP" in fmt or data[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    for name in zf.namelist():
                        if not name.endswith("/"):
                            result["documents"].append({"name": name, "content": zf.read(name)})
            else:
                result["documents"].append(
                    {"name": attrs.get("filename") or title or "document.pdf", "content": data})
        return result

    @classmethod
    def _parse_epd_response(cls, body: ET.Element, message_id: str) -> dict:
        gw, result = cls._base_response(body, message_id)
        result["titles"] = []
        results = _first(gw, "Results")
        if results is not None:
            for t in (e for e in results.iter() if _local(e.tag) == "Title"):
                address = _first(t, "Address")
                result["titles"].append({
                    "title_number": _text(t, "TitleNumber"),
                    "tenure_code": _text(t, "TenureTypeCode"),
                    "tenure": TENURE_CODES.get(_text(t, "TenureTypeCode"), ""),
                    "building_name": _text(address, "BuildingName"),
                    "sub_building_name": _text(address, "SubBuildingName"),
                    "building_number": _text(address, "BuildingNumber"),
                    "street": _text(address, "StreetName"),
                    "city": _text(address, "CityName"),
                    "postcode": _text(address, "Postcode"),
                })
        return result
