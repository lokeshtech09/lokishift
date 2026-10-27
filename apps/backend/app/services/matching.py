"""Matching: score every resume in a profile against a JD and pick the best.

Also home to the shared LLM plumbing used by matching and tailoring:
model-tier fallback, rate-limit waits and the provider error types.

The LLM judges fit; ``jd_analysis`` always adds a deterministic,
importance-weighted keyword score, so a ranking is produced even when the
LLM is unavailable.
"""

import asyncio
import logging
import re
import time
from typing import Any

import litellm

from app.ai_budget import remaining_timeout
from app.ai_limits import PromptSizeError
from app.database import db
from app.llm import (
    LLMConfig,
    complete_json,
    get_llm_config,
    get_model_name,
    get_safe_max_tokens,
)
from app.model_tiers import (
    TierTask,
    is_billing_error,
    is_daily_quota_error,
    is_model_unavailable_error,
    is_overloaded_error,
    mark_healthy,
    mark_overloaded,
    order_by_health,
    quota_day,
    seconds_until_quota_reset,
    task_reasoning_effort,
    tier_models,
)
from app.prompts.matching import RANK_BASES_PROMPT
from app.services.jd_analysis import JDAnalysis, analyze_jd, weighted_match

logger = logging.getLogger(__name__)

_JD_PROMPT_CHARS = 12_000
_BASE_PROMPT_CHARS = 9_000
_KEYWORD_LIMIT = 40


_RETRY_AFTER = re.compile(r"retry in ([\d.]+)\s*s|retryDelay\W+(\d+)s", re.IGNORECASE)
_RATE_LIMIT_MARKERS = ("resource_exhausted", "rate limit", "ratelimit", "too many requests", "quota")
_MAX_RATE_LIMIT_WAIT_SECONDS = 65.0
# Time the retried call itself needs after waiting out the provider's delay.
_CALL_HEADROOM_SECONDS = 45.0


class ProviderRateLimited(RuntimeError):
    """The LLM provider refused for quota/rate reasons and a wait did not help.

    ``daily`` means every model available for the task has used up today's
    quota, so waiting a minute will not help; ``retry_after`` is then the time
    until the quota day resets.
    """

    def __init__(
        self, retry_after: float, daily: bool = False, provider: str | None = None
    ) -> None:
        super().__init__(f"Provider rate limited; retry after {retry_after:.0f}s")
        self.retry_after = retry_after
        self.daily = daily
        self.provider = provider


class ProviderBillingError(RuntimeError):
    """The provider account has no credit (OpenAI ``insufficient_quota``)."""

    def __init__(self) -> None:
        super().__init__("Provider account has no credit")


class ProviderOverloaded(RuntimeError):
    """Every model tried was temporarily overloaded (503 "high demand")."""

    def __init__(self) -> None:
        super().__init__("All models overloaded")


def rate_limit_delay(exc: BaseException) -> float | None:
    """Seconds the provider asked us to wait, or ``None`` if not a rate limit.

    Some providers' 429s are surfaced by LiteLLM as other exception types
    (Gemini quota errors arrive as ``BadRequestError``), so the message is
    checked as well as the type.
    """
    text = str(exc)
    if not isinstance(exc, litellm.RateLimitError) and not any(
        marker in text.lower() for marker in _RATE_LIMIT_MARKERS
    ):
        return None
    match = _RETRY_AFTER.search(text)
    if match:
        return float(match.group(1) or match.group(2))
    return 20.0


async def _complete_json_patiently(**kwargs: Any) -> dict[str, Any]:
    """``complete_json`` that waits out one short provider rate limit.

    Free tiers (e.g. Gemini's per-minute request cap) reject bursts with a
    "retry in N seconds" hint. Waiting once is far better for the user than
    failing, as long as the request's own deadline leaves room for it.
    """
    try:
        return await complete_json(**kwargs)
    except Exception as exc:
        delay = rate_limit_delay(exc)
        if delay is None:
            raise
        if delay > _MAX_RATE_LIMIT_WAIT_SECONDS or delay + _CALL_HEADROOM_SECONDS > remaining_timeout():
            raise ProviderRateLimited(delay) from exc
        logger.info("Provider rate limited; waiting %.0fs before one retry", delay)
        await asyncio.sleep(delay + 1)
    try:
        return await complete_json(**kwargs)
    except Exception as exc:
        delay = rate_limit_delay(exc)
        if delay is None:
            raise
        raise ProviderRateLimited(delay) from exc


def _safe_tokens(config: LLMConfig, requested: int) -> int:
    return get_safe_max_tokens(get_model_name(config), requested=requested, config=config)


async def _complete_json_tiered(
    task: TierTask, *, max_tokens: int, **kwargs: Any
) -> tuple[dict[str, Any], str]:
    """Run ``complete_json`` on the best available model for ``task``.

    Returns the result and the model that produced it. Models move down the
    tier list when one has used up its daily quota (remembered in the
    database for the rest of the quota day) or fails outright. A per-minute
    limit is waited out once on the same model, since the better model is
    worth a short wait. Without tiers (non-Gemini provider) this is the
    configured model with the one-wait behaviour of ``_complete_json_patiently``.
    """
    base = get_llm_config()
    effort = task_reasoning_effort(task)
    if effort:
        # <TASK>_REASONING_EFFORT in .env: e.g. fast ranking, careful Add tools.
        base = base.model_copy(update={"reasoning_effort": effort})
    models = tier_models(task, base.provider)
    if not models:
        extra = {"config": base} if effort else {}
        result = await _complete_json_patiently(
            max_tokens=_safe_tokens(base, max_tokens), **extra, **kwargs
        )
        return result, base.model

    day = quota_day()
    usage = await db.get_model_usage(day)
    minute_limited: list[float] = []
    overloaded = False
    outcomes: list[str] = []  # "model: what happened", logged once if all fail
    last_error: Exception | None = None

    # Models that just returned 503 go last: a known-busy model costs time.
    for model in order_by_health(models):
        if usage.get(model, {}).get("exhausted"):
            outcomes.append(f"{model}: skipped (used up or unavailable today)")
            continue
        # No Router retries: on a 429 the quota decides, and on a 503 the next
        # model answers sooner than a retry of an overloaded one.
        config = base.model_copy(
            update={"model": model, "rate_limit_retries": 0, "num_retries": 0}
        )
        started = time.monotonic()
        call = {**kwargs, "config": config, "max_tokens": _safe_tokens(config, max_tokens)}
        for attempt in range(2):
            try:
                result = await complete_json(**call)
            except (TimeoutError, PromptSizeError):
                raise  # the request's own deadline / input limit, not the model's fault
            except Exception as exc:
                last_error = exc
                if is_billing_error(exc):
                    # Account-wide: every other model would fail the same way.
                    logger.error("%s: %s refused, account has no credit", task, model)
                    raise ProviderBillingError() from exc
                delay = rate_limit_delay(exc)
                if delay is not None and is_daily_quota_error(exc):
                    reason = "daily quota used up"
                    await db.record_model_call(day, model, succeeded=False, exhausted=True)
                elif is_model_unavailable_error(exc):
                    # Retired or renamed: skip it for the rest of the day.
                    reason = "model not available (404)"
                    await db.record_model_call(day, model, succeeded=False, exhausted=True)
                elif delay is not None:
                    fits = (
                        delay <= _MAX_RATE_LIMIT_WAIT_SECONDS
                        and delay + _CALL_HEADROOM_SECONDS <= remaining_timeout()
                    )
                    if attempt == 0 and fits:
                        logger.info("%s: %s rate limited; waiting %.0fs", task, model, delay)
                        await asyncio.sleep(delay + 1)
                        continue
                    reason = "per-minute rate limit"
                    minute_limited.append(delay)
                elif is_overloaded_error(exc):
                    reason = "overloaded (503)"
                    overloaded = True
                    mark_overloaded(model)
                else:
                    reason = f"failed: {type(exc).__name__}"
                    logger.debug("%s: %s error detail: %s", task, model, exc)
                reason += f" after {time.monotonic() - started:.0f}s"
                outcomes.append(f"{model}: {reason}")
                logger.warning("%s: %s %s, trying next model", task, model, reason)
                break
            else:
                await db.record_model_call(day, model, succeeded=True)
                mark_healthy(model)
                logger.info("%s: %s answered in %.0fs", task, model, time.monotonic() - started)
                if model != models[0]:
                    logger.info(
                        "%s: served by fallback model %s (%s)", task, model, "; ".join(outcomes)
                    )
                return result, model

    logger.error("%s: no model succeeded: %s", task, "; ".join(outcomes))
    if minute_limited:
        raise ProviderRateLimited(min(minute_limited)) from last_error
    if overloaded:
        raise ProviderOverloaded() from last_error
    if last_error is None or is_daily_quota_error(last_error) or is_model_unavailable_error(
        last_error
    ):
        # Every model was already out of quota, or the last one ran out now.
        raise ProviderRateLimited(
            seconds_until_quota_reset(), daily=True, provider=base.provider
        ) from last_error
    raise last_error


def score_text(job_description: str, text: str) -> dict[str, Any]:
    """Importance-weighted JD keyword coverage of ``text`` (0–100)."""
    return weighted_match(analyze_jd(job_description), text)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[...truncated]"


def _clamp_score(value: Any) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _str_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _priorities_block(analysis: JDAnalysis) -> str:
    lines = []
    if analysis.must_have:
        lines.append("Must-have (from the requirements section): " + ", ".join(analysis.must_have))
    if analysis.nice_to_have:
        lines.append("Secondary / nice-to-have: " + ", ".join(analysis.nice_to_have))
    if analysis.years_required:
        lines.append(f"Experience asked for: {analysis.years_required}+ years")
    return "\n".join(lines) or "(no specific skills detected; judge from the JD text)"


async def rank_bases(job_description: str, bases: list[dict[str, Any]]) -> dict[str, Any]:
    """Score every base resume against the JD and recommend one.

    ``bases`` items need ``base_id``, ``name`` and ``text``. The LLM judges fit;
    a deterministic, importance-weighted keyword score is always attached. If
    the LLM fails, the keyword score alone decides and a warning is returned.
    """
    if not bases:
        raise ValueError("No base resumes to rank.")

    analysis = analyze_jd(job_description)
    keyword_scores = {b["base_id"]: weighted_match(analysis, b["text"]) for b in bases}
    known_ids = {b["base_id"] for b in bases}

    def validate(result: dict[str, Any]) -> dict[str, Any]:
        rankings = result.get("rankings")
        if not isinstance(rankings, list) or not rankings:
            raise ValueError("rankings missing")
        seen = {r.get("base_id") for r in rankings if isinstance(r, dict)}
        if not known_ids <= seen:
            raise ValueError("rankings must cover every base resume")
        return result

    resumes_block = "\n\n".join(
        f'=== base_id: "{b["base_id"]}" | name: {b["name"]} ===\n'
        f"{_clip(b['text'], _BASE_PROMPT_CHARS)}"
        for b in bases
    )
    warning: str | None = None
    llm: dict[str, Any] = {}
    model: str | None = None
    try:
        llm, model = await _complete_json_tiered(
            "rank",
            prompt=RANK_BASES_PROMPT.format(
                job_description=_clip(analysis.cleaned_text, _JD_PROMPT_CHARS),
                priorities=_priorities_block(analysis),
                resumes=resumes_block,
            ),
            system_prompt="You are a precise, evidence-driven technical recruiter.",
            max_tokens=4096,
            schema_type="keywords",
            response_validator=validate,
        )
    except ProviderRateLimited as exc:
        logger.warning("Base ranking rate limited (daily=%s), using keyword scores", exc.daily)
        if exc.daily:
            warning = (
                "Every AI model for ranking has used up today's quota, so bases were "
                "ranked by keyword match only."
            )
        else:
            warning = (
                "The AI provider's rate limit was reached, so bases were ranked by keyword "
                "match only. Wait a minute and start a new run for AI scores."
            )
    except ProviderOverloaded:
        logger.warning("Base ranking: every model overloaded, using keyword scores")
        warning = (
            "The AI models are overloaded right now, so bases were ranked by keyword "
            "match only. Try a new run in a few minutes for AI scores."
        )
    except ProviderBillingError:
        warning = (
            "The AI provider account has no credit left, so bases were ranked by "
            "keyword match only. Add credit or switch provider in Settings."
        )
    except Exception as exc:  # provider errors vary; keyword ranking still works
        logger.warning("Base ranking LLM call failed, using keyword scores: %s", exc)
        warning = "AI ranking was unavailable, so bases were ranked by keyword match only."

    by_id = {
        r["base_id"]: r
        for r in llm.get("rankings", [])
        if isinstance(r, dict) and r.get("base_id") in known_ids
    }
    rankings = []
    for base in bases:
        ai = by_id.get(base["base_id"], {})
        kw = keyword_scores[base["base_id"]]
        rankings.append(
            {
                "base_id": base["base_id"],
                "name": base["name"],
                "ai_score": _clamp_score(ai["score"]) if "score" in ai else None,
                "keyword_score": kw["score"],
                "matched_keywords": kw["matched"],
                "missing_keywords": kw["missing"],
                "strengths": _str_list(ai.get("strengths"), 4),
                "gaps": _str_list(ai.get("gaps"), 4),
                "reasoning": str(ai.get("reasoning") or "").strip(),
            }
        )

    def sort_key(r: dict[str, Any]) -> tuple[int, int]:
        return (r["ai_score"] if r["ai_score"] is not None else -1, r["keyword_score"])

    rankings.sort(key=sort_key, reverse=True)
    recommended = llm.get("recommended_base_id")
    if recommended not in known_ids:
        recommended = rankings[0]["base_id"]

    return {
        "company": str(llm.get("company") or "").strip()[:120],
        "role": str(llm.get("role") or "").strip()[:120],
        "must_have_skills": analysis.must_have or _str_list(llm.get("must_have_skills"), 12),
        "nice_to_have_skills": analysis.nice_to_have,
        "years_required": analysis.years_required,
        "keywords": analysis.ranked_terms[:_KEYWORD_LIMIT],
        "rankings": rankings,
        "recommended_base_id": recommended,
        "warning": warning,
        "model": model,
    }


async def rank_resumes(job_description: str, resumes: list[dict[str, Any]]) -> dict[str, Any]:
    """``rank_bases`` in profile terms: ``resumes`` items need ``resume_id``, ``name``, ``text``.

    Each ranking gets a single ``score`` (AI score when available, else the
    keyword score) so the UI shows one number.
    """
    result = await rank_bases(
        job_description,
        [{"base_id": r["resume_id"], "name": r["name"], "text": r["text"]} for r in resumes],
    )
    for ranking in result["rankings"]:
        ranking["resume_id"] = ranking.pop("base_id")
        ai = ranking["ai_score"]
        ranking["score"] = ai if ai is not None else ranking["keyword_score"]
    result["recommended_resume_id"] = result.pop("recommended_base_id")
    return result
