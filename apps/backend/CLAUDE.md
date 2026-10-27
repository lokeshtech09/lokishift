# CLAUDE.md - Backend (`apps/backend`)

FastAPI backend for **LokiShift**. Python 3.13+, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + SQLite, LiteLLM, python-docx. Managed with **uv**.

## Domain

- **Profile** — one target job title (Python Developer, Data Engineer, …) with candidate details + work history.
- **ProfileResume** — N resume versions per profile, stored as the original DOCX.
- **Task** — one job application. Lifecycle: `matching → matched → tailoring → finished`, any running state → `failed`.

## Module map

| Module | Responsibility |
|---|---|
| `app/main.py` | App, lifespan (starts/stops the worker), CORS, routers under `/api/v1` |
| `app/models.py`, `app/db_engine.py`, `app/database.py` | Tables, one-time JD Studio migration, async facade returning plain dicts |
| `app/routers/profiles.py` | Profiles CRUD, DOCX upload/rename/move/replace/download |
| `app/routers/tasks.py` | Create task (queues matching), tailor, retry, rematch, download, `/dashboard`, `/reports`, notifications |
| `app/services/reports.py` | Report aggregation: trend buckets in the viewer's time zone, breakdowns (titles grouped by `title_key`), insights |
| `app/routers/connections.py`, `health.py` | AI connections CRUD/default/reorder/test (keys write-only); liveness/status |
| `app/services/worker.py` | In-process asyncio queue; DB status is the source of truth; restarts re-queue running tasks |
| `app/services/matching.py` | Ranks every resume in a profile (LLM + weighted keyword score); model-tier fallback + provider errors |
| `app/services/tailoring.py` | One-pass, no-questions tailoring: rewrites + new bullets; `is_protected()` hard-locks contact/client/date/heading lines |
| `app/services/docx_editor.py` | Reads paragraphs and writes edits/insertions back into the original DOCX |
| `app/services/jd_analysis.py`, `edit_guard.py` | JD priorities + keyword scoring; AI-phrasing polish + "added from JD" detection |
| `app/llm.py`, `app/connections.py` | LiteLLM wrapper; `get_llm_config()` = the connection the current job runs on (`use_connection`) or the default. `connection_chain()` = chosen/default then backups. Keys are encrypted per connection; `.env` is never read for them. |
| `app/redact.py` | Scrubs key-like text from every log record and error response |
| `app/model_tiers.py` | Provider error classification + quota-day helpers (no model fallback chains) |

## Rules

- Background jobs never raise out of the worker: failures are written to the task (`status="failed"`, readable `error`, `seen=False`).
- Never let tailoring touch protected paragraphs — add new patterns to `is_protected()` rather than relying on the prompt.
- AI config is Settings-page only (AI connections): never add env/`.env` lookups for provider,
  model or keys. Responses expose `has_api_key`, never key characters.
- The worker walks `connection_chain()`; only provider failures (`ProviderFailure`) move to the
  next connection — data problems (`JobError`) fail at once.
- Tests stub `_complete_json_tiered`; no test calls a real LLM. Run: `uv run pytest`.
