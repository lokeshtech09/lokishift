"""Provider error classification and per-day model usage helpers.

LokiShift runs exactly the model chosen on the Settings page; ``tier_models``
returns no fallback chain. What remains here classifies provider errors
(daily quota, billing, retired model, overload) and tracks the provider quota
day, which matching/tailoring use to give clear error messages.
"""

import re
import time as _clock
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import litellm


TierTask = Literal["rank", "tailor"]
# Tasks without a built-in list of their own follow the tailoring chain.

# Gemini daily quotas reset at midnight Pacific time.
_QUOTA_TZ = ZoneInfo("America/Los_Angeles")

# Gemini names the exhausted quota, e.g.
# "GenerateRequestsPerDayPerProjectPerModel-FreeTier". "limit: 0" means the
# model has no free quota at all, which is just as final for today.
_DAILY_QUOTA = re.compile(r"PerDay|limit:\s*0\b", re.IGNORECASE)
# OpenAI words "the account cannot pay" several ways; some arrive as a plain
# 429 without the ``insufficient_quota`` code.
_BILLING = re.compile(
    r"insufficient_quota|no credits remaining|exceeded your current quota", re.IGNORECASE
)


def quota_day(now: datetime | None = None) -> str:
    """The provider quota day (``YYYY-MM-DD``, Pacific) that ``now`` falls in."""
    return (now or datetime.now(_QUOTA_TZ)).astimezone(_QUOTA_TZ).date().isoformat()


def seconds_until_quota_reset(now: datetime | None = None) -> float:
    """Seconds until the next Pacific midnight, when daily quotas reset."""
    local = (now or datetime.now(_QUOTA_TZ)).astimezone(_QUOTA_TZ)
    reset = datetime.combine(local.date() + timedelta(days=1), time.min, _QUOTA_TZ)
    return (reset - local).total_seconds()


def tier_models(task: TierTask, provider: str) -> list[str]:
    """Models to try for ``task``. Always empty: LokiShift runs the one model
    chosen on the Settings page, with no hidden fallback chain."""
    return []


def task_reasoning_effort(task: TierTask) -> str | None:
    """Per-task effort overrides are not used; the Settings page value applies."""
    return None


def is_daily_quota_error(exc: BaseException) -> bool:
    """True when the provider says the model's quota for today is used up."""
    return bool(_DAILY_QUOTA.search(str(exc)))


def is_billing_error(exc: BaseException) -> bool:
    """True when the account itself cannot pay (OpenAI ``insufficient_quota``).

    Every model on the account fails the same way, so trying the rest of the
    chain only wastes time.
    """
    return bool(_BILLING.search(str(exc)))


def is_model_unavailable_error(exc: BaseException) -> bool:
    """True when the model does not exist for this key (retired, renamed, typo)."""
    return isinstance(exc, litellm.NotFoundError) or '"NOT_FOUND"' in str(exc)


def is_overloaded_error(exc: BaseException) -> bool:
    """True for a temporary provider-side overload (503 "high demand")."""
    text = str(exc)
    return isinstance(exc, litellm.ServiceUnavailableError) or '"UNAVAILABLE"' in text


# Models that just answered 503. Overload lasts minutes, and each 503 can take
# a long time to arrive, so for a short while these are tried after every other
# model instead of first. Process memory is enough: a restart simply forgets.
OVERLOAD_COOLDOWN_SECONDS = 300.0
_overloaded_until: dict[str, float] = {}


def mark_overloaded(model: str) -> None:
    _overloaded_until[model] = _clock.monotonic() + OVERLOAD_COOLDOWN_SECONDS


def mark_healthy(model: str) -> None:
    _overloaded_until.pop(model, None)


def order_by_health(models: list[str]) -> list[str]:
    """Same order, but models overloaded in the last few minutes go last."""
    now = _clock.monotonic()
    cooling = {m for m in models if _overloaded_until.get(m, 0.0) > now}
    return [m for m in models if m not in cooling] + [m for m in models if m in cooling]
