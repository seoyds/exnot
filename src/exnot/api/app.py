"""FastAPI application - API + Dashboard."""

import logging
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from exnot.api.routes import admin, auth, changes, comparisons, exchanges, fees, subscriptions
from exnot.config import get_settings

settings = get_settings()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

app = FastAPI(
    title="ExNot - US Options Exchange Fee Schedule Normalizer",
    description=(
        "Collects, normalizes, and monitors fee schedules from all 19 US options exchanges. "
        "Provides real-time change detection and email notifications."
    ),
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# --- API routes ---
app.include_router(exchanges.router, prefix="/api/v1")
app.include_router(fees.router, prefix="/api/v1")
app.include_router(comparisons.router, prefix="/api/v1")
app.include_router(changes.router, prefix="/api/v1")
app.include_router(subscriptions.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")

# --- Dashboard routes ---
try:
    from exnot.dashboard.routes import router as dashboard_router

    app.include_router(dashboard_router)
except ImportError:
    pass

# --- Static files ---
static_dir = Path(__file__).parent.parent / "dashboard" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/ready")
async def readiness_check():
    """Check if the app is ready (database connection, etc.)."""
    try:
        from exnot.db.engine import get_async_engine

        engine = get_async_engine()
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not_ready", "error": str(e)}


@app.on_event("startup")
async def startup_event():
    """Create admin user on first startup if it doesn't exist."""
    from exnot.api.deps import hash_password
    from exnot.db.engine import AsyncSessionLocal
    from exnot.db.models import User
    from exnot.db.repositories import UserRepository

    try:
        async with AsyncSessionLocal() as session:
            repo = UserRepository(session)
            admin = await repo.get_by_email(settings.admin_email)
            if not admin:
                admin_user = User(
                    email=settings.admin_email,
                    username="admin",
                    hashed_password=hash_password(settings.admin_password),
                    is_admin=True,
                )
                await repo.create(admin_user)
                await session.commit()
                logging.getLogger(__name__).info("Admin user created")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Could not create admin user on startup: {e}")
