from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class LpsQuery:
    search_type: str = "postcode"  # "postcode" or "advanced"
    # Postcode search fields
    postcode: str = ""
    property_number: str = ""
    # Advanced search fields
    adv_property_number: str = ""
    street: str = ""
    town: str = ""
    district_council: str = ""  # e.g. "03" for Belfast
    property_id: str = ""
    # Pagination
    max_pages: int = 3

@dataclass
class LpsProperty:
    property_id: str = ""
    full_address: str = ""
    capital_value: str = ""
    total_nav: str = ""

@dataclass
class LpsPropertyDetail:
    property_id: str = ""
    uprn: str = ""
    property_type: str = ""
    full_address: str = ""
    description: str = ""
    nav_non_exempt: str = ""
    nav_exempt: str = ""
    estimated_rate_bill: str = ""
    ot_other: str = ""
    in_industrial: str = ""
    sr_sports: str = ""
    ft_freight: str = ""
    ex_exempt: str = ""
    valuation_summaries: List[dict] = field(default_factory=list)
    error: str = ""

@dataclass
class LpsResult:
    scraped_at: str = ""
    search_type: str = ""
    properties: List[LpsProperty] = field(default_factory=list)
    property_details: List[LpsPropertyDetail] = field(default_factory=list)
    total_found: int = 0
    pages_scraped: int = 0
    screenshot_url: Optional[str] = None
    error: str = ""

    @property
    def success(self):
        return not self.error and len(self.properties) > 0

    def to_dict(self):
        return {
            "scraped_at": self.scraped_at,
            "search_type": self.search_type,
            "total_found": self.total_found,
            "pages_scraped": self.pages_scraped,
            "properties": [
                {
                    "property_id": p.property_id,
                    "full_address": p.full_address,
                    "capital_value": p.capital_value,
                    "total_nav": p.total_nav,
                }
                for p in self.properties
            ],
            "property_details": [
                {
                    "property_id": d.property_id,
                    "uprn": d.uprn,
                    "property_type": d.property_type,
                    "full_address": d.full_address,
                    "description": d.description,
                    "nav_non_exempt": d.nav_non_exempt,
                    "nav_exempt": d.nav_exempt,
                    "estimated_rate_bill": d.estimated_rate_bill,
                    "ot_other": d.ot_other,
                    "in_industrial": d.in_industrial,
                    "sr_sports": d.sr_sports,
                    "ft_freight": d.ft_freight,
                    "ex_exempt": d.ex_exempt,
                    "valuation_summaries": d.valuation_summaries,
                    "error": d.error,
                }
                for d in self.property_details
            ],
            "screenshot_url": self.screenshot_url,
            "error": self.error,
            "success": self.success,
        }

