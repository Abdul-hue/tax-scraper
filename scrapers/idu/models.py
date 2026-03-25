from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class IDUConfig:
    """Input configuration for a single IDU search."""
    forename: str
    middlename: str = ""
    surname: str | None = None
    dd: str = ""
    mm: str = ""
    yyyy: str = ""
    gender: str = ""
    house: str = ""
    street: str = ""
    town: str = ""
    postcode: str = ""
    reference: str = ""
    email: str = ""
    email2: str = ""
    mobile: str = ""
    mobile2: str = ""
    landline: str = ""
    landline2: str = ""


@dataclass
class SummaryItem:
    """One item in the summary table."""
    category: str
    label: str
    status: str


@dataclass
class PEPEntry:
    """Representation of a single PEP/sanctions match."""
    match_score: str = ""
    name: str = ""
    aliases: List[str] = field(default_factory=list)
    last_updated: str = ""
    addresses: List[str] = field(default_factory=list)
    country: str = ""
    position: str = ""
    reason: str = ""


@dataclass
class IDUResult:
    """Complete result for one search."""
    config: Dict
    scraped_at: str
    search_id: str = ""
    verdict: str = ""
    score: str = ""
    date_of_search: str = ""
    summary_items: List[SummaryItem] = field(default_factory=list)
    address_detail: Dict = field(default_factory=dict)
    credit_active: Dict = field(default_factory=dict)
    dob_verification: Dict = field(default_factory=dict)
    mortality: Dict = field(default_factory=dict)
    gone_away: Dict = field(default_factory=dict)
    pep_entries: List[PEPEntry] = field(default_factory=list)
    sanction_result: str = ""
    ccj: Dict = field(default_factory=dict)
    insolvency: Dict = field(default_factory=dict)
    company_director: Dict = field(default_factory=dict)
    search_activity: Dict = field(default_factory=dict)
    address_links: List[Dict] = field(default_factory=list)
    property_detail: Dict = field(default_factory=dict)
    screenshot_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return not self.error and bool(self.verdict)

    def to_dict(self) -> dict:
        return {
            "scraped_at": self.scraped_at,
            "search_id": self.search_id,
            "verdict": self.verdict,
            "score": self.score,
            "date_of_search": self.date_of_search,
            "summary_items": [
                {"category": item.category, "label": item.label, "status": item.status} 
                for item in self.summary_items
            ],
            "address_detail": self.address_detail,
            "credit_active": self.credit_active,
            "dob_verification": self.dob_verification,
            "mortality": self.mortality,
            "gone_away": self.gone_away,
            "pep_entries": [asdict(pep) for pep in self.pep_entries],
            "sanction_result": self.sanction_result,
            "ccj": self.ccj,
            "insolvency": self.insolvency,
            "company_director": self.company_director,
            "search_activity": self.search_activity,
            "address_links": self.address_links,
            "property_detail": self.property_detail,
            "screenshot_url": self.screenshot_url,
            "error": self.error,
        }

    def to_json(self, indent: int = 2) -> str:
        """Return pretty JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
