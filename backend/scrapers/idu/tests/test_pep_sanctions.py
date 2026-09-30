"""
Unit tests for scrapers.idu.parser.parse_pep_sanctions — no browser required.

TraceSmart's "PEP & Sanction" section has TWO sub-sections, each with its own
WorldCompliance(tm) line (the live layout, 2026-09-30):

    PEP            WorldCompliance(tm): No matches found | the match blocks
    Sanction List  WorldCompliance(tm): No matches found | the match blocks

The markup below is built to that layout. The reader works from the section's
text, so the tests vary the markup (divs, a table, the (tm) as its own element)
to pin that it does not depend on it.

Run from backend/:
    python -m unittest scrapers.idu.tests.test_pep_sanctions -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from bs4 import BeautifulSoup  # noqa: E402

from scrapers.idu.parser import parse_pep_sanctions  # noqa: E402


def _row(label, value):
    return (f'<div class="res-profile-row"><div class="res-profile-item">{label}</div>'
            f'<div class="res-profile-val-icon"></div>'
            f'<div class="res-profile-val-norm">{value}</div></div>')


def _sub(title):
    return f'<div class="res-profile-subheading"><span class="icon-info"></span>{title}</div>'


NO_MATCH = _row("WorldCompliance&trade;:", "No matches found")

REBECCA = (_row("Match Score:", "100") + _row("Name:", "Rebecca Hyde")
           + _row("Position:", "<ul><li>Mother of Dane Lloyd, Member of Parliament of Canada</li></ul>")
           + _row("Country:", "Canada") + _row("Reason:", "National:PEP:Family Member"))

OFSI = (_row("Match Score:", "92") + _row("Name:", "John Smith")
        + _row("Aliases:", "<ul><li>J Smith</li><li>Johnny Smith</li></ul>")
        + _row("Reason:", "International:Sanction:OFSI"))

FOOTER = '<div class="res-powered">Powered by <span>LexisNexis</span><sup>&reg;</sup> WorldCompliance<sup>&trade;</sup></div>'


def _page(pep, sanction, footer=FOOTER):
    return BeautifulSoup(
        '<div id="res-sanction-profile-heading" class="res-profile-heading">PEP &amp; Sanction</div>'
        f'<div id="res-sanction-body">{_sub("PEP")}{pep}{_sub("Sanction List")}{sanction}{footer}</div>',
        "html.parser")


class PepSanctionsTests(unittest.TestCase):

    def test_neither_the_reference_page(self):
        entries, sanction = parse_pep_sanctions(_page(NO_MATCH, NO_MATCH))
        self.assertEqual(entries, [])
        self.assertEqual(sanction, "No matches found")

    def test_a_PEP_match_and_a_clean_sanction_list(self):
        entries, sanction = parse_pep_sanctions(_page(REBECCA, NO_MATCH))
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual((e.match_score, e.name, e.country, e.reason, e.list_type),
                         ("100", "Rebecca Hyde", "Canada", "National:PEP:Family Member", "pep"))
        self.assertEqual(e.position, "Mother of Dane Lloyd, Member of Parliament of Canada")
        self.assertEqual(sanction, "No matches found")

    def test_a_clean_PEP_line_never_hides_a_sanctions_match(self):
        """The old reader took the FIRST WorldCompliance line -- the PEP one."""
        entries, sanction = parse_pep_sanctions(_page(NO_MATCH, OFSI))
        self.assertEqual([(e.name, e.list_type) for e in entries], [("John Smith", "sanction")])
        self.assertEqual(entries[0].aliases, ["J Smith", "Johnny Smith"])
        self.assertIn("John Smith", sanction)
        self.assertNotIn("no match", sanction.lower())

    def test_both(self):
        entries, sanction = parse_pep_sanctions(_page(REBECCA, OFSI))
        self.assertEqual([(e.name, e.list_type) for e in entries],
                         [("Rebecca Hyde", "pep"), ("John Smith", "sanction")])
        self.assertTrue(sanction.startswith("1 match(es): John Smith"))

    def test_two_PEP_matches_are_two_entries(self):
        second = (_row("Match Score:", "85") + _row("Name:", "R Hyde")
                  + _row("Reason:", "National:PEP:Associate"))
        entries, _ = parse_pep_sanctions(_page(REBECCA + second, NO_MATCH))
        self.assertEqual([e.name for e in entries], ["Rebecca Hyde", "R Hyde"])

    def test_the_trade_mark_as_its_own_element(self):
        split = ('<div class="res-profile-row"><div class="res-profile-item">WorldCompliance'
                 '<sup>&trade;</sup>:</div><div class="res-profile-val-norm">No matches found</div></div>')
        entries, sanction = parse_pep_sanctions(_page(REBECCA, split))
        self.assertEqual([e.name for e in entries], ["Rebecca Hyde"])
        self.assertEqual(sanction, "No matches found")

    def test_a_table_layout_reads_the_same(self):
        def tr(label, value):
            return f"<tr><td>{label}</td><td></td><td>{value}</td></tr>"
        pep = ("<table>" + tr("Match Score:", "100") + tr("Name:", "Rebecca Hyde")
               + tr("Reason:", "National:PEP:Family Member") + "</table>")
        clean = "<table>" + tr("WorldCompliance&trade;:", "No matches found") + "</table>"
        entries, sanction = parse_pep_sanctions(_page(pep, clean))
        self.assertEqual([(e.name, e.reason) for e in entries],
                         [("Rebecca Hyde", "National:PEP:Family Member")])
        self.assertEqual(sanction, "No matches found")

    def test_the_live_383022_page(self):
        """Rebecca Hyde's TraceSmart page, 28/09/2026, field for field -- an
        info icon (as the letter "i") before Match Score and each sub-heading."""
        icon = '<span class="icon-info">i</span>'
        pep = (_row(f"{icon}Match Score:", "100") + _row("Name:", "Rebecca Hyde")
               + _row("Last Updated:", "02/07/2026") + _row("Addresses:", "<ul><li>Canada</li></ul>")
               + _row("Country:", "Canada")
               + _row("Position:", "<ul><li>Mother of Dane Lloyd, Member of Parliament of Canada.</li></ul>")
               + _row("Reason:", "National PEP Family Member"))
        soup = BeautifulSoup(
            f'<div id="res-sanction-body">{_sub(icon + "PEP")}{pep}'
            f'{_sub(icon + "Sanction List")}{NO_MATCH}{FOOTER}</div>', "html.parser")
        entries, sanction = parse_pep_sanctions(soup)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(
            (e.match_score, e.name, e.last_updated, e.addresses, e.country, e.position, e.reason, e.list_type),
            ("100", "Rebecca Hyde", "02/07/2026", ["Canada"], "Canada",
             "Mother of Dane Lloyd, Member of Parliament of Canada.", "National PEP Family Member", "pep"))
        self.assertEqual(sanction, "No matches found")

    def test_the_cross_icon_is_never_the_sanction_result(self):
        """383022: the (x) beside "No matches found" became the Sanction List
        result, and CAT raised a false sanctions hard block."""
        for glyph in ("✖", "⊗", "×", "✘", "ⓧ"):
            def crossed(label, value):
                return (f'<div class="res-profile-row"><div class="res-profile-item">{label}</div>'
                        f'<div class="res-profile-val-icon">{glyph}</div>'
                        f'<div class="res-profile-val-norm">{value}</div></div>')
            clean = crossed("WorldCompliance&trade;:", "No matches found")
            entries, sanction = parse_pep_sanctions(_page(REBECCA, clean))
            self.assertEqual(sanction, "No matches found", ascii(glyph))
            self.assertEqual([(e.name, e.list_type) for e in entries], [("Rebecca Hyde", "pep")])
            entries, sanction = parse_pep_sanctions(_page(clean, clean))
            self.assertEqual((entries, sanction), ([], "No matches found"), ascii(glyph))

    def test_a_split_off_colon_still_closes_the_label(self):
        split = ('<div class="res-profile-row"><div class="res-profile-item">WorldCompliance'
                 '<sup>&trade;</sup><span>:</span></div>'
                 '<div class="res-profile-val-norm">No matches found</div></div>')
        self.assertEqual(parse_pep_sanctions(_page(NO_MATCH, split))[1], "No matches found")

    def test_no_section_is_nothing(self):
        self.assertEqual(parse_pep_sanctions(BeautifulSoup("<div></div>", "html.parser")), ([], ""))

    def test_a_layout_without_sub_headings_falls_back_to_the_class_reader(self):
        soup = BeautifulSoup(
            '<div id="res-sanction-body"><div class="res-profile-row res-profile-bottom-row">'
            '<div class="res-profile-item">WorldCompliance:</div>'
            '<div class="res-profile-val-norm">No matches found</div></div></div>', "html.parser")
        self.assertEqual(parse_pep_sanctions(soup), ([], "No matches found"))


if __name__ == "__main__":
    unittest.main()
