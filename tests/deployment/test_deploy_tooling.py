"""Deployment tooling: internal ports, the pre-start and post-start checks, run.sh.

The scripts are run for real, in a throwaway copy of the files they need, with
a stand-in ``docker`` command on the PATH that records what it is asked and
answers as told. Nothing here talks to a Docker daemon, except the one test
that asks ``docker compose config`` to render the compose file (no daemon
needed for that either).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_TEXT = (ROOT / "docker-compose.yml").read_text()
COMPOSE = yaml.safe_load(COMPOSE_TEXT)
SERVICES = COMPOSE["services"]
METHODS = {"dowser": 8001, "gctree": 8002, "brepphylo": 8003, "clonaltree": 8004}
PORT_VARIABLES = {
    "PHYLO_PORT_POSTGRES": 5432, "PHYLO_PORT_MINIO": 9000, "PHYLO_PORT_MINIO_CONSOLE": 9001,
    "PHYLO_PORT_API": 8000, "PHYLO_PORT_WEB": 3000,
    **{f"METHOD_{name.upper()}_CONTAINER_PORT": port for name, port in METHODS.items()},
}
PROD_SERVICES = ["api-prod", "api-worker-prod", "brepphylo", "clonaltree", "dowser", "gctree", "minio",
                 "minio-init", "postgres", "web-prod"]
SYSTEM_PATH = "/usr/bin:/bin"          # sh, awk, sed, od, env; no node (docker: see run())

STUB_DOCKER = r"""#!/bin/sh
# Stand-in for docker: records each call, answers from the environment.
echo "$*" >> "$STUB_DIR/calls.log"
args=" $* "
case "$args" in
  " info ") exit "${STUB_INFO_EXIT:-0}" ;;
  " compose version --short ") echo "${STUB_COMPOSE_VERSION-2.24.5}"; exit 0 ;;
  *" config --quiet "*) [ -z "${STUB_CONFIG_ERR:-}" ] || { echo "$STUB_CONFIG_ERR" >&2; exit 1; }; exit 0 ;;
  *" config --services "*) cat "$STUB_DIR/services"; exit 0 ;;
  " network inspect "*) exit "${STUB_NETWORK_EXIT:-0}" ;;
  " volume inspect "*) exit "${STUB_VOLUME_EXIT:-1}" ;;
  *" ps -a -q "*) svc="${args% }"; svc="${svc##* }"; [ -f "$STUB_DIR/absent-$svc" ] || echo "id-$svc"; exit 0 ;;
  " inspect -f "*) id="${args% }"; id="${id##* }"; svc="${id#id-}"
     if [ -f "$STUB_DIR/state-$svc" ]; then cat "$STUB_DIR/state-$svc"
     elif [ "$svc" = "minio-init" ]; then echo "exited|none|0|0"
     else echo "running|healthy|0|0"; fi; exit 0 ;;
  *" exec -T api-prod python -m apps.api.scripts.deploy_check "*) cat "$STUB_DIR/inside"; exit "${STUB_INSIDE_EXIT:-0}" ;;
esac
exit 0
"""
INSIDE_OK = """  OK    configuration        production settings accepted
  OK    database             reachable
  OK    migrations           at 016_result_retention
  OK    object storage       datasets=phylo-datasets, artifacts=phylo-artifacts
  OK    method services      brepphylo (1 job slot), clonaltree (1 job slot), dowser (1 job slot), gctree (1 job slot)
  OK    version information  v2.1.0 (commit 928f1b58f834, built 2026-10-13T08:30:05.123Z)
  WARN  email                switched off (SMTP_HOST is empty): no notification or confirmation email is sent
"""


class Deployment:
    """A copy of what the scripts need, plus the stand-in docker."""

    def __init__(self, tmp_path: Path):
        self.repo = tmp_path / "repo"
        self.stub = tmp_path / "stub"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / ".git").mkdir()
        (self.repo / ".git/HEAD").write_text("ref: refs/heads/main\n")
        (self.repo / "config/no-git").mkdir(parents=True)
        for name in ("run.sh", "docker-compose.yml"):
            shutil.copy(ROOT / name, self.repo / name)
        for name in ("ports.sh", "deploy-check.sh", "resource-plan.sh"):
            shutil.copy(ROOT / "scripts" / name, self.repo / "scripts" / name)
        self.env_file = self.repo / ".env"
        shutil.copy(ROOT / ".env.example", self.env_file)
        (self.stub / "bin").mkdir(parents=True)
        docker = self.stub / "bin/docker"
        docker.write_text(STUB_DOCKER)
        docker.chmod(0o755)
        (self.stub / "services").write_text("\n".join(PROD_SERVICES) + "\n")
        (self.stub / "inside").write_text(INSIDE_OK)

    def system_path_without_docker(self) -> str:
        """SYSTEM_PATH with any real docker left out: Linux installs it in
        /usr/bin itself (GitHub runners do), so that PATH alone does not hide it."""
        hidden = self.stub / "no-docker-bin"
        if not hidden.exists():
            hidden.mkdir()
            for directory in SYSTEM_PATH.split(":"):
                for tool in Path(directory).iterdir():
                    link = hidden / tool.name
                    if not tool.name.startswith("docker") and not os.path.lexists(link):
                        link.symlink_to(tool)
        return str(hidden)

    def run(self, *command: str, docker: bool = True, **env: str) -> subprocess.CompletedProcess:
        path = f"{self.stub / 'bin'}:{SYSTEM_PATH}" if docker else self.system_path_without_docker()
        (self.stub / "calls.log").write_text("")
        return subprocess.run(list(command), cwd=self.repo, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              env={"PATH": path, "STUB_DIR": str(self.stub), "HOME": str(self.stub), **env})

    def check(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return self.run("sh", "scripts/deploy-check.sh", *args, **env)

    def ports(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return self.run("sh", "scripts/ports.sh", *args, **env)

    def calls(self) -> list[str]:
        return (self.stub / "calls.log").read_text().splitlines()

    def set(self, **values: str) -> None:
        with self.env_file.open("a") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")

    def value(self, key: str) -> str | None:
        found = None
        for line in self.env_file.read_text().splitlines():
            if line.startswith(f"{key}="):
                found = line.split("=", 1)[1]
        return found


@pytest.fixture
def deployment(tmp_path) -> Deployment:
    return Deployment(tmp_path)


# --------------------------------------------------------------------------- #
# docker-compose.yml: one variable per port
# --------------------------------------------------------------------------- #
def test_no_port_number_is_written_into_the_compose_file_except_as_a_default():
    """Every internal port appears only as ``${VARIABLE:-default}``."""
    without_comments = "\n".join(line for line in COMPOSE_TEXT.splitlines() if not line.lstrip().startswith("#"))
    for variable, default in PORT_VARIABLES.items():
        uses = re.findall(rf"\$\{{{variable}:-(\d+)\}}", without_comments)
        assert uses and set(uses) == {str(default)}, (variable, uses)       # same default wherever it is used
        stripped = without_comments.replace(f"${{{variable}:-{default}}}", "")
        # What is left of the number may only be host-side: the public URLs
        # users type (http://localhost:3000 / :8000) and the host ports the
        # development services publish (API_PORT, WEB_PORT). Neither is an
        # internal port.
        left = [m.group(0) for m in re.finditer(rf".{{0,24}}(?<![0-9]){default}(?![0-9]).{{0,4}}", stripped)]
        host_side = ("localhost", "${API_PORT:-", "${WEB_PORT:-")
        assert all(any(mark in snippet for mark in host_side) for snippet in left), (variable, left)


def test_every_place_that_needs_a_port_uses_its_variable():
    env = COMPOSE["x-api-common-env"]
    assert env["POSTGRES_PORT"] == "${PHYLO_PORT_POSTGRES:-5432}"
    assert SERVICES["postgres"]["environment"]["PGPORT"] == "${PHYLO_PORT_POSTGRES:-5432}"
    # Through the environment, not flags: the object store image's built-in
    # health check reads MINIO_ADDRESS, and probed port 9000 regardless of a flag.
    store = SERVICES["minio"]
    assert store["command"] == "server /data" and "healthcheck" not in store
    assert store["environment"]["MINIO_ADDRESS"] == ":${PHYLO_PORT_MINIO:-9000}"
    assert store["environment"]["MINIO_CONSOLE_ADDRESS"] == ":${PHYLO_PORT_MINIO_CONSOLE:-9001}"
    for name in ("api", "api-prod"):
        assert "--port ${PHYLO_PORT_API:-8000}" in SERVICES[name]["command"]
    assert "http://127.0.0.1:${PHYLO_PORT_API:-8000}/health" in SERVICES["api-prod"]["healthcheck"]["test"]
    assert SERVICES["web-prod"]["environment"]["PORT"] == "${PHYLO_PORT_WEB:-3000}"
    assert "127.0.0.1:${PHYLO_PORT_WEB:-3000}/" in " ".join(SERVICES["web-prod"]["healthcheck"]["test"])
    # The development services publish a host port onto the same internal port they listen on.
    assert SERVICES["api"]["ports"] == ["${API_PORT:-8000}:${PHYLO_PORT_API:-8000}"]
    assert SERVICES["web"]["ports"] == ["${WEB_PORT:-3000}:${PHYLO_PORT_WEB:-3000}"]
    assert "-p ${PHYLO_PORT_WEB:-3000}" in SERVICES["web"]["command"]
    for name, port in METHODS.items():
        variable = f"METHOD_{name.upper()}_CONTAINER_PORT"
        assert env[f"METHOD_{name.upper()}_URL"] == (
            f"${{METHOD_{name.upper()}_URL_DOCKER:-http://phylo-{name}:${{{variable}:-{port}}}}}")
        assert variable in str(SERVICES[name]["command"])


def test_compose_defaults_agree_with_the_method_service_registry_and_the_ports_tool():
    """Production no longer runs the Node step that copied these into .env."""
    registry = {s["id"]: s for s in json.loads((ROOT / "config/method-services.json").read_text())["services"]}
    for name, port in METHODS.items():
        assert registry[name]["containerPort"] == port and registry[name]["composeHost"] == f"phylo-{name}"
    table = dict(re.findall(r"^[a-z-]+:([A-Z_]+):(\d+):[01]$", (ROOT / "scripts/ports.sh").read_text(), re.MULTILINE))
    assert {k: int(v) for k, v in table.items()} == PORT_VARIABLES


def test_storage_directories_are_created_on_a_fresh_checkout():
    """runtime/ is not in the repository; the first start must not fail on it."""
    binds = [v for service in SERVICES.values() for v in service.get("volumes", [])
             if isinstance(v, dict) and v.get("target") == "/runtime/storage"]
    assert len(binds) == 8 and all(v["bind"] == {"create_host_path": True} for v in binds)


@pytest.mark.parametrize("name", ["api", "api-worker", "api-prod", "api-worker-prod"])
def test_api_and_worker_are_built_the_same_way_with_git_information(name):
    assert SERVICES[name]["build"] == {
        "context": ".", "dockerfile": "apps/api/Dockerfile",
        "additional_contexts": {"gitmeta": "${PHYLO_GIT_DIR:-./.git}"},
    }
    # Version information is part of the image: nothing has to exist on the host.
    assert not any("version-info" in str(v) for v in SERVICES[name].get("volumes", []))
    test_stack = yaml.safe_load((ROOT / "docker-compose.test.yml").read_text())
    assert test_stack["services"]["api"]["build"]["additional_contexts"] == {"gitmeta": "${PHYLO_GIT_DIR:-./.git}"}


def test_other_ports_reach_every_url_command_and_health_check(tmp_path):
    """Rendered by Compose itself with nine non-default ports."""
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    shutil.copy(ROOT / "docker-compose.yml", tmp_path / "docker-compose.yml")
    env_lines = [line for line in (ROOT / ".env.example").read_text().splitlines()
                 if not re.match(r"(S3_ENDPOINT_URL_DOCKER|METHOD_[A-Z]+_(URL_DOCKER|CONTAINER_PORT))=", line)]
    chosen = {variable: 21000 + index for index, variable in enumerate(sorted(PORT_VARIABLES))}
    (tmp_path / ".env").write_text("\n".join(env_lines + [f"{k}={v}" for k, v in chosen.items()]) + "\n")
    # The developer's own exported settings must not leak into the rendering.
    clean = {k: v for k, v in os.environ.items() if not re.match(r"(PHYLO_|METHOD_|S3_|POSTGRES_|MINIO_|COMPOSE_)", k)}
    done = subprocess.run(["docker", "compose", "--profile", "prod", "config", "--format", "json"], cwd=tmp_path,
                          capture_output=True, text=True, env=clean)
    assert done.returncode == 0, done.stderr
    rendered = json.loads(done.stdout)["services"]
    api = rendered["api-prod"]["environment"]
    port = lambda variable: str(chosen[variable])       # noqa: E731

    assert f"@phylo-postgres:{port('PHYLO_PORT_POSTGRES')}/" in api["DATABASE_URL"]
    assert api["POSTGRES_PORT"] == rendered["postgres"]["environment"]["PGPORT"] == port("PHYLO_PORT_POSTGRES")
    store = f"http://phylo-minio:{port('PHYLO_PORT_MINIO')}"
    assert api["S3_ENDPOINT_URL"] == rendered["api-worker-prod"]["environment"]["S3_ENDPOINT_URL"] == store
    assert store in " ".join(rendered["minio-init"]["entrypoint"])
    assert rendered["minio"]["environment"]["MINIO_ADDRESS"] == f":{port('PHYLO_PORT_MINIO')}"
    assert rendered["minio"]["environment"]["MINIO_CONSOLE_ADDRESS"] == f":{port('PHYLO_PORT_MINIO_CONSOLE')}"
    assert f"--port {port('PHYLO_PORT_API')}" in " ".join(rendered["api-prod"]["command"])
    assert f"http://127.0.0.1:{port('PHYLO_PORT_API')}/health" in rendered["api-prod"]["healthcheck"]["test"]
    assert rendered["web-prod"]["environment"]["PORT"] == port("PHYLO_PORT_WEB")
    assert f"127.0.0.1:{port('PHYLO_PORT_WEB')}/" in " ".join(rendered["web-prod"]["healthcheck"]["test"])
    for name in METHODS:
        variable = f"METHOD_{name.upper()}_CONTAINER_PORT"
        assert rendered[name]["environment"]["S3_ENDPOINT_URL"] == store
        assert rendered[name]["environment"][variable] == port(variable)
        # The Python services get the port on their command line; the R
        # services read the same variable from their environment when they start.
        command = " ".join(rendered[name]["command"])
        assert port(variable) in command or f"Sys.getenv('{variable}')" in command
        for service in ("api-prod", "api-worker-prod"):
            assert rendered[service]["environment"][f"METHOD_{name.upper()}_URL"] == f"http://phylo-{name}:{port(variable)}"
    # Nothing still points at a default port, and production publishes none.
    text = json.dumps({name: rendered[name] for name in PROD_SERVICES})
    for default in PORT_VARIABLES.values():
        leftovers = re.findall(rf"[a-z0-9.-]+:{default}(?![0-9])", text)
        assert all(item.startswith("localhost:") for item in leftovers), (default, leftovers)
    assert not any("ports" in rendered[name] for name in PROD_SERVICES)


# --------------------------------------------------------------------------- #
# scripts/ports.sh
# --------------------------------------------------------------------------- #
def test_the_documented_configuration_has_consistent_default_ports(deployment):
    shown = deployment.ports()
    assert shown.returncode == 0, shown.stderr
    for variable, default in PORT_VARIABLES.items():
        assert re.search(rf"{variable}\s+{default}\b", shown.stdout), variable
    assert shown.stdout.count("the reverse proxy connects here") == 2 and "ports: consistent." in shown.stdout


def test_a_value_from_the_shell_wins_as_it_does_for_compose(deployment):
    deployment.set(PHYLO_PORT_API="18000")
    assert re.search(r"PHYLO_PORT_API\s+18000\s+\(default 8000\)", deployment.ports().stdout)
    assert re.search(r"PHYLO_PORT_API\s+19000", deployment.ports(PHYLO_PORT_API="19000").stdout)


@pytest.mark.parametrize("values,complaint", [
    ({"PHYLO_PORT_API": "eight-thousand"}, "PHYLO_PORT_API=eight-thousand is not a port number"),
    ({"PHYLO_PORT_WEB": "80"}, "PHYLO_PORT_WEB=80 is outside 1024-65535"),
    ({"PHYLO_PORT_POSTGRES": "70000"}, "PHYLO_PORT_POSTGRES=70000 is outside 1024-65535"),
    ({"PHYLO_PORT_MINIO_CONSOLE": "9000"}, "needs two different ports"),
    ({"PHYLO_PORT_MINIO": "9500"}, "S3_ENDPOINT_URL_DOCKER uses port 9000 but PHYLO_PORT_MINIO is 9500"),
    ({"METHOD_GCTREE_CONTAINER_PORT": "8102"}, "METHOD_GCTREE_URL_DOCKER uses port 8002 but METHOD_GCTREE_CONTAINER_PORT is 8102"),
    ({"METHOD_DOWSER_URL_DOCKER": "http://phylo-dowser:9999"}, "METHOD_DOWSER_URL_DOCKER uses port 9999"),
])
def test_a_port_that_cannot_work_is_refused_by_name(deployment, values, complaint):
    deployment.set(**values)
    checked = deployment.ports("check")
    assert checked.returncode == 1 and complaint in checked.stderr


def test_random_ports_are_written_once_and_then_kept(deployment):
    deployment.env_file.chmod(0o600)
    before = deployment.env_file.read_text().splitlines()
    done = deployment.ports("randomize")
    assert done.returncode == 0, done.stderr
    internal = [v for v in PORT_VARIABLES if v not in ("PHYLO_PORT_API", "PHYLO_PORT_WEB")]
    ports = {variable: int(deployment.value(variable)) for variable in internal}
    assert len(set(ports.values())) == 7 and all(20000 <= p <= 39999 for p in ports.values())
    # The two ports the reverse proxy uses are left alone unless asked for.
    assert deployment.value("PHYLO_PORT_API") is None and deployment.value("PHYLO_PORT_WEB") is None
    assert "reverse proxy must now" not in done.stdout
    # URLs some env files spell out follow their port.
    assert deployment.value("S3_ENDPOINT_URL_DOCKER") == f"http://phylo-minio:{ports['PHYLO_PORT_MINIO']}"
    for name in METHODS:
        assert deployment.value(f"METHOD_{name.upper()}_URL_DOCKER") == (
            f"http://phylo-{name}:{ports[f'METHOD_{name.upper()}_CONTAINER_PORT']}")
    # Nothing else in the file changed: earlier assignments are commented out, not lost.
    after = deployment.env_file.read_text().splitlines()
    body = after[:after.index("# >>> internal ports (generated by scripts/ports.sh randomize) >>>")]
    restored = [line.replace("# (replaced by scripts/ports.sh) ", "") for line in body]
    while restored and not restored[-1].strip():
        restored.pop()
    assert restored == before
    assert stat.S_IMODE(deployment.env_file.stat().st_mode) == 0o600        # still private
    assert deployment.ports("check").returncode == 0

    stored = deployment.env_file.read_text()
    again = deployment.ports("randomize")
    assert again.returncode == 0 and "they are kept" in again.stderr
    assert deployment.env_file.read_text() == stored                        # stable: a restart keeps its ports

    forced = deployment.ports("randomize", "--force", "--all")
    assert forced.returncode == 0 and deployment.env_file.read_text() != stored
    assert deployment.env_file.read_text().count(">>> internal ports") == 1
    api, web = deployment.value("PHYLO_PORT_API"), deployment.value("PHYLO_PORT_WEB")
    assert api and web and f"phylo-api-prod:{api}" in forced.stdout and f"phylo-web-prod:{web}" in forced.stdout
    assert deployment.ports("check").returncode == 0


def test_randomize_needs_an_env_file_and_rejects_unknown_arguments(deployment):
    assert deployment.ports("--bogus").returncode == 1
    deployment.env_file.unlink()
    missing = deployment.ports("randomize")
    assert missing.returncode == 1 and "copy .env.example to .env first" in missing.stderr


# --------------------------------------------------------------------------- #
# scripts/deploy-check.sh: before starting
# --------------------------------------------------------------------------- #
def test_a_usable_configuration_is_ready_and_the_check_changes_nothing(deployment):
    deployment.set(POSTGRES_PASSWORD="Zx-distinct-db-secret-91", JWT_SECRET_KEY="Zx-distinct-jwt-secret-91-abcdefghijklmnop")
    before = deployment.env_file.read_bytes()
    done = deployment.check()
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("  OK    ") == 9 and "FAIL" not in done.stdout
    assert "Ready to start (0 warning(s)):  docker compose --profile prod up -d --build" in done.stdout
    assert "volume phylo_postgres_data does not exist yet: it will be created empty (fresh installation)" in done.stdout
    assert deployment.env_file.read_bytes() == before
    assert "Zx-distinct" not in done.stdout + done.stderr                   # no secret is echoed
    # Only questions were asked of Docker.
    verbs = {re.sub(r"^compose --env-file \S+ --profile prod ", "compose ", call).split(" --")[0].rsplit(" ", 1)[0]
             if call.startswith(("network", "volume")) else re.sub(r"^compose --env-file \S+ --profile prod ", "compose ", call)
             for call in deployment.calls()}
    assert verbs == {"info", "compose version --short", "compose config --quiet", "network inspect", "volume inspect"}


def test_existing_volumes_are_reported_as_kept(deployment):
    done = deployment.check(STUB_VOLUME_EXIT="0")
    assert "volume phylo_minio_data exists: its data will be used as it is" in done.stdout and done.returncode == 0


@pytest.mark.parametrize("env,expected", [
    ({"STUB_INFO_EXIT": "1"}, "the Docker daemon does not answer"),
    ({"STUB_COMPOSE_VERSION": ""}, "Docker Compose v2 is not installed"),
    ({"STUB_COMPOSE_VERSION": "2.16.0"}, "Docker Compose 2.16.0 is too old: 2.17 or newer is needed"),
    ({"STUB_COMPOSE_VERSION": "1.29.2"}, "is too old"),
    ({"STUB_CONFIG_ERR": "required variable JWT_SECRET_KEY is missing a value: set JWT_SECRET_KEY in .env"},
     "required variable JWT_SECRET_KEY is missing a value"),
    ({"STUB_NETWORK_EXIT": "1"}, "the reverse-proxy network 'proxy_net' does not exist"),
])
def test_what_would_stop_the_start_is_named(deployment, env, expected):
    done = deployment.check(**env)
    assert done.returncode == 1 and expected in done.stdout and "problem(s) to fix" in done.stdout
    assert "Ready to start" not in done.stdout


@pytest.mark.parametrize("version", ["2.17.0", "v2.20.3", "5.3.1", "2.24.5-desktop.1"])
def test_supported_compose_versions_are_accepted(deployment, version):
    assert deployment.check(STUB_COMPOSE_VERSION=version).returncode == 0


def test_without_docker_or_configuration_the_check_says_so_and_stops(deployment):
    no_docker = deployment.run("sh", "scripts/deploy-check.sh", docker=False)
    assert no_docker.returncode == 1 and "Docker is not installed" in no_docker.stdout
    deployment.env_file.unlink()
    no_env = deployment.check()
    assert no_env.returncode == 1 and "cp .env.example .env" in no_env.stdout
    assert not any("config" in call for call in deployment.calls())          # nothing further was attempted


def test_git_information_missing_unreadable_or_deliberately_absent(deployment):
    shutil.rmtree(deployment.repo / ".git")
    missing = deployment.check()
    assert missing.returncode == 1 and "./.git does not exist" in missing.stdout
    assert "PHYLO_GIT_DIR=config/no-git" in missing.stdout
    (deployment.repo / ".git").write_text("gitdir: /somewhere/else\n")       # a git worktree
    worktree = deployment.check()
    assert worktree.returncode == 1 and "is a file, not a directory" in worktree.stdout
    deployment.set(PHYLO_GIT_DIR="config/no-git")
    chosen = deployment.check()
    assert chosen.returncode == 0 and "WARN  config/no-git holds no git data" in chosen.stdout
    assert "Ready to start (1 warning(s))" in chosen.stdout


def test_a_resource_budget_must_be_stored_before_plain_compose_can_honour_it(deployment):
    deployment.set(PHYLO_CPU_BUDGET="8", PHYLO_MEMORY_BUDGET_MB="16384")
    unstored = deployment.check()
    assert unstored.returncode == 1 and "its container limits are not stored" in unstored.stdout
    assert "sh scripts/resource-plan.sh --write" in unstored.stdout
    assert deployment.run("sh", "scripts/resource-plan.sh", "--write").returncode == 0
    stored = deployment.check()
    assert stored.returncode == 0 and "container limits in the env file match the resource budget" in stored.stdout
    deployment.set(PHYLO_CPU_BUDGET="6")                                     # budget changed, plan not rewritten
    stale = deployment.check()
    assert stale.returncode == 1 and "belong to a different resource budget" in stale.stdout


def test_inconsistent_ports_stop_the_start(deployment):
    deployment.set(PHYLO_PORT_MINIO="9500")
    done = deployment.check()
    assert done.returncode == 1 and "S3_ENDPOINT_URL_DOCKER uses port 9000 but PHYLO_PORT_MINIO is 9500" in done.stdout


# --------------------------------------------------------------------------- #
# scripts/deploy-check.sh --running: after starting
# --------------------------------------------------------------------------- #
def test_a_complete_deployment_is_reported_with_its_warnings(deployment):
    done = deployment.check("--running")
    assert done.returncode == 0, done.stdout + done.stderr
    for service in PROD_SERVICES:
        assert f"{service}: " in done.stdout
    assert "minio-init: finished successfully (buckets and storage user created)" in done.stdout
    assert "migrations           at 016_result_retention" in done.stdout    # the in-container check is passed on
    assert "The deployment is complete (1 warning(s))." in done.stdout      # email is off: a warning, not a failure
    assert any("exec -T api-prod python -m apps.api.scripts.deploy_check" in call for call in deployment.calls())


@pytest.mark.parametrize("service,state,expected", [
    ("api-worker-prod", "exited|none|1|0", "FAIL  api-worker-prod: exited"),
    ("web-prod", "running|unhealthy|0|0", "FAIL  web-prod: running but unhealthy"),
    ("minio-init", "exited|none|1|0", "FAIL  minio-init: ended with exit code 1"),
    ("dowser", "restarting|none|137|4", "FAIL  dowser: restarting"),
])
def test_a_container_that_is_not_well_fails_the_check(deployment, service, state, expected):
    (deployment.stub / f"state-{service}").write_text(state + "\n")
    done = deployment.check("--running")
    assert done.returncode == 1 and expected in done.stdout and "problem(s) to fix" in done.stdout


def test_restarts_and_slow_starts_are_warnings(deployment):
    (deployment.stub / "state-gctree").write_text("running|none|0|3\n")
    (deployment.stub / "state-api-prod").write_text("running|starting|0|0\n")
    done = deployment.check("--running")
    assert done.returncode == 0
    assert "WARN  gctree: running, restarted 3 time(s)" in done.stdout and "WARN  api-prod: still starting" in done.stdout


def test_a_service_without_a_container_and_a_failed_inner_check(deployment):
    (deployment.stub / "absent-clonaltree").write_text("")
    (deployment.stub / "inside").write_text(INSIDE_OK.replace(
        "  OK    migrations           at 016_result_retention",
        "  FAIL  migrations           database is at 015_auth_abuse_prevention, this image expects 016_result_retention"))
    done = deployment.check("--running", STUB_INSIDE_EXIT="1")
    assert done.returncode == 1
    assert "FAIL  clonaltree: no container" in done.stdout
    assert "FAIL  migrations           database is at 015_auth_abuse_prevention" in done.stdout
    assert "2 problem(s) to fix, 1 warning(s)." in done.stdout


def test_an_inner_check_that_could_not_run_is_a_failure_not_silence(deployment):
    (deployment.stub / "inside").write_text('service "api-prod" is not running\n')
    done = deployment.check("--running", STUB_INSIDE_EXIT="1")
    assert done.returncode == 1 and "the check inside the API container did not run" in done.stdout
    assert 'service "api-prod" is not running' in done.stdout


# --------------------------------------------------------------------------- #
# run.sh: a thin wrapper, no Node
# --------------------------------------------------------------------------- #
UP = "compose --profile prod up -d"


def test_prod_ends_in_the_documented_compose_command_without_node(deployment):
    assert shutil.which("node", path=f"{deployment.stub / 'bin'}:{SYSTEM_PATH}") is None
    done = deployment.run("bash", "run.sh", "prod")
    assert done.returncode == 0, done.stdout + done.stderr
    assert deployment.calls()[-1] == f"{UP} --build"
    assert "Ready to start" in done.stdout                                  # the pre-start check ran first
    assert "# >>> resource plan" in deployment.env_file.read_text()          # limits for the budget are stored
    # The only compose command that changes anything is that one.
    changing = [c for c in deployment.calls() if re.search(r"\b(up|down|rm|build|run|start|stop|restart|pull)\b", c)]
    assert changing == [f"{UP} --build"]


@pytest.mark.parametrize("args,expected", [
    (["--no-build"], UP),
    (["--pull", "always"], f"{UP} --build --pull always"),
    (["--no-build", "--force-recreate"], f"{UP} --force-recreate"),
])
def test_prod_passes_extra_arguments_on(deployment, args, expected):
    assert deployment.run("bash", "run.sh", "prod", *args).returncode == 0
    assert deployment.calls()[-1] == expected


def test_prod_does_not_start_anything_when_the_check_fails(deployment):
    done = deployment.run("bash", "run.sh", "prod", STUB_NETWORK_EXIT="1")
    assert done.returncode == 1 and "Not started." in done.stderr
    assert not any(" up " in f" {call} " for call in deployment.calls())
    deployment.env_file.unlink()
    no_env = deployment.run("bash", "run.sh", "prod")
    assert no_env.returncode == 1 and "cp .env.example .env" in no_env.stderr and deployment.calls() == []


def test_the_other_commands(deployment):
    before = deployment.env_file.read_bytes()
    check = deployment.run("bash", "run.sh", "check")
    assert check.returncode == 0 and "Before starting:" in check.stdout
    assert deployment.env_file.read_bytes() == before                       # `check` never writes
    status = deployment.run("bash", "run.sh", "status")
    assert status.returncode == 0 and "The deployment is complete" in status.stdout
    ports = deployment.run("bash", "run.sh", "ports", "check")
    assert ports.returncode == 0 and "ports: consistent." in ports.stdout
    down = deployment.run("bash", "run.sh", "down")
    assert down.returncode == 0 and deployment.calls() == ["compose --profile prod down"]   # volumes are never removed
    usage = deployment.run("bash", "run.sh", "help")
    assert usage.returncode == 0 and "./run.sh prod" in usage.stdout and deployment.calls() == []
    unknown = deployment.run("bash", "run.sh", "deploy-everything")
    assert unknown.returncode == 1 and "Unknown command" in unknown.stderr and deployment.calls() == []


def test_the_text_menu_offers_production_without_node(deployment):
    done = subprocess.run(["bash", "run.sh"], cwd=deployment.repo, input="3\n", capture_output=True, text=True,
                          env={"PATH": f"{deployment.stub / 'bin'}:{SYSTEM_PATH}", "STUB_DIR": str(deployment.stub),
                               "HOME": str(deployment.stub)})
    assert done.returncode == 0, done.stderr
    assert "3) Prod - docker compose" in done.stdout
    assert (deployment.stub / "calls.log").read_text().splitlines()[-1] == f"{UP} --build"


def test_there_is_one_implementation_of_the_production_path():
    menu = (ROOT / "scripts/select-mode.mjs").read_text()
    assert 'run(path.join(ROOT, "run.sh"), ["prod"])' in menu
    assert "sync-env" not in menu and '"compose"' not in menu
    package = json.loads((ROOT / "package.json").read_text())["scripts"]
    assert package["phylo:prod"] == "./run.sh prod"
    runner = (ROOT / "run.sh").read_text()
    assert "sync-env" not in runner and runner.count("docker compose --profile prod up -d") == 2   # usage text + the call
    for script in ("ports.sh", "deploy-check.sh", "resource-plan.sh"):
        text = (ROOT / "scripts" / script).read_text()
        assert text.startswith("#!/bin/sh") and "node " not in text and "python" not in text.replace("api-prod python -m", "")


# --------------------------------------------------------------------------- #
# What the administrator is told
# --------------------------------------------------------------------------- #
def test_documented_ports_are_the_defaults_and_stay_commented_out():
    example = (ROOT / ".env.example").read_text()
    for variable, default in PORT_VARIABLES.items():
        if variable.startswith("METHOD_"):
            assert f"\n{variable}={default}\n" in example                    # generated block, already present
        else:
            assert f"\n# {variable}={default}\n" in example, variable        # a default: nothing to set
    assert "\n# PHYLO_GIT_DIR=config/no-git\n" in example
    # The example configuration itself passes the port check (see the ports tests above).


def test_the_guide_describes_the_one_command_start_and_its_consequences():
    guide = (ROOT / "docs/DEPLOYMENT.md").read_text()
    for needed in ("### Starting and checking a deployment", "docker compose --profile prod up -d --build",
                   "./run.sh check", "./run.sh status", "no Node", "### Version information", "PHYLO_GIT_DIR=config/no-git",
                   "### Internal ports", "its configuration must change", "Compose 2.17"):
        assert needed in guide, needed
    for variable, default in PORT_VARIABLES.items():
        if not variable.startswith("METHOD_"):
            assert f"| `{variable}` | `{default}` |" in guide
    # Steps that no longer exist are not described as required.
    production = guide[guide.index("## Server / production deployment"):]
    assert "npm run" not in production and "version:capture" not in guide
    # The manual backup commands follow the configured port: they take the
    # store's address from the running API container instead of assuming one.
    assert "val S3_ENDPOINT_URL" in guide and "phylo-minio:9000\"" not in guide
