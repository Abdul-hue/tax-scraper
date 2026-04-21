from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://child-maintenance.dwp.gov.uk/calculate/details/will-you-be-paying-or-receiving-child-maintenance-payments")
        
        # Accept cookies
        for selector in ["#cookies-accept", "#accept-cookies", "button:has-text('Accept all cookies')", "button:has-text('Accept additional cookies')"]:
            try:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=2000):
                    btn.click()
                    break
            except Exception:
                pass

        print("1. " + page.url)
        page.get_by_label("Paying").first.click()
        page.locator("button[type='submit']").click()
        page.wait_for_load_state("domcontentloaded")
        print("2. " + page.url)

        # Number of parents
        if "more-than-one" in page.url:
            page.get_by_label("No").first.click()
            page.locator("button[type='submit']").click()
            page.wait_for_load_state("domcontentloaded")
            print("2b. " + page.url)

        if "how-many-people" in page.url:
            page.locator("input[type='text']").first.fill("1")
            page.locator("button[type='submit']").click()
            page.wait_for_load_state("domcontentloaded")
            print("2c. " + page.url)

        # Benefits
        page.get_by_label("No").first.click()
        page.locator("button[type='submit']").click()
        page.wait_for_load_state("domcontentloaded")
        print("3. " + page.url)
        
        # Income
        page.get_by_label("Yes").first.click()
        page.locator("button[type='submit']").click()
        page.wait_for_load_state("domcontentloaded")
        print("4. " + page.url)
        
        page.locator("input[type='text']").first.fill("1500")
        page.locator("button[type='submit']").click()
        page.wait_for_load_state("domcontentloaded")
        print("5. " + page.url)
        
        page.get_by_label("Monthly").first.click()
        page.locator("button[type='submit']").click()
        page.wait_for_load_state("domcontentloaded")
        print("6. " + page.url)

        # Number of children
        page.locator("input[type='text']").first.fill("1")
        page.locator("button[type='submit']").click()
        page.wait_for_load_state("domcontentloaded")
        print("7. " + page.url)

        # Let's see what happens next
        browser.close()

run()
