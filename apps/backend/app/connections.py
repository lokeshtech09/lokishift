"""AI connections: turn saved provider/model/key setups into LLM configs.

* ``get_llm_config()`` (in ``app.llm``) asks ``active_llm_config()``: the
  connection a background job is running on, else the default connection.
* ``connection_chain()`` gives a job its order of attempts: the task's chosen
  connection (or the default), then every other ``use_as_backup`` connection
  in position order.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from app.crypto import decrypt

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "openrouter": "OpenRouter",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "azure_foundry": "Azure AI Foundry",
    "ollama": "Ollama",
    "openai_compatible": "OpenAI-compatible",
}
KEYLESS_PROVIDERS = frozenset({"ollama", "openai_compatible"})


@dataclass(frozen=True)
class ActiveConnection:
    connection_id: str
    name: str
    provider: str
    model: str
    api_base: str | None
    reasoning_effort: str | None
    api_key: str  # plaintext, in memory only

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model})"

    @property
    def usable(self) -> bool:
        if self.provider in KEYLESS_PROVIDERS:
            return bool(self.api_base)
        return bool(self.api_key)

    def llm_config(self) -> Any:
        from app.llm import LLMConfig

        effort = self.reasoning_effort if self.reasoning_effort in ("minimal", "low", "medium", "high") else None
        return LLMConfig(
            provider=self.provider,
            model=self.model,
            api_key=self.api_key,
            api_base=self.api_base or None,
            reasoning_effort=effort,
        )


def _activate(row: dict[str, Any]) -> ActiveConnection:
    return ActiveConnection(
        connection_id=row["connection_id"],
        name=row["name"],
        provider=row["provider"],
        model=row["model"],
        api_base=row["api_base"],
        reasoning_effort=row["reasoning_effort"],
        api_key=decrypt(row["key_ciphertext"] or ""),
    )


def _rows() -> list[dict[str, Any]]:
    from app.database import db

    return db.list_connections_sync()


def default_connection() -> ActiveConnection | None:
    rows = _rows()
    row = next((r for r in rows if r["is_default"]), rows[0] if rows else None)
    return _activate(row) if row else None


def connection_chain(preferred_id: str | None = None) -> list[ActiveConnection]:
    """Attempt order for a job: preferred (or default) first, then backups."""
    rows = _rows()
    if not rows:
        return []
    first = next((r for r in rows if r["connection_id"] == preferred_id), None)
    first = first or next((r for r in rows if r["is_default"]), rows[0])
    backups = [r for r in rows if r is not first and r["use_as_backup"]]
    return [_activate(r) for r in [first, *backups]]


_current: ContextVar[ActiveConnection | None] = ContextVar("ai_connection", default=None)


@contextmanager
def use_connection(connection: ActiveConnection) -> Iterator[None]:
    """Run the enclosed AI calls on ``connection`` (async-task local)."""
    token = _current.set(connection)
    try:
        yield
    finally:
        _current.reset(token)


def active_connection() -> ActiveConnection | None:
    return _current.get() or default_connection()
