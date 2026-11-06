"""Tailoring rules: same length, swaps only, key skills in recent roles, ATS >= 95."""

import io
from typing import Any

import docx
import pytest

from app.services import tailoring
from app.services.docx_editor import apply_edits, read_paragraphs

JD = (
    "Senior Data Engineer\n\nRequirements:\n"
    "- Strong Python and SQL\n- Must have Spark and Airflow\n- Snowflake required\n"
    "- AWS (Glue, S3)\n\nResponsibilities:\n- Build batch and streaming pipelines with Kafka\n"
)


def resume() -> bytes:
    d = docx.Document()
    d.add_paragraph("Ravi Kumar")
    d.add_paragraph("Email: ravi@example.com | Phone: 512-555-0101")
    d.add_paragraph("Professional Summary:")
    d.add_paragraph("Data engineer with 7 years of experience building data pipelines and reports.")
    d.add_paragraph("Technical Skills:")
    d.add_paragraph("Skills: Python, SQL, Pandas, Hadoop, Tableau, Excel")
    d.add_paragraph("Professional Experience:")
    roles = [
        ("Client: Delta Bank, Dallas, TX", "Duration: Jan 2023 - Present"),
        ("Client: Orion Health, Austin, TX", "Duration: Mar 2021 - Dec 2022"),
        ("Client: Nova Retail, Plano, TX", "Duration: Jun 2019 - Feb 2021"),
        ("Client: Old Mutual, Houston, TX", "Duration: Jan 2016 - May 2019"),
    ]
    for client, dates in roles:
        d.add_paragraph(client)
        d.add_paragraph(dates)
        for text in (
            "Built data pipelines in Python to load daily transaction files into the warehouse.",
            "Wrote SQL queries and stored procedures for monthly finance reports.",
            "Maintained Excel macros used by the operations team for reconciliations.",
        ):
            d.add_paragraph(text, style="List Bullet")
    d.add_paragraph("EDUCATION")
    d.add_paragraph("Bachelor of Technology, JNTU University, 2011 - 2015")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def index_of(paragraphs, text: str, nth: int = 0) -> int:
    return [p.index for p in paragraphs if text in p.text][nth]


def test_detect_roles_finds_clients_in_order_and_skips_education():
    paragraphs = read_paragraphs(resume())
    layout = tailoring.detect_roles(paragraphs)
    assert sorted(set(layout.role_of.values())) == [1, 2, 3, 4]
    assert layout.role_names[1].startswith("Client: Delta Bank")
    assert all(len(layout.bullets(r)) == 3 for r in (1, 2, 3, 4))
    assert layout.top_roles == [1, 2, 3]
    summary = index_of(paragraphs, "Data engineer with 7 years")
    assert summary not in layout.role_of  # summary and skills are not role bullets


def test_apply_edits_can_remove_a_paragraph():
    content = resume()
    paragraphs = read_paragraphs(content)
    weak = index_of(paragraphs, "Excel macros")
    anchor = index_of(paragraphs, "Wrote SQL queries")
    out = read_paragraphs(apply_edits(content, {}, [(anchor, "Built Airflow DAGs.")], [weak]))
    texts = [p.text for p in out]
    assert len(out) == len(paragraphs)
    assert texts.count("Built Airflow DAGs.") == 1
    assert sum("Excel macros" in t for t in texts) == 3  # only the first role's copy went


@pytest.fixture
def fake_llm(monkeypatch):
    calls: dict[str, Any] = {"prompts": []}
    responses: list[dict[str, Any]] = []

    async def fake(task: str, **kwargs: Any):
        calls["prompts"].append(kwargs["prompt"])
        return responses.pop(0), "stub"

    monkeypatch.setattr(tailoring, "_complete_json_tiered", fake)
    calls["responses"] = responses
    return calls


async def test_tailoring_keeps_length_swaps_and_reaches_ats_target(fake_llm):
    content = resume()
    paragraphs = read_paragraphs(content)
    summary = index_of(paragraphs, "Data engineer with 7 years")
    r1_pipe, r1_sql, r1_excel = (index_of(paragraphs, t, 0) for t in ("Built data pipelines", "Wrote SQL", "Excel macros"))
    r2_pipe, r2_excel = index_of(paragraphs, "Built data pipelines", 1), index_of(paragraphs, "Excel macros", 1)
    r3_pipe = index_of(paragraphs, "Built data pipelines", 2)
    r4_excel = index_of(paragraphs, "Excel macros", 3)

    fake_llm["responses"] += [
        {
            "summary": "stub",
            "edits": [
                {"index": r1_pipe, "new_text": "Built Spark pipelines in Python to load daily transaction files into Snowflake.", "keywords": []},
                {"index": r1_sql, "new_text": "Wrote SQL queries and stored procedures for monthly finance reports, " * 3, "keywords": []},  # far too long: dropped
            ],
            "swaps": [
                {"remove": r1_excel, "after": r1_sql, "text": "Scheduled batch jobs with Airflow DAGs and AWS Glue jobs.", "keywords": []},
                {"remove": r2_excel, "after": r2_pipe, "text": "Built many new things " * 10, "keywords": []},  # longer than removed: dropped
                {"remove": r4_excel, "after": index_of(paragraphs, "Built data pipelines", 3), "text": "Ran Glue.", "keywords": []},  # role 4: dropped
            ],
        },
        # repair pass: fill what the ATS check still finds missing
        {"edits": [{"index": r3_pipe, "new_text": "Built Kafka streaming pipelines in Python loading daily files into S3.", "keywords": []}]},
        {"edits": []},
    ]

    result = await tailoring.tailor_docx(docx=content, job_description=JD, job_title="Senior Data Engineer")
    report = result["report"]

    # Same length: same number of paragraphs, total text within the small allowance.
    assert report["paragraphs_after"] == report["paragraphs_before"]
    assert report["length_after"] <= tailoring.total_budget(report["length_before"])
    # Only the valid swap landed: one bullet out, one in, inside role 1.
    assert [a["removed_index"] for a in report["additions"]] == [r1_excel]
    assert r1_sql not in [e["index"] for e in report["edits"]]
    # Every key skill is in the bullets of the three most recent clients.
    assert report["key_skills_missing_in_recent_roles"] == []
    # ATS target met, and the repair pass was what got it there.
    assert report["ats_score"] >= 95 and report["ats_target_met"] is True
    assert report["keyword_score_after"] > report["keyword_score_before"]
    assert report["repair_passes"] >= 1 and "STILL MISSING" in fake_llm["prompts"][1]


async def test_reports_when_ats_target_cannot_be_met(fake_llm):
    content = resume()
    paragraphs = read_paragraphs(content)
    summary = index_of(paragraphs, "Data engineer with 7 years")
    fake_llm["responses"] += [
        {"summary": "stub", "edits": [{"index": summary, "new_text": "Data engineer with 7 years building pipelines and reports in Python.", "keywords": []}], "swaps": []},
        {"edits": []},
        {"edits": []},
    ]
    result = await tailoring.tailor_docx(docx=content, job_description=JD, job_title="Senior Data Engineer")
    report = result["report"]
    assert report["repair_passes"] == tailoring.MAX_REPAIR_PASSES
    assert report["length_after"] <= tailoring.total_budget(report["length_before"])
    assert report["ats_target_met"] is (report["ats_score"] >= 95)
    if not report["ats_target_met"]:
        assert report["missing_after"]  # the UI can say exactly what is still missing


def test_clean_requests_keeps_real_roles_and_any_count():
    layout = tailoring.detect_roles(read_paragraphs(resume()))
    raw = [
        {"action": "add", "skill": "Kafka", "count": 3, "roles": [1, 2, 9]},  # role 9 does not exist
        {"action": "add", "skill": "Snowflake", "count": 40, "roles": [4]},  # no cap on the number asked
        {"action": "rewrite", "skill": "Azure", "count": "all", "roles": [2]},
        {"action": "remove", "skill": "Excel", "roles": [3, 4]},  # no count: all matching bullets
        {"action": "add", "skill": "", "count": 2, "roles": [1]},  # add needs a skill: dropped
        {"action": "explode", "skill": "x", "roles": [1]},  # unknown action: dropped
        {"skill": "dbt", "roles": []},  # defaults: add, 2, role 1
        "nonsense",
    ]
    assert tailoring.clean_requests(raw, layout) == [
        {"action": "add", "skill": "Kafka", "count": 3, "roles": [1, 2]},
        {"action": "add", "skill": "Snowflake", "count": 40, "roles": [4]},
        {"action": "rewrite", "skill": "Azure", "count": "all", "roles": [2]},
        {"action": "remove", "skill": "Excel", "count": "all", "roles": [3, 4]},
        {"action": "add", "skill": "dbt", "count": 2, "roles": [1]},
    ]


async def test_requested_bullets_land_in_the_clients_named_in_the_instructions(fake_llm):
    content = resume()
    paragraphs = read_paragraphs(content)
    layout = tailoring.detect_roles(paragraphs)
    role2, role4 = layout.bullets(2), layout.bullets(4)
    r1_pipe = layout.bullets(1)[0]

    fake_llm["responses"] += [
        # 1) the instructions, read into structured requests
        {"requests": [{"action": "add", "skill": "Kafka", "count": 3, "roles": [2]}, {"action": "add", "skill": "Kafka", "count": 2, "roles": [4]}]},
        # 2) first tailoring pass: role 2 gets 3 swaps but one never names Kafka; role 4 gets 1 of 2
        {
            "summary": "stub",
            "edits": [{"index": r1_pipe, "new_text": "Built Spark and Airflow pipelines in Python loading files into Snowflake on AWS S3.", "keywords": []}],
            "swaps": [
                {"remove": role2[0], "after": role2[0], "text": "Built Kafka consumers in Python feeding claims events into the warehouse.", "keywords": [], "request": 1},
                {"remove": role2[1], "after": role2[1], "text": "Tuned Kafka topics and partitions for daily claims feeds.", "keywords": [], "request": 1},
                {"remove": role2[2], "after": role2[2], "text": "Maintained reconciliation macros for the operations team.", "keywords": [], "request": 1},  # no Kafka
                {"remove": role4[0], "after": role4[0], "text": "Built Kafka producers in Python for daily policy files.", "keywords": [], "request": 2},
            ],
        },
        # 3) repair pass: the code asks only for what is still missing
        {
            "edits": [],
            "swaps": [
                {"remove": role2[2], "after": role2[2], "text": "Monitored Kafka consumer lag for the operations team.", "keywords": [], "request": 1},
                {"remove": role4[2], "after": role4[2], "text": "Wrote Kafka Connect jobs to load policy data into SQL.", "keywords": [], "request": 2},
            ],
        },
    ]

    result = await tailoring.tailor_docx(
        docx=content,
        job_description=JD,
        job_title="Senior Data Engineer",
        instructions="Add 3 points on Kafka in Orion Health and 2 points on Kafka in Old Mutual.",
    )
    report = result["report"]

    status = {(s["role"], s["skill"]): (s["done"], s["requested"]) for s in report["requests"]}
    assert status == {(2, "Kafka"): (3, 3), (4, "Kafka"): (2, 2)}
    # The repair prompt asked for exactly the missing bullets.
    repair_prompt = fake_llm["prompts"][2]
    assert "add 1 more bullet(s) about Kafka in ROLE 2" in repair_prompt
    assert "add 1 more bullet(s) about Kafka in ROLE 4" in repair_prompt
    # Same bullet count, and the new bullets sit inside the right clients.
    assert report["paragraphs_after"] == report["paragraphs_before"]
    texts = [p.text for p in read_paragraphs(result["docx"])]
    orion, old_mutual, education = (
        texts.index("Client: Orion Health, Austin, TX"),
        texts.index("Client: Old Mutual, Houston, TX"),
        texts.index("EDUCATION"),
    )
    nova = texts.index("Client: Nova Retail, Plano, TX")
    assert sum("Kafka" in t for t in texts[orion:nova]) == 3
    assert sum("Kafka" in t for t in texts[old_mutual:education]) == 2
    assert not any("reconciliation macros" in t for t in texts)  # the bullet without Kafka was refused


async def test_rewrite_all_remove_and_counts_beyond_the_role_size(fake_llm):
    content = resume()
    paragraphs = read_paragraphs(content)
    layout = tailoring.detect_roles(paragraphs)
    role1, role2, role3 = layout.bullets(1), layout.bullets(2), layout.bullets(3)
    excel3 = next(i for i in role3 if "Excel" in paragraphs[i].text)

    fake_llm["responses"] += [
        {"requests": [
            {"action": "add", "skill": "Kafka", "count": 10, "roles": [1]},  # more than role 1 has
            {"action": "rewrite", "skill": "Azure", "count": "all", "roles": [2]},
            {"action": "remove", "skill": "Excel", "roles": [3]},
        ]},
        {
            "summary": "stub",
            "edits": [
                {"index": role2[0], "new_text": "Built data pipelines in Python on Azure to load daily transaction files.", "keywords": [], "request": 2},
                {"index": role2[1], "new_text": "Wrote SQL queries and stored procedures on Azure SQL for finance reports.", "keywords": [], "request": 2},
                {"index": role2[2], "new_text": "Maintained macros used by the operations team for reconciliations.", "keywords": [], "request": 2},  # no Azure
            ],
            "swaps": [
                {"remove": i, "after": i, "text": f"Built Kafka streaming job {n} in Python for daily transaction events.", "keywords": [], "request": 1}
                for n, i in enumerate(role1, start=1)
            ],
            "removals": [{"index": excel3, "request": 3}, {"index": role3[0], "request": 3}],  # second one is not about Excel
        },
        {"edits": [{"index": role2[2], "new_text": "Maintained Azure Data Factory jobs for the operations team.", "keywords": [], "request": 2}]},
        {"edits": []},
    ]
    result = await tailoring.tailor_docx(
        docx=content, job_description=JD, job_title="Senior Data Engineer",
        instructions="Add 10 points on Kafka in my latest client, change all points in client 2 to Azure, remove the Excel points from client 3.",
    )
    report = result["report"]
    status = {(s["action"], s["role"]): (s["done"], s["requested"], s["asked"]) for s in report["requests"]}
    # 10 asked, role 1 has 3 bullets: all 3 replaced. All of role 2 rewritten. Only the Excel bullet removed.
    assert status == {("add", 1): (3, 3, 10), ("rewrite", 2): (3, 3, "all"), ("remove", 3): (1, 1, "all")}
    assert [r["index"] for r in report["removed"]] == [excel3]
    assert report["paragraphs_after"] == report["paragraphs_before"] - 1
    texts = [p.text for p in read_paragraphs(result["docx"])]
    assert sum("Kafka streaming job" in t for t in texts) == 3
    assert sum("Azure" in t for t in texts) >= 3
