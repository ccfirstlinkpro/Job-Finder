"""FastAPI app: serves the page and a small JSON API."""
from __future__ import annotations

import asyncio
import os
import re
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import ai, db  # noqa: E402  (after .env is loaded)
from .config import load_companies, load_profile, parse_company_input, save_companies, set_env_value  # noqa: E402
from .pipeline import run_search  # noqa: E402

app = FastAPI(title="Job Dashboard")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
db.init()
_search_lock = asyncio.Lock()


@app.middleware("http")
async def no_stale_files(request, call_next):
    # Always revalidate the page/CSS/JS so updates show up without a hard refresh.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/state")
def state():
    """Everything the page needs on load: your name, last results, and the last search's report."""
    last = db.last_search()
    prev_ran_at = None
    if last:
        with db.connect() as c:
            r = c.execute("SELECT ran_at FROM searches WHERE id<? ORDER BY id DESC LIMIT 1", (last["id"],)).fetchone()
            prev_ran_at = r[0] if r else None
    return {
        "name": load_profile().get("name", "there"),
        "ai_enabled": ai.enabled(),
        "settings": settings_status(),
        "search": last and {**last, "prev_ran_at": prev_ran_at},
        "jobs": db.results_for_search(last["id"]) if last else [],
    }


@app.post("/api/search")
async def search():
    if _search_lock.locked():
        raise HTTPException(409, "A search is already running.")
    async with _search_lock:
        prev = db.last_search()
        result = await run_search()
        result["prev_ran_at"] = prev["ran_at"] if prev else None
        return {"search": result, "jobs": db.results_for_search(result["id"])}


@app.post("/api/summaries")
async def summaries():
    last = db.last_search()
    if not last or not ai.enabled():
        return {"written": 0, "summaries": {}}
    jobs = db.results_for_search(last["id"])
    written = await ai.summarize_top(jobs, limit=20)
    return {"written": written, "error": "Claude rejected the API key." if written == -1 else None,
            "summaries": {j["id"]: j["summary"] for j in jobs[:20] if j.get("summary")}}


# ---------- settings (JSearch key) ----------

def settings_status() -> dict:
    key = os.getenv("JSEARCH_API_KEY", "").strip()
    saved_at = None
    env_path = ROOT / ".env"
    if key and env_path.exists():
        saved_at = datetime.fromtimestamp(env_path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    return {"jsearch_saved": bool(key), "jsearch_last4": key[-4:] if key else None, "jsearch_saved_at": saved_at}


@app.get("/api/settings")
def get_settings():
    return settings_status()


class SettingsIn(BaseModel):
    jsearch_key: str


@app.post("/api/settings")
def save_settings(body: SettingsIn):
    key = body.jsearch_key.strip()
    if not key:
        raise HTTPException(400, "Paste your key into the box first.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", key):
        raise HTTPException(400, "That doesn't look like a JSearch key. It should be one long line of "
                                 "letters and numbers with no spaces. Copy it again from RapidAPI.")
    set_env_value("JSEARCH_API_KEY", key)
    db.cache_clear("jsearch")      # so the next Search uses the new key right away
    return settings_status()


class StatusIn(BaseModel):
    status: Optional[str] = None   # saved | applied | hidden | None (clear)


@app.post("/api/jobs/{job_id}/status")
def set_status(job_id: str, body: StatusIn):
    if body.status not in (None, "saved", "applied", "hidden"):
        raise HTTPException(400, "Unknown status")
    job = db.set_status(job_id, body.status)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.post("/api/jobs/{job_id}/report")
def report_job(job_id: str):
    """Hide this job for good and block where it came from.
    For big shared sites (LinkedIn, Indeed, Workday…) we block the company, not the whole site."""
    from .trust import base_domain, host_of, load_sites, save_sites
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    db.set_status(job_id, "hidden")
    sites = load_sites()
    host = job.get("apply_domain") or host_of(job.get("url") or "")
    shared = job.get("apply_kind") == "board" or any(
        host == d or host.endswith("." + d)
        for domains in sites.get("company_hiring_systems", {}).values() for d in domains)
    if shared or not host:
        company = (job.get("company") or "").strip()
        if company and company.lower() not in {c.lower() for c in sites.get("blocked_companies", [])}:
            sites.setdefault("blocked_companies", []).append(company)
        save_sites(sites)
        site_name = job.get("apply_site") or host
        return {"blocked": company, "message": f"Hidden. You won't see jobs from {company} again."
                + (f" ({site_name} itself is still allowed.)" if job.get("apply_kind") == "board" else "")}
    domain = base_domain(host)
    name = job.get("apply_site") or domain
    sites.setdefault("blocked_sites", {})[name if name not in sites["blocked_sites"] else domain] = {
        "domains": [domain], "reason": "you reported it as sketchy"}
    save_sites(sites)
    return {"blocked": domain, "message": f"Hidden. You won't see jobs from {domain} again."}


@app.post("/api/jobs/{job_id}/broken")
async def broken_link(job_id: str):
    """You said the Apply link didn't work: try a backup trusted site, otherwise hide the job.
    Either way, save a report so the link checks can be improved."""
    from .linkcheck import first_working, inspect_url
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    recheck = await inspect_url(job["url"])
    backup, tried = await first_working(job.get("alt_options") or [])
    recheck["backups_tried"] = tried
    if backup:
        remaining = [o for o in job["alt_options"] if o is not backup and o.get("url") != backup["url"]]
        db.update_job(job_id, url=backup["url"], apply_site=backup["site"], apply_kind=backup["kind"],
                      apply_domain=backup["domain"], alt_options=remaining, viewed_at=None)
        db.add_broken_link(job, recheck, "switched")
        return {"outcome": "switched", "job": db.get_job(job_id),
                "message": f"Thanks! That link was broken, so this job now opens on {backup['site']} instead."}
    db.update_job(job_id, removed_reason="you said the link didn't work")
    db.add_broken_link(job, recheck, "hidden")
    return {"outcome": "hidden",
            "message": "Thanks! I couldn't find another working link, so I hid this job. Your report was saved."}


@app.get("/api/review-notes")
def review_notes():
    path = ROOT / "data" / "review_notes.md"
    return {"text": path.read_text(encoding="utf-8")[:20000] if path.exists() else ""}


@app.get("/api/broken-links")
def list_broken_links():
    return db.broken_links()


@app.post("/api/jobs/{job_id}/viewed")
def viewed(job_id: str):
    db.mark_viewed(job_id)
    return {"ok": True}


@app.get("/api/my-jobs")
def my_jobs():
    return db.my_jobs()


# ---------- companies checked directly (Greenhouse / Lever) ----------

@app.get("/api/companies")
def companies():
    return load_companies()


class CompanyIn(BaseModel):
    text: str               # slug or board URL
    ats: str = ""           # optional: greenhouse | lever
    name: str = ""


@app.post("/api/companies")
async def add_company(body: CompanyIn):
    c = parse_company_input(body.text, body.ats)
    if not c["slug"]:
        raise HTTPException(400, "Enter a company's job-board name or link.")
    existing = load_companies()
    if any(e["ats"] == c["ats"] and e["slug"] == c["slug"] for e in existing):
        raise HTTPException(400, "That company is already on your list.")

    # Check the board actually exists (try the other ATS if the first one fails and none was specified).
    tries = [c["ats"]] if (body.ats or "://" in body.text) else ["greenhouse", "lever"]
    async with httpx.AsyncClient(timeout=15) as client:
        for ats in tries:
            url = (f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}" if ats == "greenhouse"
                   else f"https://api.lever.co/v0/postings/{c['slug']}?mode=json&limit=1")
            try:
                r = await client.get(url)
            except httpx.HTTPError:
                raise HTTPException(502, "Couldn't reach the job board to check that company. Try again.")
            if r.status_code == 200:
                name = body.name.strip()
                if not name and ats == "greenhouse":
                    name = r.json().get("name") or ""
                c = {"name": name or c["slug"].replace("-", " ").title(), "ats": ats, "slug": c["slug"]}
                save_companies(existing + [c])
                return c
    raise HTTPException(404, f"Couldn't find a Greenhouse or Lever job board called “{c['slug']}”. "
                             "Try pasting the link to their careers page.")


@app.delete("/api/companies/{ats}/{slug}")
def remove_company(ats: str, slug: str):
    existing = load_companies()
    kept = [e for e in existing if not (e["ats"] == ats and e["slug"] == slug)]
    if len(kept) == len(existing):
        raise HTTPException(404, "Not on your list")
    save_companies(kept)
    return {"ok": True}


# ---------- close button ----------

@app.post("/api/shutdown")
def shutdown(request: Request):
    """Stops the site. Only works from this computer."""
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "Job Finder can only be closed from this computer.")
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGINT)).start()
    return {"ok": True}
