
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://www.listentotaxman.com")
    page.wait_for_load_state("domcontentloaded")
    
    # Let's inspect the #pension-prepend select
    select_element = page.query_selector("#pension-prepend")
    options = select_element.query_selector_all("option")
    print("Options in #pension-prepend:")
    for opt in options:
        print(f"  value: {opt.get_attribute('value')}, text: '{opt.inner_text()}'")
    
    browser.close()
