from __future__ import annotations

from pathlib import Path
import json
import logging
import time
from typing import Union

logger = logging.getLogger(__name__)


def save_session(context, path: Union[str, Path]) -> None:
    """Serialize the full browser storage state (cookies + localStorage) to a
    JSON file.  This is more reliable than saving cookies alone because it
    preserves auth tokens that live in localStorage / sessionStorage.
    """
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        state = context.storage_state()     # returns dict with cookies + origins
        state["_saved_at"] = time.time()    # timestamp for diagnostic logging only
        with p.open("w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        logger.info("Saved storage state to %s (%.0f cookies)", p, len(state.get("cookies", [])))
    except (FileNotFoundError, PermissionError) as exc:
        logger.warning("Could not save session file %s: %s", p, exc)
    except Exception:
        logger.exception("Unexpected error saving session to %s", p)


def load_session(context, path: Union[str, Path]) -> bool:
    """Load storage state from JSON file into the browser context.

    Returns True if the file was loaded successfully.
    Returns False if the file is missing or corrupt.

    NOTE: There is intentionally NO age/time limit here.  The only thing that
    determines whether a session is still valid is is_session_valid(), which
    actually navigates to the site.  This lets the background session keeper
    proactively refresh, meaning the AI agent never hits an expired session.
    """
    p = Path(path)
    try:
        if not p.exists():
            logger.info("No session file found at %s", p)
            return False

        with p.open("r", encoding="utf-8") as fh:
            state = json.load(fh)

        # Handle backward compatibility: if the file was saved by the old
        # cookies-only system, state will be a list, not a dict.
        if isinstance(state, list):
            logger.info("Found old-format session file (list). Deleting and forcing re-login.")
            try:
                p.unlink()
            except Exception:
                pass
            return False

        # Log age for diagnostics (no enforcement)
        saved_at = state.pop("_saved_at", None)
        if saved_at is not None:
            age_h = (time.time() - saved_at) / 3600
            logger.info("Session file is %.1f hours old — validating against site", age_h)

        # ------------------------------------------------------------------
        # Apply state to the context.  storage_state files produced by
        # context.storage_state() have "cookies" and "origins" keys.
        # ------------------------------------------------------------------
        cookies = state.get("cookies", [])
        if cookies:
            context.add_cookies(cookies)

        # Restore localStorage / sessionStorage via a JS snippet on a blank
        # page for each origin present in the state.
        origins = state.get("origins", [])
        if origins:
            page = context.new_page()
            try:
                for entry in origins:
                    origin = entry.get("origin", "")
                    local_storage = entry.get("localStorage", [])
                    if origin and local_storage:
                        try:
                            page.goto(origin, timeout=15000, wait_until="domcontentloaded")
                            for item in local_storage:
                                key = item.get("name", "")
                                value = item.get("value", "")
                                if key:
                                    page.evaluate(
                                        f"localStorage.setItem({json.dumps(key)}, {json.dumps(value)})"
                                    )
                        except Exception as e:
                            logger.debug("Could not restore localStorage for %s: %s", origin, e)
            finally:
                page.close()

        logger.info("Loaded session state from %s (%d cookies)", p, len(cookies))
        return True

    except (FileNotFoundError, PermissionError) as exc:
        logger.warning("Could not read session file %s: %s", p, exc)
        return False
    except Exception:
        logger.exception("Failed to load session from %s", p)
        return False


def is_session_valid(page, timeout_ms: int = 30000) -> bool:
    """Navigate to the IDU dashboard and check whether we are already logged in.

    Returns True  → session is live, scraper can proceed.
    Returns False → session has expired, a fresh login is required.
    """
    try:
        page.goto("https://idu.tracesmart.co.uk/", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            logger.debug("Network did not go idle during session validation, continuing...")

        # Primary indicators that we are on the IDU dashboard
        try:
            page.wait_for_selector("#hd-logout-button, .newSearch", timeout=10000)
            logger.info("Session is valid — dashboard detected")
            return True
        except Exception:
            pass

        # Fallback: text search in page content
        html = page.content()
        if "You are logged in" in html or "hd-logout-button" in html:
            logger.info("Session is valid — found login indicator in HTML")
            return True

        # If we ended up on the SSO login page the session has expired
        if "sso.tracesmart.co.uk" in page.url or "login" in page.url.lower():
            logger.info("Session expired — redirected to login page")
            return False

        logger.info("Session status unclear — treating as invalid")
        return False

    except Exception as e:
        logger.warning("Session validation failed: %s", e)
        return False


def delete_session(path: Union[str, Path]) -> None:
    """Remove a saved session file so the next run triggers a fresh login."""
    p = Path(path)
    try:
        if p.exists():
            p.unlink()
            logger.info("Deleted session file %s", p)
    except Exception as exc:
        logger.warning("Could not delete session file %s: %s", p, exc)
