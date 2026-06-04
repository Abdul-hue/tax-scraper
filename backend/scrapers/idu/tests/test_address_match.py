"""
Unit tests for scrapers.idu.address_match — no browser required.

Run from backend/:
    python -m unittest scrapers.idu.tests.test_address_match -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure backend/ is on sys.path regardless of where the runner is invoked
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scrapers.idu.address_match import (
    NoAddressMatchError,
    _token_match,
    _link_house_matches_config,
    match_address_link,
)


def _links(*texts: str) -> list[dict]:
    """Build a minimal links list from raw address text strings."""
    return [{"text": t} for t in texts]


# ---------------------------------------------------------------------------
# _token_match
# ---------------------------------------------------------------------------

class TestTokenMatch(unittest.TestCase):

    def test_exact(self):
        self.assertTrue(_token_match("1", "1"))
        self.assertTrue(_token_match("FLAT", "FLAT"))
        self.assertTrue(_token_match("7", "7"))

    def test_alpha_suffix_allowed(self):
        self.assertTrue(_token_match("1", "1A"))
        self.assertTrue(_token_match("1", "1B"))
        self.assertTrue(_token_match("2", "2A"))
        self.assertTrue(_token_match("36", "36A"))
        self.assertTrue(_token_match("40", "40A"))
        self.assertTrue(_token_match("7", "7B"))

    def test_digit_suffix_rejected(self):
        self.assertFalse(_token_match("1", "10"))
        self.assertFalse(_token_match("1", "11"))
        self.assertFalse(_token_match("1", "100"))
        self.assertFalse(_token_match("7", "70"))
        self.assertFalse(_token_match("7", "17"))  # 17 doesn't start with 7

    def test_no_partial_word(self):
        # "21" does not start with "1"
        self.assertFalse(_token_match("1", "21"))
        # "10" reversed — "10" starts with "1" but suffix "0" is digit
        self.assertFalse(_token_match("1", "10"))

    def test_mixed_suffix_rejected(self):
        # suffix contains a digit — not allowed
        self.assertFalse(_token_match("1", "1A2"))


# ---------------------------------------------------------------------------
# _link_house_matches_config
# ---------------------------------------------------------------------------

class TestLinkHouseMatchesConfig(unittest.TestCase):

    def test_exact_single_token(self):
        self.assertTrue(_link_house_matches_config("1", "1"))
        self.assertTrue(_link_house_matches_config("7", "7"))

    def test_exact_multi_token(self):
        self.assertTrue(_link_house_matches_config("FLAT 7", "FLAT 7"))
        self.assertTrue(_link_house_matches_config("FLAT 36A", "FLAT 36A"))

    def test_number_in_flat_name(self):
        # config="7" should match "FLAT 7" (7 is a token in the link)
        self.assertTrue(_link_house_matches_config("7", "FLAT 7"))

    def test_alpha_suffix_in_flat(self):
        # config="36" should match "FLAT 36A" via suffix rule
        self.assertTrue(_link_house_matches_config("36", "FLAT 36A"))

    def test_digit_suffix_rejected_in_flat(self):
        # "FLAT 70" must NOT match config "FLAT 7"
        self.assertFalse(_link_house_matches_config("FLAT 7", "FLAT 70"))
        # "FLAT 17" must NOT match config "FLAT 7"
        self.assertFalse(_link_house_matches_config("FLAT 7", "FLAT 17"))

    def test_plain_number_vs_higher_number(self):
        self.assertFalse(_link_house_matches_config("1", "10"))
        self.assertFalse(_link_house_matches_config("1", "11"))
        self.assertFalse(_link_house_matches_config("1", "21"))

    def test_number_in_street_name(self):
        # "1 DENSHAW DRIVE" — config "1" matches the first token "1"
        self.assertTrue(_link_house_matches_config("1", "1 DENSHAW DRIVE"))
        # "10 DENSHAW DRIVE" — config "1" must NOT match "10"
        self.assertFalse(_link_house_matches_config("1", "10 DENSHAW DRIVE"))

    def test_ten_does_not_match_one(self):
        # config "10" must NOT match link_house "1 DENSHAW DRIVE"
        self.assertFalse(_link_house_matches_config("10", "1 DENSHAW DRIVE"))

    def test_ten_matches_ten(self):
        self.assertTrue(_link_house_matches_config("10", "10 DENSHAW DRIVE"))

    def test_ground_floor_flat(self):
        self.assertTrue(_link_house_matches_config("GROUND FLOOR FLAT", "GROUND FLOOR FLAT"))


# ---------------------------------------------------------------------------
# match_address_link — integration-level tests
# ---------------------------------------------------------------------------

class TestMatchAddressLink(unittest.TestCase):

    # ── Test case 1: house="1" must NOT match "10 DENSHAW DRIVE" ─────────────

    def test_tc1_house_1_selects_1_not_10(self):
        links = _links(
            "10 DENSHAW DRIVE, MORLEY, LEEDS, LS27 8RR",
            "11 DENSHAW DRIVE, MORLEY, LEEDS, LS27 8RR",
            "1 DENSHAW DRIVE, MORLEY, LEEDS, LS27 8RR",
            "21 DENSHAW DRIVE, MORLEY, LEEDS, LS27 8RR",
        )
        idx, link = match_address_link("1", links)
        self.assertIn("1 DENSHAW DRIVE", link["text"])
        self.assertNotIn("10 DENSHAW DRIVE", link["text"])
        self.assertNotIn("11 DENSHAW DRIVE", link["text"])
        self.assertNotIn("21 DENSHAW DRIVE", link["text"])

    def test_tc1_comma_format_house_1(self):
        # IDU sometimes puts a bare number before the comma
        links = _links(
            "10, DENSHAW DRIVE, MORLEY, LEEDS",
            "1, DENSHAW DRIVE, MORLEY, LEEDS",
        )
        idx, link = match_address_link("1", links)
        self.assertEqual(link["text"], "1, DENSHAW DRIVE, MORLEY, LEEDS")

    # ── Test case 2: house="10" selects "10 DENSHAW DRIVE" ───────────────────

    def test_tc2_house_10_selects_10(self):
        links = _links(
            "1 DENSHAW DRIVE, MORLEY, LEEDS, LS27 8RR",
            "10 DENSHAW DRIVE, MORLEY, LEEDS, LS27 8RR",
            "100 DENSHAW DRIVE, MORLEY, LEEDS, LS27 8RR",
        )
        idx, link = match_address_link("10", links)
        self.assertIn("10 DENSHAW DRIVE", link["text"])

    # ── Test case 3: house="Flat 7" — exact match, no FLAT 17 / FLAT 70 ─────

    def test_tc3_flat_7_exact(self):
        # Full E5 9HD list slice
        links = _links(
            "FLAT 1, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 17, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 70, FERRY HOUSE, HARRINGTON HILL, LONDON",
        )
        idx, link = match_address_link("Flat 7", links)
        self.assertEqual(link["text"], "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON")

    def test_tc3_flat_7_not_flat_17(self):
        links = _links(
            "FLAT 17, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON",
        )
        idx, link = match_address_link("Flat 7", links)
        self.assertEqual(link["text"], "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON")

    def test_tc3_plain_7_matches_flat_7(self):
        # config "7" (no "FLAT" prefix) should still find "FLAT 7"
        links = _links(
            "FLAT 1, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 17, FERRY HOUSE, HARRINGTON HILL, LONDON",
        )
        idx, link = match_address_link("7", links)
        self.assertEqual(link["text"], "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON")

    # ── Test case 4: house="1A" — exact match ────────────────────────────────

    def test_tc4_exact_1A(self):
        links = _links(
            "1, SOME STREET, CITY",
            "1A, SOME STREET, CITY",
            "1B, SOME STREET, CITY",
        )
        idx, link = match_address_link("1A", links)
        self.assertEqual(link["text"], "1A, SOME STREET, CITY")

    def test_tc4_flat_1A_exact(self):
        links = _links(
            "FLAT 1, SOME HOUSE, TOWN",
            "FLAT 1A, SOME HOUSE, TOWN",
        )
        idx, link = match_address_link("Flat 1A", links)
        self.assertEqual(link["text"], "FLAT 1A, SOME HOUSE, TOWN")

    # ── Test case 5a: "2" present — exact wins over "2A" / "2B" ─────────────

    def test_tc5a_exact_2_over_2A_2B(self):
        links = _links(
            "2, SOME STREET, CITY",
            "2A, SOME STREET, CITY",
            "2B, SOME STREET, CITY",
        )
        idx, link = match_address_link("2", links)
        self.assertEqual(link["text"], "2, SOME STREET, CITY")

    # ── Test case 5b: "2" absent — ambiguous tie raises error ────────────────

    def test_tc5b_ambiguous_2A_2B_raises(self):
        links = _links(
            "2A, SOME STREET, CITY",
            "2B, SOME STREET, CITY",
        )
        with self.assertRaises(NoAddressMatchError):
            match_address_link("2", links)

    # ── Alpha-suffix single candidate — allowed ───────────────────────────────

    def test_alpha_suffix_single_match_ok(self):
        # Only "2A" in list, config="2" → one candidate → should succeed
        links = _links("2A, SOME STREET, CITY")
        idx, link = match_address_link("2", links)
        self.assertEqual(link["text"], "2A, SOME STREET, CITY")

    # ── FLAT 36A / 40A (real IDU formats) ────────────────────────────────────

    def test_flat_36A_exact(self):
        links = _links(
            "FLAT 36, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 36A, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 37, FERRY HOUSE, HARRINGTON HILL, LONDON",
        )
        idx, link = match_address_link("Flat 36A", links)
        self.assertEqual(link["text"], "FLAT 36A, FERRY HOUSE, HARRINGTON HILL, LONDON")

    def test_flat_36_suffix_rule(self):
        # config "Flat 36" — no exact "FLAT 36" in list, only "FLAT 36A"
        links = _links(
            "FLAT 35, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 36A, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 37, FERRY HOUSE, HARRINGTON HILL, LONDON",
        )
        idx, link = match_address_link("Flat 36", links)
        self.assertEqual(link["text"], "FLAT 36A, FERRY HOUSE, HARRINGTON HILL, LONDON")

    # ── No match raises error ─────────────────────────────────────────────────

    def test_no_match_raises(self):
        links = _links(
            "FLAT 1, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 2, FERRY HOUSE, HARRINGTON HILL, LONDON",
        )
        with self.assertRaises(NoAddressMatchError):
            match_address_link("Flat 99", links)

    # ── Shortest wins when unambiguous ───────────────────────────────────────

    def test_shortest_wins(self):
        # config "7" could match "7 SOME ROAD" and (hypothetically) "FLAT 7 SOME ROAD"
        # — "7 SOME ROAD" link_house is shorter → wins
        links = _links(
            "7 SOME ROAD, CITY",
            "FLAT 7 SOME ROAD, CITY",
        )
        idx, link = match_address_link("7", links)
        # "7 SOME ROAD" has link_house "7 SOME ROAD" (10 chars)
        # "FLAT 7 SOME ROAD" has link_house "FLAT 7 SOME ROAD" (16 chars)
        self.assertEqual(link["text"], "7 SOME ROAD, CITY")

    # ── Ground-floor / basement (no number) ──────────────────────────────────

    def test_ground_floor_flat_exact(self):
        links = _links(
            "GROUND FLOOR FLAT, 1 FERRY HOUSE, LONDON",
            "FLAT 1, FERRY HOUSE, LONDON",
        )
        idx, link = match_address_link("Ground Floor Flat", links)
        self.assertEqual(link["text"], "GROUND FLOOR FLAT, 1 FERRY HOUSE, LONDON")

    # ── Case-insensitive input ────────────────────────────────────────────────

    def test_case_insensitive(self):
        links = _links("FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON")
        idx, link = match_address_link("flat 7", links)
        self.assertEqual(link["text"], "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON")

    def test_case_insensitive_lower(self):
        links = _links("FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON")
        idx, link = match_address_link("Flat 7", links)
        self.assertEqual(link["text"], "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON")

    # ── Index returned is the correct position in the list ───────────────────

    def test_correct_index_returned(self):
        links = _links(
            "FLAT 1, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 2, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 7, FERRY HOUSE, HARRINGTON HILL, LONDON",
            "FLAT 8, FERRY HOUSE, HARRINGTON HILL, LONDON",
        )
        idx, link = match_address_link("Flat 7", links)
        self.assertEqual(idx, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
