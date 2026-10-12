"""Shared-server rules in docker-compose.yml, checked on the file itself.

Parsed as YAML (no Docker needed, no .env needed): every assertion is about what
the compose file declares. The matching runtime behaviour (limits visible in
`docker inspect`, no route to the internet, restart after a crash) is verified
on a live stack and recorded in docs/DEPLOYMENT.md.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
DEV = yaml.safe_load((ROOT / "docker-compose.dev.yml").read_text())
SERVICES: dict[str, dict] = COMPOSE["services"]

METHODS = ["dowser", "gctree", "brepphylo", "clonaltree"]
R_METHODS = ["dowser", "brepphylo"]
DEV_ONLY = ["web", "api", "api-worker"]
LONG_RUNNING = ["postgres", "minio", "web-prod", "api-prod", "api-worker-prod", *METHODS]
MAY_READ_DOTENV = {"api", "api-worker", "api-prod", "api-worker-prod"}
CORE_SECRETS = {
    "POSTGRES_PASSWORD", "DATABASE_URL", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD",
    "JWT_SECRET_KEY", "GOOGLE_CLIENT_SECRET", "RESEND_API_KEY", "SMTP_PASSWORD",
}
PLAN_KEY = {
    "postgres": "POSTGRES", "minio": "MINIO", "minio-init": "MINIO_INIT", "web-prod": "WEB",
    "api-prod": "API", "api-worker-prod": "WORKER", "dowser": "DOWSER", "gctree": "GCTREE",
    "brepphylo": "BREPPHYLO", "clonaltree": "CLONALTREE",
}


def networks_of(service: dict) -> set[str]:
    nets = service.get("networks") or []
    return set(nets.keys()) if isinstance(nets, dict) else set(nets)


def test_the_expected_services_exist():
    assert set(SERVICES) == {*LONG_RUNNING, *DEV_ONLY, "minio-init"}


# --------------------------------------------------------------------------- #
# Resource limits
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", [*LONG_RUNNING, "minio-init"])
def test_cpu_memory_and_process_limits_come_from_the_plan(name):
    service, key = SERVICES[name], PLAN_KEY[name]
    assert re.fullmatch(rf"\$\{{PHYLO_CPUS_{key}:-[0-9.]+\}}", str(service["cpus"]))
    assert re.fullmatch(rf"\$\{{PHYLO_MEM_{key}:-[0-9]+m\}}", str(service["mem_limit"]))
    assert re.fullmatch(rf"\$\{{PHYLO_PIDS_{key}:-[0-9]+\}}", str(service["pids_limit"]))
    # Swap disabled: memory + swap limit equals the memory limit.
    assert service["memswap_limit"] == service["mem_limit"]
    assert service["cgroup_parent"] == "${PHYLO_CGROUP_PARENT:-}"


def test_no_limit_is_a_hard_coded_number():
    for name, service in SERVICES.items():
        for field in ("cpus", "mem_limit", "memswap_limit", "pids_limit"):
            if field in service:
                assert str(service[field]).startswith("${PHYLO_"), (name, field)


# --------------------------------------------------------------------------- #
# Restart, logging, privileges
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", LONG_RUNNING)
def test_long_running_services_restart(name):
    assert SERVICES[name]["restart"] == "unless-stopped"


def test_one_shot_init_container_never_restarts():
    assert SERVICES["minio-init"]["restart"] == "no"


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_logs_are_rotated_and_privilege_escalation_is_off(name):
    service = SERVICES[name]
    assert service["logging"]["driver"] == "json-file"
    assert service["logging"]["options"]["max-size"] == "${PHYLO_LOG_MAX_SIZE:-10m}"
    assert service["logging"]["options"]["max-file"] == "${PHYLO_LOG_MAX_FILES:-5}"
    assert "no-new-privileges:true" in service["security_opt"]


def test_no_privileged_containers_or_docker_socket():
    for name, service in SERVICES.items():
        assert not service.get("privileged"), name
        assert "cap_add" not in service, name
        for volume in service.get("volumes", []):
            source = volume.get("source", "") if isinstance(volume, dict) else str(volume)
            assert "docker.sock" not in source, name


@pytest.mark.parametrize("name", [*METHODS, "web-prod"])
def test_untrusted_input_parsers_and_web_drop_all_capabilities(name):
    assert SERVICES[name]["cap_drop"] == ["ALL"]


@pytest.mark.parametrize("name", R_METHODS)
def test_r_services_run_an_init_to_reap_finished_jobs(name):
    assert SERVICES[name]["init"] is True


# --------------------------------------------------------------------------- #
# Secret isolation
# --------------------------------------------------------------------------- #
def test_only_api_and_worker_load_dotenv():
    assert {n for n, s in SERVICES.items() if "env_file" in s} == MAY_READ_DOTENV


@pytest.mark.parametrize("name", [*METHODS, "web", "web-prod"])
def test_method_and_web_containers_hold_no_core_secret(name):
    env = SERVICES[name].get("environment", {})
    assert not (set(env) & CORE_SECRETS)
    rendered = yaml.safe_dump(env)
    for secret in ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "MINIO_ROOT_USER", "JWT_SECRET_KEY"):
        assert secret not in rendered, (name, secret)


@pytest.mark.parametrize("name", METHODS)
def test_methods_use_the_write_only_object_store_user(name):
    env = SERVICES[name]["environment"]
    assert env["S3_ACCESS_KEY_ID"].startswith("${MINIO_METHODS_USER:?")
    assert env["S3_SECRET_ACCESS_KEY"].startswith("${MINIO_METHODS_PASSWORD:?")


def test_database_and_object_store_get_only_their_own_credentials():
    assert set(SERVICES["postgres"]["environment"]) == {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}
    assert set(SERVICES["minio"]["environment"]) == {"MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"}


def test_no_credential_has_a_fallback_value():
    text = (ROOT / "docker-compose.yml").read_text()
    for variable in ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "MINIO_METHODS_PASSWORD", "JWT_SECRET_KEY"):
        assert not re.search(rf"\$\{{{variable}:-", text), variable


# --------------------------------------------------------------------------- #
# Networks
# --------------------------------------------------------------------------- #
def test_network_definitions():
    nets = COMPOSE["networks"]
    assert nets["phylo_db"] == {"internal": True}
    assert nets["phylo_internal"] == {"internal": True}
    assert nets["proxy_net"] == {"external": True}
    assert not (nets["phylo_egress"] or {}).get("internal")


def test_each_service_is_on_exactly_the_networks_it_needs():
    assert networks_of(SERVICES["postgres"]) == {"phylo_db"}
    assert networks_of(SERVICES["minio"]) == {"phylo_internal"}
    assert networks_of(SERVICES["minio-init"]) == {"phylo_internal"}
    for name in METHODS:  # no database, no internet, no proxy
        assert networks_of(SERVICES[name]) == {"phylo_internal"}, name
    assert networks_of(SERVICES["web-prod"]) == {"proxy_net"}
    assert networks_of(SERVICES["api-prod"]) == {"phylo_db", "phylo_internal", "phylo_egress", "proxy_net"}
    assert networks_of(SERVICES["api-worker-prod"]) == {"phylo_db", "phylo_internal", "phylo_egress"}


def test_internal_services_have_unique_dns_names():
    expected = {"postgres": ("phylo_db", "phylo-postgres"), "minio": ("phylo_internal", "phylo-minio"),
                **{m: ("phylo_internal", f"phylo-{m}") for m in METHODS}}
    for name, (network, alias) in expected.items():
        assert SERVICES[name]["networks"][network]["aliases"] == [alias]


def test_internal_urls_use_the_unique_names():
    env = COMPOSE["x-api-common-env"]
    assert "@phylo-postgres:5432/" in env["DATABASE_URL"]
    assert env["POSTGRES_HOST"] == "phylo-postgres"
    assert env["S3_ENDPOINT_URL"].endswith(":-http://phylo-minio:9000}")
    for method in METHODS:
        assert f":-http://phylo-{method}:" in env[f"METHOD_{method.upper()}_URL"]
    assert COMPOSE["x-method-common-env"]["S3_ENDPOINT_URL"].endswith(":-http://phylo-minio:9000}")
    assert "http://phylo-minio:9000" in SERVICES["minio-init"]["entrypoint"]


def test_production_publishes_no_host_ports():
    for name in [*LONG_RUNNING, "minio-init"]:
        assert "ports" not in SERVICES[name], name


def test_dev_override_keeps_the_database_on_loopback():
    assert DEV["services"]["postgres"]["ports"] == ["127.0.0.1:${POSTGRES_PORT:-5440}:5432"]
    # Publishing needs a non-internal network in addition to the internal one.
    assert DEV["services"]["postgres"]["networks"] == ["phylo_egress"]
    assert DEV["services"]["minio"]["networks"] == ["phylo_egress"]


# --------------------------------------------------------------------------- #
# Object-store initialisation must not fail silently
# --------------------------------------------------------------------------- #
def test_object_store_init_fails_loudly_and_verifies_its_result():
    script = SERVICES["minio-init"]["entrypoint"]
    assert "set -e;" in script
    assert "mc admin user info local" in script and "exit 1" in script
    # Bounded wait with the real error printed, not an endless silent loop.
    assert "-ge 60" in script and "cat /tmp/alias.log" in script
    for step in ("mc admin user add", "mc admin policy create"):
        line = next(part for part in script.split(";") if step in part)
        assert "|| true" not in line and "2>/dev/null" not in line, step


def test_production_services_are_marked_production():
    assert COMPOSE["x-api-prod-env"]["ENV"] == "production"
    for name in ("api-prod", "api-worker-prod"):
        assert SERVICES[name]["environment"]["ENV"] == "production"


# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #
def test_clonaltree_runtime_stage_has_no_build_toolchain():
    dockerfile = (ROOT / "services/clonaltree/Dockerfile").read_text()
    build_stage, runtime_stage = dockerfile.split("# --- Runtime stage")
    assert "AS muscle-build" in build_stage and "build-essential" in build_stage
    # Nothing is installed with apt in the runtime stage except security updates.
    assert "apt-get install" not in runtime_stage
    for tool in ("build-essential", "g++", "linux-libc-dev"):
        assert tool not in runtime_stage, tool
    assert "COPY --from=muscle-build /usr/local/bin/muscle" in runtime_stage
    # The alignment smoke test must run in the stage that ships.
    assert "muscle -align" in runtime_stage


def test_recorded_base_images_are_resolved(tmp_path):
    """Provenance must name the real runtime base image, not a build-arg placeholder."""
    import json
    import shutil
    import subprocess

    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    out = tmp_path / "version-info.json"
    subprocess.run(["node", str(ROOT / "scripts/generate-version-info.mjs"), "--out", str(out)],
                   check=True, capture_output=True, cwd=ROOT)
    services = json.loads(out.read_text())["services"]
    bases = {name: record["base_image"] for name, record in services.items()}
    assert all(base and "$" not in base for base in bases.values()), bases
    assert bases["clonaltree"].startswith("python:3.12")
    assert bases["gctree"].startswith("python:3.11")


def test_object_store_images_are_pinned_by_digest_and_mirrorable():
    """Upstream MinIO images are gone; the stack runs the Silo fork, pinned by
    digest, with an override so a deployment can pull the same digest from its
    own registry mirror."""
    digest = r"@sha256:[0-9a-f]{64}"
    store = SERVICES["minio"]["image"]
    client = SERVICES["minio-init"]["image"]
    assert re.fullmatch(r"\$\{PHYLO_OBJECT_STORE_IMAGE:-pgsty/silo" + digest + r"\}", store)
    assert re.fullmatch(r"\$\{PHYLO_OBJECT_STORE_CLIENT_IMAGE:-pgsty/mc" + digest + r"\}", client)
    text = (ROOT / "docker-compose.yml").read_text() + (ROOT / "docker-compose.test.yml").read_text()
    assert "minio/minio" not in text and "minio/mc" not in text
    # The test stack runs the very same server image as production.
    test_compose = yaml.safe_load((ROOT / "docker-compose.test.yml").read_text())
    assert test_compose["services"]["minio"]["image"] == store.split(":-", 1)[1].rstrip("}")


# --------------------------------------------------------------------------- #
# Resource-aware execution (job slots, thread budgets, admission)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", METHODS)
def test_methods_receive_their_execution_tunables(name):
    env = SERVICES[name]["environment"]
    upper = name.upper()
    assert env["METHOD_MAX_CONCURRENT_JOBS"] == f"${{PHYLO_{upper}_MAX_JOBS:-}}"
    assert env["METHOD_THREADS_PER_JOB"] == f"${{PHYLO_{upper}_THREADS_PER_JOB:-}}"
    assert env["METHOD_JOB_MEMORY_MB"] == f"${{PHYLO_{upper}_JOB_MEMORY_MB:-}}"
    assert env["METHOD_MEMORY_HEADROOM_PERCENT"] == "${PHYLO_MEMORY_HEADROOM_PERCENT:-10}"


def test_no_fixed_worker_concurrency_is_configured():
    """The worker derives its concurrency from the method services' job slots."""
    text = (ROOT / "docker-compose.yml").read_text()
    assert "WORKER_MAX_CONCURRENT_RUNS" not in text
    worker_source = (ROOT / "apps/api/workers/run_worker.py").read_text()
    assert 'getenv("WORKER_MAX_CONCURRENT_RUNS", "4")' not in worker_source


def _load_resource_limits():
    import importlib.util

    spec = importlib.util.spec_from_file_location("rl_for_plan", ROOT / "services/gctree/resource_limits.py")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module  # dataclasses need the module to be registered
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("budget", [
    (),                                                              # default budget
    ("--cpus", "2.05", "--memory-mb", "6592", "--pids", "2432"),     # smallest accepted budget
    ("--cpus", "8", "--memory-mb", "16384"),
    ("--cpus", "8", "--memory-mb", "16384", "--mode", "pooled"),
])
def test_every_method_can_run_at_least_one_job_under_the_resource_plan(tmp_path, budget, monkeypatch):
    """scripts/resource-plan.sh and the services' own capacity plan must agree:
    the limits the script hands a container are enough for one job there, and
    jobs x threads never exceeds the CPUs the container was given."""
    import subprocess

    rl = _load_resource_limits()
    monkeypatch.setattr(rl, "host_cpus", lambda: 64)
    out = subprocess.run(["sh", str(ROOT / "scripts/resource-plan.sh"), "--env-file", "/dev/null", "--env", *budget],
                         capture_output=True, text=True, check=True, env={"PATH": "/usr/bin:/bin:/usr/local/bin"}).stdout
    plan = dict(line.split("=", 1) for line in out.splitlines() if line.startswith("PHYLO_"))
    for method in METHODS:
        cpus = float(plan[f"PHYLO_CPUS_{method.upper()}"])
        memory_mb = int(plan[f"PHYLO_MEM_{method.upper()}"].rstrip("m"))
        root = tmp_path / method
        root.mkdir(exist_ok=True)
        (root / "cpu.max").write_text(f"{int(cpus * 100000)} 100000\n")
        (root / "memory.max").write_text(f"{memory_mb * 1024 * 1024}\n")
        capacity = rl.plan_capacity(method, {"PHYLO_CGROUP_ROOT": str(root)})
        assert capacity.job_slots >= 1, (method, cpus, memory_mb, capacity)
        assert capacity.job_slots * capacity.threads_per_job <= max(1, int(cpus)), (method, capacity)
        idle = capacity.baseline_memory_mb * 1024 * 1024
        assert rl.admit(capacity, 0, idle).accepted, method


# --------------------------------------------------------------------------- #
# Run limits and recovery (timeouts, lost jobs, artifact persistence)
# --------------------------------------------------------------------------- #
SHARED_SERVICE_FILES = {
    ("gctree", "clonaltree"): ["job_manager.py", "resource_limits.py", "object_storage.py", "artifact_manifest.py"],
    ("dowser", "brepphylo"): ["job_manager.R", "job_runner.R", "resource_limits.R", "object_storage.R",
                              "artifact_manifest.R"],
}


@pytest.mark.parametrize("pair,filename", [(pair, f) for pair, files in SHARED_SERVICE_FILES.items() for f in files])
def test_shared_service_files_do_not_drift_apart(pair, filename):
    """Each pair of services ships its own copy of these files. A fix applied
    to one copy only would leave the other service with the old behaviour."""
    first, second = (ROOT / "services" / name / filename for name in pair)
    assert first.read_bytes() == second.read_bytes(), f"{first} and {second} differ"


def test_python_job_runners_differ_only_in_their_log_prefix():
    gctree = (ROOT / "services/gctree/job_runner.py").read_text()
    clonaltree = (ROOT / "services/clonaltree/job_runner.py").read_text()
    assert gctree.replace("[gctree.job_runner]", "[clonaltree.job_runner]") == clonaltree


@pytest.mark.parametrize("name", METHODS)
def test_methods_can_be_given_a_fallback_job_time_limit(name):
    assert SERVICES[name]["environment"]["METHOD_JOB_TIMEOUT_SECONDS"] == "${PHYLO_METHOD_JOB_TIMEOUT_SECONDS:-}"


def test_documented_run_limits_match_the_built_in_defaults():
    """.env.example states the defaults; they must be the ones the code uses."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("worker_limits", ROOT / "apps/api/workers/limits.py")
    limits = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(limits)
    example = (ROOT / ".env.example").read_text()

    def documented(name: str) -> str:
        lines = [l for l in example.splitlines() if l.lstrip("# ").startswith(f"{name}=")]
        assert lines, f"{name} is not documented in .env.example"
        return lines[0].lstrip("# ").split("=", 1)[1].strip()

    assert int(documented("RUN_TIMEOUT_SECONDS")) == limits.DEFAULT_RUN_TIMEOUT_SECONDS
    assert int(documented("RUN_QUEUE_WAIT_TIMEOUT_SECONDS")) == limits.DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS
    assert int(documented("WORKER_METHOD_UNREACHABLE_SECONDS")) == limits.DEFAULT_METHOD_UNREACHABLE_SECONDS
    assert int(documented("WORKER_CANCEL_CONFIRM_SECONDS")) == limits.DEFAULT_CANCEL_CONFIRM_SECONDS
    for name in ("RUN_TIMEOUT_SECONDS_DOWSER", "ARTIFACT_VERIFY_ATTEMPTS", "ARTIFACT_VERIFY_RETRY_SECONDS",
                 "ARTIFACT_VERIFY_TIMEOUT_SECONDS", "PHYLO_METHOD_JOB_TIMEOUT_SECONDS"):
        documented(name)


def test_run_limits_reach_the_worker_through_dotenv_not_through_fixed_values():
    """The worker reads its limits from .env (env_file); compose must not pin them."""
    text = (ROOT / "docker-compose.yml").read_text()
    for name in ("RUN_TIMEOUT_SECONDS", "RUN_QUEUE_WAIT_TIMEOUT_SECONDS", "WORKER_METHOD_UNREACHABLE_SECONDS"):
        assert f"{name}:" not in text
    assert "env_file" in SERVICES["api-worker-prod"]


@pytest.mark.parametrize("name", R_METHODS)
def test_r_service_images_keep_coreutils_for_the_job_time_limit(name):
    """The R job manager enforces a job's time limit with coreutils `timeout`;
    the Fedora base images ship coreutils and the Dockerfile must not remove it."""
    dockerfile = (ROOT / "services" / name / "Dockerfile").read_text()
    removals = [l for l in dockerfile.splitlines() if "coreutils" in l and ("remove" in l or "erase" in l)]
    assert not removals, removals


# --------------------------------------------------------------------------- #
# Limits on creating runs
# --------------------------------------------------------------------------- #
def test_documented_run_creation_limits_match_the_built_in_defaults():
    source = (ROOT / "apps/api/services/run_quota.py").read_text()
    defaults = {}
    for name in ("DEFAULT_RUNS_PER_HOUR", "DEFAULT_MAX_QUEUED", "DEFAULT_SUBMISSIONS_PER_HOUR", "WINDOW_SECONDS"):
        line = next(l for l in source.splitlines() if l.startswith(f"{name} = "))
        defaults[name] = int(line.split("=", 1)[1])
    assert defaults == {"DEFAULT_RUNS_PER_HOUR": 5, "DEFAULT_MAX_QUEUED": 5,
                        "DEFAULT_SUBMISSIONS_PER_HOUR": 30, "WINDOW_SECONDS": 3600}
    example = {l.split("=", 1)[0]: l.split("=", 1)[1].strip()
               for l in (ROOT / ".env.example").read_text().splitlines()
               if l and not l.startswith("#") and "=" in l}
    assert int(example["MAX_RUNS_PER_USER_PER_HOUR"]) == defaults["DEFAULT_RUNS_PER_HOUR"]
    assert int(example["MAX_QUEUED_RUNS_PER_USER"]) == defaults["DEFAULT_MAX_QUEUED"]
    assert int(example["MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR"]) == defaults["DEFAULT_SUBMISSIONS_PER_HOUR"]


def test_run_creation_limits_are_not_pinned_in_compose():
    """They reach the API through .env (env_file), so the server's .env decides."""
    text = (ROOT / "docker-compose.yml").read_text()
    for name in ("MAX_RUNS_PER_USER_PER_HOUR", "MAX_QUEUED_RUNS_PER_USER", "MAX_RUN_SUBMISSIONS_PER_USER_PER_HOUR"):
        assert name not in text
    assert "env_file" in SERVICES["api-prod"]


@pytest.mark.parametrize("name", METHODS)
def test_every_method_ships_its_success_criteria(name):
    import json

    contract = json.loads((ROOT / "packages/contracts/methods" / name / "completion.json").read_text())
    assert contract["minTrees"] >= 1
    assert "clone_bundle_zip" in contract["requiredArtifactRoles"]
    # The role must be one the method really declares, or no run could ever finish.
    sources = "".join(p.read_text() for p in (ROOT / "services" / name).glob("*.[pR]*") if p.is_file())
    assert "clone_bundle_zip" in sources, f"{name} never declares a clone_bundle_zip artifact"
