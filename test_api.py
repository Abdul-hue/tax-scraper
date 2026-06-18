
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# Test with pension_type='%'
params = {
    'salary': 3000,
    'period': 'month',
    'tax_year': '2025/26',
    'region': 'UK',
    'age': 'under 65',
    'ni_letter': 'A',
    'student_loan': 'No',
    'pension_amount': 5,
    'pension_type': '%',  # This should work now!
    'pension_relief': 'Net',
    'rental_income': 0,
    'allowances': 0,
    'tax_code': '',
    'married': False,
    'blind': False,
    'no_ni': False,
}

print("Testing tax scraper with pension_type='%'...")
response = client.get("/api/scrapers/taxman", params=params)
print(f"Response status code: {response.status_code}")
print(f"Response JSON keys: {list(response.json().keys())}")
if 'payslip' in response.json():
    print(f"Got payslip with {len(response.json()['payslip'])} rows!")
