"""Dataset expiration, renewal and cleanup.

Real PostgreSQL where the behavior depends on row locks or storage. Result
retention is not what removes a dataset: this file drives the dataset sweep
directly.
"""
from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.database.models import File, Run, RunStatus, StorageState, StorageType, User
from apps.api.repositories.file_repository import FileRepository
from apps.api.services import retention as settings
from apps.api.services.dataset_service import RenewOutcome, renew_dataset
from apps.api.storage.local_storage import LocalStorage
from apps.api.tests.test_run_recovery import make_user
from apps.api.workers import dataset_retention

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "database" / "migrations" / "versions" / "018_dataset_retention.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_018_dataset_retention", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Configuration (no database)
# --------------------------------------------------------------------------- #
def test_dataset_retention_defaults_and_invalid_values(monkeypatch):
    monkeypatch.delenv("DATASET_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("DATASET_EXPIRATION_WARNING_HOURS", raising=False)
    assert settings.dataset_retention_days() == 60
    assert settings.dataset_retention_period() == 60 * DAY
    assert settings.dataset_warning_hours() == 24
    assert settings.effective_dataset_warning() == 24 * HOUR

    monkeypatch.setenv("DATASET_RETENTION_DAYS", "not-a-number")
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "also-bad")
    assert settings.dataset_retention_days() == 60
    assert settings.dataset_warning_hours() == 24

    monkeypatch.setenv("DATASET_RETENTION_DAYS", "-4")
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "0")
    assert settings.dataset_retention_days() == 60
    assert settings.dataset_warning_hours() == 24
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "-3")
    assert settings.dataset_warning_hours() == 24

    monkeypatch.setenv("DATASET_RETENTION_DAYS", "0")
    assert settings.dataset_retention_period() is None
    assert settings.effective_dataset_warning() is None
    assert settings.dataset_expires_at(datetime.now(timezone.utc)) is None


@pytest.mark.parametrize("hours", ["24", "48", "72"])
def test_warning_window_follows_the_configured_hours(monkeypatch, hours):
    monkeypatch.setenv("DATASET_RETENTION_DAYS", "60")
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", hours)
    assert settings.effective_dataset_warning() == timedelta(hours=float(hours))


def test_warning_window_is_shortened_when_it_covers_the_whole_retention(monkeypatch):
    monkeypatch.setenv("DATASET_RETENTION_DAYS", "1")
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "48")
    assert settings.effective_dataset_warning() == 23 * HOUR

    monkeypatch.setenv("DATASET_RETENTION_DAYS", "2")
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "48")
    assert settings.effective_dataset_warning() == 47 * HOUR

    monkeypatch.setenv("DATASET_RETENTION_DAYS", "0.01")
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "24")
    period = timedelta(days=0.01)
    assert settings.effective_dataset_warning() == period / 2


def test_renewal_eligibility_uses_the_warning_window_and_utc(monkeypatch):
    monkeypatch.setenv("DATASET_RETENTION_DAYS", "60")
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "24")
    assert settings.renewal_eligible(now + 10 * DAY, now) is False
    assert settings.renewal_eligible(now + 12 * HOUR, now) is True
    assert settings.renewal_eligible(now, now) is False
    assert settings.renewal_eligible(now - HOUR, now) is False
    # A naive timestamp is treated as UTC, the same zone the column is stored in.
    assert settings.renewal_eligible((now + 2 * HOUR).replace(tzinfo=None), now) is True

    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "48")
    assert settings.renewal_eligible(now + 36 * HOUR, now) is True
    assert settings.renewal_eligible(now + 36 * HOUR, now) is True
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "72")
    assert settings.renewal_eligible(now + 60 * HOUR, now) is True
    assert settings.renewal_eligible(now + 80 * HOUR, now) is False

    monkeypatch.setenv("DATASET_RETENTION_DAYS", "0")
    assert settings.renewal_eligible(now + HOUR, now) is False


def test_a_new_expiration_is_counted_from_the_given_moment(monkeypatch):
    monkeypatch.setenv("DATASET_RETENTION_DAYS", "15")
    moment = datetime(2026, 3, 1, 8, 30, tzinfo=timezone.utc)
    assert settings.dataset_expires_at(moment) == moment + 15 * DAY


# --------------------------------------------------------------------------- #
# Database and storage
# --------------------------------------------------------------------------- #
db_test = pytest.mark.integration


@pytest.fixture
def store(tmp_path, monkeypatch):
    bucket = LocalStorage(str(tmp_path / "datasets"))
    monkeypatch.setattr(dataset_retention, "_storage", bucket)
    return bucket


@pytest.fixture
def db(session, monkeypatch, store):
    maker = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(dataset_retention, "AsyncSessionLocal", maker)
    monkeypatch.setenv("DATASET_RETENTION_DAYS", "60")
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "24")
    return session


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _dataset(db, user: User, store: LocalStorage, *, name: str = "sample.tsv", expires_at=None, body: bytes = b"data") -> File:
    key = f"datasets/{user.id}/{uuid.uuid4()}.tsv"
    await store.upload(body, key)
    row = File(
        id=uuid.uuid4(),
        user_id=user.id,
        original_filename=name,
        storage_type=StorageType.LOCAL,
        storage_path=key,
        file_size=len(body),
        storage_state=StorageState.ACTIVE,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _run(db, user: User, file_id, status: RunStatus) -> Run:
    row = Run(
        id=uuid.uuid4(),
        user_id=user.id,
        input_file_id=file_id,
        method_id="dowser",
        status=status,
        params={},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _reload(db, file_id) -> File:
    result = await db.execute(
        select(File).where(File.id == file_id).execution_options(populate_existing=True)
    )
    return result.scalar_one()


@db_test
async def test_migration_backfill_dates_only_active_datasets_that_have_none(db, store):
    user = await make_user(db, "migrate")
    missing = await _dataset(db, user, store, name="old.tsv", expires_at=None)
    promised = _now() + 90 * DAY
    kept = await _dataset(db, user, store, name="kept.tsv", expires_at=promised)
    gone = await _dataset(db, user, store, name="gone.tsv", expires_at=None)
    gone.storage_state = StorageState.DELETED
    await db.commit()

    migration = _migration()
    assert migration.revision == "018_dataset_retention"
    assert migration.down_revision == "017_runs_write_cost"
    await db.execute(text(migration.backfill_sql(30)))
    await db.execute(text(migration.INDEX_SQL))
    await db.commit()

    filled = await _reload(db, missing.id)
    assert filled.expires_at is not None
    remaining = filled.expires_at - _now()
    assert 29 * DAY < remaining < 31 * DAY
    assert abs((await _reload(db, kept.id)).expires_at - promised) < timedelta(seconds=1)
    assert (await _reload(db, gone.id)).expires_at is None
    source = _MIGRATION_PATH.read_text()
    assert "DROP INDEX IF EXISTS idx_files_expiry_due" in source
    assert "DELETE FROM files" not in source


@db_test
async def test_upload_stores_an_expiration_and_the_list_returns_it(db, store, client, account, monkeypatch):
    monkeypatch.setenv("DATASET_RETENTION_DAYS", "10")
    before = _now()
    init = (await client.post("/uploads/init", json={"original_filename": "sample.fasta", "expected_size": 4})).json()
    uploaded = await client.put(init["content_url"], content=b"ACGT")
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    expires = datetime.fromisoformat(body["expires_at"])
    assert before + 10 * DAY - timedelta(minutes=1) < expires < before + 10 * DAY + timedelta(minutes=1)

    listed = (await client.get("/files")).json()
    summary = next(item for item in listed["files"] if item["id"] == body["file_id"])
    assert summary["expires_at"] == body["expires_at"]
    assert summary["renewal_eligible"] is False
    assert listed["approaching"] == []


@db_test
async def test_expired_datasets_are_removed_and_history_stays(db, store):
    user = await make_user(db, "expire")
    due = await _dataset(db, user, store, name="due.tsv", expires_at=_now() - HOUR)
    fresh = await _dataset(db, user, store, name="fresh.tsv", expires_at=_now() + 30 * DAY)
    undated = await _dataset(db, user, store, name="undated.tsv", expires_at=None)
    finished = await _run(db, user, due.id, RunStatus.DONE)

    assert await dataset_retention.sweep() == {"expired": 1}
    removed = await _reload(db, due.id)
    assert removed.storage_state == StorageState.DELETED
    assert removed.deleted_by is None
    assert not await store.exists(due.storage_path)
    assert (await _reload(db, fresh.id)).storage_state == StorageState.ACTIVE
    assert (await _reload(db, undated.id)).storage_state == StorageState.ACTIVE
    assert await store.exists(fresh.storage_path)
    run = (await db.execute(select(Run).where(Run.id == finished.id))).scalar_one()
    assert run.input_file_id == due.id and run.status == RunStatus.DONE
    assert await dataset_retention.sweep() == {}


@db_test
async def test_a_dataset_in_use_by_an_active_run_is_left_until_the_run_ends(db, store):
    user = await make_user(db, "busy")
    due = await _dataset(db, user, store, expires_at=_now() - HOUR)
    await _run(db, user, due.id, RunStatus.RUNNING)
    assert await dataset_retention.sweep() == {"deferred": 1}
    assert (await _reload(db, due.id)).storage_state == StorageState.ACTIVE
    assert await store.exists(due.storage_path)

    run = (
        await db.execute(
            select(Run).where(Run.input_file_id == due.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    run.status = RunStatus.DONE
    await db.commit()
    assert await dataset_retention.sweep() == {"expired": 1}
    assert (await _reload(db, due.id)).storage_state == StorageState.DELETED


@db_test
async def test_storage_failure_leaves_the_row_active_and_the_next_sweep_finishes(db, store, monkeypatch):
    user = await make_user(db, "flaky")
    due = await _dataset(db, user, store, expires_at=_now() - HOUR)

    class Down(LocalStorage):
        async def exists(self, file_path: str) -> bool:
            raise ConnectionError("store down")

    monkeypatch.setattr(dataset_retention, "_storage", Down(store.base_path))
    assert await dataset_retention.sweep() == {"retry": 1}
    assert (await _reload(db, due.id)).storage_state == StorageState.ACTIVE
    assert await store.exists(due.storage_path)

    monkeypatch.setattr(dataset_retention, "_storage", store)
    assert await dataset_retention.sweep() == {"expired": 1}
    assert not await store.exists(due.storage_path)


@db_test
async def test_a_renewal_that_lands_before_the_lock_is_not_deleted(db, store):
    user = await make_user(db, "race")
    due = await _dataset(db, user, store, expires_at=_now() - HOUR)
    due.expires_at = _now() + 60 * DAY
    await db.commit()
    assert await dataset_retention.sweep() == {}
    assert (await _reload(db, due.id)).storage_state == StorageState.ACTIVE
    assert await store.exists(due.storage_path)


@db_test
async def test_renewal_waits_out_cleanup_and_does_not_restore_a_deleted_dataset(db, store, monkeypatch):
    user = await make_user(db, "lock")
    due = await _dataset(db, user, store, name="locked.tsv", expires_at=_now() - HOUR)
    started = asyncio.Event()
    release = asyncio.Event()

    class Slow(LocalStorage):
        def __init__(self):
            super().__init__(store.base_path)
            self.calls = 0

        async def exists(self, file_path: str) -> bool:
            self.calls += 1
            if self.calls == 1:
                started.set()
                await release.wait()
                return True
            return False

        async def delete(self, file_path: str) -> bool:
            return await store.delete(file_path)

    monkeypatch.setattr(dataset_retention, "_storage", Slow())

    async def try_renew():
        maker = async_sessionmaker(db.bind, expire_on_commit=False)
        async with maker() as other:
            return await renew_dataset(db=other, file_id=due.id, user=user)

    cleanup = asyncio.create_task(dataset_retention.expire_dataset(due.id))
    await asyncio.wait_for(started.wait(), timeout=5)
    renewal = asyncio.create_task(try_renew())
    await asyncio.sleep(0.2)
    assert not renewal.done()
    release.set()
    assert await cleanup == "expired"
    result = await renewal
    assert result.outcome == RenewOutcome.DELETED
    assert (await _reload(db, due.id)).storage_state == StorageState.DELETED
    assert not await store.exists(due.storage_path)


@db_test
async def test_owner_can_renew_inside_the_window_from_now(db, store, client, account, monkeypatch):
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "48")
    user_id = uuid.UUID(account["user"]["id"]) if "user" in account else None
    listed_before = None
    init = (await client.post("/uploads/init", json={"original_filename": "keep.fasta", "expected_size": 4})).json()
    uploaded = (await client.put(init["content_url"], content=b"ACGT")).json()
    file_id = uuid.UUID(uploaded["file_id"])
    row = await FileRepository(db).get_by_id(file_id)
    assert user_id is None or row.user_id == user_id
    owner = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one()

    too_early = await client.post(f"/files/{file_id}/renew")
    assert too_early.status_code == 409
    assert too_early.json()["data"]["code"] == "RENEWAL_NOT_DUE"

    previous = _now() + 36 * HOUR
    row.expires_at = previous
    await db.commit()
    before = _now()
    renewed = await client.post(f"/files/{file_id}/renew")
    assert renewed.status_code == 200, renewed.text
    body = renewed.json()
    new_expiry = datetime.fromisoformat(body["file"]["expires_at"])
    assert before + 60 * DAY - timedelta(minutes=1) < new_expiry < before + 60 * DAY + timedelta(minutes=1)
    assert body["file"]["renewal_eligible"] is False
    assert new_expiry - previous > 50 * DAY

    same = await client.post(f"/datasets/{file_id}/renew")
    assert same.status_code == 409
    assert same.json()["data"]["code"] == "RENEWAL_NOT_DUE"

    listed = (await client.get("/files")).json()
    assert listed["approaching"] == []
    summary = next(item for item in listed["files"] if item["id"] == str(file_id))
    assert summary["expires_at"] == body["file"]["expires_at"]
    assert summary["renewal_eligible"] is False
    assert owner.id == row.user_id
    assert listed_before is None


@db_test
async def test_approaching_datasets_are_listed_for_their_owner_only(db, store, client, account, monkeypatch):
    monkeypatch.setenv("DATASET_EXPIRATION_WARNING_HOURS", "72")
    init = (await client.post("/uploads/init", json={"original_filename": "soon.fasta", "expected_size": 4})).json()
    uploaded = (await client.put(init["content_url"], content=b"ACGT")).json()
    file_id = uuid.UUID(uploaded["file_id"])
    row = await FileRepository(db).get_by_id(file_id)
    row.expires_at = _now() + 48 * HOUR
    other_user = await make_user(db, "stranger")
    hidden = await _dataset(db, other_user, store, name="theirs.tsv", expires_at=_now() + 2 * HOUR)
    await db.commit()

    listed = (await client.get("/files")).json()
    ids = [item["id"] for item in listed["approaching"]]
    assert str(file_id) in ids
    assert str(hidden.id) not in ids
    mine = next(item for item in listed["files"] if item["id"] == str(file_id))
    assert mine["renewal_eligible"] is True

    other = await client.post("/auth/register", json={
        "email": "else@example.org", "username": "else", "password": "test-password-123",
    })
    client.headers["Authorization"] = f"Bearer {other.json()['access_token']}"
    assert (await client.post(f"/files/{file_id}/renew")).status_code == 404
    client.headers["Authorization"] = f"Bearer {account['access_token']}"


@db_test
async def test_expired_and_deleted_datasets_cannot_be_renewed(db, store, client, account, monkeypatch):
    init = (await client.post("/uploads/init", json={"original_filename": "old.fasta", "expected_size": 4})).json()
    uploaded = (await client.put(init["content_url"], content=b"ACGT")).json()
    file_id = uuid.UUID(uploaded["file_id"])
    row = await FileRepository(db).get_by_id(file_id)
    row.expires_at = _now() - HOUR
    await db.commit()
    from apps.api.routers import uploads
    monkeypatch.setattr(dataset_retention, "_storage", uploads.storage())
    expired = await client.post(f"/files/{file_id}/renew")
    assert expired.status_code == 409
    assert expired.json()["data"]["code"] == "DATASET_EXPIRED"
    await db.rollback()
    assert (await _reload(db, file_id)).storage_state == StorageState.ACTIVE

    assert await dataset_retention.sweep() == {"expired": 1}
    db.expire_all()
    deleted = await client.post(f"/datasets/{file_id}/renew")
    assert deleted.status_code == 410
    assert await uploads.storage().exists(row.storage_path) is False


@db_test
async def test_retention_off_rejects_renewal_and_skips_cleanup(db, store, client, account, monkeypatch):
    init = (await client.post("/uploads/init", json={"original_filename": "keep.fasta", "expected_size": 4})).json()
    uploaded = (await client.put(init["content_url"], content=b"ACGT")).json()
    file_id = uuid.UUID(uploaded["file_id"])
    from apps.api.routers import uploads
    monkeypatch.setattr(dataset_retention, "_storage", uploads.storage())
    monkeypatch.setenv("DATASET_RETENTION_DAYS", "0")
    refused = await client.post(f"/files/{file_id}/renew")
    assert refused.status_code == 409
    assert refused.json()["data"]["code"] == "RETENTION_DISABLED"
    row = await _reload(db, file_id)
    row.expires_at = _now() - HOUR
    await db.commit()
    assert await dataset_retention.sweep() == {}
    assert (await _reload(db, file_id)).storage_state == StorageState.ACTIVE
