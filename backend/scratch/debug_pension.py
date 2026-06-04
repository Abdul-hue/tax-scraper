import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from scrapers.listentotaxman import ListenToTaxmanScraper

with ListenToTaxmanScraper(headless=True) as scraper:
    scraper._page.goto(scraper.URL, wait_until="domcontentloaded", timeout=40_000)
    scraper._wait_for_form()
    
    # Let's see what elements exist around pension-prepend
    html = scraper._page.content()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    
    pension_wrapper = soup.find(id="pension-prepend")
    print("pension-prepend wrapper element:", pension_wrapper)
    if pension_wrapper:
        print("pension-prepend options:")
        for opt in pension_wrapper.find_all("option"):
            print(f"  text: {repr(opt.text)}, value: {repr(opt.get('value'))}")
            
    pension_select = soup.find("select", id="pension-prepend")
    print("select with id='pension-prepend':", pension_select)
