"""Email verification, session invalidation, hashed tokens, rate limits, CAPTCHA replay table

Revision ID: 015_auth_abuse_prevention
Revises: 014_notification_outbox
Create Date: 2026-10-12

users
  * email_verified_at, email_verification_token (a SHA-256 hash),
    email_verification_expires
  * tokens_valid_after: sessions issued earlier are refused
  Every account that exists when this migration runs is marked verified (with
  the time of the migration): these accounts were created before verification
  existed and must keep working.
  Outstanding password-reset tokens are cleared. They were stored in readable
  form; from now on only a hash is stored, so an old token could no longer be
  matched. A user in the middle of a reset simply requests a new link.

rate_limits        counters for the authentication rate limits
captcha_used       challenges already spent, so a solution cannot be replayed

Additive apart from clearing the short-lived reset tokens. Downgrade drops the
new tables and columns.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "015_auth_abuse_prevention"
down_revision: Union[str, None] = "014_notification_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(64)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_expires TIMESTAMPTZ")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tokens_valid_after TIMESTAMPTZ")
    op.execute("UPDATE users SET email_verified_at = now() WHERE email_verified_at IS NULL")
    op.execute(
        "UPDATE users SET password_reset_token = NULL, password_reset_expires = NULL "
        "WHERE password_reset_token IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_email_verification_token "
        "ON users (email_verification_token) WHERE email_verification_token IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_limits (
            bucket VARCHAR(80) NOT NULL,
            window_start BIGINT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (bucket, window_start)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_expires ON rate_limits (expires_at)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS captcha_used (
            nonce VARCHAR(64) PRIMARY KEY,
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_captcha_used_expires ON captcha_used (expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS captcha_used")
    op.execute("DROP TABLE IF EXISTS rate_limits")
    op.execute("DROP INDEX IF EXISTS idx_users_email_verification_token")
    for column in ("tokens_valid_after", "email_verification_expires", "email_verification_token", "email_verified_at"):
        op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {column}")
