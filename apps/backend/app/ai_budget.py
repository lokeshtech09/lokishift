"""One cancellation budget shared by all stages of a background AI job."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar


from app.config import settings

logger = logging.getLogger(__name__)
_deadline: ContextVar[float | None] = ContextVar("ai_operation_deadline", default=None)


class AIOperationDeadlineExceeded(TimeoutError):
    """The request's shared AI operation budget has been exhausted."""


def remaining_timeout(preferred: float | None = None) -> float:
    """Cap a stage timeout at the operation's remaining monotonic budget."""
    limit = settings.request_timeout_seconds if preferred is None else preferred
    deadline = _deadline.get()
    if deadline is None:
        return float(limit)
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise AIOperationDeadlineExceeded("AI operation deadline exceeded")
    return min(float(limit), remaining)


@asynccontextmanager
async def operation_budget(seconds: float) -> AsyncIterator[None]:
    """Nested operations inherit the earliest deadline, never a fresh budget."""
    deadline = asyncio.get_running_loop().time() + seconds
    parent = _deadline.get()
    if parent is not None:
        deadline = min(deadline, parent)
    token = _deadline.set(deadline)
    try:
        async with asyncio.timeout_at(deadline):
            yield
    finally:
        _deadline.reset(token)
