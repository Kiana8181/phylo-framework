"""The SMTP mailer against a real (local, in-process) SMTP server.

Nothing here is mocked at the protocol level: smtplib talks to
tests/support/smtp_sink.py over a socket, with and without TLS, so what is
tested is what a mail server will actually see.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time

import pytest

from apps.api.services import email as mailer
from apps.api.services import email_templates as templates
from tests.support.smtp_sink import SmtpSink

SMTP_ENV = ("SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM",
            "SMTP_TIMEOUT_SECONDS", "SMTP_TLS_VERIFY", "SMTP_TLS_CA_FILE")
SECRET = "s3cr3t-Mail-Passw0rd"


@pytest.fixture(autouse=True)
def clean_smtp_env(monkeypatch):
    for name in SMTP_ENV:
        monkeypatch.delenv(name, raising=False)


def configure(monkeypatch, sink: SmtpSink, **overrides):
    values = {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(sink.port), "SMTP_SECURITY": "none",
              "SMTP_FROM": "Phylo Runner <phylo@lab.example>", "SMTP_TIMEOUT_SECONDS": "5"}
    values.update({k: str(v) for k, v in overrides.items()})
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.fixture(scope="session")
def tls_files(tmp_path_factory):
    """A self-signed certificate for 127.0.0.1, made with the openssl CLI."""
    if shutil.which("openssl") is None:
        pytest.skip("openssl is not available to create a test certificate")
    directory = tmp_path_factory.mktemp("smtp-tls")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=127.0.0.1",
         "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost", "-keyout", str(key), "-out", str(cert)],
        check=True, capture_output=True,
    )
    return str(cert), str(key)


def server_tls(tls_files):
    import ssl
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(*tls_files)
    return context


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def test_without_a_mail_server_email_is_off_and_says_so():
    assert mailer.email_enabled({}) is False
    assert mailer.settings_problems({}) == []
    with pytest.raises(mailer.EmailNotConfigured, match="SMTP_HOST is empty"):
        mailer.smtp_settings({})


@pytest.mark.parametrize("security,port", [("", 587), ("starttls", 587), ("ssl", 465), ("none", 25), ("STARTTLS", 587)])
def test_port_and_security_defaults(security, port):
    env = {"SMTP_HOST": "mail.example", "SMTP_FROM": "a@b.example", "SMTP_SECURITY": security}
    settings = mailer.smtp_settings(env)
    assert settings.port == port and settings.security == (security.lower() or "starttls")
    assert settings.verify_tls is True and settings.timeout == 15 and settings.username is None


def test_every_setting_comes_from_the_environment():
    env = {"SMTP_HOST": "relay.lab", "SMTP_PORT": "2525", "SMTP_SECURITY": "ssl", "SMTP_USERNAME": "phylo",
           "SMTP_PASSWORD": SECRET, "SMTP_FROM": "Phylo <p@lab.example>", "SMTP_TIMEOUT_SECONDS": "7.5",
           "SMTP_TLS_VERIFY": "false"}
    settings = mailer.smtp_settings(env)
    assert (settings.host, settings.port, settings.security, settings.username, settings.password) == (
        "relay.lab", 2525, "ssl", "phylo", SECRET)
    assert settings.timeout == 7.5 and settings.verify_tls is False


@pytest.mark.parametrize("change,expected", [
    ({"SMTP_SECURITY": "tls"}, "SMTP_SECURITY must be one of"),
    ({"SMTP_PORT": "smtp"}, "SMTP_PORT must be a port number"),
    ({"SMTP_PORT": "70000"}, "SMTP_PORT must be a port number"),
    ({"SMTP_FROM": ""}, "SMTP_FROM is required"),
    ({"SMTP_FROM": "Phylo Runner"}, "SMTP_FROM must contain an email address"),
    ({"SMTP_USERNAME": "phylo"}, "must be set together"),
    ({"SMTP_PASSWORD": SECRET}, "must be set together"),
    ({"SMTP_USERNAME": "phylo", "SMTP_PASSWORD": SECRET, "SMTP_SECURITY": "none"}, "credentials are not sent without TLS"),
    ({"SMTP_TIMEOUT_SECONDS": "0"}, "SMTP_TIMEOUT_SECONDS must be a positive number"),
    ({"SMTP_TLS_CA_FILE": "/nonexistent/ca.pem"}, "SMTP_TLS_CA_FILE does not point to a file"),
])
def test_configuration_mistakes_are_named_without_revealing_values(change, expected):
    env = {"SMTP_HOST": "mail.example", "SMTP_FROM": "a@b.example", **change}
    problems = mailer.settings_problems(env)
    assert any(expected in p for p in problems), problems
    assert SECRET not in " ".join(problems)
    with pytest.raises(mailer.EmailNotConfigured) as raised:
        mailer.smtp_settings(env)
    assert SECRET not in str(raised.value) and raised.value.temporary is True


def test_the_password_is_never_shown_by_the_settings_object():
    settings = mailer.smtp_settings({"SMTP_HOST": "m", "SMTP_FROM": "a@b.example", "SMTP_USERNAME": "u",
                                     "SMTP_PASSWORD": SECRET})
    assert SECRET not in repr(settings) and SECRET not in str(settings) and "***" in repr(settings)


def test_start_up_line_reports_off_invalid_and_working(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="phylo.api.email"):
        mailer.log_configuration("worker")
        monkeypatch.setenv("SMTP_HOST", "mail.example")
        mailer.log_configuration("worker")
        monkeypatch.setenv("SMTP_FROM", "a@b.example")
        monkeypatch.setenv("SMTP_USERNAME", "phylo")
        monkeypatch.setenv("SMTP_PASSWORD", SECRET)
        mailer.log_configuration("worker")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "email is switched off" in text
    assert "configuration is invalid" in text and "SMTP_FROM is required" in text
    assert "email via mail.example:587 (starttls, authenticated)" in text
    assert SECRET not in text


# --------------------------------------------------------------------------- #
# The message
# --------------------------------------------------------------------------- #
def settings_for(port=25, **over):
    env = {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(port), "SMTP_SECURITY": "none",
           "SMTP_FROM": "Phylo Runner <phylo@lab.example>"}
    env.update(over)
    return mailer.smtp_settings(env)


def test_message_has_text_and_html_parts_and_is_marked_automatic():
    message = mailer.build_message(settings_for(), to="Ada <ada@uni.example>", subject="Run finished",
                                   text="plain body", html="<p>html body</p>")
    assert message["From"] == "Phylo Runner <phylo@lab.example>" and message["To"] == "Ada <ada@uni.example>"
    assert message["Subject"] == "Run finished" and message["Auto-Submitted"] == "auto-generated"
    assert message["Date"] and message["Message-ID"].endswith("@lab.example>")
    assert message.get_body(("plain",)).get_content().strip() == "plain body"
    assert message.get_body(("html",)).get_content().strip() == "<p>html body</p>"
    text_only = mailer.build_message(settings_for(), to="ada@uni.example", subject="s", text="t")
    assert not text_only.is_multipart()


@pytest.mark.parametrize("to", ["ada@uni.example\r\nBcc: spy@evil.example", "ada@uni.example\nSubject: x", "no-at-sign", ""])
def test_a_recipient_cannot_inject_headers(to):
    with pytest.raises(mailer.EmailError) as raised:
        mailer.build_message(settings_for(), to=to, subject="s", text="t")
    assert raised.value.temporary is False


def test_a_subject_cannot_inject_headers():
    message = mailer.build_message(settings_for(), to="ada@uni.example",
                                   subject="Run finished\r\nBcc: spy@evil.example", text="t")
    assert message["Subject"] == "Run finished Bcc: spy@evil.example"
    assert message["Bcc"] is None and "\nBcc:" not in message.as_string()


# --------------------------------------------------------------------------- #
# Real SMTP exchanges
# --------------------------------------------------------------------------- #
async def test_plain_smtp_delivers_the_message_intact(monkeypatch):
    async with SmtpSink() as sink:
        configure(monkeypatch, sink)
        await mailer.send_email("ada@uni.example", "Your GCtree run has finished",
                                "Results are ready.\n.A line starting with a dot\nÜmläut ✓", "<p>Results are <b>ready</b>.</p>")
    (received,) = sink.messages
    assert received["recipients"] == ["ada@uni.example"] and received["envelope_from"].startswith("FROM:<phylo@lab.example>")
    assert received["subject"] == "Your GCtree run has finished"
    assert received["from"] == "Phylo Runner <phylo@lab.example>"
    assert received["text"].replace("\r\n", "\n") == "Results are ready.\n.A line starting with a dot\nÜmläut ✓\n"
    assert "<b>ready</b>" in received["html"]
    assert received["tls"] is False and received["authenticated"] is False


async def test_starttls_encrypts_before_logging_in(monkeypatch, tls_files):
    async with SmtpSink(tls_context=server_tls(tls_files), credentials=("phylo", SECRET)) as sink:
        configure(monkeypatch, sink, SMTP_SECURITY="starttls", SMTP_USERNAME="phylo", SMTP_PASSWORD=SECRET,
                  SMTP_TLS_CA_FILE=tls_files[0])
        await mailer.send_email("ada@uni.example", "s", "t")
    (received,) = sink.messages
    assert received["tls"] is True and received["authenticated"] is True
    assert sink.logins == [("phylo", SECRET)]


async def test_implicit_tls_mode(monkeypatch, tls_files):
    async with SmtpSink(tls_context=server_tls(tls_files), implicit_tls=True, credentials=("phylo", SECRET)) as sink:
        configure(monkeypatch, sink, SMTP_SECURITY="ssl", SMTP_USERNAME="phylo", SMTP_PASSWORD=SECRET,
                  SMTP_TLS_CA_FILE=tls_files[0])
        await mailer.send_email("ada@uni.example", "s", "t")
    assert sink.messages[0]["tls"] is True and sink.messages[0]["authenticated"] is True


async def test_an_untrusted_certificate_is_refused_unless_verification_is_switched_off(monkeypatch, tls_files):
    async with SmtpSink(tls_context=server_tls(tls_files), credentials=("phylo", SECRET)) as sink:
        configure(monkeypatch, sink, SMTP_SECURITY="starttls", SMTP_USERNAME="phylo", SMTP_PASSWORD=SECRET)
        with pytest.raises(mailer.EmailError, match="TLS negotiation") as raised:
            await mailer.send_email("ada@uni.example", "s", "t")
        assert raised.value.temporary is True
        assert sink.messages == [] and sink.logins == []           # no credentials to an unverified server
        monkeypatch.setenv("SMTP_TLS_VERIFY", "false")
        await mailer.send_email("ada@uni.example", "s", "t")
    assert len(sink.messages) == 1 and sink.messages[0]["tls"] is True


async def test_no_silent_downgrade_when_the_server_offers_no_starttls(monkeypatch):
    """Asked for STARTTLS, offered none: send nothing rather than send in clear."""
    async with SmtpSink() as sink:                                    # no TLS on offer
        configure(monkeypatch, sink, SMTP_SECURITY="starttls", SMTP_USERNAME="phylo", SMTP_PASSWORD=SECRET)
        with pytest.raises(mailer.EmailError, match="does not offer STARTTLS"):
            await mailer.send_email("ada@uni.example", "s", "t")
    assert sink.messages == [] and sink.logins == []


async def test_a_rejected_login_is_reported_without_the_password(monkeypatch, tls_files, caplog):
    async with SmtpSink(tls_context=server_tls(tls_files), credentials=("phylo", "the-right-one")) as sink:
        configure(monkeypatch, sink, SMTP_SECURITY="starttls", SMTP_USERNAME="phylo", SMTP_PASSWORD=SECRET,
                  SMTP_TLS_CA_FILE=tls_files[0])
        with caplog.at_level(logging.DEBUG), pytest.raises(mailer.EmailError, match="rejected the login") as raised:
            await mailer.send_email("ada@uni.example", "s", "t")
    assert raised.value.temporary is True                             # an administrator can correct it
    assert SECRET not in str(raised.value) and SECRET not in caplog.text
    assert raised.value.__cause__ is None                             # no chained exception carrying server text
    assert sink.messages == []


@pytest.mark.parametrize("mode,temporary,match", [
    ("refuse", True, "could not reach the mail server|closed the connection"),
    ("tempfail", True, "451"),
    ("reject", False, "refused the recipient"),
])
async def test_failures_say_whether_trying_again_can_help(monkeypatch, mode, temporary, match):
    async with SmtpSink() as sink:
        sink.mode = mode
        configure(monkeypatch, sink)
        with pytest.raises(mailer.EmailError, match=match) as raised:
            await mailer.send_email("ada@uni.example", "s", "t")
    assert raised.value.temporary is temporary and sink.messages == []


async def test_a_server_that_never_answers_is_given_up_on_after_the_timeout(monkeypatch):
    async with SmtpSink() as sink:
        sink.mode = "hang"
        configure(monkeypatch, sink, SMTP_TIMEOUT_SECONDS="0.5")
        started = time.monotonic()
        with pytest.raises(mailer.EmailError, match="did not answer in time") as raised:
            await mailer.send_email("ada@uni.example", "s", "t")
        assert time.monotonic() - started < 3 and raised.value.temporary is True


async def test_an_unreachable_server_is_a_temporary_failure(monkeypatch):
    async with SmtpSink() as sink:
        port = sink.port
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(port))                        # nothing listens here any more
    monkeypatch.setenv("SMTP_SECURITY", "none")
    monkeypatch.setenv("SMTP_FROM", "phylo@lab.example")
    with pytest.raises(mailer.EmailError, match="could not reach the mail server") as raised:
        await mailer.send_email("ada@uni.example", "s", "t")
    assert raised.value.temporary is True


async def test_sending_while_email_is_off_or_misconfigured_raises_not_configured(monkeypatch):
    with pytest.raises(mailer.EmailNotConfigured, match="SMTP_HOST is empty"):
        await mailer.send_email("ada@uni.example", "s", "t")
    monkeypatch.setenv("SMTP_HOST", "mail.example")
    with pytest.raises(mailer.EmailNotConfigured, match="SMTP_FROM is required"):
        await mailer.send_email("ada@uni.example", "s", "t")


# --------------------------------------------------------------------------- #
# Wording
# --------------------------------------------------------------------------- #
FACTS = templates.RunFacts(run_id="6f0c1b2e-0000-4000-8000-000000000001", method_name="Dowser",
                           dataset_name="clones_2024.tsv")
URL = "https://phylo.lab.example/dashboard?runId=6f0c1b2e-0000-4000-8000-000000000001"


def test_done_notification_points_to_the_results():
    content = templates.run_finished("DONE", FACTS, run_url=URL)
    assert content.subject == "Your Dowser run has finished"
    assert 'Your Dowser run on "clones_2024.tsv" has finished and its results are ready.' in content.text
    assert f"View the results: {URL}" in content.text and FACTS.run_id in content.text
    assert f'<a href="{URL}">View the results</a>' in content.html


def test_error_notification_gives_the_reason_the_app_shows():
    facts = templates.RunFacts(run_id=FACTS.run_id, method_name="Dowser", error_code="TIMEOUT",
                               error_message="The run was stopped because it exceeded the maximum run time of 24 hours for dowser.")
    content = templates.run_finished("ERROR", facts, run_url=URL)
    assert content.subject == "Your Dowser run failed"
    assert "Reason: [TIMEOUT] The run was stopped because it exceeded the maximum run time" in content.text
    assert "produced no results" in content.text and "See the details and logs" in content.text
    long = templates.RunFacts(run_id=FACTS.run_id, method_name="Dowser", error_message="x" * 5000)
    assert len(templates.run_finished("ERROR", long, run_url=URL).text) < 1200          # quoted, not dumped


def test_queue_timeout_notification_says_the_run_never_started():
    content = templates.run_finished("QUEUE_TIMEOUT", FACTS, run_url=URL)
    assert content.subject == "Your Dowser run expired before it could start"
    text = content.text
    assert "waited too long for a free slot and was removed from the queue" in text
    assert "It never started" in text and "nothing was computed" in text
    assert "does not count toward your hourly run limit" in text
    assert "please submit the run again" in text
    assert "failed" not in text.lower() and "error" not in text.lower()   # it is not presented as a failure of the analysis


def test_there_is_no_notification_for_a_cancelled_run():
    with pytest.raises(ValueError, match="no notification is sent"):
        templates.run_finished("CANCELLED", FACTS, run_url=URL)


def test_user_and_method_supplied_text_is_escaped_in_html():
    facts = templates.RunFacts(run_id=FACTS.run_id, method_name="GCtree", dataset_name='<img src=x onerror=alert(1)>.fa',
                               error_code="X", error_message='<script>alert("x")</script> & more')
    for outcome in ("DONE", "ERROR", "QUEUE_TIMEOUT"):
        html = templates.run_finished(outcome, facts, run_url=URL + '&x="><script>').html
        assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in templates.run_finished("ERROR", facts, run_url=URL).html


def test_account_emails():
    link = "https://phylo.lab.example/auth/reset-password?token=abc"
    reset = templates.password_reset(reset_link=link, expires_hours=1)
    assert reset.subject == "Reset your Phylo Runner password"
    assert f"Reset your password: {link}" in reset.text and "works for 1 hour." in reset.text
    assert "you can ignore this email" in reset.text and f'href="{link}"' in reset.html
    verify = templates.email_verification(verification_link="https://phylo.lab.example/auth/verify?token=abc", expires_hours=24)
    assert verify.subject == "Confirm your Phylo Runner email address"
    assert "works for 24 hours" in verify.text and "Confirm your email address: https://" in verify.text
