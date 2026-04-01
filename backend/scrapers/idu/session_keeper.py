"""
session_keeper.py
=================
Background daemon that keeps the IDU/Tracesmart session alive indefinitely.

How it works
------------
1. On app startup, call ``start_session_keeper(username, password)``.
2. The daemon wakes up every REFRESH_INTERVAL_SECONDS and invokes
   is_session_valid() against the real site.
3. If the session has expired, it runs a full headless re-login (including
   the OTP step — retrieved automatically from email via otp_email.py).
4. The refreshed session is saved to disk so the main scraper always finds
   a fresh cookie file and never has to log in during an actual search.

The keeper runs in its own daemon thread, so it shuts down cleanly when the
main process exits.  It is safe to call start_session_keeper() multiple times
— only one keeper thread will be active at a time.
"""

from __future__ import annotations

import threading
import logging
import time
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# How often the keeper checks whether the session is still alive (seconds).
# Default: every 4 hours.  Tracesmart sessions typically last ~8 h, so
# refreshing at 4 h gives a comfortable safety margin with no human action.
REFRESH_INTERVAL_SECONDS = int(os.getenv("IDU_SESSION_REFRESH_HOURS", "4")) * 3600

_keeper_thread: threading.Thread | None = None
_keeper_stop = threading.Event()
_keeper_lock  = threading.Lock()


def _do_refresh(username: str, password: str, session_file: str) -> bool:
    """Open a headless browser, validate the saved session, and re-login if
    needed (automatically reading OTP from email).  Returns True on success."""
    from playwright.sync_api import sync_playwright
    from scrapers.idu import session as session_mod
    from scrapers.idu.otp_email import fetch_otp_from_email
    from scrapers.common.browser import get_browser_args
    from app.scrapers.service import _idu_operation_lock

    logger.info("[SessionKeeper] Starting refresh check...")

    with _idu_operation_lock:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=get_browser_args(),
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    " AppleWebKit/537.36 (KHTML, like Gecko)"
                    " Chrome/114.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            try:
                # Step 1 — Load saved session
                loaded = session_mod.load_session(context, session_file)
                if loaded and session_mod.is_session_valid(page):
                    logger.info("[SessionKeeper] Session still valid — no refresh needed.")
                    return True

                logger.info("[SessionKeeper] Session expired or missing — re-logging in...")
                session_mod.delete_session(session_file)

                # Step 2 — Navigate to login page
                page.goto("https://sso.tracesmart.co.uk/login/idu", timeout=30000)
                page.wait_for_selector("#username", timeout=20000)
                page.fill("#username", username)
                page.fill("#password", password)
                page.click('input[data-testid="sign-in"]')

                # Step 3 — Send OTP button
                try:
                    otp_send_btn = page.locator('[data-testid="otp-send"]')
                    if otp_send_btn.is_visible(timeout=4000):
                        otp_trigger_time = time.time()
                        logger.info("[SessionKeeper] Clicking 'Send OTP' button...")
                        otp_send_btn.click()
                        page.wait_for_load_state("networkidle", timeout=15000)
                    else:
                        otp_trigger_time = time.time()
                except Exception:
                    otp_trigger_time = time.time()

                # Step 4 — Auto-read OTP from email
                otp_needed = False
                try:
                    page.wait_for_selector('[data-testid="otp-code"]', timeout=10000)
                    otp_needed = True
                except Exception:
                    pass

                if otp_needed:
                    logger.info("[SessionKeeper] OTP field detected — fetching from email...")
                    otp = fetch_otp_from_email(
                        poll_interval=5.0,
                        timeout=120.0,
                        since_timestamp=otp_trigger_time,
                    )
                    if not otp:
                        logger.error("[SessionKeeper] OTP not received from email — refresh failed.")
                        return False

                    logger.info("[SessionKeeper] Injecting OTP: %s", otp)
                    page.fill('[data-testid="otp-code"]', otp)
                    page.click('[data-testid="otp-submit"]')
                    page.wait_for_load_state("networkidle", timeout=30000)

                # Step 5 — Handle concurrent-session conflict page
                try:
                    page.wait_for_selector('[data-testid="accept"]', timeout=8000)
                    logger.info("[SessionKeeper] Conflict page — accepting...")
                    page.click('[data-testid="accept"]')
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                # Step 6 — Verify dashboard
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                    indicator = page.locator("#hd-logout-button, .newSearch").or_(
                        page.get_by_text("You are logged in")
                    ).first
                    indicator.wait_for(state="visible", timeout=15000)
                    logger.info("[SessionKeeper] Dashboard confirmed at %s", page.url)
                except Exception as e:
                    logger.error(
                        "[SessionKeeper] Dashboard not found after login. URL: %s — %s",
                        page.url, e,
                    )
                    return False

                # Step 7 — Save fresh session
                session_mod.save_session(context, session_file)
                logger.info("[SessionKeeper] Session refreshed and saved successfully.")
                return True

            except Exception as exc:
                logger.exception("[SessionKeeper] Unexpected error during refresh: %s", exc)
                return False
            finally:
                try:
                    page.close()
                    context.close()
                    browser.close()
                except Exception:
                    pass


def _keeper_loop(username: str, password: str, session_file: str) -> None:
    """The main loop for the background keeper thread."""
    # Do an immediate refresh on startup so the session is always fresh
    _do_refresh(username, password, session_file)

    while not _keeper_stop.wait(timeout=REFRESH_INTERVAL_SECONDS):
        if _keeper_stop.is_set():
            break
        logger.info(
            "[SessionKeeper] Scheduled refresh (every %.0f h)...",
            REFRESH_INTERVAL_SECONDS / 3600,
        )
        _do_refresh(username, password, session_file)

    logger.info("[SessionKeeper] Stopped.")


def start_session_keeper(
    username: str,
    password: str,
    session_file: str = None,
) -> None:
    """Start the background session-keeper thread (idempotent).

    Call this once when your application boots.  The keeper will
    silently maintain the IDU session forever without any human input.

    Parameters
    ----------
    username, password:
        IDU / Tracesmart credentials (also read from env as fallback).
    session_file:
        Path to the JSON session file.  Defaults to the standard path
        inside ``output/sessions/``.
    """
    global _keeper_thread, _keeper_stop

    if not session_file:
        session_file = str(
            Path(__file__).parent.parent.parent
            / "output" / "sessions" / "idu_session.json"
        )

    # Load env fallbacks
    from dotenv import load_dotenv
    load_dotenv()
    username = username or os.getenv("IDU_USERNAME", "")
    password = password or os.getenv("IDU_PASSWORD", "")

    if not username or not password:
        logger.error(
            "[SessionKeeper] IDU_USERNAME / IDU_PASSWORD not set — keeper not started."
        )
        return

    with _keeper_lock:
        if _keeper_thread is not None and _keeper_thread.is_alive():
            logger.info("[SessionKeeper] Already running — not starting a second instance.")
            return

        _keeper_stop.clear()
        _keeper_thread = threading.Thread(
            target=_keeper_loop,
            args=(username, password, session_file),
            daemon=True,
            name="IDUSessionKeeper",
        )
        _keeper_thread.start()
        logger.info(
            "[SessionKeeper] Started. Refresh interval: every %.0f hours.",
            REFRESH_INTERVAL_SECONDS / 3600,
        )


def stop_session_keeper() -> None:
    """Signal the keeper thread to exit gracefully."""
    global _keeper_stop
    _keeper_stop.set()
    logger.info("[SessionKeeper] Stop signal sent.")
