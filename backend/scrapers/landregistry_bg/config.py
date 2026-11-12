"""Settings for HM Land Registry Business Gateway (SOAP web services).

Everything is read from environment variables (see backend/.env.example).
Docs: https://landregistry.github.io/bgtechdoc/
"""
import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Base URLs per environment. Service names (e.g. EnquiryByPropertyDescriptionV2_0WebService)
# are appended to these.
BASE_URLS = {
    # bgtest stub: returns canned responses, no real data, no charges.
    "test": "https://bgtest.landregistry.gov.uk/b2b/ECBG_StubService",
    # Live: taken from the developer guide's "All Other Services" entry. Confirm against
    # the live WSDL once the live certificate is issued; override with LR_BG_BASE_URL if needed.
    "live": "https://businessgateway.landregistry.gov.uk/b2b/BGSoapEngine",
}

# Published bgtest vendor test credentials. The stub only accepts these, so real portal
# credentials are never sent to the test environment.
# https://landregistry.github.io/bgtechdoc/documents/search_property_desc/SearchByPropertyDescriptionVendorTest.html
TEST_USERNAME = "BGUser001"
TEST_PASSWORD = "landreg001"


@dataclass(frozen=True)
class BGConfig:
    env: str
    base_url: str
    username: str
    password: str
    cert_file: str
    key_file: str
    ca_file: str
    contact_name: str = ""
    contact_phone: str = ""
    # ExpectedPrice sent with official copy orders (GBP). With continue_if_fee_exceeds=True
    # HMLR still processes the order if the real fee is higher.
    price_single: float = 7.0
    price_both: float = 14.0
    continue_if_fee_exceeds: bool = True
    timeout: int = 60
    locale: str = "en"


def load_config() -> BGConfig:
    env = os.getenv("LR_BG_ENV", "test").strip().lower()
    if env not in BASE_URLS:
        raise ValueError(f"LR_BG_ENV must be 'test' or 'live', got {env!r}")

    cert_dir = Path(os.getenv("LR_BG_CERT_DIR") or BACKEND_DIR / "certs")

    if env == "test":
        username = os.getenv("LR_BG_USERNAME") or TEST_USERNAME
        password = os.getenv("LR_BG_PASSWORD") or TEST_PASSWORD
    else:
        # Business Gateway uses the same user ID / password as the HMLR portal.
        username = os.getenv("LR_BG_USERNAME") or os.getenv("LAND_REGISTRY_USERNAME", "")
        password = os.getenv("LR_BG_PASSWORD") or os.getenv("LAND_REGISTRY_PASSWORD", "")
        if not username or not password:
            raise ValueError("Live Business Gateway needs LR_BG_USERNAME/LR_BG_PASSWORD "
                             "(or LAND_REGISTRY_USERNAME/PASSWORD) in .env")

    cfg = BGConfig(
        env=env,
        base_url=(os.getenv("LR_BG_BASE_URL") or BASE_URLS[env]).rstrip("/"),
        username=username,
        password=password,
        cert_file=str(cert_dir / os.getenv("LR_BG_CERT_FILE", "client.crt.pem")),
        key_file=str(cert_dir / os.getenv("LR_BG_KEY_FILE", "client.key.pem")),
        ca_file=str(cert_dir / os.getenv("LR_BG_CA_FILE", "lr_ca_bundle.pem")),
        # Contact is mandatory on official copy orders (who HMLR calls about the order).
        contact_name=os.getenv("LR_BG_CONTACT_NAME") or "The Insolvency Group",
        contact_phone=os.getenv("LR_BG_CONTACT_PHONE") or ("01234567" if env == "test" else ""),
        price_single=float(os.getenv("LR_BG_EXPECTED_PRICE_SINGLE", "7")),
        price_both=float(os.getenv("LR_BG_EXPECTED_PRICE_BOTH", "14")),
        continue_if_fee_exceeds=os.getenv("LR_BG_CONTINUE_IF_FEE_EXCEEDS", "true").lower() == "true",
        timeout=int(os.getenv("LR_BG_TIMEOUT", "60")),
    )
    if not cfg.contact_phone:
        raise ValueError("Set LR_BG_CONTACT_PHONE in .env (required for official copy orders)")
    for f in (cfg.cert_file, cfg.key_file, cfg.ca_file):
        if not Path(f).is_file():
            raise FileNotFoundError(f"Business Gateway certificate file missing: {f}")
    return cfg
