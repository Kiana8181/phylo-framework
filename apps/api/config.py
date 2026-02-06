import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from apps/api directory
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)
# Also try loading from root (for Alembic)
root_env = Path(__file__).parent.parent.parent / ".env"
if root_env.exists():
    load_dotenv(root_env, override=False)

# Repository root = .../phylo
ROOT_DIR = Path(__file__).resolve().parents[2]

# CONTRACTS_DIR can be absolute or relative to repo root
_env_contracts = os.getenv("CONTRACTS_DIR", "packages/contracts")
CONTRACTS_DIR = (Path(_env_contracts) if Path(_env_contracts).is_absolute()
                 else (ROOT_DIR / _env_contracts)).resolve()

# CORS origins (comma-separated)
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

# Service URLs are fully dynamic via env:
# e.g. METHOD_DOWSER_URL=http://localhost:8001, METHOD_GCTREE_URL=..., etc.
def method_service_url(method_id: str) -> str | None:
    key = f"METHOD_{method_id.strip().upper()}_URL"
    return os.getenv(key)

# Timeouts
HTTP_CLIENT_TIMEOUT = int(os.getenv("HTTP_CLIENT_TIMEOUT", "600"))   # seconds
SPEC_TIMEOUT = int(os.getenv("SPEC_TIMEOUT", "60"))                  # seconds

# Per-user storage quota (bytes). Default 2 GB.
STORAGE_QUOTA_PER_USER_GB = float(os.getenv("STORAGE_QUOTA_PER_USER_GB", "2"))
STORAGE_QUOTA_PER_USER_BYTES = int(STORAGE_QUOTA_PER_USER_GB * (1024**3))

# Email (Resend) for password reset
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Phylo Runner <onboarding@resend.dev>")

# Database configuration
def get_database_url() -> str:
    """Build database URL from environment variables or use defaults."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url
    
    # Build from individual components
    postgres_user = os.getenv("POSTGRES_USER", "phylo_user")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "phylo_pass")
    # Use 127.0.0.1 instead of localhost on Windows to avoid IPv6 issues
    postgres_host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    postgres_port = os.getenv("POSTGRES_PORT", "5432")
    postgres_db = os.getenv("POSTGRES_DB", "phylo_db")
    
    return f"postgresql+asyncpg://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"

DATABASE_URL = get_database_url()
