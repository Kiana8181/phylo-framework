"""Initial schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2025-02-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('username', sa.String(100), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('email', name='uq_users_email'),
        sa.UniqueConstraint('username', name='uq_users_username'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=False)
    op.create_index('ix_users_username', 'users', ['username'], unique=False)

    # Create runs table
    op.create_table(
        'runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('method_id', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.CheckConstraint('progress >= 0 AND progress <= 100', name='ck_runs_progress'),
    )
    op.create_index('idx_runs_user_id', 'runs', ['user_id'], unique=False)
    op.create_index('idx_runs_status', 'runs', ['status'], unique=False)
    op.create_index('idx_runs_created_at', 'runs', ['created_at'], unique=False)
    op.create_index('idx_runs_method_id', 'runs', ['method_id'], unique=False)
    op.create_index('ix_runs_user_id', 'runs', ['user_id'], unique=False)
    op.create_index('ix_runs_status', 'runs', ['status'], unique=False)
    op.create_index('ix_runs_method_id', 'runs', ['method_id'], unique=False)

    # Create files table
    op.create_table(
        'files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('storage_type', sa.String(20), nullable=False, server_default='local'),
        sa.Column('storage_path', sa.Text(), nullable=False),
        sa.Column('storage_url', sa.Text(), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
    )
    op.create_index('idx_files_run_id', 'files', ['run_id'], unique=False)
    op.create_index('idx_files_user_id', 'files', ['user_id'], unique=False)
    op.create_index('ix_files_run_id', 'files', ['run_id'], unique=False)
    op.create_index('ix_files_user_id', 'files', ['user_id'], unique=False)

    # Create job_queue table
    op.create_table(
        'job_queue',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('job_id', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='QUEUED'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('job_id', name='uq_job_queue_job_id'),
    )
    op.create_index('idx_job_queue_run_id', 'job_queue', ['run_id'], unique=False)
    op.create_index('idx_job_queue_status', 'job_queue', ['status'], unique=False)
    op.create_index('ix_job_queue_run_id', 'job_queue', ['run_id'], unique=False)
    op.create_index('ix_job_queue_status', 'job_queue', ['status'], unique=False)
    op.create_index('ix_job_queue_job_id', 'job_queue', ['job_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_job_queue_job_id', table_name='job_queue')
    op.drop_index('ix_job_queue_status', table_name='job_queue')
    op.drop_index('ix_job_queue_run_id', table_name='job_queue')
    op.drop_index('idx_job_queue_status', table_name='job_queue')
    op.drop_index('idx_job_queue_run_id', table_name='job_queue')
    op.drop_table('job_queue')
    
    op.drop_index('ix_files_user_id', table_name='files')
    op.drop_index('ix_files_run_id', table_name='files')
    op.drop_index('idx_files_user_id', table_name='files')
    op.drop_index('idx_files_run_id', table_name='files')
    op.drop_table('files')
    
    op.drop_index('ix_runs_method_id', table_name='runs')
    op.drop_index('ix_runs_status', table_name='runs')
    op.drop_index('ix_runs_user_id', table_name='runs')
    op.drop_index('idx_runs_method_id', table_name='runs')
    op.drop_index('idx_runs_created_at', table_name='runs')
    op.drop_index('idx_runs_status', table_name='runs')
    op.drop_index('idx_runs_user_id', table_name='runs')
    op.drop_table('runs')
    
    op.drop_index('ix_users_username', table_name='users')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')
