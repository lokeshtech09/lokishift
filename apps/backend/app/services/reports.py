"""Reporting: trends and breakdowns over the user's tasks.

Everything is computed in Python from the (small) task list, so the rules
stay readable: which tasks count, how titles are grouped, which insights are
worth saying out loud.
"""

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

NOT_SPECIFIED = "Not specified"
_TOP = 10

# Words that mean the same thing in job titles.
_TITLE_SYNONYMS = {
    "sr": "senior",
    "snr": "senior",
    "jr": "junior",
    "eng": "engineer",
    "engr": "engineer",
    "dev": "developer",
    "mgr": "manager",
    "ai/ml": "ai ml",
}


def _parse(ts: str) -> datetime:
    value = datetime.fromisoformat(ts)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def title_key(title: str) -> str:
    """Group 'Sr. Data Engineer', 'Senior Data Engineer' and
    'Data Engineer (Senior)' together: same words, any order."""
    words = re.findall(r"[a-z0-9+#/]+", (title or "").lower())
    words = [_TITLE_SYNONYMS.get(w, w) for w in words]
    return " ".join(sorted(set(words)))


def location_key(location: str) -> str:
    text = " ".join((location or "").replace(",", ", ").split()).strip(" ,")
    if not text:
        return ""
    if "remote" in text.lower():
        return "remote"
    return text.lower()


def _vendor_key(task: dict[str, Any]) -> str:
    return " ".join((task["vendor_company"] or "").lower().split())


def _avg(values: list[float]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def _breakdown(
    tasks: list[dict[str, Any]], key_fn, label_fn=None, top: int = _TOP
) -> list[dict[str, Any]]:
    """Group tasks; most common original spelling becomes the label."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        groups[key_fn(task)].append(task)
    rows = []
    for key, items in groups.items():
        if key:
            names = Counter((label_fn or (lambda t: key))(t) for t in items)
            name = names.most_common(1)[0][0]
        else:
            name = NOT_SPECIFIED
        rows.append(
            {
                "name": name,
                "tasks": len(items),
                "tailored": sum(1 for t in items if t["status"] == "finished"),
                "avg_match": _avg([t["match_score"] for t in items if t["match_score"] is not None]),
                "last_at": max(t["created_at"] for t in items),
            }
        )
    # Unspecified sorts last so real names lead.
    rows.sort(key=lambda r: (r["name"] == NOT_SPECIFIED, -r["tasks"], -(r["avg_match"] or 0)))
    return rows[:top]


def _trend(tasks: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    monthly = (end - start).days > 120
    if monthly:
        cursor = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        cursor = day - timedelta(days=day.weekday())
    buckets: list[dict[str, Any]] = []
    while cursor <= end:
        if monthly:
            nxt = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            nxt = cursor + timedelta(days=7)
        buckets.append({"start": cursor.isoformat(), "end": nxt.isoformat(), "total": 0, "tailored": 0})
        cursor = nxt
    for task in tasks:
        created = _parse(task["created_at"])
        for bucket in buckets:
            if bucket["start"] <= created.isoformat() < bucket["end"]:
                bucket["total"] += 1
                bucket["tailored"] += task["status"] == "finished"
                break
    return {"bucket": "month" if monthly else "week", "points": buckets}


def _insights(totals: dict[str, Any], vendors, positions, locations, profiles) -> list[str]:
    out: list[str] = []
    named = [v for v in vendors if v["name"] != NOT_SPECIFIED]
    if named and totals["tasks"]:
        top = named[0]
        share = round(top["tasks"] / totals["tasks"] * 100)
        out.append(f"{top['name']} is your most active vendor: {top['tasks']} tasks ({share}% of the period).")
    if positions:
        top = positions[0]
        out.append(f"You target “{top['name']}” most often ({top['tasks']} tasks).")
    scored = [p for p in positions if p["avg_match"] is not None and p["tasks"] >= 2]
    if len(scored) >= 2:
        best = max(scored, key=lambda p: p["avg_match"])
        weakest = min(scored, key=lambda p: p["avg_match"])
        if best["name"] != weakest["name"]:
            out.append(
                f"Your resumes fit “{best['name']}” best (avg {best['avg_match']}%) and "
                f"“{weakest['name']}” least (avg {weakest['avg_match']}%)."
            )
    real_locations = [l for l in locations if l["name"] != NOT_SPECIFIED]
    if real_locations:
        top = real_locations[0]
        out.append(f"Most roles are in {top['name']} ({top['tasks']} tasks).")
    if totals["ready"]:
        out.append(f"{totals['ready']} task{'s are' if totals['ready'] != 1 else ' is'} matched and waiting to be tailored.")
    if totals["avg_gain"]:
        out.append(f"Tailoring raised match scores by {totals['avg_gain']} points on average.")
    if len(profiles) > 1:
        top = profiles[0]
        out.append(f"Your busiest profile is “{top['name']}” ({top['tasks']} tasks).")
    return out


def build_report(
    tasks: list[dict[str, Any]],
    days: int,
    now: datetime | None = None,
    tz_offset_minutes: int = 0,
) -> dict[str, Any]:
    """``tz_offset_minutes`` is the viewer's offset from UTC (Austin in winter:
    -360), so weeks and months start at the viewer's local midnight."""
    tz = timezone(timedelta(minutes=tz_offset_minutes))
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    tasks = [{**t, "created_at": _parse(t["created_at"]).astimezone(tz).isoformat()} for t in tasks]
    if days > 0:
        start = now - timedelta(days=days)
        tasks = [t for t in tasks if _parse(t["created_at"]) >= start]
    else:
        start = min((_parse(t["created_at"]) for t in tasks), default=now - timedelta(days=30))

    tailored = [t for t in tasks if t["status"] == "finished"]
    gains = [
        t["tailored_score"] - t["match_score"]
        for t in tailored
        if t["tailored_score"] is not None and t["match_score"] is not None
    ]
    totals = {
        "tasks": len(tasks),
        "tailored": len(tailored),
        "ready": sum(1 for t in tasks if t["status"] == "matched"),
        "running": sum(1 for t in tasks if t["status"] in ("matching", "tailoring")),
        "failed": sum(1 for t in tasks if t["status"] == "failed"),
        "avg_match": _avg([t["match_score"] for t in tasks if t["match_score"] is not None]),
        "avg_tailored": _avg([t["tailored_score"] for t in tailored if t["tailored_score"] is not None]),
        "avg_gain": _avg(gains),
        "tailored_rate": round(len(tailored) / len(tasks) * 100) if tasks else 0,
        "vendors": len({_vendor_key(t) for t in tasks} - {""}),
    }

    vendors = _breakdown(
        tasks,
        _vendor_key,
        lambda t: " ".join(t["vendor_company"].split()),
    )
    positions = _breakdown(tasks, lambda t: title_key(t["job_title"]), lambda t: " ".join(t["job_title"].split()))
    locations = _breakdown(
        tasks,
        lambda t: location_key(t["job_location"]),
        lambda t: "Remote" if location_key(t["job_location"]) == "remote" else " ".join(t["job_location"].split()),
    )
    profiles = _breakdown(tasks, lambda t: t["profile_id"], lambda t: t["profile_title"] or "Profile")
    domains = _breakdown(tasks, lambda t: (t["domain"] or "").lower(), lambda t: t["domain"])

    return {
        "range": {"from": start.isoformat(), "to": now.isoformat(), "days": days},
        "totals": totals,
        "trend": _trend(tasks, start, now),
        "vendors": vendors,
        "positions": positions,
        "locations": locations,
        "profiles": profiles,
        "domains": domains,
        "insights": _insights(totals, vendors, positions, locations, profiles),
    }
