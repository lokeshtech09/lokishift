"""API keys never leave the backend: not in responses, not in logs."""

import logging

import pytest

KEY = "sk-proj-SECRETabcdefghijklmnop1234EaoA"
GEMINI = "AIzaSyD-SECRETsecretSECRET12345"


@pytest.fixture
def configure_llm() -> bool:
    return False


def test_no_key_material_in_any_response(client):
    a = client.post("/api/v1/connections", json={"name": "OpenAI", "provider": "openai", "model": "m", "api_key": KEY})
    b = client.post("/api/v1/connections", json={"name": "Gemini", "provider": "gemini", "model": "g", "api_key": GEMINI})
    cid = a.json()["connection_id"]
    bodies = [
        a.text,
        b.text,
        client.get("/api/v1/connections").text,
        client.patch(f"/api/v1/connections/{cid}", json={"name": "Renamed"}).text,
        client.post(f"/api/v1/connections/{cid}/default").text,
        client.get("/api/v1/status").text,
        client.get("/api/v1/dashboard").text,
    ]
    for body in bodies:
        for secret in (KEY, GEMINI):
            for fragment in (secret, secret[:8], secret[-4:]):
                assert fragment not in body, (fragment, body)
    row = client.get("/api/v1/connections").json()["connections"][0]
    assert row["has_api_key"] is True and "api_key" not in row and "key_ciphertext" not in row


def test_key_can_be_replaced_or_removed_but_never_read(client):
    cid = client.post(
        "/api/v1/connections", json={"name": "OpenAI", "provider": "openai", "model": "m", "api_key": KEY}
    ).json()["connection_id"]
    # Removing the only key of a provider that needs one is refused.
    assert client.patch(f"/api/v1/connections/{cid}", json={"api_key": ""}).status_code == 422
    r = client.patch(f"/api/v1/connections/{cid}", json={"api_key": "sk-new-key-123456789"})
    assert r.status_code == 200 and r.json()["has_api_key"] is True
    from app.llm import get_llm_config

    assert get_llm_config().api_key == "sk-new-key-123456789"


def test_logs_are_scrubbed(caplog):
    from app.redact import install_log_redaction

    install_log_redaction()
    log = logging.getLogger("app.test")
    with caplog.at_level(logging.INFO):
        log.info("Incorrect API key provided: %s", KEY)
        log.warning("gemini said %s", GEMINI)
        log.info("headers: Authorization: Bearer %s", "abc.def.ghi")
        try:
            raise RuntimeError(f"AuthenticationError: api_key={KEY}")
        except RuntimeError:
            log.exception("call failed")
    text = caplog.text + "".join(r.exc_text or "" for r in caplog.records)
    for secret in (KEY, GEMINI, "abc.def.ghi"):
        assert secret not in text
    assert "<redacted>" in text


def test_servers_listen_on_this_computer_only():
    from app.config import Settings

    assert Settings.model_fields["host"].default == "127.0.0.1"


def test_log_redaction_keeps_access_log_args():
    """uvicorn's access formatter unpacks record.args; redaction must keep it a tuple."""
    from app.redact import install_log_redaction

    install_log_redaction()
    record = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api/v1/health", "1.1", 200), None,
    )
    assert record.args == ("127.0.0.1:5000", "GET", "/api/v1/health", "1.1", 200)
    leaked = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", f"/x?key={KEY}", "1.1", 200), None,
    )
    assert isinstance(leaked.args, tuple) and len(leaked.args) == 5
    assert KEY not in leaked.getMessage()
