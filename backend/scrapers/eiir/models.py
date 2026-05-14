from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import json


@dataclass
class EiirQuery:
    """Input for a single Individual Insolvency Register lookup."""
    forename: str = ""
    surname: str = ""
    follow_details: bool = True  # If True, click into each result and parse the detail page


@dataclass
class EiirRecord:
    """One row returned from the EIIR search results, optionally enriched with detail-page fields."""
    name: str = ""
    insolvency_type: str = ""
    court: str = ""
    case_number: str = ""
    date_of_order: str = ""
    status: str = ""
    detail_url: str = ""
    # Detail-page extras (populated when follow_details=True)
    date_of_birth: str = ""
    last_known_address: str = ""
    insolvency_practitioner: str = ""
    detail_fields: dict = field(default_factory=dict)  # catch-all for any other dt/dd pairs


@dataclass
class EiirResult:
    """
    Full result for one EIIR search.
    Always returned — check .success before consuming .records.
    Backend-ready: call .to_dict() or .to_json().
    """
    search_term: str = ""
    forename: str = ""
    surname: str = ""
    scraped_at: str = ""
    records: list[EiirRecord] = field(default_factory=list)
    screenshot_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and len(self.records) > 0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
