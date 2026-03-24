from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import json

@dataclass
class CouncilTaxQuery:
    """Input for a single council tax lookup."""
    postcode: str   # e.g. "LS27 8RR" — normalised to uppercase, stripped

@dataclass
class PropertyRecord:
    """One property returned from the council tax search."""
    address:        str
    band:           str   # "A" through "H", or "" if not found
    annual_amount:  str   # e.g. "£1,842" or "" if not found
    monthly_amount: float = 0.0
    local_authority: str = ""  # e.g. "Leeds City Council" or ""
    postcode:       str = ""  # e.g. "LS27 8RR"

@dataclass
class CouncilTaxResult:
    """
    Full result for one postcode lookup.
    Always returned — check .success before consuming .properties.
    Backend-ready: call .to_dict() or .to_json().
    """
    postcode:    str
    scraped_at:  str
    properties:  list[PropertyRecord] = field(default_factory=list)
    screenshot_url: Optional[str]     = None
    error:       Optional[str]        = None

    @property
    def success(self) -> bool:
        return self.error is None and len(self.properties) > 0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
