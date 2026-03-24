from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal, Dict
import json

InputMethod = Literal["registration", "dropdown"]

@dataclass
class ParkersConfig:
    """
    Input config for one Parkers valuation.
    Use EITHER reg_plate OR all of make/range/model/year — not both.
    """
    # Browser settings
    headless:    bool = True   # Run browser in headless mode

    # Path A — registration plate
    reg_plate:   str = ""   # e.g. "AB12CDE" — spaces stripped automatically

    # Path B — dropdown selection
    make:        str = ""   # e.g. "Ford"
    range_name:  str = ""   # e.g. "Focus"  (named range_name to avoid 'range' builtin)
    model:       str = ""   # e.g. "1.0 EcoBoost 125 ST-Line"
    year:        str = ""   # e.g. "2019"

    # Optional reference for batch tracking
    reference:   str = ""

    @property
    def input_method(self) -> InputMethod:
        return "registration" if self.reg_plate else "dropdown"

    def validate(self) -> None:
        """Raise ValueError if neither reg nor full dropdown set is provided."""
        if not self.reg_plate and not all([self.make, self.range_name, self.model, self.year]):
            raise ValueError(
                "Provide either reg_plate OR all of make/range_name/model/year"
            )

@dataclass
class ValuationPrices:
    """Price range from free Parkers valuation."""
    private_low:      Optional[str] = None
    private_high:     Optional[str] = None
    dealer_low:       Optional[str] = None
    dealer_high:      Optional[str] = None
    part_exchange:    Optional[str] = None

@dataclass
class ParkersResult:
    """
    Full result for one Parkers valuation.
    Always returned — check .success before consuming .prices.
    Backend-ready: call .to_dict() or .to_json().
    """
    plate:           str    = ""
    config:          dict   = field(default_factory=dict)
    scraped_at:      str    = ""
    reg_plate:       str    = ""
    make:            str    = ""
    model:           str    = ""
    year:            str    = ""
    vehicle_version: str    = ""
    vehicle_full_name: str  = ""
    vehicle_image:   str    = ""
    vehicle_details: Dict[str, str] = field(default_factory=dict)
    prices:          ValuationPrices = field(default_factory=ValuationPrices)
    screenshot_url:  Optional[str] = None
    error:           Optional[str] = None
    message:         Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
