from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import json


@dataclass
class ChildOvernightStay:
    name: str
    overnight_stays: str = "never"


@dataclass
class ReceivingParent:
    children: list[ChildOvernightStay] = field(default_factory=list)


@dataclass
class ChildMaintenanceQuery:
    role: str = "paying"
    multiple_receiving_parents: bool = False
    benefits: list[str] = field(default_factory=list)
    income: float = 0.0
    income_frequency: str = "monthly"
    add_parent_names: bool = False
    paying_parent_name: str = "Parent"
    receiving_parent_name: str = "Parent"
    child_name: str = "Child"
    other_children_in_home: int = 0
    receiving_parents: list[ReceivingParent] = field(default_factory=list)


@dataclass
class ChildMaintenanceResult:
    scraped_at: str = ""
    result: str = ""
    reason: str = ""
    screenshot_url: Optional[str] = None
    pdf_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and self.result != ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
