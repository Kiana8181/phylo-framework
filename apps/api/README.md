# مستندات Backend API

## فهرست مطالب

- [معرفی](#معرفی)
- [معماری](#معماری)
- [ساختار پروژه](#ساختار-پروژه)
- [راه‌اندازی](#راه‌اندازی)
- [دیتابیس](#دیتابیس)
- [Authentication](#authentication)
- [API Endpoints](#api-endpoints)
- [Task Queue System](#task-queue-system)
- [Configuration](#configuration)
- [Migrations](#migrations)

---

## معرفی

Backend API این پروژه با استفاده از **FastAPI** ساخته شده است و به عنوان یک **Orchestrator** برای مدیریت و اجرای متدهای فیلوژنی عمل می‌کند. این API با میکروسرویس‌های مختلف (Dowser, GCtree, BrepPhylo, ClonalTree) ارتباط برقرار می‌کند و وظایف را مدیریت می‌کند.

### ویژگی‌های کلیدی

- ✅ **PostgreSQL** برای ذخیره‌سازی داده‌ها
- ✅ **Redis + RQ** برای مدیریت صف وظایف (Task Queue)
- ✅ **FastAPI Users** برای Authentication با پشتیبانی از Google OAuth
- ✅ **SQLAlchemy** با پشتیبانی از Async
- ✅ **Alembic** برای Database Migrations
- ✅ **Background Workers** برای اجرای موازی وظایف

---

## معماری

```
┌─────────────┐
│   Frontend  │  Next.js (Port 3000)
└──────┬──────┘
       │ HTTP
┌──────▼──────────────────────────────────┐
│         Backend API (FastAPI)           │
│              Port 8000                   │
├─────────────────────────────────────────┤
│  • Authentication (FastAPI Users)       │
│  • REST API Endpoints                   │
│  • Task Queue Management                │
└──────┬──────────────────────────────────┘
       │
       ├──────────────┬────────────────────┐
       │              │                    │
┌──────▼──────┐ ┌────▼─────┐ ┌───────────▼──────┐
│ PostgreSQL  │ │  Redis   │ │  Method Services  │
│  Port 5432  │ │ Port 6379│ │  (Dowser, etc.)  │
└─────────────┘ └──────────┘ └──────────────────┘
       │              │
       │              │
┌──────▼──────────────▼──────┐
│      RQ Workers             │
│  (Background Task Executor) │
└─────────────────────────────┘
```

---

## ساختار پروژه

```
apps/api/
├── alembic/                 # Database migrations
│   ├── versions/            # Migration files
│   ├── env.py              # Alembic configuration
│   └── script.py.mako      # Migration template
├── auth/                    # Authentication module
│   ├── config.py           # Auth configuration
│   ├── dependencies.py     # User manager & dependencies
│   ├── google_oauth.py     # Google OAuth setup
│   └── router.py           # Auth routes
├── clients/                 # External service clients
│   └── method_client.py    # Method service client
├── contracts/               # Contract loader
│   └── loader.py           # Load method contracts
├── database/                # Database layer
│   ├── database.py         # Database connection & session
│   ├── base.py             # Base model class
│   └── models/             # Database models
│       ├── user.py         # User model
│       ├── run.py          # Run model
│       ├── method_spec.py  # MethodSpec cache model
│       └── result.py       # Result model
├── routers/                 # API routes
│   ├── methods.py          # Methods endpoints
│   └── runs.py             # Runs endpoints
├── services/                # Business logic services
│   ├── queue.py            # Queue management
│   ├── storage.py          # Storage utilities
│   └── validate.py         # Validation utilities
├── workers/                 # Background workers
│   ├── queue.py            # RQ queue setup
│   ├── tasks.py             # Task definitions
│   └── progress.py          # Progress tracking
├── worker.py                # Worker entry point
├── main.py                  # FastAPI application
├── config.py                # Configuration
├── requirements.txt         # Python dependencies
└── alembic.ini              # Alembic configuration
```

---

## راه‌اندازی

### پیش‌نیازها

- Python 3.10+
- PostgreSQL 15+
- Redis 7+
- Docker & Docker Compose (اختیاری)

### نصب Dependencies

```bash
# ایجاد virtual environment
python -m venv .venv

# فعال‌سازی virtual environment
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# نصب dependencies
pip install -r requirements.txt
```

### تنظیم Environment Variables

یک فایل `.env` در پوشه `apps/api/` ایجاد کنید:

```env
# Database
DATABASE_URL=postgresql+asyncpg://phylo:phylo@localhost:5432/phylo

# Redis
REDIS_URL=redis://localhost:6379/0

# Authentication
SECRET_KEY=your-secret-key-here
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# Method Services
METHOD_DOWSER_URL=http://localhost:8001
METHOD_GCTREE_URL=http://localhost:8002
METHOD_BREPPHYLO_URL=http://localhost:8003
METHOD_CLONALTREE_URL=http://localhost:8004

# CORS
CORS_ORIGINS=http://localhost:3000

# Queue
RQ_WORKER_CONCURRENCY=4
RQ_QUEUE_NAME=default

# Timeouts
HTTP_CLIENT_TIMEOUT=600
SPEC_TIMEOUT=60
```

### راه‌اندازی با Docker Compose

```bash
# از root directory پروژه
docker-compose --profile dev up -d
```

این دستور تمام سرویس‌ها را شامل می‌شود:
- PostgreSQL
- Redis
- API Server
- Worker
- Method Services

### راه‌اندازی دستی

#### 1. راه‌اندازی PostgreSQL

```bash
# با Docker
docker run -d \
  --name postgres \
  -e POSTGRES_USER=phylo \
  -e POSTGRES_PASSWORD=phylo \
  -e POSTGRES_DB=phylo \
  -p 5432:5432 \
  postgres:15-alpine

# یا با نصب محلی
# (بسته به سیستم عامل)
```

#### 2. راه‌اندازی Redis

```bash
# با Docker
docker run -d \
  --name redis \
  -p 6379:6379 \
  redis:7-alpine

# یا با نصب محلی
```

#### 3. اجرای Migrations

```bash
cd apps/api
alembic upgrade head
```

#### 4. راه‌اندازی API Server

```bash
cd apps/api
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 5. راه‌اندازی Worker (در ترمینال جداگانه)

```bash
cd apps/api
python -m apps.api.worker
```

---

## دیتابیس

### مدل‌های دیتابیس

#### User
مدل کاربر با پشتیبانی از FastAPI Users و OAuth:

```python
- id: UUID (Primary Key)
- email: String (Unique, Indexed)
- hashed_password: String (Nullable - برای Google OAuth)
- is_active: Boolean
- is_superuser: Boolean
- is_verified: Boolean
- oauth_accounts: Relationship (برای Google OAuth)
- created_at: DateTime
- updated_at: DateTime
```

#### Run
مدل برای ردیابی اجرای متدها:

```python
- id: UUID (Primary Key)
- user_id: UUID (Foreign Key to User, Nullable)
- method_id: String (Indexed)
- status: Enum (PENDING, RUNNING, DONE, ERROR)
- progress: Integer (0-100)
- message: String (Nullable)
- file_path: String (Nullable)
- params: JSON (پارامترهای متد)
- created_at: DateTime
- started_at: DateTime (Nullable)
- finished_at: DateTime (Nullable)
- error: Text (Nullable)
```

#### MethodSpec
مدل برای Cache کردن مشخصات متدها:

```python
- id: UUID (Primary Key)
- method_id: String (Unique, Indexed)
- spec_data: JSON
- cached_at: DateTime
- expires_at: DateTime (Nullable)
```

#### Result
مدل برای ذخیره نتایج اجرا:

```python
- id: UUID (Primary Key)
- run_id: UUID (Foreign Key to Run, Unique)
- result_data: JSON
- created_at: DateTime
```

### استفاده از Database در کد

```python
from apps.api.database import get_db
from apps.api.database.models import Run, RunStatus
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

async def my_endpoint(session: AsyncSession = Depends(get_db)):
    # Query
    from sqlalchemy import select
    result = await session.execute(select(Run).where(Run.status == RunStatus.PENDING))
    runs = result.scalars().all()
    
    # Create
    new_run = Run(method_id="dowser", status=RunStatus.PENDING)
    session.add(new_run)
    await session.commit()
    
    return runs
```

---

## Authentication

این پروژه از **FastAPI Users** برای مدیریت Authentication استفاده می‌کند.

### روش‌های Authentication

1. **Email/Password**: ثبت‌نام و ورود با ایمیل و رمز عبور
2. **Google OAuth**: ورود با حساب Google

### Endpoints

#### ثبت‌نام
```http
POST /auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secure-password"
}
```

#### ورود
```http
POST /auth/login
Content-Type: application/json

{
  "username": "user@example.com",
  "password": "secure-password"
}
```

#### Google OAuth
```http
GET /auth/google/authorize
# Redirects to Google OAuth

GET /auth/google/callback
# Callback from Google
```

### استفاده در Endpoints

```python
from apps.api.auth.router import fastapi_users
from apps.api.database.models.user import User
from fastapi import Depends

# Required authentication
async def protected_endpoint(user: User = Depends(fastapi_users.current_user)):
    return {"user_id": str(user.id)}

# Optional authentication
async def public_endpoint(user: User | None = Depends(fastapi_users.current_user(optional=True))):
    if user:
        return {"authenticated": True, "user_id": str(user.id)}
    return {"authenticated": False}
```

---

## API Endpoints

### Methods

#### لیست متدها
```http
GET /methods
```

**Response:**
```json
{
  "status": "success",
  "data": [
    {
      "id": "dowser",
      "name": "Dowser",
      "version": "1.0.0"
    }
  ]
}
```

#### دریافت Spec متد
```http
GET /methods/{method_id}/spec
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "dowser",
    "name": "Dowser",
    "version": "1.0.0",
    "accepts": ["text/csv", "application/x-rds"],
    "paramSchema": {...},
    "uiHints": {...}
  }
}
```

### Runs

#### ایجاد Run جدید
```http
POST /runs?method={method_id}
Content-Type: multipart/form-data

params: {"key": "value"}  # JSON string
file: <file>
```

**Response:**
```json
{
  "run_id": "uuid-here"
}
```

#### دریافت وضعیت Run
```http
GET /runs/{run_id}/status
```

**Response:**
```json
{
  "status": "RUNNING",
  "progress": 45,
  "message": "Processing..."
}
```

#### دریافت نتیجه Run
```http
GET /runs/{run_id}/result
```

**Response:**
```json
{
  "ok": true,
  "trees": [...],
  "stats": {...},
  ...
}
```

#### لیست Runs
```http
GET /runs?page=1&limit=20&status=DONE&method_id=dowser
```

**Query Parameters:**
- `page`: شماره صفحه (default: 1)
- `limit`: تعداد آیتم در هر صفحه (default: 20, max: 100)
- `status`: فیلتر بر اساس وضعیت (PENDING, RUNNING, DONE, ERROR)
- `method_id`: فیلتر بر اساس متد
- `user_id`: فیلتر بر اساس کاربر (اگر authenticated باشید، فقط runs خودتان را می‌بینید)

#### لغو Run
```http
DELETE /runs/{run_id}
```

**Response:**
```json
{
  "message": "Run cancelled"
}
```

#### وضعیت Queue
```http
GET /runs/queue/status
```

**Response:**
```json
{
  "name": "default",
  "count": 5,
  "failed": 0
}
```

---

## Task Queue System

این پروژه از **RQ (Redis Queue)** برای مدیریت وظایف پس‌زمینه استفاده می‌کند.

### چرا Queue؟

- اجرای موازی چندین Run
- عدم blocking شدن API در هنگام اجرای متدهای طولانی
- امکان Retry در صورت خطا
- مدیریت بهتر منابع

### ساختار Queue

```
API Server (FastAPI)
    │
    ├─> Enqueue Task ──> Redis Queue
    │                           │
    │                           ├─> Worker 1
    │                           ├─> Worker 2
    │                           └─> Worker 3
    │
    └─> Poll Status <─── Database (Run Status)
```

### Worker

Worker وظایف را از Queue می‌خواند و اجرا می‌کند:

```bash
python -m apps.api.worker
```

یا با Docker:
```bash
docker-compose --profile dev up worker
```

### اضافه کردن Task به Queue

```python
from apps.api.services.queue import enqueue_run

# در endpoint
run_id = str(uuid.uuid4())
# ... create run in database ...
enqueue_run(run_id)  # اضافه به queue
```

### Task Execution Flow

1. کاربر درخواست ایجاد Run می‌دهد
2. API Run را در دیتابیس ایجاد می‌کند
3. Task به Queue اضافه می‌شود
4. Worker Task را از Queue می‌خواند
5. Worker با Method Service ارتباط برقرار می‌کند
6. Worker نتیجه را در دیتابیس ذخیره می‌کند
7. کاربر می‌تواند وضعیت را از طریق API بررسی کند

---

## Configuration

تمام تنظیمات از طریق Environment Variables انجام می‌شود.

### Database

- `DATABASE_URL`: Connection string برای PostgreSQL
  - Format: `postgresql+asyncpg://user:password@host:port/database`

### Redis

- `REDIS_URL`: Connection string برای Redis
  - Format: `redis://host:port/db`

### Authentication

- `SECRET_KEY`: کلید مخفی برای JWT signing
- `GOOGLE_CLIENT_ID`: Google OAuth Client ID
- `GOOGLE_CLIENT_SECRET`: Google OAuth Client Secret
- `GOOGLE_REDIRECT_URI`: Redirect URI برای Google OAuth

### Queue

- `RQ_WORKER_CONCURRENCY`: تعداد worker threads (default: 4)
- `RQ_QUEUE_NAME`: نام queue (default: "default")

### Method Services

- `METHOD_DOWSER_URL`: URL سرویس Dowser
- `METHOD_GCTREE_URL`: URL سرویس GCtree
- `METHOD_BREPPHYLO_URL`: URL سرویس BrepPhylo
- `METHOD_CLONALTREE_URL`: URL سرویس ClonalTree

### Timeouts

- `HTTP_CLIENT_TIMEOUT`: Timeout برای درخواست‌های HTTP به method services (ثانیه)
- `SPEC_TIMEOUT`: Timeout برای دریافت spec (ثانیه)

### CORS

- `CORS_ORIGINS`: لیست origins مجاز (comma-separated)

---

## Migrations

این پروژه از **Alembic** برای مدیریت migrations استفاده می‌کند.

### ایجاد Migration جدید

```bash
cd apps/api
alembic revision --autogenerate -m "description"
```

### اعمال Migrations

```bash
cd apps/api
alembic upgrade head
```

### Rollback

```bash
cd apps/api
alembic downgrade -1  # یک migration به عقب
alembic downgrade base  # به ابتدا
```

### مشاهده تاریخچه

```bash
cd apps/api
alembic history
```

### Migration Files

Migrations در پوشه `apps/api/alembic/versions/` ذخیره می‌شوند.

---

## توسعه و Debugging

### Logging

برای فعال‌سازی SQL query logging:

```env
SQL_ECHO=true
```

### Testing

```bash
# Run tests (اگر test suite وجود دارد)
pytest

# با coverage
pytest --cov=apps.api
```

### API Documentation

بعد از راه‌اندازی API، مستندات Swagger در دسترس است:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## Troubleshooting

### مشکل اتصال به دیتابیس

```bash
# بررسی اتصال
psql -h localhost -U phylo -d phylo

# بررسی logs
docker logs postgres
```

### مشکل اتصال به Redis

```bash
# بررسی اتصال
redis-cli ping

# بررسی logs
docker logs redis
```

### Worker اجرا نمی‌شود

```bash
# بررسی logs
docker logs worker

# بررسی queue
redis-cli
> LLEN rq:queue:default
```

### Migration خطا می‌دهد

```bash
# بررسی وضعیت migrations
alembic current

# بررسی history
alembic history

# اگر migration ناقص است، می‌توانید آن را حذف و دوباره ایجاد کنید
```

---

## Best Practices

1. **همیشه از async/await استفاده کنید** برای database operations
2. **Transaction management**: از `session.commit()` و `session.rollback()` به درستی استفاده کنید
3. **Error handling**: خطاها را به درستی handle کنید و به کاربر پیام مناسب بدهید
4. **Validation**: از Pydantic models برای validation استفاده کنید
5. **Security**: هرگز SECRET_KEY را در کد hardcode نکنید
6. **Logging**: از logging برای debugging استفاده کنید
7. **Testing**: قبل از commit، tests را اجرا کنید

---

## منابع و مراجع

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [FastAPI Users Documentation](https://fastapi-users.github.io/fastapi-users/)
- [SQLAlchemy Async Documentation](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [RQ Documentation](https://python-rq.org/)

---

## پشتیبانی

برای سوالات و مشکلات، لطفاً issue در repository ایجاد کنید.
