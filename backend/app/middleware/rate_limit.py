"""Redis-backed sliding window rate limiter.

Prevents API abuse and protects LLM-heavy endpoints from cost overruns.
Uses Redis sorted sets for accurate sliding-window counting.
"""

from __future__ import annotations

import logging
import time

import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

logger = logging.getLogger(__name__)

# Endpoint-specific limits (requests per minute)
RATE_LIMITS: dict[str, int] = {
    "/api/v1/compliance-brain/query": 10,   # LLM-heavy
    "/api/v1/reports/export": 10,           # Resource-heavy
    "/api/v1/reports/export/oscal": 10,     # Resource-heavy
    "default": 100,                         # Standard endpoints
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(self, app):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.redis = aioredis.from_url(settings.REDIS_URL)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health checks
        if request.url.path.endswith("/health"):
            return await call_next(request)

        # Best-effort: if Redis is down, don't block the request
        try:
            return await self._apply_rate_limit(request, call_next)
        except Exception:
            logger.warning("Rate limiter unavailable — allowing request through")
            return await call_next(request)

    async def _apply_rate_limit(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        # Identify user (from JWT sub claim or IP fallback)
        user_id = "anon"
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            from jose import jwt as jose_jwt

            try:
                payload = jose_jwt.decode(
                    auth[7:],
                    settings.JWT_SECRET_KEY,
                    algorithms=[settings.JWT_ALGORITHM],
                )
                user_id = payload.get("sub", "anon")
            except Exception:
                pass

        # Determine limit for this endpoint
        path = request.url.path
        limit = RATE_LIMITS.get(path, RATE_LIMITS["default"])

        # Sliding window check
        key = f"rate_limit:{user_id}:{path}"
        now = time.time()
        window = 60  # 1 minute

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)  # Remove expired
        pipe.zadd(key, {str(now): now})               # Add current
        pipe.zcard(key)                                # Count in window
        pipe.expire(key, window)                       # TTL cleanup
        results = await pipe.execute()
        request_count = results[2]

        if request_count > limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(window)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - request_count))
        return response
