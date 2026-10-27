import time

from tests.conftest import JD, make_docx

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _wait(client, task_id, statuses=("matched", "finished", "failed"), timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/v1/tasks/{task_id}").json()
        if task["status"] in statuses:
            return task
        time.sleep(0.05)
    raise AssertionError(f"task stuck in {task['status']}")


def _profile_with_resumes(client):
    profile = client.post("/api/v1/profiles", json={"title": "Python Developer", "full_name": "Jane Doe"}).json()
    pid = profile["profile_id"]
    for name, bullets in (
        ("Plain", None),
        ("Streaming", ["Built Kafka consumers in Python.", "Ran services on Kubernetes."]),
    ):
        r = client.post(f"/api/v1/profiles/{pid}/resumes", files={"file": (f"{name}.docx", make_docx(bullets), DOCX)}, data={"name": name})
        assert r.status_code == 200, r.text
    return pid


def _task(pid, **extra):
    return {"profile_id": pid, "job_title": "Senior Python Developer", "job_location": "Austin, TX",
            "vendor_company": "ABC Staffing", "job_description": JD, **extra}


def test_profile_crud_and_resume_upload(client):
    pid = _profile_with_resumes(client)
    profile = client.get(f"/api/v1/profiles/{pid}").json()
    assert [r["name"] for r in profile["resumes"]] == ["Plain", "Streaming"]
    assert "docx" not in profile["resumes"][0]
    upd = client.patch(f"/api/v1/profiles/{pid}", json={"total_experience": "8 years", "experience": [{"title": "Engineer", "company": "Acme"}]})
    assert upd.json()["experience"][0]["company"] == "Acme"
    listing = client.get("/api/v1/profiles").json()["profiles"]
    assert listing[0]["resume_count"] == 2


def test_rejects_non_docx(client):
    pid = client.post("/api/v1/profiles", json={"title": "X"}).json()["profile_id"]
    r = client.post(f"/api/v1/profiles/{pid}/resumes", files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 400
    r = client.post(f"/api/v1/profiles/{pid}/resumes", files={"file": ("a.docx", b"not a zip", DOCX)})
    assert r.status_code == 422


def test_task_matches_then_tailors_in_background(client, stub_llm):
    pid = _profile_with_resumes(client)
    created = client.post("/api/v1/tasks", json=_task(pid))
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "matching"

    task = _wait(client, created.json()["task_id"])
    assert task["status"] == "matched"
    streaming = next(r for r in task["ranking"]["rankings"] if r["name"] == "Streaming")
    assert task["best_resume_id"] == streaming["resume_id"]
    assert task["match_score"] == 90

    r = client.post(f"/api/v1/tasks/{task['task_id']}/tailor")
    assert r.json()["status"] == "tailoring"
    task = _wait(client, task["task_id"], ("finished", "failed"))
    assert task["status"] == "finished", task["error"]
    report = task["tailoring"]
    # The protected phone line edit was dropped; summary edit and new bullet kept.
    assert [e["index"] for e in report["edits"]] != [] and all(e["index"] != 1 for e in report["edits"])
    assert len(report["additions"]) == 1
    assert task["tailored_filename"] == "Jane Doe - Senior Python Developer - ABC Staffing.docx"
    assert task["seen"] is False

    dash = client.get("/api/v1/dashboard").json()
    assert dash["stats"]["completed"] == 1 and dash["stats"]["week_count"] == 1
    assert [n["task_id"] for n in dash["notifications"]] == [task["task_id"]]
    client.post("/api/v1/tasks/seen", json=[task["task_id"]])
    assert client.get("/api/v1/dashboard").json()["notifications"] == []

    download = client.get(f"/api/v1/tasks/{task['task_id']}/download")
    assert download.status_code == 200
    import io, docx
    texts = [p.text for p in docx.Document(io.BytesIO(download.content)).paragraphs]
    assert "Email: jane@example.com | Phone: 512-555-0100" in texts
    assert "Built event-driven microservices with Kafka on Kubernetes." in texts
    assert any(t.startswith("Senior Python developer with 8 years") for t in texts)


def test_auto_tailor(client, stub_llm):
    pid = _profile_with_resumes(client)
    tid = client.post("/api/v1/tasks", json=_task(pid, auto_tailor=True)).json()["task_id"]
    task = _wait(client, tid, ("finished", "failed"))
    assert task["status"] == "finished" and stub_llm["tailor"] == 1


def test_failure_is_recorded_and_retry_works(client, stub_llm):
    pid = _profile_with_resumes(client)
    tid = client.post("/api/v1/tasks", json=_task(pid)).json()["task_id"]
    _wait(client, tid)
    stub_llm["fail_tailor"] = RuntimeError("Connection error.")
    client.post(f"/api/v1/tasks/{tid}/tailor")
    task = _wait(client, tid, ("finished", "failed"))
    assert task["status"] == "failed" and "reach the AI provider" in task["error"]
    assert client.get("/api/v1/dashboard").json()["stats"]["failed"] == 1

    stub_llm["fail_tailor"] = None
    assert client.post(f"/api/v1/tasks/{tid}/retry").json()["status"] == "tailoring"
    assert _wait(client, tid, ("finished", "failed"))["status"] == "finished"


def test_tailor_a_chosen_resume(client):
    pid = _profile_with_resumes(client)
    tid = client.post("/api/v1/tasks", json=_task(pid)).json()["task_id"]
    task = _wait(client, tid)
    plain = next(r for r in task["ranking"]["rankings"] if r["name"] == "Plain")
    client.post(f"/api/v1/tasks/{tid}/tailor", json={"resume_id": plain["resume_id"]})
    task = _wait(client, tid, ("finished", "failed"))
    assert task["tailored_resume_id"] == plain["resume_id"]


def test_task_requires_resumes_and_has_no_limit(client):
    empty = client.post("/api/v1/profiles", json={"title": "Empty"}).json()["profile_id"]
    assert client.post("/api/v1/tasks", json=_task(empty)).status_code == 400

    pid = _profile_with_resumes(client)
    for _ in range(3):
        assert client.post("/api/v1/tasks", json=_task(pid)).status_code == 200
    stats = client.get("/api/v1/dashboard").json()["stats"]
    assert stats["week_count"] == 3 and "weekly_limit" not in stats


def test_is_protected():
    from app.services.docx_editor import DocxParagraph
    from app.services.tailoring import is_protected

    def p(text, index=5, style="Normal"):
        return DocxParagraph(index=index, text=text, style=style, is_list=False, editable=True)

    for text in ("Email: a@b.com", "Ph No: 555-010-0199", "Client: Acme Bank, Springfield, IL",
                 "Duration: April 2025- Till Date", "Work Experience:", "Jan 2019 – Present",
                 "https://linkedin.com/in/x"):
        assert is_protected(p(text)), text
    for text in ("Senior Data Engineer", "Built Spark pipelines on AWS Glue.",
                 "Languages: Python, SQL, Scala"):
        assert not is_protected(p(text)), text


def test_previous_database_name_is_adopted(tmp_path):
    import sqlite3

    from app.database import Database

    old = tmp_path / "lokicv.db"
    sqlite3.connect(old).execute("create table marker (x)").connection.commit()
    new = tmp_path / "lokishift.db"
    Database(new)
    assert new.exists() and not old.exists()
    assert sqlite3.connect(new).execute("select name from sqlite_master").fetchone() == ("marker",)


def test_list_tasks_by_period_and_running(client):
    pid = _profile_with_resumes(client)
    tid = client.post("/api/v1/tasks", json=_task(pid)).json()["task_id"]
    _wait(client, tid)
    ids = lambda r: [t["task_id"] for t in r.json()["tasks"]]  # noqa: E731
    assert ids(client.get("/api/v1/tasks", params={"created_from": "2020-01-01T00:00:00Z"})) == [tid]
    assert ids(client.get("/api/v1/tasks", params={"created_to": "2020-01-01T00:00:00Z"})) == []
    assert ids(client.get("/api/v1/tasks", params={"created_from": "2099-01-01T00:00:00-05:00"})) == []
    assert ids(client.get("/api/v1/tasks", params={"status": "running"})) == []
    assert client.get("/api/v1/tasks", params={"status": "nope"}).status_code == 400
