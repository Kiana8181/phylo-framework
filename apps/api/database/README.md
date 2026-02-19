# Database Setup Guide

## Prerequisites

1. PostgreSQL 15 running in Docker:

```bash
docker compose --profile dev up -d postgres
```

2. Environment variables in repo-root `.env`:

```env
POSTGRES_USER=phylo_user
POSTGRES_PASSWORD=phylo_pass
POSTGRES_DB=phylo_db
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5440
# Optional explicit override:
# DATABASE_URL=postgresql+asyncpg://phylo_user:phylo_pass@127.0.0.1:5440/phylo_db
```

## Running Migrations

### From Project Root (recommended)

```bash
# From project root
source .venv/bin/activate   # Linux/macOS
# or
.venv\Scripts\Activate.ps1 # Windows PowerShell

alembic upgrade head
```

### From `apps/api` directory

```bash
# From apps/api directory
cd apps/api

# Use the local alembic.ini
alembic -c alembic.ini upgrade head
```

## Creating New Migrations

```bash
# From project root
alembic revision --autogenerate -m "description of changes"

# Review the generated migration file, then apply:
alembic upgrade head
```

## Checking Migration Status

```bash
# Show current revision
alembic current

# Show migration history
alembic history

# Show pending migrations
alembic heads
```

## Troubleshooting

### Connection Errors

1. Verify PostgreSQL is running:

```bash
docker ps | grep phylo-postgres
```

2. Verify credentials/host/port in root `.env`.

3. Test connection manually:

```bash
psql -h 127.0.0.1 -U phylo_user -d phylo_db -p 5440
```

### Migration Path Errors

- Run `alembic` from project root when using root `alembic.ini`
- Or pass `-c` to point to the intended Alembic config file
