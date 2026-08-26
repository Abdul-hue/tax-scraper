"""
Unit tests for listentotaxman.py's result-reconciliation check — no browser,
no network, no live site required.

Run from backend/:
    python -m unittest scrapers.tests.test_listentotaxman_reconciliation -v

THE GAP THIS PROTECTS. `_submit()` waits for the page's Gross Pay cell to
show a non-zero value after clicking "Calculate My Wage", but only WARNS on
a timeout rather than failing. If the results never actually re-render for
the submitted salary (a slow load, a JS hiccup, a page that already shows
some default figures before the form is touched), `_parse_payslip` could
still read a non-empty — but STALE — payslip table, and `TaxResult.success`
(`self.error is None and bool(self.payslip)`) would report a confident,
silently wrong answer.

`_verify_gross_pay_reconciles` closes that gap with pure arithmetic instead
of more page-timing guesswork: gross pay carries no tax adjustment, so it
must equal `salary × periods-per-year` exactly (mod display rounding). That
is checkable entirely from data already parsed — no live browser needed to
verify it, which is exactly why these tests can run here.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure backend/ is on sys.path regardless of where the runner is invoked
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.listentotaxman import (
    SALARY_PERIOD_MAP,
    ListenToTaxmanScraper,
    ScrapeConfig,
)


def _cfg(**overrides) -> ScrapeConfig:
    return ScrapeConfig(**overrides)


def _summary(yearly: str) -> dict:
    return {"Gross Pay": {"percent": "", "yearly": yearly, "monthly": "", "weekly": ""}}


class ParseMoneyTests(unittest.TestCase):

    def test_parses_a_normal_amount(self):
        self.assertEqual(ListenToTaxmanScraper._parse_money("£26,364.00"), 26364.00)

    def test_parses_without_currency_symbol_or_commas(self):
        self.assertEqual(ListenToTaxmanScraper._parse_money("1200.50"), 1200.50)

    def test_blank_dash_and_none_are_unparseable(self):
        for value in ("", "   ", "-", None):
            self.assertIsNone(ListenToTaxmanScraper._parse_money(value), repr(value))

    def test_non_numeric_text_is_unparseable(self):
        self.assertIsNone(ListenToTaxmanScraper._parse_money("n/a"))


class VerifyGrossPayReconcilesTests(unittest.TestCase):
    """The check that replaces trusting page-load timing with arithmetic."""

    def test_matching_monthly_salary_passes(self):
        cfg = _cfg(salary=2200, salary_period="month")
        summary = _summary("£26,400.00")  # 2200 * 12
        ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, summary)  # no raise

    def test_matching_weekly_salary_passes(self):
        cfg = _cfg(salary=500, salary_period="week")
        summary = _summary("£26,000.00")  # 500 * 52
        ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, summary)  # no raise

    def test_matching_annual_salary_passes(self):
        cfg = _cfg(salary=30000, salary_period="year")
        summary = _summary("£30,000.00")  # 30000 * 1
        ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, summary)  # no raise

    def test_small_display_rounding_is_tolerated(self):
        """A penny or two of display rounding must not trip a false alarm."""
        cfg = _cfg(salary=437, salary_period="week")  # 437 * 52 = 22724.00
        summary = _summary("£22,724.01")
        ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, summary)  # no raise

    def test_stale_page_showing_the_default_salary_is_caught(self):
        """THE bug this exists for: the page never updated for the
        submitted salary and is still showing its own default (2200/month =
        26,400/yr) while we actually submitted 500/week (26,000/yr) — close
        enough to have looked plausible, wrong enough to matter."""
        cfg = _cfg(salary=500, salary_period="week")
        summary = _summary("£26,400.00")  # the site's own DEFAULT config's result
        with self.assertRaises(ValueError):
            ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, summary)

    def test_completely_stale_page_is_caught(self):
        cfg = _cfg(salary=5000, salary_period="month")  # expected 60,000
        summary = _summary("£12,000.00")  # left over from a previous run
        with self.assertRaises(ValueError):
            ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, summary)

    def test_missing_gross_pay_row_is_caught(self):
        cfg = _cfg(salary=2200, salary_period="month")
        with self.assertRaises(ValueError):
            ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, {})

    def test_unparseable_gross_pay_value_is_caught(self):
        cfg = _cfg(salary=2200, salary_period="month")
        with self.assertRaises(ValueError):
            ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, _summary("n/a"))

    def test_every_salary_period_reconciles_at_its_own_multiplier(self):
        """Every SalaryPeriod value the site's dropdown accepts, exercised
        against its own periods-per-year multiplier — see SALARY_PERIOD_MAP."""
        for period, periods_per_year in SALARY_PERIOD_MAP.items():
            salary = 100
            expected_yearly = salary * int(periods_per_year)
            cfg = _cfg(salary=salary, salary_period=period)
            summary = _summary(f"£{expected_yearly:,.2f}")
            ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, summary)  # no raise

    def test_unrecognised_period_falls_back_to_monthly_multiplier(self):
        """Matches _fill_form's own SALARY_PERIOD_MAP.get(..., '12') default
        for an unrecognised salary_period — verification must agree with
        what was actually submitted to the form."""
        cfg = _cfg(salary=1000, salary_period="fortnightly")  # not a real SalaryPeriod value
        summary = _summary("£12,000.00")  # 1000 * 12, the '12' fallback
        ListenToTaxmanScraper._verify_gross_pay_reconciles(cfg, summary)  # no raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
