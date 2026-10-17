"""A small SMTP server for tests: it accepts mail and keeps it, and can be told
to misbehave. Standard library only, so it runs in any of the project's images.

Used in two ways:
  - in-process by unit tests:        async with SmtpSink() as sink: ...
  - as a container in the test stack: python tests/support/smtp_sink.py
    which also serves a tiny HTTP API to read what arrived and to switch modes:
        GET  /messages          -> {"messages": [...]}
        POST /reset             -> forget everything, mode "ok"
        POST /mode  {"mode": "ok" | "refuse" | "tempfail" | "reject" | "hang"}

Modes:
    ok        accept
    refuse    close every connection at once (server down / connection reset)
    tempfail  answer 451 to DATA (try again later)
    reject    answer 550 to RCPT (this recipient is refused for good)
    hang      accept the connection and never answer (tests the client timeout)

It speaks enough SMTP for smtplib: EHLO/HELO, STARTTLS, AUTH PLAIN/LOGIN, MAIL,
RCPT, DATA, RSET, NOOP, QUIT. It is not a mail server and must never be exposed
outside a test.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import ssl
from email import message_from_bytes, policy
from typing import Any, Optional

MODES = ("ok", "refuse", "tempfail", "reject", "hang")


class SmtpSink:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        tls_context: Optional[ssl.SSLContext] = None,
        implicit_tls: bool = False,
        credentials: Optional[tuple[str, str]] = None,
    ):
        self.host, self.port = host, port
        self.tls_context = tls_context
        self.implicit_tls = implicit_tls          # "ssl" mode: TLS from the first byte
        self.credentials = credentials            # when set, mail requires this login
        self.mode = "ok"
        self.messages: list[dict[str, Any]] = []
        self.connections = 0
        self.logins: list[tuple[str, str]] = []
        self.sessions: list[dict[str, Any]] = []  # per connection: was TLS on, did it log in
        self._server: Optional[asyncio.AbstractServer] = None

    async def __aenter__(self) -> "SmtpSink":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, self.host, self.port,
            ssl=self.tls_context if self.implicit_tls else None,
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=2)
            except asyncio.TimeoutError:
                pass

    def reset(self) -> None:
        self.mode = "ok"
        self.messages.clear()
        self.logins.clear()
        self.sessions.clear()
        self.connections = 0

    # ------------------------------------------------------------------ #
    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        session = {"tls": self.implicit_tls, "authenticated": False}
        self.sessions.append(session)

        async def say(line: str) -> None:
            writer.write(line.encode() + b"\r\n")
            await writer.drain()

        try:
            if self.mode == "refuse":
                return
            if self.mode == "hang":
                await asyncio.sleep(3600)
                return
            await say("220 smtp-sink ready")
            mail_from, rcpts = None, []
            while True:
                raw = await reader.readline()
                if not raw:
                    return
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                verb, _, arg = line.partition(" ")
                verb = verb.upper()
                if verb in ("EHLO", "HELO"):
                    extensions = ["smtp-sink", "8BITMIME", "SMTPUTF8"]
                    if self.tls_context is not None and not session["tls"]:
                        extensions.append("STARTTLS")
                    if self.credentials is not None:
                        extensions.append("AUTH PLAIN LOGIN")
                    for ext in extensions[:-1]:
                        await say(f"250-{ext}")
                    await say(f"250 {extensions[-1]}")
                elif verb == "STARTTLS" and self.tls_context is not None and not session["tls"]:
                    await say("220 go ahead")
                    await writer.start_tls(self.tls_context)
                    session["tls"] = True
                elif verb == "AUTH":
                    mechanism, _, initial = arg.partition(" ")
                    user = password = ""
                    if mechanism.upper() == "PLAIN":
                        if not initial:
                            await say("334 ")
                            initial = (await reader.readline()).decode().strip()
                        parts = base64.b64decode(initial).split(b"\0")
                        user, password = parts[-2].decode(), parts[-1].decode()
                    elif mechanism.upper() == "LOGIN":
                        if initial:
                            user = base64.b64decode(initial).decode()
                        else:
                            await say("334 VXNlcm5hbWU6")
                            user = base64.b64decode((await reader.readline()).strip()).decode()
                        await say("334 UGFzc3dvcmQ6")
                        password = base64.b64decode((await reader.readline()).strip()).decode()
                    else:
                        await say("504 unsupported mechanism")
                        continue
                    self.logins.append((user, password))
                    if self.credentials == (user, password):
                        session["authenticated"] = True
                        await say("235 authenticated")
                    else:
                        await say("535 authentication failed")
                elif verb == "MAIL":
                    if self.credentials is not None and not session["authenticated"]:
                        await say("530 authentication required")
                        continue
                    mail_from, rcpts = arg, []
                    await say("250 ok")
                elif verb == "RCPT":
                    if self.mode == "reject":
                        await say("550 no such user here")
                    else:
                        rcpts.append(arg.split(":", 1)[-1].strip().strip("<>"))
                        await say("250 ok")
                elif verb == "DATA":
                    if not rcpts:
                        await say("503 no recipients")
                        continue
                    if self.mode == "tempfail":
                        await say("451 try again later")
                        continue
                    await say("354 end with .")
                    body = bytearray()
                    while True:
                        chunk = await reader.readline()
                        if chunk in (b".\r\n", b".\n", b""):
                            break
                        body += chunk[1:] if chunk.startswith(b"..") else chunk
                    self.messages.append(self._parse(bytes(body), mail_from, rcpts, session))
                    await say("250 accepted")
                elif verb == "RSET":
                    mail_from, rcpts = None, []
                    await say("250 ok")
                elif verb == "NOOP":
                    await say("250 ok")
                elif verb == "QUIT":
                    await say("221 bye")
                    return
                else:
                    await say("502 not implemented")
        except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _parse(raw: bytes, mail_from: Optional[str], rcpts: list[str], session: dict[str, Any]) -> dict[str, Any]:
        message = message_from_bytes(raw, policy=policy.default)
        text_part = message.get_body(preferencelist=("plain",))
        html_part = message.get_body(preferencelist=("html",))
        return {
            "envelope_from": mail_from,
            "recipients": list(rcpts),
            "from": str(message["From"]),
            "to": str(message["To"]),
            "subject": str(message["Subject"]),
            "headers": {k: str(v) for k, v in message.items()},
            "text": text_part.get_content() if text_part else "",
            "html": html_part.get_content() if html_part else "",
            "tls": bool(session["tls"]),
            "authenticated": bool(session["authenticated"]),
        }


# ---------------------------------------------------------------------- #
# Stand-alone: SMTP on one port, a minimal HTTP control API on another.
# ---------------------------------------------------------------------- #
async def _http(sink: SmtpSink, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request_line = (await reader.readline()).decode().split()
        headers: dict[str, str] = {}
        while True:
            line = (await reader.readline()).decode().strip()
            if not line:
                break
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        body = await reader.readexactly(int(headers.get("content-length", "0") or 0))
        method, path = (request_line + ["", ""])[:2]
        status, payload = 200, {"ok": True}
        if method == "GET" and path == "/messages":
            payload = {"messages": sink.messages, "mode": sink.mode, "connections": sink.connections}
        elif method == "POST" and path == "/reset":
            sink.reset()
        elif method == "POST" and path == "/mode":
            mode = (json.loads(body or b"{}") or {}).get("mode")
            if mode in MODES:
                sink.mode = mode
            else:
                status, payload = 400, {"ok": False, "error": f"mode must be one of {MODES}"}
        elif method == "GET" and path == "/health":
            pass
        else:
            status, payload = 404, {"ok": False}
        data = json.dumps(payload).encode()
        writer.write(
            f"HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data
        )
        await writer.drain()
    except Exception:  # noqa: BLE001
        pass
    finally:
        writer.close()


async def _serve(smtp_port: int, http_port: int) -> None:
    sink = SmtpSink("0.0.0.0", smtp_port)
    await sink.start()
    http = await asyncio.start_server(lambda r, w: _http(sink, r, w), "0.0.0.0", http_port)
    print(f"smtp-sink: SMTP on :{sink.port}, control on :{http_port}", flush=True)
    async with http:
        await http.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smtp-port", type=int, default=1025)
    parser.add_argument("--http-port", type=int, default=8025)
    args = parser.parse_args()
    asyncio.run(_serve(args.smtp_port, args.http_port))
