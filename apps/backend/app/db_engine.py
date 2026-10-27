"""SQLite engine/session plumbing for the SQLAlchemy data layer.

Every ``Database`` instance owns its own engines (one async for the document
tables, one sync for the encrypted ``api_keys`` table read on the synchronous
LLM hot path) built from these factories. Keeping construction here lets tests
spin up fully isolated engines against a temp-file database.
"""

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.models import Base

__all__ = ["Base", "make_async_engine", "make_sync_engine", "init_models_sync"]


def _apply_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """Set per-connection SQLite PRAGMAs.

    WAL improves concurrent read/write between the async (doc tables) and sync
    (api_keys) engines pointed at the same file; ``busy_timeout`` rides out the
    brief lock contention that creates; ``foreign_keys`` enforces relational
    integrity (off by default in SQLite).
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def _url(path: Path, *, driver: str) -> str:
    """Build a SQLite URL. Absolute paths yield the required four slashes."""
    return f"sqlite+{driver}:///{path}" if driver else f"sqlite:///{path}"


def make_async_engine(path: Path) -> AsyncEngine:
    """Create the async engine (``aiosqlite``) for the document tables."""
    engine = create_async_engine(_url(path, driver="aiosqlite"), future=True)
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    return engine


def make_sync_engine(path: Path) -> Engine:
    """Create the sync engine used for the encrypted api_keys table.

    Key reads happen synchronously (``get_llm_config`` → ``load_config_file`` →
    ``resolve_api_key``), so a sync engine avoids threading async through
    ``llm.py``. It points at the same file as the async engine.
    """
    engine = create_engine(_url(path, driver=""), future=True)
    event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "azure_foundry": "Azure AI Foundry",
    "ollama": "Ollama",
    "openai_compatible": "OpenAI-compatible",
}
# Key-store names used by the old api_keys table -> provider ids.
_KEYSTORE_TO_PROVIDER = {"google": "gemini"}
_DEFAULT_MODELS = {
    "openai": "gpt-5.4-mini",
    "anthropic": "claude-sonnet-5-5",
    "gemini": "gemini-3.5-flash",
    "deepseek": "deepseek-chat",
}


def init_models_sync(engine: Engine) -> None:
    """Create all tables (idempotent) and apply small additive migrations."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        task_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(tasks)")}
        for column in ("connection_id", "llm_used"):
            if column not in task_columns:
                conn.exec_driver_sql(f"ALTER TABLE tasks ADD COLUMN {column} VARCHAR")
        tables = {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
        if "api_keys" in tables:
            _migrate_keys_to_connections(conn, Path(engine.url.database or ""))


def _migrate_keys_to_connections(conn: Any, db_path: Path) -> None:
    """Turn the old per-provider keys + config.json into AI connections, once.

    Ciphertexts are copied as-is (same encryption key). The provider/model that
    was active becomes the default connection.
    """
    import json
    from uuid import uuid4

    from app.models import utcnow_iso

    config_path = db_path.with_name("config.json")
    try:
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
    except (OSError, ValueError):
        config = {}
    active = config.get("provider") or "openai"
    has_connections = conn.exec_driver_sql("SELECT COUNT(*) FROM ai_connections").scalar()
    if not has_connections:
        rows = conn.exec_driver_sql("SELECT provider, ciphertext FROM api_keys").all()
        ordered = sorted(rows, key=lambda r: _KEYSTORE_TO_PROVIDER.get(r[0], r[0]) != active)
        for position, (store_name, ciphertext) in enumerate(ordered):
            provider = _KEYSTORE_TO_PROVIDER.get(store_name, store_name)
            is_active = provider == active
            model = (config.get("model") if is_active else None) or _DEFAULT_MODELS.get(provider, "")
            now = utcnow_iso()
            conn.exec_driver_sql(
                "INSERT INTO ai_connections (connection_id, name, provider, model, api_base, "
                "reasoning_effort, key_ciphertext, is_default, use_as_backup, position, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (
                    str(uuid4()),
                    _PROVIDER_LABELS.get(provider, provider),
                    provider,
                    model,
                    config.get("api_base") if is_active else None,
                    config.get("reasoning_effort") if is_active else None,
                    ciphertext,
                    1 if position == 0 else 0,
                    position,
                    now,
                    now,
                ),
            )
    conn.exec_driver_sql("DROP TABLE api_keys")
    if config_path.exists():
        config_path.unlink()
