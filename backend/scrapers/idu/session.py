from __future__ import annotations

from pathlib import Path
import json
import logging
from typing import Union

logger = logging.getLogger(__name__)


def save_session(context, path: Union[str, Path]) -> None:
    """Serialize context.cookies() to JSON file. Create parent dirs."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        cookies = context.cookies()
        with p.open("w", encoding="utf-8") as fh:
            json.dump(cookies, fh, ensure_ascii=False, indent=2)
        logger.info("Saved session cookies to %s", p)
    except (FileNotFoundError, PermissionError) as exc:
        logger.warning("Could not save session file %s: %s", p, exc)
    except Exception:
        logger.exception("Unexpected error saving session to %s", p)


def load_session(context, path: Union[str, Path]) -> bool:
    """Load cookies from JSON file into context. Returns True if loaded."""
    p = Path(path)
    try:
        if not p.exists():
            return False
        with p.open("r", encoding="utf-8") as fh:
            cookies = json.load(fh)
        # Playwright expects list of cookie dicts
        context.add_cookies(cookies)
        logger.info("Loaded %d cookies from %s", len(cookies), p)
        return True
    except (FileNotFoundError, PermissionError) as exc:
        logger.warning("Could not read session file %s: %s", p, exc)
        return False
    except Exception:
        logger.exception("Failed to load session from %s", p)
        return False


def is_session_valid(page, timeout_ms: int = 8000) -> bool:
    """Check if we are already logged in by looking for logout or message.

    Returns True if logged in, False if redirected to SSO login page.
    """
    try:
        page.goto("https://idu.tracesmart.co.uk/", timeout=timeout_ms)
        try:
            page.wait_for_selector("#hd-logout-button", timeout=timeout_ms)
            return True
        except Exception:
            # fallback: look for textual indicator
            html = page.content()
            if "You are logged in" in html:
                return True
            return False
    except Exception:
        logger.exception("Error while validating session")
        return False
