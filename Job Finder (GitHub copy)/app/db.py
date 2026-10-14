"""SQLite storage: every job we've seen, what you did with it, and search history."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT, company TEXT, location TEXT, is_remote INTEGER,
    salary TEXT, posted_at TEXT, url TEXT, sources TEXT,
    snippet TEXT, score INTEGER, badge TEXT,
    matched TEXT, missing TEXT, summary TEXT,
    first_seen_at TEXT, last_seen_at TEXT, last_search_id INTEGER,
    status TEXT,              -- saved | applied | hidden | NULL
    status_at TEXT, applied_at TEXT, viewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_search ON jobs(last_search_id);
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at TEXT, total INTEGER, new_count INTEGER, report TEXT
);
CREATE TABLE IF NOT EXISTS broken_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reported_at TEXT, job_id TEXT, title TEXT, company TEXT,
    apply_site TEXT, url TEXT,
    recheck TEXT,             -- what the page showed when re-checked right after your report
    outcome TEXT,             -- switched (to another site) | hidden
    reviewed_at TEXT, review_note TEXT
);
CREATE TABLE IF NOT EXISTS source_cache (
    key TEXT PRIMARY KEY, fetched_at TEXT, payload TEXT
);
"""

JOB_FIELDS = ("title", "company", "location", "is_remote", "salary", "posted_at", "url",
              "sources", "snippet", "score", "badge", "matched", "missing",
              "apply_site", "apply_kind", "apply_domain", "trust", "warnings", "removed_reason",
              "alt_options", "category", "entry_level")

# Columns added after the first version; added to older databases automatically.
NEW_COLUMNS = {"apply_site": "TEXT", "apply_kind": "TEXT", "apply_domain": "TEXT",
               "trust": "TEXT", "warnings": "TEXT", "removed_reason": "TEXT", "alt_options": "TEXT",
               "category": "TEXT", "entry_level": "INTEGER"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as c:
        c.executescript(SCHEMA)
        have = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
        for col, typ in NEW_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
        if "safety" not in {r[1] for r in c.execute("PRAGMA table_info(searches)")}:
            c.execute("ALTER TABLE searches ADD COLUMN safety TEXT")


def _row_to_job(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["is_remote"] = bool(d["is_remote"])
    d["entry_level"] = bool(d.get("entry_level"))
    d["sources"] = json.loads(d["sources"] or "[]")
    d["matched"] = json.loads(d["matched"] or "[]")
    d["missing"] = json.loads(d["missing"] or "[]")
    d["warnings"] = json.loads(d.get("warnings") or "[]")
    d["alt_options"] = json.loads(d.get("alt_options") or "[]")
    return d


def last_search() -> Optional[dict]:
    with connect() as c:
        r = c.execute("SELECT * FROM searches ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    d = dict(r)
    d["report"] = json.loads(d["report"] or "[]")
    d["safety"] = json.loads(d.get("safety") or "{}")
    return d


def save_search_results(jobs: Iterable[dict], report: list, safety: Optional[dict] = None) -> dict:
    """Upsert jobs from a fresh search. Returns the new search row (with new_count)."""
    jobs = list(jobs)
    ts = now()
    with connect() as c:
        cur = c.execute("INSERT INTO searches (ran_at, total, new_count, report, safety) VALUES (?,?,?,?,?)",
                        (ts, 0, 0, json.dumps(report), json.dumps(safety or {})))
        sid = cur.lastrowid
        new_count = 0
        for j in jobs:
            vals = {k: j.get(k) for k in JOB_FIELDS}
            for k in ("sources", "matched", "missing", "warnings", "alt_options"):
                vals[k] = json.dumps(vals[k] or [])
            vals["is_remote"] = 1 if vals["is_remote"] else 0
            vals["entry_level"] = 1 if vals["entry_level"] else 0
            exists = c.execute("SELECT status FROM jobs WHERE id=?", (j["id"],)).fetchone()
            if exists:
                sets = ", ".join(f"{k}=?" for k in JOB_FIELDS)
                c.execute(f"UPDATE jobs SET {sets}, last_seen_at=?, last_search_id=? WHERE id=?",
                          (*vals.values(), ts, sid, j["id"]))
            else:
                new_count += 1
                cols = ", ".join(JOB_FIELDS)
                qs = ", ".join("?" for _ in JOB_FIELDS)
                c.execute(f"INSERT INTO jobs (id, {cols}, first_seen_at, last_seen_at, last_search_id) "
                          f"VALUES (?, {qs}, ?, ?, ?)", (j["id"], *vals.values(), ts, ts, sid))
        c.execute("UPDATE searches SET total=?, new_count=? WHERE id=?", (len(jobs), new_count, sid))
    return {"id": sid, "ran_at": ts, "total": len(jobs), "new_count": new_count, "report": report,
            "safety": safety or {}}


def results_for_search(search_id: int) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM jobs WHERE last_search_id=? AND (status IS NULL OR status!='hidden') "
            "AND removed_reason IS NULL "
            "ORDER BY score DESC, posted_at DESC", (search_id,)).fetchall()
    return [_row_to_job(r) for r in rows]


def my_jobs() -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM jobs WHERE status IN ('saved','applied') "
                         "ORDER BY COALESCE(applied_at, status_at) DESC").fetchall()
    return [_row_to_job(r) for r in rows]


def hidden_ids() -> set:
    with connect() as c:
        return {r[0] for r in c.execute("SELECT id FROM jobs WHERE status='hidden'")}


def set_status(job_id: str, status: Optional[str]) -> Optional[dict]:
    ts = now()
    with connect() as c:
        if status == "applied":
            c.execute("UPDATE jobs SET status=?, status_at=?, applied_at=COALESCE(applied_at, ?) WHERE id=?",
                      (status, ts, ts, job_id))
        else:
            c.execute("UPDATE jobs SET status=?, status_at=? WHERE id=?", (status, ts, job_id))
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(r) if r else None


def mark_viewed(job_id: str) -> None:
    with connect() as c:
        c.execute("UPDATE jobs SET viewed_at=COALESCE(viewed_at, ?) WHERE id=?", (now(), job_id))


def set_summary(job_id: str, summary: str) -> None:
    with connect() as c:
        c.execute("UPDATE jobs SET summary=? WHERE id=?", (summary, job_id))


def cache_get(key: str, max_age_minutes: int) -> Optional[object]:
    with connect() as c:
        r = c.execute("SELECT fetched_at, payload FROM source_cache WHERE key=?", (key,)).fetchone()
    if not r:
        return None
    age = datetime.now(timezone.utc) - datetime.fromisoformat(r["fetched_at"])
    if age.total_seconds() > max_age_minutes * 60:
        return None
    return json.loads(r["payload"])


def cache_put(key: str, payload: object) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO source_cache (key, fetched_at, payload) VALUES (?,?,?)",
                  (key, now(), json.dumps(payload)))


def cache_clear(prefix: str = "") -> None:
    with connect() as c:
        c.execute("DELETE FROM source_cache WHERE key LIKE ?", (prefix + "%",))


def get_job(job_id: str) -> Optional[dict]:
    with connect() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(r) if r else None


def all_jobs() -> list[dict]:
    with connect() as c:
        return [_row_to_job(r) for r in c.execute("SELECT * FROM jobs")]


def update_job(job_id: str, **fields) -> None:
    for k in ("warnings", "alt_options"):
        if k in fields:
            fields[k] = json.dumps(fields[k] or [])
    sets = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))


def add_broken_link(job: dict, recheck: dict, outcome: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO broken_links (reported_at, job_id, title, company, apply_site, url, recheck, outcome) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (now(), job["id"], job["title"], job["company"], job.get("apply_site"), job["url"],
                   json.dumps(recheck), outcome))


def broken_links(unreviewed_only: bool = False) -> list[dict]:
    q = "SELECT * FROM broken_links" + (" WHERE reviewed_at IS NULL" if unreviewed_only else "") + " ORDER BY id DESC"
    with connect() as c:
        rows = [dict(r) for r in c.execute(q)]
    for r in rows:
        r["recheck"] = json.loads(r["recheck"] or "{}")
    return rows
