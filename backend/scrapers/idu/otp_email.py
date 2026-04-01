"""
otp_email.py
============
Automatically retrieve the Tracesmart One-Time Password from an email inbox
using IMAP.  No human interaction required.

Required environment variables (in backend/.env):
    OTP_EMAIL_HOST     e.g. imap.gmail.com  or  imap.mail.yahoo.com
    OTP_EMAIL_PORT     e.g. 993  (SSL) or 143 (STARTTLS)
    OTP_EMAIL_USER     full email address used to receive the OTP
    OTP_EMAIL_PASS     email password (or app-password for Gmail/Outlook)
    OTP_EMAIL_USE_SSL  true | false  (default true)

Gmail note:
    Use an App Password (Google Account → Security → App passwords) instead of
    your normal password.  2-Step Verification must be enabled.

Outlook / Hotmail note:
    Host: imap-mail.outlook.com, Port: 993
    Also generate an app password if 2FA is enabled.
"""

from __future__ import annotations

import imaplib
import email
import re
import time
import os
import logging
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)

# Senders Tracesmart uses to deliver OTPs (case-insensitive substring match)
# Includes lexisnexisrisk because Tracesmart is owned by LexisNexis,
# and your forwarding email address in case the 'From' gets replaced by Outlook.
_TRACESMART_SENDERS = [
    "tracesmart",
    "noreply@tracesmart",
    "no-reply@tracesmart",
    "lexisnexisrisk.com",
    "noreply@lexisnexisrisk.com",
    "abdul.wasay@theinsolvencygroup.co.uk"
]


# Regex patterns that match 4–8 digit OTP codes inside email bodies
_OTP_PATTERNS = [
    r"(?:one[- ]?time[- ]?(?:password|code|passcode)[^\d]{0,30})(\d{4,8})",
    r"(?:verification[- ]?code[^\d]{0,30})(\d{4,8})",
    r"(?:your[^\d]{0,20}code[^\d]{0,20}is[^\d]{0,10})(\d{4,8})",
    r"\b(\d{6})\b",   # fallback: any standalone 6-digit number
]


def _decode_part(part) -> str:
    """Decode a single email message part to a string."""
    charset = part.get_content_charset() or "utf-8"
    raw = part.get_payload(decode=True)
    if raw is None:
        return ""
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _extract_otp_from_text(text: str) -> Optional[str]:
    """Run all regex patterns against the text and return the first match."""
    for pattern in _OTP_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1)
    return None


def _get_email_body(msg) -> str:
    """Walk the MIME tree and return all text content concatenated."""
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                body_parts.append(_decode_part(part))
    else:
        body_parts.append(_decode_part(msg))
    return "\n".join(body_parts)


def _is_tracesmart_sender(msg) -> bool:
    from_header = msg.get("From", "").lower()
    return any(s in from_header for s in _TRACESMART_SENDERS)


def fetch_otp_from_email(
    *,
    poll_interval: float = 5.0,
    timeout: float = 120.0,
    since_timestamp: float = None,
) -> Optional[str]:
    """Poll the configured IMAP inbox and return the OTP code when found.

    Parameters
    ----------
    poll_interval:
        Seconds between inbox checks.
    timeout:
        Maximum seconds to wait before giving up (returns None).
    since_timestamp:
        Unix timestamp; only emails received *after* this time are considered.
        Defaults to ``time.time()`` at the moment this function is called, so
        old OTP emails are never re-used.

    Returns
    -------
    str | None
        The numeric OTP code, or None if not found within the timeout.
    """
    # ------------------------------------------------------------------ config
    host = os.getenv("OTP_EMAIL_HOST", "")
    port = int(os.getenv("OTP_EMAIL_PORT", "993"))
    user = os.getenv("OTP_EMAIL_USER", "")
    password = os.getenv("OTP_EMAIL_PASS", "")
    use_ssl = os.getenv("OTP_EMAIL_USE_SSL", "true").lower() != "false"

    if not host or not user or not password:
        logger.error(
            "OTP email not configured. Set OTP_EMAIL_HOST, OTP_EMAIL_USER, "
            "OTP_EMAIL_PASS in backend/.env"
        )
        return None

    if since_timestamp is None:
        since_timestamp = time.time()

    # IMAP date string for SINCE filter (day-level granularity is fine — we
    # check the actual received time below for precision).
    import datetime
    since_date_str = datetime.datetime.fromtimestamp(since_timestamp).strftime("%d-%b-%Y")

    logger.info(
        "Polling %s for Tracesmart OTP email (timeout=%ds)...", host, int(timeout)
    )

    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            # Open a fresh connection each poll so we always see new mail
            if use_ssl:
                imap = imaplib.IMAP4_SSL(host, port)
            else:
                imap = imaplib.IMAP4(host, port)
                imap.starttls()

            # Google App passwords copy-pasted often include spaces, which break IMAP auth
            clean_password = password.replace(" ", "")
            imap.login(user, clean_password)
            imap.select("INBOX")

            # Search for recent messages from Tracesmart
            status, data = imap.search(
                None, f'(SINCE "{since_date_str}" UNSEEN)'
            )
            if status != "OK":
                imap.logout()
                time.sleep(poll_interval)
                continue

            msg_ids = data[0].split()
            logger.debug("IMAP UNSEEN messages since %s: %d", since_date_str, len(msg_ids))

            for msg_id in reversed(msg_ids):  # newest first
                status2, msg_data = imap.fetch(msg_id, "(RFC822)")
                if status2 != "OK":
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                # Check sender
                if not _is_tracesmart_sender(msg):
                    continue

                # Check received time — must be after we triggered the OTP
                date_str = msg.get("Date", "")
                try:
                    from email.utils import parsedate_to_datetime
                    received_dt = parsedate_to_datetime(date_str)
                    received_ts = received_dt.timestamp()
                    if received_ts < since_timestamp - 10:  # 10-sec tolerance
                        logger.debug(
                            "Skipping old Tracesmart email (received %.0f s ago)",
                            time.time() - received_ts,
                        )
                        continue
                except Exception:
                    pass  # if date parsing fails, still try it

                body = _get_email_body(msg)
                otp = _extract_otp_from_text(body)
                if otp:
                    logger.info("OTP found in email: %s", otp)
                    # Mark as read so we don't pick it up again
                    try:
                        imap.store(msg_id, "+FLAGS", "\\Seen")
                    except Exception:
                        pass
                    imap.logout()
                    return otp

            imap.logout()

        except imaplib.IMAP4.error as exc:
            logger.warning("IMAP error: %s — retrying...", exc)
        except Exception as exc:
            logger.warning("Unexpected error reading email: %s — retrying...", exc)

        time.sleep(poll_interval)

    logger.warning("OTP not found in email within %d seconds", int(timeout))
    return None
