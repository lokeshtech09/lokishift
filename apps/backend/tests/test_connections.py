"""Several AI connections: default, backup order, per-task choice, migration."""

import time

from tests.conftest import JD, make_docx

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _conn(client, name, model, **extra):
    body = {"name": name, "provider": "openai", "model": model, "api_key": f"sk-{name}-0123456789abcdef", **extra}
    r = client.post("/api/v1/connections", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(client):
    return [c["name"] for c in client.get("/api/v1/connections").json()["connections"]]


def _setup_task(client, **extra):
    pid = client.post("/api/v1/profiles", json={"title": "Python Developer", "full_name": "Jane"}).json()["profile_id"]
    client.post(f"/api/v1/profiles/{pid}/resumes", files={"file": ("a.docx", make_docx(), DOCX)})
    body = {"profile_id": pid, "job_title": "Dev", "job_location": "Austin", "vendor_company": "ABC", "job_description": JD, **extra}
    r = client.post("/api/v1/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()["task_id"]


def _wait(client, tid, done=("matched", "finished", "failed")):
    for _ in range(200):
        t = client.get(f"/api/v1/tasks/{tid}").json()
        if t["status"] in done:
            return t
        time.sleep(0.05)
    raise AssertionError(t["status"])


def test_default_reorder_and_delete_promotes_next(client):
    # conftest created "OpenAI" (default, gpt-test)
    b = _conn(client, "Backup", "m-b")
    c = _conn(client, "Claude", "m-c", make_default=True)
    rows = client.get("/api/v1/connections").json()["connections"]
    assert [r["name"] for r in rows if r["is_default"]] == ["Claude"]
    client.post("/api/v1/connections/reorder", json={"connection_ids": [c["connection_id"], b["connection_id"]]})
    assert _ids(client)[:2] == ["Claude", "Backup"]
    client.delete(f"/api/v1/connections/{c['connection_id']}")
    rows = client.get("/api/v1/connections").json()["connections"]
    assert rows[0]["name"] == "Backup" and rows[0]["is_default"] is True


def test_backup_connection_takes_over_when_default_fails(client, stub_llm):
    stub_llm["broken_models"] = {"gpt-test"}  # the default (from conftest) has no credit
    _conn(client, "Backup", "m-backup")
    tid = _setup_task(client, auto_tailor=True)
    task = _wait(client, tid, ("finished", "failed"))
    assert task["status"] == "finished", task["error"]
    assert task["llm_used"] == "Backup (m-backup)"
    assert task["tailoring"]["backup_used"] is True
    assert task["tailoring"]["failed_connections"][0].startswith("OpenAI:")


def test_backups_can_be_switched_off(client, stub_llm):
    stub_llm["broken_models"] = {"gpt-test"}
    _conn(client, "Backup", "m-backup", use_as_backup=False)
    tid = _setup_task(client)
    task = _wait(client, tid)
    # Matching falls back to keyword scores on the last connection rather than failing.
    assert task["status"] == "matched" and task["ranking"]["warning"]
    client.post(f"/api/v1/tasks/{tid}/tailor")
    task = _wait(client, tid, ("finished", "failed"))
    assert task["status"] == "failed" and "credit" in task["error"]


def test_task_can_choose_its_connection(client, stub_llm):
    special = _conn(client, "Special", "m-special")
    tid = _setup_task(client, connection_id=special["connection_id"], auto_tailor=True)
    task = _wait(client, tid, ("finished", "failed"))
    assert task["status"] == "finished" and task["llm_used"] == "Special (m-special)"
    assert "gpt-test" not in stub_llm["models"]
    assert client.post("/api/v1/tasks", json={"profile_id": task["profile_id"], "job_title": "x", "job_location": "y",
                                              "vendor_company": "z", "job_description": JD,
                                              "connection_id": "nope"}).status_code == 404


def test_every_connection_failing_lists_them(client, stub_llm):
    _conn(client, "Backup", "m-backup")
    stub_llm["broken_models"] = {"gpt-test", "m-backup"}
    tid = _setup_task(client)
    _wait(client, tid)
    client.post(f"/api/v1/tasks/{tid}/tailor")
    task = _wait(client, tid, ("finished", "failed"))
    assert task["status"] == "failed"
    assert "Every AI connection failed" in task["error"] and "OpenAI:" in task["error"] and "Backup:" in task["error"]


def test_old_keys_and_config_migrate_to_connections(tmp_path):
    import json
    import sqlite3

    from app.crypto import encrypt
    from app.database import Database

    db_path = tmp_path / "lokishift.db"
    con = sqlite3.connect(db_path)
    con.execute("create table api_keys (provider varchar primary key, ciphertext text, updated_at varchar)")
    con.execute("insert into api_keys values ('google', ?, 'x')", (encrypt("AIza-gemini-key-123"),))
    con.execute("insert into api_keys values ('openai', ?, 'x')", (encrypt("sk-openai-key-1234567"),))
    con.commit()
    con.close()
    (tmp_path / "config.json").write_text(json.dumps({"provider": "openai", "model": "gpt-6-luna", "reasoning_effort": "low"}))

    rows = Database(db_path).list_connections_sync()
    assert [(r["provider"], r["model"], r["is_default"]) for r in rows] == [
        ("openai", "gpt-6-luna", True),
        ("gemini", "gemini-3.5-flash", False),
    ]
    assert rows[0]["reasoning_effort"] == "low"
    assert not (tmp_path / "config.json").exists()
    tables = {r[0] for r in sqlite3.connect(db_path).execute("select name from sqlite_master")}
    assert "api_keys" not in tables
