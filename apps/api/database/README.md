# Database Setup Guide

## Prerequisites

1. PostgreSQL 15 running in Docker:
   ```bash
   docker-compose up postgres -d
   ```

2. Environment variables set in `apps/api/.env`:
   ```
   POSTGRES_USER=phylo_user
   POSTGRES_PASSWORD=phylo_pass
   POSTGRES_DB=phylo_db
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   DATABASE_URL=postgresql+asyncpg://phylo_user:phylo_pass@localhost:5432/phylo_db
   ```

## Running Migrations

### From Project Root (Recommended)

```bash
# From project root directory
cd f:\Programming\Kiana\phylo-framework

# Activate virtual environment
.venv\Scripts\Activate.ps1  # Windows PowerShell
# or
source .venv/bin/activate   # Linux/Mac

# Run migrations
alembic upgrade head
```

### From apps/api Directory

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

1. Make sure PostgreSQL is running:
   ```bash
   docker ps | grep postgres
   ```

2. Check credentials match in:
   - `apps/api/.env`
   - `docker-compose.yml`

3. Test connection manually:
   ```bash
   psql -h localhost -U phylo_user -d phylo_db
   # Password: phylo_pass
   ```

### Migration Path Errors

- Always run `alembic` from project root when using root `alembic.ini`
- Or use `-c` flag to specify config file location
