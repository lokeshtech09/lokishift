"""Health check and status endpoints."""

import logging
import time

from fastapi import APIRouter

from app.database import db
from app.llm import LLMConfig, check_llm_health, get_llm_config, llm_is_configured
from app.schemas import HealthResponse, StatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])

# Returned for database_stats when the stats query itself fails, so /status can
# still respond (degraded) instead of 500-ing.
_EMPTY_DB_STATS: dict = {"profiles": 0, "resumes": 0, "total": 0}


# /status is fetched on every page load. Probing the provider each time costs a
# real completion and can exhaust free-tier quotas (e.g. Gemini's 5 requests per
# minute) before any actual work happens, so probe results are cached per
# config. POST /config/llm-test still probes live.
_HEALTHY_TTL_SECONDS = 300.0
_UNHEALTHY_TTL_SECONDS = 60.0
_llm_health_cache: dict[str, tuple[float, bool]] = {}


def _cache_key(config: LLMConfig) -> str:
    parts = [str(getattr(config, f, "")) for f in ("provider", "model", "api_base", "api_version")]
    # hash() keeps the raw key out of memory-resident cache keys.
    parts.append(str(hash(getattr(config, "api_key", "") or "")))
    return "|".join(parts)


async def _cached_llm_health(config: LLMConfig) -> bool:
    key = _cache_key(config)
    now = time.monotonic()
    cached = _llm_health_cache.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]
    healthy = bool((await check_llm_health(config)).get("healthy"))
    ttl = _HEALTHY_TTL_SECONDS if healthy else _UNHEALTHY_TTL_SECONDS
    _llm_health_cache.clear()  # only the current config matters
    _llm_health_cache[key] = (now + ttl, healthy)
    return healthy


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Lightweight liveness check for Docker HEALTHCHECK.

    Does NOT call the LLM provider. Use GET /status for full LLM health.
    """
    return HealthResponse(status="healthy")


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Get comprehensive application status.

    Each subsystem check is isolated: a failure in the LLM health probe or the
    database stats query degrades only its own field instead of 500-ing the
    whole endpoint, so the status page can still report partial/degraded state.
    """
    llm_configured = False
    llm_healthy = False
    try:
        config = get_llm_config()
        llm_configured = llm_is_configured(config)
        llm_healthy = await _cached_llm_health(config) if llm_configured else False
    except Exception:
        logger.exception("Status: LLM health check failed")

    db_stats: dict = dict(_EMPTY_DB_STATS)
    try:
        db_stats = await db.task_stats()
    except Exception:
        logger.exception("Status: database stats failed")

    has_resumes = bool(db_stats.get("resumes"))

    return StatusResponse(
        status="ready" if llm_healthy and has_resumes else "setup_required",
        llm_configured=llm_configured,
        llm_healthy=llm_healthy,
        has_resumes=has_resumes,
        database_stats=db_stats,
    )
