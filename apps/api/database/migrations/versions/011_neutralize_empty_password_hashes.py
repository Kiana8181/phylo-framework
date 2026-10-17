"""Neutralize password hashes of the empty string

Revision ID: 011_empty_password_hashes
Revises: 010_display_newick
Create Date: 2026-10-08

Accounts created through Google sign-in used to be stored with a bcrypt hash of
the empty string, which let anyone log in to them with an empty password. Login
now rejects empty passwords outright; this data migration also removes the
stored weakness by replacing every hash that verifies against "" with the
unusable-password marker (see apps/api/auth/password.py).

Only ``users.password_hash`` of affected rows changes. Affected users sign in
with Google as before, or set a password through the reset flow. Idempotent: a
second run finds nothing to change. Downgrade is a no-op, because the original
hashes carried no secret worth restoring.
"""
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from alembic import op

revision: str = "011_empty_password_hashes"
down_revision: Union[str, None] = "010_display_newick"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNUSABLE_PASSWORD_HASH = "!unusable"


def _is_hash_of_empty_string(stored: str) -> bool:
    try:
        return bcrypt.checkpw(b"", stored.encode("utf-8"))
    except (ValueError, TypeError):
        # Not a bcrypt hash at all; nothing an empty password could match.
        return False


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, password_hash FROM users")).fetchall()
    affected = [row.id for row in rows if row.password_hash and _is_hash_of_empty_string(row.password_hash)]
    for user_id in affected:
        bind.execute(
            sa.text("UPDATE users SET password_hash = :marker WHERE id = :id"),
            {"marker": UNUSABLE_PASSWORD_HASH, "id": user_id},
        )
    if affected:
        print(f"[011] neutralized {len(affected)} empty-password hash(es)")


def downgrade() -> None:
    pass
