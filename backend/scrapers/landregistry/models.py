from dataclasses import dataclass, field
from typing import Optional, Dict
import json


@dataclass
class LandRegistryQuery:
    username: str
    password: str
    customer_reference: str
    title_number: str = ""
    flat: str = ""
    house: str = ""
    street: str = ""
    town: str = ""
    postcode: str = ""
    order_register: bool = True
    order_title_plan: bool = True


@dataclass
class LandRegistryResult:
    scraped_at: str = ""
    title_number: str = ""
    address: str = ""
    tenure: str = ""
    administered_by: str = ""
    customer_reference: str = ""
    register_url: str = ""
    title_plan_url: str = ""
    register_local_path: str = ""
    title_plan_local_path: str = ""
    register_data: Dict = field(default_factory=dict)
    title_plan_data: Dict = field(default_factory=dict)
    screenshot_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return not self.error and (self.register_url or self.title_plan_url)

    def to_dict(self) -> dict:
        return {
            "scraped_at": self.scraped_at,
            "title_number": self.title_number,
            "address": self.address,
            "tenure": self.tenure,
            "administered_by": self.administered_by,
            "customer_reference": self.customer_reference,
            "register_url": self.register_url,
            "title_plan_url": self.title_plan_url,
            "register_local_path": self.register_local_path,
            "title_plan_local_path": self.title_plan_local_path,
            "register_data": self.register_data,
            "title_plan_data": self.title_plan_data,
            "screenshot_url": self.screenshot_url,
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

