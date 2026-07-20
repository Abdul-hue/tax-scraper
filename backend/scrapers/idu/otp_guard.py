"""
otp_guard.py
============
Cross-process safety net around the IDU/Tracesmart login + OTP-send flow.

Why this exists
----------------
In production the app runs behind ``uvicorn --workers 2`` (see
supervisord.conf).  That means there are TWO separate OS processes serving
requests.  The old ``_idu_operation_lock = threading.Lock()`` in
app/scrapers/service.py only ever protected threads *within one process* —
it did nothing to stop the other worker from independently deciding the
session was missing/expired and starting its own full login at the same
time.  Two (or more) concurrent logins each click "Send One Time Password",
so Tracesmart fires off 2+ OTP emails for the same account in quick
succession — which is exactly the behaviour that trips their account lock
after a handful of sends.

On top of that, ``IDUScraper.search()`` retries its whole body (including
``_ensure_logged_in()``) up to ``retry_limit`` times on ANY exception. If the
full login flow throws *after* the OTP was submitted but *before*
``save_session()`` runs (e.g. a slow dashboard-detection timeout), the retry
re-enters the login flow from scratch and clicks "Send OTP" again — a second
resend for the very same logical request.

This module fixes both problems with two small, file-backed primitives that
work across processes (unlike an in-memory threading.Lock):

1. ``idu_login_lock()`` — a real cross-process mutex (via ``filelock``)
   guarding the entire login critical section. Only one process, across
   however many uvicorn workers exist, can be mid-login at any moment.
2. ``otp_send_allowed()`` / ``mark_otp_sent()`` — a persisted cooldown so
   that even serialized, sequential login attempts won't click "Send OTP"
   again within IDU_OTP_MIN_INTERVAL_SECONDS of the previous send. Any
   attempt that arrives inside the cooldown window is expected to just wait
   for the OTP email that is already in flight instead of asking Tracesmart
   to send another one.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from filelock import FileLock

logger = logging.getLogger(__name__)

_SESSIONS_DIR = Path(__file__).parent.parent.parent / "output" / "sessions"
_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

_LOGIN_LOCK_PATH = _SESSIONS_DIR / "idu_login.lock"
_OTP_STATE_PATH = _SESSIONS_DIR / "idu_otp_state.json"

# Minimum seconds between two "Send One Time Password" clicks for the same
# account. Tracesmart's OTP page itself has a resend cooldown, and repeated
# sends within it are what causes Tracesmart to lock the account — this must
# stay comfortably above that page's own cooldown. Configurable via env.
OTP_MIN_INTERVAL_SECONDS = int(os.getenv("IDU_OTP_MIN_INTERVAL_SECONDS", "90"))

# How long a process may hold the login lock before we assume something is
# stuck and let a waiter proceed anyway (avoids indefinite deadlock if a
# process dies mid-login without releasing cleanly).
_LOGIN_LOCK_TIMEOUT_SECONDS = int(os.getenv("IDU_LOGIN_LOCK_TIMEOUT_SECONDS", "180"))


def idu_login_lock() -> FileLock:
    """Cross-process mutex for the IDU login critical section.

    Usage::

        with idu_login_lock():
            ... full login / OTP flow ...

    Backed by a lock *file*, so it serializes correctly across separate
    uvicorn worker processes (and separate containers sharing the same
    output volume), which an in-memory ``threading.Lock`` cannot do.
    """
    return FileLock(str(_LOGIN_LOCK_PATH), timeout=_LOGIN_LOCK_TIMEOUT_SECONDS)


def _read_state() -> dict:
    try:
        if _OTP_STATE_PATH.exists():
            return json.loads(_OTP_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Could not read OTP state file, treating as empty", exc_info=True)
    return {}


def _write_state(state: dict) -> None:
    try:
        _OTP_STATE_PATH.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        logger.warning("Could not persist OTP state file", exc_info=True)


def otp_send_allowed() -> bool:
    """True if enough time has passed since the last OTP send to allow another.

    Callers MUST hold :func:`idu_login_lock` while calling this and while
    acting on the result, otherwise two processes could both read "allowed"
    before either marks a send.
    """
    last_sent = _read_state().get("last_otp_sent_at", 0)
    elapsed = time.time() - last_sent
    allowed = elapsed >= OTP_MIN_INTERVAL_SECONDS
    if not allowed:
        logger.warning(
            "[OTPGuard] Skipping 'Send OTP' click — only %.0fs since the last "
            "send (cooldown %ds). Will wait for the in-flight OTP email instead "
            "of asking Tracesmart to resend.",
            elapsed, OTP_MIN_INTERVAL_SECONDS,
        )
    return allowed


def mark_otp_sent() -> None:
    """Record that an OTP was just requested, starting the cooldown window."""
    state = _read_state()
    state["last_otp_sent_at"] = time.time()
    _write_state(state)


def seconds_since_last_otp() -> float:
    """How long ago (seconds) the last OTP send happened. Large if never sent."""
    last_sent = _read_state().get("last_otp_sent_at", 0)
    if not last_sent:
        return float("inf")
    return time.time() - last_sent
