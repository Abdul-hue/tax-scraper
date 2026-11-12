"""First Business Gateway call: Enquiry by Property Description against bgtest.

Uses vendor test case 1a (building 99, postcode TQ56 4HY -> expect TypeCode 30, single result).
Run from backend/:  python scratch/test_bg_epd.py
"""
import json
import logging
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND))
# Register the `scrapers` package without running scrapers/__init__.py, which pulls in
# Playwright-based scrapers this script doesn't need.
pkg = types.ModuleType("scrapers")
pkg.__path__ = [str(BACKEND / "scrapers")]
sys.modules.setdefault("scrapers", pkg)

from scrapers.landregistry_bg.client import BusinessGatewayClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

client = BusinessGatewayClient()
print(f"env={client.cfg.env} base={client.cfg.base_url} user={client.cfg.username}")
result = client.enquiry_by_property_description(
    customer_reference="TIG-BGTEST-1A",
    building_number="99",
    postcode="TQ56 4HY",
)
print(json.dumps(result, indent=2))
