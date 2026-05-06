"""Enhanced health check endpoint.

Verifies all backend dependencies: PostgreSQL, Redis, and Celery.
Returns 200 when all healthy, 503 when degraded.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.database import async_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    """Comprehensive health check that verifies all backend dependencies."""
    checks: dict[str, bool] = {}

    # Database
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # Redis
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    # Celery (best-effort — ping may timeout)
    try:
        from app.workers.celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=2.0)
        ping_result = inspect.ping()
        checks["celery"] = bool(ping_result)
    except Exception:
        checks["celery"] = False

    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_healthy else "degraded",
            "checks": checks,
            "service": "sentinellai",
        },
    )
