import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import logging
logging.basicConfig(level=logging.DEBUG)

from scrapers.listentotaxman import ListenToTaxmanScraper, ScrapeConfig

config = ScrapeConfig(
    salary         = 2200,
    salary_period  = "month",
    tax_year       = "2025/26",
    region         = "UK",
    pension_amount = 0,
    pension_type   = "£",
)

with ListenToTaxmanScraper(headless=False) as scraper:
    result = scraper.scrape(config, screenshot=True, save_json=True)
    print(result.to_json())
