"""The one place this application sends email from: plain SMTP.

Every transactional email (password reset, account emails, run notifications)
goes through :func:`send_email`. Nothing else talks to a mail server, and no
third-party mail API is used.

Configuration is read from the environment each time it is needed, so the
values the deployment provides are the only source of truth:

    SMTP_HOST              mail server. Empty = email is switched off: nothing
                           is sent and callers are told so.
    SMTP_PORT              default by security: 587 (starttls), 465 (ssl), 25 (none)
    SMTP_SECURITY          starttls (default) | ssl | none
    SMTP_USERNAME          optional; with SMTP_PASSWORD enables authentication
    SMTP_PASSWORD          optional
    SMTP_FROM              sender, e.g. "Phylo Runner <phylo@example.org>"
    SMTP_TIMEOUT_SECONDS   connection and command timeout (default 15)
    SMTP_TLS_VERIFY        verify the server certificate (default true)
    SMTP_TLS_CA_FILE       optional CA bundle for a server with a private CA

Credentials are only ever sent over TLS: a username/password with
SMTP_SECURITY=none is reported as a configuration problem instead of being
transmitted in clear text. The password never appears in a log line or in an
error this module raises.

Sending is blocking network I/O, so the async entry point runs it in a thread.
A send either succeeds, or fails with :class:`EmailError` saying whether a
later attempt could succeed (``temporary``) — the notification outbox uses that
to decide between retrying and giving up.
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Mapping, Optional

logger = logging.getLogger("phylo.api.email")

SECURITY_MODES = ("starttls", "ssl", "none")
DEFAULT_PORTS = {"starttls": 587, "ssl": 465, "none": 25}
DEFAULT_TIMEOUT_SECONDS = 15.0


class EmailError(Exception):
    """An email could not be sent.

    ``temporary`` is True when trying again later may work (server unreachable,
    timeout, a 4xx answer, rejected login that an administrator may correct)
    and False when it cannot (the server refused this recipient or message for
    good, or the message itself is invalid).
    """

    def __init__(self, message: str, *, temporary: bool):
        super().__init__(message)
        self.temporary = temporary


class EmailNotConfigured(EmailError):
    """Email is switched off (no SMTP_HOST) or its configuration is invalid."""

    def __init__(self, message: str):
        super().__init__(message, temporary=True)


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    security: str
    username: Optional[str]
    password: Optional[str]
    from_addr: str
    timeout: float
    verify_tls: bool
    ca_file: Optional[str]

    def __repr__(self) -> str:  # never let the password into a log line or traceback
        return (
            f"SmtpSettings(host={self.host!r}, port={self.port}, security={self.security!r}, "
            f"username={self.username!r}, password={'***' if self.password else None}, "
            f"from_addr={self.from_addr!r})"
        )


def _get(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _flag(raw: str, default: bool) -> bool:
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def email_enabled(env: Mapping[str, str] = os.environ) -> bool:
    """True when a mail server is configured at all."""
    return bool(_get(env, "SMTP_HOST"))


def settings_problems(env: Mapping[str, str] = os.environ) -> list[str]:
    """What is wrong with the SMTP configuration, naming variables only (never
    values). Empty when email is switched off or correctly configured."""
    if not email_enabled(env):
        return []
    problems: list[str] = []
    security = _get(env, "SMTP_SECURITY").lower() or "starttls"
    if security not in SECURITY_MODES:
        problems.append("SMTP_SECURITY must be one of: starttls, ssl, none")
    port = _get(env, "SMTP_PORT")
    if port and not (port.isdigit() and 0 < int(port) < 65536):
        problems.append("SMTP_PORT must be a port number")
    sender = _get(env, "SMTP_FROM")
    if not sender:
        problems.append("SMTP_FROM is required when SMTP_HOST is set")
    elif "@" not in parseaddr(sender)[1]:
        problems.append("SMTP_FROM must contain an email address")
    username, password = _get(env, "SMTP_USERNAME"), env.get("SMTP_PASSWORD") or ""
    if bool(username) != bool(password):
        problems.append("SMTP_USERNAME and SMTP_PASSWORD must be set together")
    if username and security == "none":
        problems.append("SMTP_USERNAME/SMTP_PASSWORD require SMTP_SECURITY=starttls or ssl (credentials are not sent without TLS)")
    timeout = _get(env, "SMTP_TIMEOUT_SECONDS")
    if timeout:
        try:
            if float(timeout) <= 0:
                raise ValueError
        except ValueError:
            problems.append("SMTP_TIMEOUT_SECONDS must be a positive number")
    ca_file = _get(env, "SMTP_TLS_CA_FILE")
    if ca_file and not os.path.isfile(ca_file):
        problems.append("SMTP_TLS_CA_FILE does not point to a file")
    return problems


def smtp_settings(env: Mapping[str, str] = os.environ) -> SmtpSettings:
    """The SMTP settings to use. Raises EmailNotConfigured when email is
    switched off or the configuration is invalid."""
    if not email_enabled(env):
        raise EmailNotConfigured("email is not configured (SMTP_HOST is empty)")
    problems = settings_problems(env)
    if problems:
        raise EmailNotConfigured("email configuration is invalid: " + "; ".join(problems))
    security = _get(env, "SMTP_SECURITY").lower() or "starttls"
    username = _get(env, "SMTP_USERNAME") or None
    return SmtpSettings(
        host=_get(env, "SMTP_HOST"),
        port=int(_get(env, "SMTP_PORT") or DEFAULT_PORTS[security]),
        security=security,
        username=username,
        password=(env.get("SMTP_PASSWORD") or None) if username else None,
        from_addr=_get(env, "SMTP_FROM"),
        timeout=float(_get(env, "SMTP_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS),
        verify_tls=_flag(_get(env, "SMTP_TLS_VERIFY"), True),
        ca_file=_get(env, "SMTP_TLS_CA_FILE") or None,
    )


def build_message(
    settings: SmtpSettings, *, to: str, subject: str, text: str, html: Optional[str] = None
) -> EmailMessage:
    """A standards-conforming message: plain text always, HTML as an alternative.

    Header values are set through the email package's policy, which refuses line
    breaks: a recipient or subject cannot smuggle extra headers into the message.
    """
    name, address = parseaddr(to)
    if "@" not in address or any(c in to for c in "\r\n"):
        raise EmailError("invalid recipient address", temporary=False)
    message = EmailMessage()
    try:
        message["From"] = settings.from_addr
        message["To"] = str(Address(display_name=name, addr_spec=address)) if name else address
        message["Subject"] = " ".join(subject.split())
    except (ValueError, IndexError) as exc:
        raise EmailError(f"invalid message header: {exc}", temporary=False) from exc
    message["Date"] = formatdate(localtime=False)
    sender_domain = parseaddr(settings.from_addr)[1].rpartition("@")[2] or None
    message["Message-ID"] = make_msgid(domain=sender_domain)
    # Machine-generated mail: tells well-behaved auto-responders not to reply.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _tls_context(settings: SmtpSettings) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=settings.ca_file)
    if not settings.verify_tls:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _smtp_reply(exc: smtplib.SMTPResponseException) -> str:
    text = exc.smtp_error.decode("utf-8", "replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
    return f"{exc.smtp_code} {' '.join(text.split())}"[:300]


def send_sync(settings: SmtpSettings, message: EmailMessage) -> None:
    """Deliver one message. Raises EmailError; never returns a "maybe"."""
    try:
        if settings.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.host, settings.port, timeout=settings.timeout, context=_tls_context(settings)
            )
        else:
            client = smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout)
        with client:
            client.ehlo()
            if settings.security == "starttls":
                if not client.has_extn("starttls"):
                    # Never fall back to an unencrypted session by accident.
                    raise EmailError("the mail server does not offer STARTTLS", temporary=True)
                client.starttls(context=_tls_context(settings))
                client.ehlo()
            if settings.username:
                client.login(settings.username, settings.password or "")
            refused = client.send_message(message)
            if refused:  # only possible with several recipients; we send to one
                raise EmailError("the mail server refused the recipient", temporary=False)
    except EmailError:
        raise
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError(f"the mail server rejected the login ({exc.smtp_code})", temporary=True) from None
    except smtplib.SMTPRecipientsRefused as exc:
        codes = [code for code, _ in exc.recipients.values()]
        temporary = bool(codes) and all(400 <= code < 500 for code in codes)
        raise EmailError(f"the mail server refused the recipient ({', '.join(map(str, codes))})",
                         temporary=temporary) from None
    except smtplib.SMTPResponseException as exc:
        raise EmailError(f"the mail server answered {_smtp_reply(exc)}",
                         temporary=400 <= exc.smtp_code < 500) from None
    except ssl.SSLError as exc:
        reason = getattr(exc, "reason", None) or type(exc).__name__
        raise EmailError(f"TLS negotiation with the mail server failed ({reason})", temporary=True) from None
    except (socket.timeout, TimeoutError):
        raise EmailError("the mail server did not answer in time", temporary=True) from None
    except smtplib.SMTPServerDisconnected as exc:
        # smtplib reports a read timeout as a disconnect whose text says so.
        if "timed out" in str(exc).lower():
            raise EmailError("the mail server did not answer in time", temporary=True) from None
        raise EmailError("the mail server closed the connection", temporary=True) from None
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"could not reach the mail server ({type(exc).__name__})", temporary=True) from None


async def send_email(to: str, subject: str, text: str, html: Optional[str] = None) -> None:
    """Send one email, or raise EmailError (EmailNotConfigured when email is
    switched off). Blocking SMTP work happens in a worker thread and is bounded
    by SMTP_TIMEOUT_SECONDS per network operation."""
    settings = smtp_settings()
    message = build_message(settings, to=to, subject=subject, text=text, html=html)
    await asyncio.to_thread(send_sync, settings, message)
    logger.info("email sent to=%s subject=%r", to, message["Subject"])


def log_configuration(component: str) -> None:
    """One start-up line saying whether email works, so a silent
    misconfiguration is visible on day one."""
    if not email_enabled():
        logger.warning("%s: email is switched off (SMTP_HOST is empty); no email will be sent", component)
        return
    problems = settings_problems()
    if problems:
        logger.error("%s: email configuration is invalid, no email can be sent: %s", component, "; ".join(problems))
        return
    settings = smtp_settings()
    logger.info("%s: email via %s:%s (%s%s)", component, settings.host, settings.port, settings.security,
                ", authenticated" if settings.username else "")
    frontend = (os.getenv("FRONTEND_URL") or "http://localhost:3000").lower()
    if any(local in frontend for local in ("://localhost", "://127.0.0.1")):
        logger.warning("%s: FRONTEND_URL points to this machine; links in emails will not work for recipients", component)
