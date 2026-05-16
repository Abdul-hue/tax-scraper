
import asyncio
import logging
from scrapers.child_maintenance.scraper import ChildMaintenanceScraper
from scrapers.child_maintenance.models import ChildMaintenanceQuery, ReceivingParent, ChildOvernightStay

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_scraper():
    query = ChildMaintenanceQuery(
        role="paying",
        multiple_receiving_parents=True,
        benefits=[],
        income=0,
        income_frequency="monthly",
        add_parent_names=True,
        paying_parent_name="Alex",
        receiving_parent_name="Sam",
        child_name="Charlie",
        other_children_in_home="1",
        receiving_parents=[
            ReceivingParent(
                children=[
                    ChildOvernightStay(name="Charlie", overnight_stays="never")
                ]
            )
        ]
    )

    print(f"Starting test with query: {query}")
    
    with ChildMaintenanceScraper(headless=False) as scraper:
        result = scraper.scrape(query)
        print("\n--- RESULTS ---")
        print(f"Result: {result.result}")
        print(f"Reason: {result.reason}")
        print(f"PDF URL: {result.pdf_url}")
        if result.error:
            print(f"Error: {result.error}")
        
        # Check normalization
        normalized = scraper._normalize_query(query)
        print("\n--- NORMALIZED QUERY ---")
        print(f"Child Name: {normalized.receiving_parents[0].children[0].name}")
        print(f"Multiple Parents: {normalized.multiple_receiving_parents}")

if __name__ == "__main__":
    asyncio.run(test_scraper())
