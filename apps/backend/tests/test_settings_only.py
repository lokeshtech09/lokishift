"""AI provider, model and key come only from AI connections (the Settings page)."""

import pytest

from tests.conftest import JD, make_docx

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def configure_llm() -> bool:
    return False


def test_env_keys_are_ignored(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    from app.llm import get_llm_config, llm_is_configured

    config = get_llm_config()
    assert config.api_key == "" and config.model != "env-model"
    assert not llm_is_configured(config)
    assert client.get("/api/v1/status").json()["llm_configured"] is False


def test_task_creation_requires_a_connection(client):
    pid = client.post("/api/v1/profiles", json={"title": "Python Developer"}).json()["profile_id"]
    client.post(f"/api/v1/profiles/{pid}/resumes", files={"file": ("a.docx", make_docx(), DOCX)})
    body = {"profile_id": pid, "job_title": "Dev", "job_location": "Austin", "vendor_company": "ABC", "job_description": JD}
    r = client.post("/api/v1/tasks", json=body)
    assert r.status_code == 400 and "Settings" in r.json()["detail"]


def test_default_connection_is_used(client):
    client.post("/api/v1/connections", json={"name": "A", "provider": "openai", "model": "m-a", "api_key": "sk-aaaaaaaaaaaaaaaa"})
    b = client.post("/api/v1/connections", json={"name": "B", "provider": "anthropic", "model": "m-b", "api_key": "sk-ant-bbbbbbbbbbbb"}).json()
    from app.llm import get_llm_config

    assert get_llm_config().model == "m-a"  # first connection became default
    client.post(f"/api/v1/connections/{b['connection_id']}/default")
    config = get_llm_config()
    assert (config.provider, config.model, config.api_key) == ("anthropic", "m-b", "sk-ant-bbbbbbbbbbbb")
