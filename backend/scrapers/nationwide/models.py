from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import json

@dataclass
class NationwideQuery:
    """Input for a Nationwide HPI lookup."""
    region: str = "Greater London"
    postcode: str = ""
    property_value: int = 0
    from_year: int = 0
    from_quarter: int = 1
    to_year: int = 0
    to_quarter: int = 1

@dataclass
class NationwideResult:
    """
    Full result for one Nationwide HPI scrape.
    Always returned — check .success before consuming fields.
    Backend-ready: call .to_dict() or .to_json().
    """
    scraped_at:        str = ""
    from_label:        str = ""
    from_value:        str = ""
    to_label:          str = ""
    to_value:          str = ""
    percentage_change: str = ""
    description:       str = ""
    screenshot_path:   Optional[str] = None
    screenshot_url:    Optional[str] = None
    error:             Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and self.percentage_change != ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
