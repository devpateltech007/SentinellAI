import asyncio
import json

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession, get_current_user
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("/{task_id}/stream")
async def stream_task_status(
    task_id: str,
    db: DbSession,
    token: str = Query(default=None),
    authorization: str | None = Header(default=None),
):
    """Stream Celery task status via Server-Sent Events."""

    # SSE does not support standard auth headers natively in the browser's EventSource.
    # Therefore, we support passing the token as a query parameter.
    actual_token = token
    if not actual_token and authorization and authorization.startswith("Bearer "):
        actual_token = authorization.split(" ")[1]

    if not actual_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Reuse the existing dependency logic to decode and validate token
        current_user = await get_current_user(token=actual_token, db=db)
    except HTTPException:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def event_generator():
        previous_state = None
        while True:
            result = celery_app.AsyncResult(task_id)
            state = result.state  # PENDING, STARTED, SUCCESS, FAILURE, RETRY, REVOKED

            if state != previous_state:
                # Build SSE event payload
                data = {
                    "task_id": task_id,
                    "state": state,
                    "result": None,
                    "error": None,
                }

                if state == "SUCCESS":
                    data["result"] = result.result
                elif state == "FAILURE":
                    data["error"] = str(result.info)

                yield f"data: {json.dumps(data)}\n\n"
                previous_state = state

            # Stop streaming on terminal states
            if state in ("SUCCESS", "FAILURE", "REVOKED"):
                break

            await asyncio.sleep(2)  # Poll every 2 seconds

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
