import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger.json import JsonFormatter

from app.api import (
    auth,
    compliance_brain,
    connectors,
    controls,
    dashboard,
    evidence,
    health,
    projects,
    reports,
    tasks,
)
from app.config import settings
from app.database import engine
from app.middleware.logging import CorrelationIdFilter, CorrelationIdMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
handler = logging.StreamHandler()
formatter = JsonFormatter(
    "%(asctime)s %(name)s %(levelname)s %(correlation_id)s %(message)s"
)
handler.setFormatter(formatter)

root = logging.getLogger()
root.handlers = [handler]
root.setLevel(logging.INFO)
root.addFilter(CorrelationIdFilter())


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(
    title="SentinellAI",
    description="AI-Powered Compliance Auditing Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# Correlation-ID middleware (outermost — runs first)
app.add_middleware(CorrelationIdMiddleware)

# Rate limiting middleware
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api/v1"

app.include_router(auth.router, prefix=PREFIX)
app.include_router(projects.router, prefix=PREFIX)
app.include_router(connectors.router, prefix=PREFIX)
app.include_router(evidence.router, prefix=PREFIX)
app.include_router(controls.router, prefix=PREFIX)
app.include_router(reports.router, prefix=PREFIX)
app.include_router(dashboard.router, prefix=PREFIX)
app.include_router(compliance_brain.router, prefix=PREFIX)
app.include_router(tasks.router, prefix=PREFIX)
app.include_router(health.router, prefix=PREFIX)

