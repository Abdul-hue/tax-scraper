"""Business Gateway flow (scrapers/landregistry_bg/service.py) against a FAKE client.

Nothing here reaches HM Land Registry: every test hands `order` / `poll` a stand-in
client whose replies are canned in the shape client.py parses them into.

Run from backend/:  python -m unittest tests.test_landregistry_bg_service
"""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
# Register `scrapers` without running scrapers/__init__.py (it imports Playwright scrapers).
_pkg = types.ModuleType("scrapers")
_pkg.__path__ = [str(BACKEND / "scrapers")]
sys.modules.setdefault("scrapers", _pkg)

from scrapers.landregistry_bg import service  # noqa: E402
from scrapers.landregistry_bg.client import BGError, BGTransportError  # noqa: E402


class FakeCfg:
    env = "test"
    price_single, price_both = 7.0, 14.0
    continue_if_fee_exceeds = True


def _title(number="TT12345", tenure="Freehold", building_number="99"):
    return {"title_number": number, "tenure_code": "10", "tenure": tenure,
            "building_name": "", "sub_building_name": "", "building_number": building_number,
            "street": "Test Street", "city": "Testtown", "postcode": "TQ56 4HY"}


class FakeClient:
    """Records what it was asked; answers from `epd` / `oc1` (a dict, or an exception)."""

    def __init__(self, epd=None, oc1=None):
        self.cfg = FakeCfg()
        self.epd, self.oc1 = epd, oc1
        self.epd_calls, self.oc1_calls = [], []

    def _answer(self, value):
        if isinstance(value, Exception):
            raise value
        return value

    def enquiry_by_property_description(self, **kw):
        self.epd_calls.append(kw)
        return self._answer(self.epd)

    def official_copy_title_known(self, **kw):
        self.oc1_calls.append(kw)
        return self._answer(self.oc1)

    def poll_property_description(self, message_id):
        self.epd_calls.append({"poll": message_id})
        return self._answer(self.epd)

    def poll_official_copy(self, message_id):
        self.oc1_calls.append({"poll": message_id})
        return self._answer(self.oc1)


def epd_success(*titles):
    return {"status": "success", "message_id": "x", "titles": list(titles)}


def oc1_success(content=b"%PDF-1.4 register"):
    return {"status": "success", "message_id": "x", "price": "7.00", "hmlr_reference": "HM1",
            "documents": [{"name": "register.pdf", "content": content}], "message": ""}


class OrderTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.mkdtemp()
        for name in ("DOWNLOAD_DIR", "SCREENSHOT_DIR", "RESULTS_DIR"):
            patcher = mock.patch.object(service, name, tmp)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(service, "_render_preview", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def order(self, client, **kw):
        kw.setdefault("customer_reference", "430142")
        return service.order(client=client, **kw)

    # ── the happy path ───────────────────────────────────────────────────
    def test_one_title_orders_the_REGISTER_ONLY_by_default(self):
        client = FakeClient(epd=epd_success(_title()), oc1=oc1_success())
        res = self.order(client, house="99", postcode="tq564hy", message_id="CAT430142P0abc")

        self.assertEqual("ok", res["code"])
        self.assertEqual("TT12345", res["title_number"])
        self.assertTrue(res["register_url"].startswith("/api/files/landregistry/"))
        oc = client.oc1_calls[0]
        self.assertTrue(oc["register"])
        self.assertFalse(oc["title_plan"])
        self.assertEqual(7.0, oc["expected_price"])

    def test_the_callers_message_id_names_both_requests(self):
        client = FakeClient(epd=epd_success(_title()), oc1=oc1_success())
        res = self.order(client, house="99", postcode="TQ56 4HY", message_id="CAT430142P0abc")

        self.assertEqual("CAT430142P0abc-EPD", client.epd_calls[0]["message_id"])
        self.assertEqual("CAT430142P0abc-OC1", client.oc1_calls[0]["message_id"])
        self.assertEqual({"epd": "CAT430142P0abc-EPD", "oc1": "CAT430142P0abc-OC1"},
                         res["message_ids"])

    def test_a_known_title_number_skips_the_address_search(self):
        client = FakeClient(oc1=oc1_success())
        res = self.order(client, title_number=" tt 12345 ")
        self.assertEqual("ok", res["code"])
        self.assertEqual([], client.epd_calls)
        self.assertEqual("TT12345", client.oc1_calls[0]["title_number"])

    # ── what came back is judged by what it SAYS ────────────────────────
    def test_a_title_plan_sent_for_a_register_order_is_wrong_document_not_ok(self):
        """bgtest returned its sample title plan (title DN100) for a register-only
        order; it used to be saved -- and filed by CAT -- as the register."""
        plan = {"status": "success", "message_id": "x", "price": "14.00", "hmlr_reference": "",
                "documents": [{"name": "document.pdf", "content": b"%PDF plan"}], "message": ""}
        with mock.patch.object(service, "_pdf_text", return_value=(
                "these are the notes referred to on the following official copy. the electronic "
                "official copy of the title plan follows this message.")):
            res = self.order(FakeClient(oc1=plan), title_number="DN100")
        self.assertEqual(("wrong_document", "oc1"), (res["code"], res["stage"]))
        self.assertIn("title plan, not the register", res["error"])
        self.assertEqual("", res["register_url"])
        self.assertTrue(res["title_plan_url"])               # kept -- it was paid for
        self.assertEqual("14.00", res["price"])

    def test_a_file_named_as_a_plan_is_a_plan_whatever_was_asked(self):
        plan = {**oc1_success(), "documents": [{"name": "Title Plan DN100.pdf", "content": b"x"}]}
        res = self.order(FakeClient(oc1=plan), title_number="DN100")
        self.assertEqual("wrong_document", res["code"])

    def test_a_register_that_says_so_is_ok(self):
        reg = {**oc1_success(), "documents": [{"name": "document.pdf", "content": b"%PDF reg"}]}
        with mock.patch.object(service, "_pdf_text", return_value=(
                "the electronic official copy of the register follows this message. "
                "a: property register  b: proprietorship register  c: charges register")):
            res = self.order(FakeClient(oc1=reg), title_number="DN100")
        self.assertEqual("ok", res["code"])
        self.assertTrue(res["register_url"])

    def test_a_file_that_says_nothing_takes_the_requested_type(self):
        """No text and no telling name: the requested type, as before."""
        reg = {**oc1_success(), "documents": [{"name": "document.pdf", "content": b"x"}]}
        res = self.order(FakeClient(oc1=reg), title_number="DN100")
        self.assertEqual("ok", res["code"])

    # ── outcomes that are not a document ────────────────────────────────
    def test_several_titles_are_returned_to_choose_from_and_nothing_is_ordered(self):
        client = FakeClient(epd=epd_success(_title("TT1", "Leasehold"), _title("TT2")))
        res = self.order(client, flat="7", house="44", postcode="TQ56 4HY")
        self.assertEqual("multiple_titles", res["code"])
        self.assertEqual(["TT1", "TT2"], [t["title_number"] for t in res["title_matches"]])
        self.assertEqual([], client.oc1_calls)

    def test_no_title(self):
        res = self.order(FakeClient(epd=epd_success()), house="1", postcode="TQ56 4HY")
        self.assertEqual("no_title", res["code"])

    def test_a_queued_order_is_pending_with_the_id_to_collect_it(self):
        ack = {"status": "acknowledgement", "message_id": "CAT1-OC1",
               "acknowledgement": {"expected_response": "2026-11-14T09:00:00", "message": "queued",
                                   "hmlr_reference": "R1"}}
        res = self.order(FakeClient(epd=epd_success(_title()), oc1=ack),
                         house="99", postcode="TQ56 4HY", message_id="CAT1")
        self.assertEqual("pending", res["code"])
        self.assertEqual("oc1", res["stage"])
        self.assertEqual("CAT1-OC1", res["pending"]["message_id"])
        self.assertIsNone(res["error"])

    def test_a_rejection(self):
        rej = {"status": "rejection", "message_id": "x",
               "rejection": {"code": "E1", "reason": "Title closed", "validation_errors": []}}
        res = self.order(FakeClient(oc1=rej), title_number="TT1")
        self.assertEqual("rejected", res["code"])
        self.assertIn("Title closed", res["error"])

    # ── transport: the charged step is told apart from the free one ─────
    def test_no_answer_to_the_ORDER_is_transport_at_oc1(self):
        client = FakeClient(epd=epd_success(_title()), oc1=BGTransportError("timed out"))
        res = self.order(client, house="99", postcode="TQ56 4HY", message_id="CAT1")
        self.assertEqual(("transport", "oc1"), (res["code"], res["stage"]))
        self.assertEqual("CAT1-OC1", res["message_ids"]["oc1"])

    def test_no_answer_to_the_SEARCH_is_transport_at_epd(self):
        res = self.order(FakeClient(epd=BGTransportError("down")), house="99", postcode="TQ56 4HY")
        self.assertEqual(("transport", "epd"), (res["code"], res["stage"]))

    def test_a_soap_fault_is_a_fault_not_transport(self):
        res = self.order(FakeClient(oc1=BGError("SOAP fault x: y")), title_number="TT1")
        self.assertEqual("fault", res["code"])

    # ── input checked before anything is sent ───────────────────────────
    def test_invalid_input_is_refused_before_any_call(self):
        cases = [
            dict(house="1", postcode="SW1A"),            # partial postcode
            dict(house="1", postcode="CF81 1UO"),        # O is never an inward letter
            dict(house="1", postcode=""),                # nothing to search by
            dict(postcode="TQ56 4HY"),                   # postcode alone
            dict(title_number="NOT-A-TITLE"),
            dict(title_number="TT1", message_id="bad id!"),
            dict(customer_reference="   ", title_number="TT1"),
        ]
        for kw in cases:
            with self.subTest(**kw):
                client = FakeClient()
                res = self.order(client, **kw)
                self.assertEqual("invalid", res["code"], res["error"])
                self.assertEqual([], client.epd_calls + client.oc1_calls)

    # ── the stored result, for a caller that gave up waiting ────────────
    def test_the_outcome_is_kept_under_the_message_id(self):
        self.order(FakeClient(epd=epd_success(_title()), oc1=oc1_success()),
                   house="99", postcode="TQ56 4HY", message_id="CAT9P0abc")
        stored = service.stored_result("CAT9P0abc")
        self.assertEqual("ok", stored["code"])
        self.assertEqual("TT12345", stored["title_number"])

    def test_it_reads_in_progress_while_the_order_runs(self):
        seen = {}

        class Watching(FakeClient):
            def official_copy_title_known(inner, **kw):
                seen["during"] = service.stored_result("CAT9P0run")["code"]
                return super().official_copy_title_known(**kw)

        self.order(Watching(epd=epd_success(_title()), oc1=oc1_success()),
                   house="99", postcode="TQ56 4HY", message_id="CAT9P0run")
        self.assertEqual("in_progress", seen["during"])
        self.assertEqual("ok", service.stored_result("CAT9P0run")["code"])

    def test_an_unknown_or_malformed_id_is_not_found(self):
        for message_id in ("never-seen", "../../etc/passwd", ""):
            with self.subTest(message_id=message_id):
                self.assertEqual("not_found", service.stored_result(message_id)["code"])

    def test_fields_are_cut_to_the_schema_limits(self):
        client = FakeClient(epd=epd_success())
        self.order(client, house="1", street="S" * 100, town="T" * 50, postcode="TQ56 4HY")
        call = client.epd_calls[0]
        self.assertEqual(80, len(call["street"]))
        self.assertEqual(35, len(call["city"]))


class AddressFieldTests(unittest.TestCase):

    def test_mapping(self):
        cases = {
            ("", "44"): ("44", ""),
            ("", "44a"): ("44A", ""),
            ("", "15-17"): ("15", ""),            # a range sends its lower number
            ("7", "44"): ("44", "Flat 7"),
            ("Apartment 7", ""): ("", "Apartment 7"),
            ("Ground Floor Flat", "1"): ("1", "Ground Floor Flat"),
            ("A", "12"): ("12", "Flat A"),
            ("", "Rose Cottage"): ("", "Rose Cottage"),
            ("", "123456"): ("", "123456"),       # too long for BuildingNumber
        }
        for (flat, house), expected in cases.items():
            with self.subTest(flat=flat, house=house):
                self.assertEqual(expected, service._address_fields(flat, house))


class PollTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.mkdtemp()
        for name in ("DOWNLOAD_DIR", "SCREENSHOT_DIR", "RESULTS_DIR"):
            patcher = mock.patch.object(service, name, tmp)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(service, "_render_preview", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_queued_search_completes_into_THIS_orders_oc1_id_and_is_stored(self):
        client = FakeClient(epd=epd_success(_title()), oc1=oc1_success())
        res = service.poll("epd", "CAT5P0abc-EPD", "430142", client=client)
        self.assertEqual("ok", res["code"])
        self.assertEqual("CAT5P0abc-OC1", client.oc1_calls[0]["message_id"])
        self.assertEqual("ok", service.stored_result("CAT5P0abc")["code"])

    def test_polling_the_same_search_AGAIN_never_orders_twice(self):
        client = FakeClient(epd=epd_success(_title()), oc1=oc1_success())
        service.poll("epd", "CAT5P0twice-EPD", "430142", client=client)
        again = service.poll("epd", "CAT5P0twice-EPD", "430142", client=client)
        self.assertEqual("ok", again["code"])
        self.assertEqual(1, len(client.oc1_calls), "the second poll must return the stored order")

    def test_collecting_an_order(self):
        client = FakeClient(oc1=oc1_success())
        res = service.poll("oc1", "CAT1-OC1", "430142", title_number="TT1", client=client)
        self.assertEqual("ok", res["code"])
        self.assertEqual({"poll": "CAT1-OC1"}, client.oc1_calls[0])
        self.assertTrue(res["register_url"])

    def test_a_bad_message_id_is_refused(self):
        res = service.poll("oc1", "no spaces allowed", "430142", client=FakeClient())
        self.assertEqual("invalid", res["code"])


if __name__ == "__main__":
    unittest.main()
