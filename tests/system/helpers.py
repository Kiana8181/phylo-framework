"""What the system tests share: a user of the running stack, and a handle on
the stack itself (the isolated ``phylo-tests`` compose project).

Everything a test does to the stack goes through :class:`Stack`: changing a
service's environment or limits, stopping, killing and restarting containers,
looking inside them. A change made for one test is undone when the test ends.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

import asyncpg
import httpx
import yaml

from tests.support.accounts import messages_for, register_verified, unwrap

ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:58000"
MAIL = "http://127.0.0.1:58025"
DATABASE = "postgresql://phylo_test:phylo_test@127.0.0.1:55432/phylo_e2e_test"
METHOD_PORTS = {"dowser": 58001, "gctree": 58002, "brepphylo": 58003, "clonaltree": 58004}
PARAMS = json.loads((ROOT / "tests/fixtures/scientific-params.json").read_text())
SAMPLE = ROOT / "apps/web/public/samples/ExampleAirr_clone_3128.tsv"
TERMINAL = ("DONE", "ERROR", "CANCELLED")
BASE_FILES = ["docker-compose.test.yml", "tests/system/docker-compose.system.yml"]


async def eventually(check: Callable[[], Awaitable[Any]], seconds: float, what: str, every: float = 0.5) -> Any:
    """The first truthy value ``check`` returns; fails with ``what`` after ``seconds``."""
    deadline = time.monotonic() + seconds
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = await check()
        except (httpx.HTTPError, OSError, asyncpg.PostgresError) as exc:   # a service that is restarting
            last = exc
        else:
            if last:
                return last
        await asyncio.sleep(every)
    raise AssertionError(f"timed out after {seconds:g}s waiting for {what} (last: {last!r})")


# --------------------------------------------------------------------------- #
# A user
# --------------------------------------------------------------------------- #
class User:
    """A freshly registered, confirmed account with one uploaded dataset."""

    def __init__(self) -> None:
        self.api = httpx.AsyncClient(base_url=API, timeout=60, trust_env=False)
        self.email = f"{uuid4().hex}@example.org"
        self.file_id: Optional[str] = None

    @classmethod
    async def create(cls) -> "User":
        user = cls()
        await register_verified(user.api, user.email, user.email.split("@")[0], "system-test-password")
        init = unwrap(await user.api.post("/uploads/init", json={"original_filename": SAMPLE.name}))
        user.file_id = unwrap(await user.api.put(init["content_url"], content=SAMPLE.read_bytes()))["file_id"]
        return user

    async def close(self) -> None:
        await self.api.aclose()

    async def submit(self, method: str, **params: Any) -> httpx.Response:
        return await self.api.post(f"/runs?method={method}",
                                   json={"file_id": self.file_id, "params": {**PARAMS[method], **params}})

    async def start(self, method: str, **params: Any) -> str:
        response = await self.submit(method, **params)
        assert response.status_code == 200, f"submitting a {method} run: HTTP {response.status_code} {response.text[:400]}"
        return unwrap(response)["run_id"]

    async def status(self, run_id: str) -> dict:
        return unwrap(await self.api.get(f"/runs/{run_id}/status"))

    async def wait(self, run_id: str, seconds: float = 300) -> dict:
        async def ended():
            status = await self.status(run_id)
            return status if status["status"] in TERMINAL else None
        return await eventually(ended, seconds, f"run {run_id} to end")

    async def wait_until(self, run_id: str, predicate: Callable[[dict], bool], seconds: float, what: str) -> dict:
        async def reached():
            status = await self.status(run_id)
            if status["status"] in TERMINAL and not predicate(status):
                raise AssertionError(f"run ended as {status['status']} before {what}: {status.get('message')}")
            return status if predicate(status) else None
        return await eventually(reached, seconds, what, every=0.2)

    async def runs(self) -> list[dict]:
        return unwrap(await self.api.get("/runs"))

    async def quota(self) -> dict:
        return unwrap(await self.api.get("/runs/quota"))

    async def artifacts(self, run_id: str) -> list[dict]:
        return unwrap(await self.api.get(f"/runs/{run_id}/artifacts"))["artifacts"]

    async def mail(self, containing: str = "") -> list[dict]:
        return [m for m in await messages_for(self.email) if containing in m["subject"]]


def error_code(status: dict) -> Optional[str]:
    return (status.get("error") or {}).get("code")


async def run_row(run_id: str) -> asyncpg.Record:
    connection = await asyncpg.connect(DATABASE)
    try:
        return await connection.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
    finally:
        await connection.close()


async def sql(statement: str, *args: Any) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(DATABASE)
    try:
        return await connection.fetch(statement, *args)
    finally:
        await connection.close()


async def capacity(method: str) -> dict:
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        return (await client.get(f"http://127.0.0.1:{METHOD_PORTS[method]}/capacity")).json()


async def job_status(method: str, job_id: str) -> Optional[dict]:
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.get(f"http://127.0.0.1:{METHOD_PORTS[method]}/jobs/{job_id}/status")
    return response.json() if response.status_code == 200 else None


# --------------------------------------------------------------------------- #
# The stack
# --------------------------------------------------------------------------- #
class Stack:
    """The ``phylo-tests`` compose project, as the system tests start it."""

    def __init__(self, scratch: Path):
        self.scratch = scratch
        self.changed: set[str] = set()

    def compose(self, *args: str, files: Optional[list[str]] = None, check: bool = True, timeout: float = 600) -> str:
        command = ["docker", "compose"]
        for name in files or BASE_FILES:
            command += ["-f", name]
        done = subprocess.run([*command, "--profile", "full", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        if check and done.returncode != 0:
            raise AssertionError(f"docker compose {' '.join(args)} failed:\n{done.stdout[-1500:]}\n{done.stderr[-1500:]}")
        return done.stdout

    def container(self, service: str) -> str:
        ids = self.compose("ps", "-a", "-q", service).split()
        assert ids, f"no container for {service}"
        return ids[0]

    def inspect(self, service: str) -> dict:
        raw = subprocess.run(["docker", "inspect", self.container(service)], capture_output=True, text=True, check=True).stdout
        return json.loads(raw)[0]

    def state(self, service: str) -> dict:
        info = self.inspect(service)
        return {"status": info["State"]["Status"], "restarts": info["RestartCount"], "started": info["State"]["StartedAt"],
                "oom_killed": info["State"].get("OOMKilled"), "exit_code": info["State"]["ExitCode"]}

    def exec(self, service: str, *command: str, check: bool = True) -> str:
        done = subprocess.run(["docker", "exec", self.container(service), *command], capture_output=True, text=True, timeout=120)
        if check and done.returncode != 0:
            raise AssertionError(f"exec in {service} failed ({done.returncode}): {done.stderr[-500:]}")
        return done.stdout

    def processes(self, service: str) -> list[dict]:
        """pid, parent, resident memory (MiB) and command line of every process in the container."""
        out = self.exec(service, "ps", "-eo", "pid,ppid,rss,args", "--no-headers")
        rows = []
        for line in out.splitlines():
            pid, ppid, rss, args = line.split(None, 3)
            rows.append({"pid": int(pid), "ppid": int(ppid), "rss_mb": int(rss) // 1024, "args": args})
        return rows

    def memory_events(self, service: str) -> dict[str, int]:
        out = self.exec(service, "cat", "/sys/fs/cgroup/memory.events")
        return {key: int(value) for key, value in (line.split() for line in out.splitlines())}

    def cpu_percent(self, service: str) -> float:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}", self.container(service)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out.rstrip("%") or 0)

    def crash(self, service: str) -> None:
        """Make the service die the way a crash does: its main process is
        killed from inside, the container exits with an error, and Docker's
        restart policy applies. (``docker kill`` would not do: Docker treats it
        as a deliberate stop and does not restart the container.)"""
        children = [p for p in self.processes(service) if p["ppid"] == 1]
        target = max(children, key=lambda p: p["rss_mb"])["pid"] if children else 1
        self.exec(service, "kill", "-9", str(target))

    def stop(self, service: str) -> None:
        self.compose("stop", "-t", "5", service)

    def start(self, service: str) -> None:
        self.compose("start", service)

    def restart(self, service: str) -> None:
        self.compose("restart", "-t", "5", service)

    def logs(self, service: str, tail: int = 200) -> str:
        return self.compose("logs", "--no-color", "--tail", str(tail), service, check=False)

    # -- configuration ------------------------------------------------------- #
    def reconfigure(self, service: str, *, environment: Optional[dict[str, str]] = None, **settings: Any) -> None:
        """Recreate one service with extra environment variables and/or compose
        settings (``mem_limit="900m"`` ...). Undone by :meth:`restore`."""
        override = {"services": {service: {**settings, **({"environment": environment} if environment else {})}}}
        path = self.scratch / f"override-{service}.yml"
        path.write_text(yaml.safe_dump(override))
        self.compose("up", "-d", "--no-deps", "--force-recreate", service, files=[*BASE_FILES, str(path)])
        self.changed.add(service)

    def restore(self) -> None:
        """Put every reconfigured service back the way the suite started it."""
        for service in sorted(self.changed):
            self.compose("up", "-d", "--no-deps", "--force-recreate", service)
        self.changed.clear()

    async def ready(self, *services: str, seconds: float = 240) -> None:
        """Wait until the given services answer (methods: their capacity
        report; api: its health endpoint; worker: its container is running)."""
        for service in services:
            if service in METHOD_PORTS:
                async def answering(name=service):
                    return (await capacity(name)).get("ok")
                await eventually(answering, seconds, f"{service} to answer")
            elif service == "api":
                async def healthy():
                    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                        return (await client.get(f"{API}/health")).status_code == 200
                await eventually(healthy, seconds, "the API to answer")
            else:
                async def running(name=service):
                    return self.state(name)["status"] == "running"
                await eventually(running, seconds, f"{service} to run")
