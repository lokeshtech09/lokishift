"""AI connections: saved provider + model + key setups, one of them default.

Keys are write-only. Responses carry ``has_api_key`` and never any part of a
key; the test endpoint scrubs provider error text before returning it.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from app.connections import KEYLESS_PROVIDERS, PROVIDER_LABELS, _activate
from app.crypto import encrypt
from app.database import db
from app.llm import check_llm_health
from app.schemas import ConnectionCreate, ConnectionUpdate, ReorderRequest

router = APIRouter(prefix="/connections", tags=["AI connections"])


def _public(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k != "key_ciphertext"}
    out["has_api_key"] = bool(row.get("key_ciphertext"))
    out["provider_label"] = PROVIDER_LABELS.get(row["provider"], row["provider"])
    out["needs_api_key"] = row["provider"] not in KEYLESS_PROVIDERS
    return out


def _clean_base(value: str | None) -> str | None:
    return (value or "").strip() or None


def _validate(provider: str, api_base: str | None, has_key: bool) -> None:
    if provider == "azure_foundry" and not api_base:
        raise HTTPException(status_code=422, detail="Azure AI Foundry needs a base URL.")
    if provider in KEYLESS_PROVIDERS and not api_base:
        raise HTTPException(status_code=422, detail="Local servers need a base URL, e.g. http://localhost:11434.")
    if provider not in KEYLESS_PROVIDERS and not has_key:
        raise HTTPException(status_code=422, detail="Add the API key for this provider.")


async def _require(connection_id: str) -> dict[str, Any]:
    row = await db.get_connection(connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return row


@router.get("")
async def list_connections() -> dict[str, Any]:
    return {"connections": [_public(r) for r in await db.list_connections()]}


@router.post("")
async def create_connection(request: ConnectionCreate) -> dict[str, Any]:
    api_key = (request.api_key or "").strip()
    api_base = _clean_base(request.api_base)
    _validate(request.provider, api_base, bool(api_key))
    row = await db.create_connection(
        {
            "name": request.name.strip(),
            "provider": request.provider,
            "model": request.model.strip(),
            "api_base": api_base,
            "reasoning_effort": request.reasoning_effort,
            "key_ciphertext": encrypt(api_key) if api_key else None,
            "use_as_backup": request.use_as_backup,
            "make_default": request.make_default,
        }
    )
    return _public(row)


@router.patch("/{connection_id}")
async def update_connection(connection_id: str, request: ConnectionUpdate) -> dict[str, Any]:
    current = await _require(connection_id)
    values: dict[str, Any] = {}
    fields = request.model_fields_set
    for field in ("name", "provider", "model", "use_as_backup"):
        if field in fields and getattr(request, field) is not None:
            value = getattr(request, field)
            values[field] = value.strip() if isinstance(value, str) else value
    if "api_base" in fields:
        values["api_base"] = _clean_base(request.api_base)
    if "reasoning_effort" in fields:
        values["reasoning_effort"] = request.reasoning_effort or None
    if "api_key" in fields and request.api_key is not None:
        key = request.api_key.strip()
        values["key_ciphertext"] = encrypt(key) if key else None
    merged = {**current, **values}
    _validate(merged["provider"], merged["api_base"], bool(merged["key_ciphertext"]))
    row = await db.update_connection(connection_id, values)
    assert row is not None
    return _public(row)


@router.post("/{connection_id}/default")
async def make_default(connection_id: str) -> dict[str, Any]:
    if not await db.set_default_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return await list_connections()


@router.post("/reorder")
async def reorder(request: ReorderRequest) -> dict[str, Any]:
    """Set the backup order (the default is always tried first)."""
    await db.reorder_connections(request.connection_ids)
    return await list_connections()


@router.post("/{connection_id}/test")
async def test_connection(connection_id: str) -> dict[str, Any]:
    connection = _activate(await _require(connection_id))
    if not connection.usable:
        return {"healthy": False, "error_detail": "This connection has no API key or base URL yet."}
    # check_llm_health scrubs key-like text from error_detail.
    return await check_llm_health(connection.llm_config(), include_details=True, test_prompt="Hi")


@router.delete("/{connection_id}")
async def delete_connection(connection_id: str) -> dict[str, Any]:
    if not await db.delete_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return await list_connections()
