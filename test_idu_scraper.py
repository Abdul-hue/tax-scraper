import os
import time
import requests
from dotenv import load_dotenv

def run_idu_test():
    print("==========================================")
    print("  IDU / TRACESMART SCRAPER - API TEST")
    print("==========================================")

    # 1. Load config from .env
    load_dotenv()
    
    internal_api_base = os.environ.get("INTERNAL_API_BASE", "http://localhost:8000")
    # Use the corrected path with /api prefix as required by backend routing
    endpoint = f"{internal_api_base}/api/scrapers/idu"

    # 2. Setup Payload (Sample identity data)
    params = {
        "forename": "Michael",
        "surname": "Smith",
        "dd": "01",
        "mm": "01",
        "yyyy": "1980",
        "gender": "Male",
        "street": "Denshaw Drive",
        "town": "Morley",
        "postcode": "LS278RR",
        "reference": "TEST_123"
    }

    print(f"Endpoint  : {endpoint} (GET)")
    print(f"Test Name : {params['forename']} {params['surname']}")
    print(f"Reference : {params['reference']}\n")

    # 3. Execution
    start_time = time.time()
    try:
        # IDU Scraper can take a while as it logs in and performs a full search
        print("Running full identity check (this may take 30-60 seconds)...")
        response = requests.get(endpoint, params=params, timeout=120)
    except Exception as e:
        print("[VERDICT]")
        print(f"❌ Scraper failed — reason: {str(e)}")
        print("==========================================")
        return
        
    execution_time_ms = int((time.time() - start_time) * 1000)
    
    print("[RESULT]")
    print(f"Status Code     : {response.status_code}")
    print(f"Response Time   : {execution_time_ms}ms")
    
    try:
        data = response.json()
        # Debug: show the full JSON
        print(f"RAW JSON        : {data}\n")
        
        print(f"Verdict         : {data.get('verdict', 'UNKNOWN')}")
        print(f"Score           : {data.get('score', 'N/A')}")
        print(f"Screenshot      : {data.get('screenshot_url', 'None')}\n")
        
        checks = data.get("checks", {})
        if checks:
            print("[INDIVIDUAL CHECKS]")
            for label, status in checks.items():
                print(f"- {label:20}: {status}")
            print("")
            
    except ValueError:
        print(f"Raw Response    : {response.text}\n")
        print("[VERDICT]")
        print("❌ Scraper failed — reason: Response is not valid JSON.")
        print("==========================================")
        return
        
    if response.status_code == 200 and data.get("status") != "error":
        print("[VERDICT]")
        print("✅ IDU Scraper successful. Decisions and screenshots captured.")
    else:
        print("[VERDICT]")
        error_msg = data.get("error") or "Non-200 status code received."
        print(f"❌ Scraper failed — reason: {error_msg}")
        
    print("==========================================")

if __name__ == "__main__":
    run_idu_test()
