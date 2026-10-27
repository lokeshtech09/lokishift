from datetime import datetime, timedelta, timezone

from app.services.reports import NOT_SPECIFIED, build_report, title_key

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)


def task(days_ago, title="Senior Data Engineer", vendor="ABC Staffing", location="Austin, TX",
         status="matched", match=80, tailored=None, profile="p1", domain="Banking"):
    return {
        "created_at": (NOW - timedelta(days=days_ago)).isoformat(),
        "job_title": title, "vendor_company": vendor, "job_location": location,
        "status": status, "match_score": match, "tailored_score": tailored,
        "profile_id": profile, "profile_title": "Data Engineer", "domain": domain,
    }


def test_title_grouping():
    assert title_key("Sr. Data Engineer") == title_key("Senior Data Engineer") == title_key("Data Engineer (Senior)")
    assert title_key("Python Developer") != title_key("Data Engineer")


def test_report_totals_breakdowns_and_trend():
    tasks = [
        task(1, title="Sr. Data Engineer", status="finished", match=70, tailored=90),
        task(2, vendor="abc  staffing", status="finished", match=80, tailored=88),
        task(3, title="Python Developer", vendor="Infosys", location="Remote - US", match=60),
        task(10, vendor="", location=""),
        task(200, vendor="Old Vendor"),  # outside 90 days
    ]
    r = build_report(tasks, 90, now=NOW)
    t = r["totals"]
    assert (t["tasks"], t["tailored"], t["ready"], t["tailored_rate"]) == (4, 2, 2, 50)
    assert t["avg_gain"] == 14 and t["vendors"] == 2
    assert r["vendors"][0]["name"] == "ABC Staffing" and r["vendors"][0]["tasks"] == 2
    assert r["vendors"][-1]["name"] == NOT_SPECIFIED
    assert r["positions"][0]["tasks"] == 3  # Sr./Senior grouped
    assert any(l["name"] == "Remote" for l in r["locations"])
    assert r["trend"]["bucket"] == "week"
    assert sum(p["total"] for p in r["trend"]["points"]) == 4
    assert sum(p["tailored"] for p in r["trend"]["points"]) == 2
    assert any("ABC Staffing" in i for i in r["insights"])


def test_all_time_uses_months_for_long_ranges():
    r = build_report([task(1), task(300)], 0, now=NOW)
    assert r["totals"]["tasks"] == 2 and r["trend"]["bucket"] == "month"


def test_empty_report():
    r = build_report([], 30, now=NOW)
    assert r["totals"]["tasks"] == 0 and r["insights"] == [] and r["vendors"] == []


def test_reports_endpoint(client):
    r = client.get("/api/v1/reports", params={"days": 30})
    assert r.status_code == 200 and r.json()["totals"]["tasks"] == 0


def test_weeks_follow_the_viewers_time_zone():
    # Sunday 9pm in Austin (UTC-5) is already Monday in UTC.
    sunday_evening = {**task(0), "created_at": "2026-10-19T02:00:00+00:00"}
    utc = build_report([sunday_evening], 30, now=NOW)
    austin = build_report([sunday_evening], 30, now=NOW, tz_offset_minutes=-300)
    week_of = lambda r: next(p["start"][:10] for p in r["trend"]["points"] if p["total"])  # noqa: E731
    assert week_of(utc) == "2026-10-19" and week_of(austin) == "2026-10-12"
