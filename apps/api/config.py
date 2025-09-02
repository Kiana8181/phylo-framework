import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

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
