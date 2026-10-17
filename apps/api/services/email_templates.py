"""Wording of every email this application sends.

Each function returns an :class:`EmailContent` (subject, plain text, HTML) and
does nothing else: no I/O, no configuration lookups beyond what it is given, so
the wording can be tested and reviewed on its own. Every value that comes from
a user or from a method (names, messages) is escaped in the HTML part.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Optional

APP_NAME = "Phylo Runner"

OUTCOME_DONE = "DONE"
OUTCOME_ERROR = "ERROR"
OUTCOME_QUEUE_TIMEOUT = "QUEUE_TIMEOUT"
RUN_OUTCOMES = (OUTCOME_DONE, OUTCOME_ERROR, OUTCOME_QUEUE_TIMEOUT)

# Longest failure reason quoted in an email; the full text is on the run page.
MAX_REASON_CHARS = 600


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str


def _page(paragraphs: list[str], *, link: Optional[tuple[str, str]] = None, footer: str) -> str:
    """Minimal HTML that every mail client renders: paragraphs, one link, a footer."""
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    if link:
        label, url = link
        body += f'<p><a href="{escape(url, quote=True)}">{escape(label)}</a></p>'
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#1f2937">'
        f"{body}"
        f'<p style="color:#6b7280;font-size:12px">{escape(footer)}</p>'
        "</div>"
    )


def _text(paragraphs: list[str], *, link: Optional[tuple[str, str]] = None, footer: str) -> str:
    parts = list(paragraphs)
    if link:
        label, url = link
        parts.append(f"{label}: {url}")
    parts.append(footer)
    return "\n\n".join(parts) + "\n"


# --------------------------------------------------------------------------- #
# Account emails
# --------------------------------------------------------------------------- #
def password_reset(*, reset_link: str, expires_hours: int) -> EmailContent:
    hours = f"{expires_hours} hour" + ("" if expires_hours == 1 else "s")
    intro = f"You asked to reset the password of your {APP_NAME} account."
    expiry = f"The link works for {hours}. If you did not ask for this, you can ignore this email; your password stays as it is."
    footer = f"Sent by {APP_NAME} because a password reset was requested for this address."
    link = ("Reset your password", reset_link)
    return EmailContent(
        subject=f"Reset your {APP_NAME} password",
        text=_text([intro, expiry], link=link, footer=footer),
        html=_page([escape(intro), escape(expiry)], link=link, footer=footer),
    )


def email_verification(*, verification_link: str, expires_hours: int) -> EmailContent:
    """Confirmation of a newly registered address."""
    hours = f"{expires_hours} hour" + ("" if expires_hours == 1 else "s")
    intro = f"Welcome to {APP_NAME}. Please confirm that this email address is yours."
    expiry = f"The link works for {hours}. If you did not create an account, you can ignore this email."
    footer = f"Sent by {APP_NAME} because an account was registered with this address."
    link = ("Confirm your email address", verification_link)
    return EmailContent(
        subject=f"Confirm your {APP_NAME} email address",
        text=_text([intro, expiry], link=link, footer=footer),
        html=_page([escape(intro), escape(expiry)], link=link, footer=footer),
    )


def account_already_exists(*, login_link: str, reset_link: str) -> EmailContent:
    """Sent instead of a confirmation link when someone registers an address
    that already has an account. The registration form answers the same way in
    both cases, so only the owner of the mailbox learns which one it was."""
    intro = f"Someone tried to create a {APP_NAME} account with this email address, but it already has one."
    yours = (f"If that was you, you do not need a new account: log in at {login_link} "
             f"or, if you have forgotten your password, reset it at {reset_link}.")
    other = "If it was not you, you can ignore this email. Nothing about your account has changed."
    footer = f"Sent by {APP_NAME} because a registration was attempted with this address."
    return EmailContent(
        subject=f"You already have a {APP_NAME} account",
        text=_text([intro, yours, other], footer=footer),
        html=_page([escape(intro), escape(yours), escape(other)], footer=footer),
    )


# --------------------------------------------------------------------------- #
# Run notifications
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RunFacts:
    """What a run notification says about the run."""

    run_id: str
    method_name: str
    dataset_name: Optional[str] = None
    finished_at: Optional[datetime] = None
    # For failures: the code and the message already shown to the user in the app.
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    # Until when the results (and the log) are kept, if they expire at all.
    expires_at: Optional[datetime] = None


def _describe(run: RunFacts) -> str:
    """'Dowser run on "my_data.tsv"' / 'Dowser run'."""
    if run.dataset_name:
        return f'{run.method_name} run on "{run.dataset_name}"'
    return f"{run.method_name} run"


def _when(moment: Optional[datetime]) -> Optional[str]:
    return moment.strftime("%Y-%m-%d %H:%M UTC") if moment else None


def _shorten(message: str) -> str:
    message = " ".join(message.split())
    return message if len(message) <= MAX_REASON_CHARS else message[: MAX_REASON_CHARS - 1].rstrip() + "…"


def run_finished(outcome: str, run: RunFacts, *, run_url: str) -> EmailContent:
    """The one notification a run gets when it ends by itself.

    ``outcome`` is DONE, ERROR or QUEUE_TIMEOUT. Cancelled runs get no email at
    all, so there is no wording for them.
    """
    if outcome not in RUN_OUTCOMES:
        raise ValueError(f"no notification is sent for outcome {outcome!r}")
    what = _describe(run)
    reference = f"Run ID: {run.run_id}"
    footer = f"Sent by {APP_NAME} because you started this run. You get one email per run when it ends."
    finished = _when(run.finished_at)

    if outcome == OUTCOME_DONE:
        subject = f"Your {run.method_name} run has finished"
        lines = [f"Your {what} has finished and its results are ready."]
        if finished:
            lines.append(f"Finished: {finished}")
        if run.expires_at:
            lines.append(
                f"The results are kept until {run.expires_at:%Y-%m-%d}. Download what you need "
                "before then; after that date they are removed."
            )
        lines.append(reference)
        link = ("View the results", run_url)

    elif outcome == OUTCOME_QUEUE_TIMEOUT:
        subject = f"Your {run.method_name} run expired before it could start"
        lines = [
            f"Your {what} waited too long for a free slot and was removed from the queue.",
            "It never started: nothing was computed, there are no results, and it does not "
            "count toward your hourly run limit.",
            "The service was busy or temporarily unavailable. If you still need this analysis, "
            "please submit the run again.",
            reference,
        ]
        link = ("Open the run", run_url)

    else:
        subject = f"Your {run.method_name} run failed"
        lines = [f"Your {what} ended with an error and produced no results."]
        if run.error_message:
            reason = _shorten(run.error_message)
            lines.append(f"Reason: [{run.error_code}] {reason}" if run.error_code else f"Reason: {reason}")
        if finished:
            lines.append(f"Ended: {finished}")
        lines.append(reference)
        link = ("See the details and logs", run_url)

    return EmailContent(
        subject=subject,
        text=_text(lines, link=link, footer=footer),
        html=_page([escape(line) for line in lines], link=link, footer=footer),
    )
