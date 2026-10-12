"""Delivery of run notifications from the outbox.

Runs as a background task of the worker process, next to run processing and
independent of it. Run processing writes a row into ``notification_outbox`` in
the transaction that ends a run and never looks at it again; this module turns
rows into emails. Nothing here can change a run: a mail server that is down,
slow or refusing only ever changes the outbox row.

One pass (:func:`deliver_due`):
  1. take the rows that are due (PENDING, next_attempt_at reached, not held by
     another sender) and hold them with a lease;
  2. for each, build the email from the run's current data and send it;
  3. record the outcome:
       sent                   -> SENT
       temporary failure      -> PENDING again, later (exponential backoff),
                                 or FAILED once the attempts are used up
       permanent failure      -> FAILED at once (the server refused this
                                 recipient or message; repeating cannot help)
       email switched off     -> SKIPPED (not sent later either: an email about
                                 a run that ended long ago helps nobody)

Settings (environment, read when used):
    RUN_NOTIFICATIONS_ENABLED        true (default) | false: no run emails
    NOTIFICATION_MAX_ATTEMPTS        attempts per email (default 6)
    NOTIFICATION_RETRY_BASE_SECONDS  wait before the 2nd attempt (default 60);
                                     each further wait is four times longer
    NOTIFICATION_RETRY_MAX_SECONDS   longest wait between attempts (default 21600)
    NOTIFICATION_POLL_SECONDS        how often the outbox is checked (default 15)

With the defaults an email is tried at about 0, 1, 5, 21, 85 minutes and 5.7
hours after the run ended, then given up.

Duplicates. The unique (run_id, kind) row means one email is owed per run, and
the lease means one sender works on it at a time. An email can still arrive
twice in exactly one situation: the mail server accepted it and the worker died
before recording that. SMTP offers no way to rule this out; the window is the
few milliseconds between the server's answer and the database commit.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import traceback
from datetime import timedelta
from typing import Any, Optional

from apps.api.auth.verification import may_use_service
from apps.api.config import FRONTEND_URL
from apps.api.contracts.loader import load_spec_from_contracts
from apps.api.database.base import AsyncSessionLocal
from apps.api.database.models import NotificationOutbox, Run, User
from apps.api.repositories.notification_repository import NotificationRepository
from apps.api.repositories.run_repository import NOTIFICATION_RUN_FINISHED
from apps.api.services import email as mailer
from apps.api.services import email_templates as templates
from apps.api.utils.datetime_util import utc_now

logger = logging.getLogger("phylo.api.notifications")

DEFAULT_MAX_ATTEMPTS = 6
DEFAULT_RETRY_BASE_SECONDS = 60.0
DEFAULT_RETRY_MAX_SECONDS = 6 * 3600.0
DEFAULT_POLL_SECONDS = 15.0
RETRY_FACTOR = 4
BATCH_SIZE = 20


def _number(name: str, default: float, minimum: float) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value >= minimum else default


def notifications_enabled() -> bool:
    raw = (os.getenv("RUN_NOTIFICATIONS_ENABLED") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def max_attempts() -> int:
    return int(_number("NOTIFICATION_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS, 1))


def poll_seconds() -> float:
    return _number("NOTIFICATION_POLL_SECONDS", DEFAULT_POLL_SECONDS, 0.05)


def retry_delay_seconds(attempts_made: int) -> float:
    """Wait after the ``attempts_made``-th failed attempt (1-based)."""
    base = _number("NOTIFICATION_RETRY_BASE_SECONDS", DEFAULT_RETRY_BASE_SECONDS, 0.0)
    longest = _number("NOTIFICATION_RETRY_MAX_SECONDS", DEFAULT_RETRY_MAX_SECONDS, 0.0)
    return min(longest, base * (RETRY_FACTOR ** max(0, attempts_made - 1)))


def lease_seconds() -> float:
    """Long enough for one send to finish or time out several times over."""
    try:
        timeout = mailer.smtp_settings().timeout
    except mailer.EmailError:
        timeout = mailer.DEFAULT_TIMEOUT_SECONDS
    return max(60.0, timeout * 6)


def _error_of(run: Run) -> tuple[Optional[str], Optional[str]]:
    """(code, message) of a failed run, as the application shows them."""
    code = None
    try:
        parsed = json.loads(run.error) if run.error else None
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            code = parsed["error"].get("code")
            message = parsed["error"].get("message")
            if isinstance(message, str) and message.strip():
                return (str(code) if code else None), message
    except (TypeError, ValueError):
        pass
    return (str(code) if code else None), (run.message or run.error or None)


def _method_name(method_id: str) -> str:
    try:
        return str(load_spec_from_contracts(method_id).get("name") or method_id)
    except Exception:  # noqa: BLE001 - a missing contract must not cost the email
        return method_id


def build_run_email(notification: NotificationOutbox, run: Run) -> templates.EmailContent:
    code, message = _error_of(run) if notification.outcome != templates.OUTCOME_DONE else (None, None)
    facts = templates.RunFacts(
        run_id=str(run.id),
        method_name=_method_name(run.method_id),
        dataset_name=run.dataset_name,
        finished_at=run.finished_at,
        error_code=code,
        error_message=message,
    )
    return templates.run_finished(notification.outcome, facts, run_url=f"{FRONTEND_URL}/dashboard?runId={run.id}")


async def _deliver_one(notification: NotificationOutbox) -> str:
    """Send one notification and record the outcome. Returns what happened."""
    attempts = notification.attempts + 1
    async with AsyncSessionLocal() as db:
        repo = NotificationRepository(db)
        if notification.kind != NOTIFICATION_RUN_FINISHED or notification.outcome not in templates.RUN_OUTCOMES:
            await repo.mark_skipped(notification.id, reason=f"unknown notification {notification.kind}/{notification.outcome}")
            return "skipped"
        if not notifications_enabled():
            await repo.mark_skipped(notification.id, reason="run notifications are switched off (RUN_NOTIFICATIONS_ENABLED)")
            return "skipped"
        if not mailer.email_enabled():
            await repo.mark_skipped(notification.id, reason="email is not configured (SMTP_HOST is empty)")
            return "skipped"
        run = await db.get(Run, notification.run_id)
        user = await db.get(User, notification.user_id)
        if run is None or user is None or not (user.email or "").strip():
            await repo.mark_skipped(notification.id, reason="the run or its owner no longer exists")
            return "skipped"
        if not may_use_service(user):
            # An address nobody has confirmed may not be the account holder's.
            await repo.mark_skipped(notification.id, reason="the owner's email address is not confirmed")
            return "skipped"
        recipient = user.email.strip()
        content = build_run_email(notification, run)

        try:
            await mailer.send_email(recipient, content.subject, content.text, content.html)
        except mailer.EmailError as exc:
            reason = str(exc)
            if exc.temporary and attempts < max_attempts():
                wait = retry_delay_seconds(attempts)
                await repo.mark_retry(
                    notification.id, attempts=attempts,
                    next_attempt_at=utc_now() + timedelta(seconds=wait), error=reason,
                )
                logger.warning("notification %s for run %s not sent (attempt %d of %d, next in %ds): %s",
                               notification.id, notification.run_id, attempts, max_attempts(), int(wait), reason)
                return "retry"
            await repo.mark_failed(notification.id, attempts=attempts, error=reason)
            logger.error("notification %s for run %s given up after %d attempt(s): %s",
                         notification.id, notification.run_id, attempts, reason)
            return "failed"
        await repo.mark_sent(notification.id, recipient=recipient, attempts=attempts)
        logger.info("notification sent run=%s outcome=%s attempt=%d", notification.run_id, notification.outcome, attempts)
        return "sent"


async def deliver_due(limit: int = BATCH_SIZE) -> dict[str, int]:
    """One pass over the outbox. Returns how many notifications ended how."""
    async with AsyncSessionLocal() as db:
        claimed = await NotificationRepository(db).claim_due(limit=limit, lease_seconds=lease_seconds())
    counts: dict[str, int] = {}
    for notification in claimed:
        try:
            outcome = await _deliver_one(notification)
        except Exception:  # noqa: BLE001 - one bad row must not stop the others
            # The row keeps its lease and is taken again when the lease ends.
            logger.exception("notification %s could not be processed", notification.id)
            outcome = "error"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def notification_loop(stop: Optional[asyncio.Event] = None) -> None:
    """Deliver notifications until cancelled. Never raises: a failure of this
    loop must not take the worker, and with it run processing, down."""
    mailer.log_configuration("worker")
    while stop is None or not stop.is_set():
        try:
            await deliver_due()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - e.g. the database is briefly away
            traceback.print_exc()
        await asyncio.sleep(poll_seconds())
