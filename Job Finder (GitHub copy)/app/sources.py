"""Job sources. Each fetcher returns a list of normalized job dicts:

    {source, title, company, location, is_remote, salary, posted_at (ISO), url, description, via}

Fetchers raise SourceError with a friendly message when something goes wrong, or
SourceSkipped when the source isn't set up (e.g. no API key). One failing source
never stops the others.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from . import db
from .config import load_companies, load_profile

UA = "PersonalJobDashboard/1.0 (personal, non-commercial use)"
TIMEOUT = httpx.Timeout(25.0, connect=10.0)


class SourceError(Exception):
    pass


class SourceSkipped(Exception):
    pass


# ---------- helpers ----------

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def html_to_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = html.unescape(s)            # Greenhouse double-escapes its HTML
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    return _WS.sub(" ", s).strip()


def iso_from_ts(ts) -> Optional[str]:
    try:
        ts = float(ts)
        if ts > 1e12:   # milliseconds
            ts /= 1000
        return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def iso_from_str(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return None


def money(lo, hi, period: str = "") -> Optional[str]:
    def fmt(v):
        v = float(v)
        return f"${v/1000:.0f}k" if v >= 1000 else f"${v:,.0f}"
    try:
        lo = float(lo) if lo else 0
        hi = float(hi) if hi else 0
    except (TypeError, ValueError):
        return None
    if not lo and not hi:
        return None
    suffix = {"HOUR": "/hr", "YEAR": "/yr", "MONTH": "/mo"}.get((period or "").upper(), "")
    if lo and hi and lo != hi:
        return f"{fmt(lo)}–{fmt(hi)}{suffix}"
    return f"{fmt(lo or hi)}{suffix}"


def annualize(amount, period) -> Optional[float]:
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return None
    return v * {"HOUR": 2080, "DAY": 260, "WEEK": 52, "MONTH": 12}.get((period or "").upper(), 1)


def friendly_http_error(name: str, e: Exception) -> SourceError:
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (401, 403):
            return SourceError(f"{name} rejected the API key — double-check it in .env.")
        if code == 429:
            return SourceError(f"{name} says we've hit the rate limit — try again later.")
        return SourceError(f"Couldn't reach {name} this time (error {code}).")
    if isinstance(e, httpx.TimeoutException):
        return SourceError(f"{name} took too long to answer this time.")
    return SourceError(f"Couldn't reach {name} this time.")


def worst_error(errors: list) -> Exception:
    """When every call failed, report a key problem ahead of a rate limit (bad keys can trigger both)."""
    def rank(e):
        code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else 0
        return 0 if code in (401, 403) else 1
    return sorted(errors, key=rank)[0]


async def get_json(client: httpx.AsyncClient, url: str, *, params=None, headers=None, retries: int = 2):
    """GET with a polite retry on 429/5xx."""
    for attempt in range(retries + 1):
        r = await client.get(url, params=params, headers=headers)
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            wait = float(r.headers.get("retry-after", 0) or 0) or (2 * (attempt + 1))
            await asyncio.sleep(min(wait, 10))
            continue
        r.raise_for_status()
        return r.json()


# ---------- JSearch (RapidAPI / Google for Jobs) ----------

async def fetch_jsearch(client: httpx.AsyncClient) -> list[dict]:
    key = os.getenv("JSEARCH_API_KEY", "").strip()
    if not key:
        raise SourceSkipped("Add your JSearch key in Settings to see jobs from LinkedIn, Indeed, Glassdoor and more.")
    cached = db.cache_get("jsearch", max_age_minutes=int(os.getenv("JSEARCH_CACHE_MINUTES", "240")))
    if cached is not None:
        return cached

    profile = load_profile()
    headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    # JSearch v5: /search-v2 returns {"data": {"jobs": [...], "cursor": "..."}}; pass the cursor back for the next page.
    url = "https://jsearch.p.rapidapi.com/search-v2"
    pages = max(1, int(os.getenv("JSEARCH_PAGES", "1")))   # each page = 1 request from your monthly quota
    # Google Jobs has few listings tagged "Hickory", so nearby searches use the Charlotte metro;
    # the location filter still keeps only towns within ~60 miles of Hickory.
    local_hub = profile.get("jsearch_local_hub", "Charlotte, NC")
    calls = []
    for q in profile.get("jsearch_queries", profile["search_queries"][:4]):
        calls.append({"query": f"{q} in {local_hub}"})
        calls.append({"query": f"{q} remote", "work_from_home": "true"})

    sem = asyncio.Semaphore(3)

    async def one(p):
        found = []
        cursor = None
        for _ in range(pages):
            params = {**p, "country": "us", "date_posted": "month"}
            if cursor:
                params["cursor"] = cursor
            async with sem:
                res = await get_json(client, url, params=params, headers=headers)
            if res.get("status") not in (None, "OK"):
                raise SourceError(f"JSearch said: {res.get('error') or res.get('message') or res.get('status')}")
            data = res.get("data") or {}
            if isinstance(data, list):          # older response shape, just in case
                found.extend(data)
                break
            found.extend(data.get("jobs") or [])
            cursor = data.get("cursor")
            if not cursor:
                break
        return found

    results = await asyncio.gather(*(one(p) for p in calls), return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    if len(errors) == len(results):
        err = worst_error(errors)
        code = err.response.status_code if isinstance(err, httpx.HTTPStatusError) else None
        if code in (401, 403):
            raise SourceError("Your key didn't work. Make sure you subscribed to the free Basic plan "
                              "on RapidAPI, then paste the key again in Settings.")
        if code == 404:
            raise SourceError("JSearch changed how it works, so Job Finder needs a small update to talk to it again.")
        if code == 429:
            raise SourceError("You've used up this month's free JSearch searches. They reset at the start of "
                              "your next billing month on RapidAPI.")
        if isinstance(err, SourceError):
            raise err
        raise friendly_http_error("JSearch", err)

    jobs = []
    for res in results:
        if isinstance(res, Exception):
            continue
        for j in res:
            city, state = j.get("job_city"), j.get("job_state")
            loc = ", ".join(x for x in (city, state) if x) or j.get("job_location") or j.get("job_country") or ""
            exp = (j.get("job_required_experience") or {}).get("required_experience_in_months")
            salary = money(j.get("job_min_salary"), j.get("job_max_salary"), j.get("job_salary_period") or "")
            jobs.append({
                "source": "JSearch",
                "via": j.get("job_publisher") or "Google Jobs",
                "title": j.get("job_title") or "",
                "company": j.get("employer_name") or "",
                "location": loc,
                "is_remote": bool(j.get("job_is_remote")),
                "salary": salary or (j.get("job_salary_string") or None),
                "posted_at": iso_from_ts(j.get("job_posted_at_timestamp")) or iso_from_str(j.get("job_posted_at_datetime_utc")),
                "url": j.get("job_apply_link") or j.get("job_google_link") or "",
                "description": j.get("job_description") or "",
                "min_years": round(exp / 12) if exp else None,
                "employer_website": j.get("employer_website") or "",
                "apply_options": [{"url": o.get("apply_link") or "", "publisher": o.get("publisher") or "",
                                   "is_direct": bool(o.get("is_direct"))} for o in (j.get("apply_options") or [])]
                                 or [{"url": j.get("job_apply_link") or "", "publisher": j.get("job_publisher") or "",
                                      "is_direct": bool(j.get("job_apply_is_direct"))}],
                "salary_max_annual": annualize(j.get("job_max_salary") or j.get("job_min_salary"), j.get("job_salary_period")),
            })
    db.cache_put("jsearch", jobs)
    return jobs


# ---------- Adzuna ----------

async def fetch_adzuna(client: httpx.AsyncClient) -> list[dict]:
    app_id = os.getenv("ADZUNA_APP_ID", "").strip()
    app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
    if not (app_id and app_key):
        raise SourceSkipped("Add ADZUNA_APP_ID and ADZUNA_APP_KEY to .env to turn on Adzuna.")
    cached = db.cache_get("adzuna", max_age_minutes=60)
    if cached is not None:
        return cached

    profile = load_profile()
    url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    base = {"app_id": app_id, "app_key": app_key, "results_per_page": "50",
            "max_days_old": "30", "content-type": "application/json"}
    calls = []
    for q in profile["search_queries"]:
        calls.append({**base, "what": q, "where": profile["home"], "distance": "97"})  # 97 km ≈ 60 mi
        calls.append({**base, "what": q, "what_and": "remote"})

    sem = asyncio.Semaphore(3)

    async def one(p):
        async with sem:
            return await get_json(client, url, params=p)

    results = await asyncio.gather(*(one(p) for p in calls), return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    if len(errors) == len(results):
        raise friendly_http_error("Adzuna", worst_error(errors))

    jobs = []
    for res in results:
        if isinstance(res, Exception):
            continue
        for j in res.get("results") or []:
            area = (j.get("location") or {}).get("area") or []
            loc = (j.get("location") or {}).get("display_name") or ""
            if len(area) >= 2 and area[1] not in loc:
                loc = f"{loc}, {area[1]}"
            desc = html_to_text(j.get("description"))
            title = html_to_text(j.get("title"))
            jobs.append({
                "source": "Adzuna", "via": "Adzuna",
                "title": title,
                "company": (j.get("company") or {}).get("display_name") or "",
                "location": loc,
                "is_remote": bool(re.search(r"\bremote\b", f"{title} {loc}", re.I)),
                "salary": money(j.get("salary_min"), j.get("salary_max"), "YEAR")
                          if not j.get("salary_is_predicted") or j.get("salary_is_predicted") == "0" else None,
                "posted_at": iso_from_str(j.get("created")),
                "url": j.get("redirect_url") or "",
                "description": desc,
            })
    db.cache_put("adzuna", jobs)
    return jobs


# ---------- Greenhouse & Lever (companies you pick) ----------

async def fetch_greenhouse(client: httpx.AsyncClient) -> list[dict]:
    companies = [c for c in load_companies() if c["ats"] == "greenhouse"]
    if not companies:
        raise SourceSkipped("No Greenhouse companies in your list.")

    async def one(c):
        key = f"gh:{c['slug']}"
        cached = db.cache_get(key, max_age_minutes=120)
        if cached is not None:
            return cached
        data = await get_json(client, f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}/jobs",
                              params={"content": "true"})
        out = []
        for j in data.get("jobs") or []:
            loc = (j.get("location") or {}).get("name") or ""
            out.append({
                "source": "Greenhouse", "via": f"{c['name']} careers site",
                "official": True,
                "title": (j.get("title") or "").strip(),
                "company": c["name"],
                "location": loc,
                "is_remote": bool(re.search(r"\bremote\b", loc, re.I)),
                "salary": None,
                "posted_at": iso_from_str(j.get("first_published") or j.get("updated_at")),
                "url": j.get("absolute_url") or "",
                "description": html_to_text(j.get("content"))[:6000],
            })
        db.cache_put(key, out)
        return out

    return await _gather_companies("Greenhouse", companies, one)


async def fetch_lever(client: httpx.AsyncClient) -> list[dict]:
    companies = [c for c in load_companies() if c["ats"] == "lever"]
    if not companies:
        raise SourceSkipped("No Lever companies in your list.")

    async def one(c):
        key = f"lever:{c['slug']}"
        cached = db.cache_get(key, max_age_minutes=120)
        if cached is not None:
            return cached
        data = await get_json(client, f"https://api.lever.co/v0/postings/{c['slug']}", params={"mode": "json"})
        out = []
        for j in data if isinstance(data, list) else []:
            cats = j.get("categories") or {}
            loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
            sr = j.get("salaryRange") or {}
            period = {"per-hour-wage": "HOUR", "per-year-salary": "YEAR", "per-month-salary": "MONTH"}.get(sr.get("interval"), "")
            desc = " ".join([j.get("descriptionPlain") or ""] +
                            [html_to_text(l.get("content")) for l in j.get("lists") or []])
            out.append({
                "source": "Lever", "via": f"{c['name']} careers site",
                "official": True,
                "title": (j.get("text") or "").strip(),
                "company": c["name"],
                "location": loc + (f", {j['country']}" if j.get("country") and j["country"] not in loc else ""),
                "is_remote": j.get("workplaceType") == "remote" or bool(re.search(r"\bremote\b", loc, re.I)),
                "salary": money(sr.get("min"), sr.get("max"), period) if sr.get("currency", "USD") == "USD" else None,
                "posted_at": iso_from_ts(j.get("createdAt")),
                "url": j.get("hostedUrl") or "",
                "description": desc[:6000],
            })
        db.cache_put(key, out)
        return out

    return await _gather_companies("Lever", companies, one)


async def _gather_companies(name: str, companies: list, fn) -> list[dict]:
    sem = asyncio.Semaphore(5)

    async def guarded(c):
        async with sem:
            return await fn(c)

    results = await asyncio.gather(*(guarded(c) for c in companies), return_exceptions=True)
    jobs, failed = [], []
    for c, res in zip(companies, results):
        if isinstance(res, Exception):
            failed.append(c["name"])
        else:
            jobs.extend(res)
    if failed and len(failed) == len(companies):
        raise SourceError(f"Couldn't reach {name} this time.")
    if failed:
        # Partial success: return jobs but leave a note.
        raise PartialResult(jobs, f"Couldn't load {', '.join(failed)} from {name} (check the company slug).")
    return jobs


class PartialResult(Exception):
    def __init__(self, jobs, note):
        super().__init__(note)
        self.jobs, self.note = jobs, note


# ---------- Remotive & RemoteOK (remote-only boards) ----------

async def fetch_remotive(client: httpx.AsyncClient) -> list[dict]:
    # Remotive asks for light usage, so we cache for 6 hours.
    cached = db.cache_get("remotive", max_age_minutes=360)
    if cached is not None:
        return cached
    data = await get_json(client, "https://remotive.com/api/remote-jobs", headers={"User-Agent": UA})
    jobs = []
    for j in data.get("jobs") or []:
        jobs.append({
            "source": "Remotive", "via": "Remotive",
            "title": j.get("title") or "",
            "company": j.get("company_name") or "",
            "location": j.get("candidate_required_location") or "Remote",
            "is_remote": True,
            "salary": (j.get("salary") or "").strip() or None,
            "posted_at": iso_from_str(j.get("publication_date")),
            "url": j.get("url") or "",
            "description": html_to_text(j.get("description"))[:6000],
        })
    db.cache_put("remotive", jobs)
    return jobs


async def fetch_remoteok(client: httpx.AsyncClient) -> list[dict]:
    cached = db.cache_get("remoteok", max_age_minutes=360)
    if cached is not None:
        return cached
    data = await get_json(client, "https://remoteok.com/api", headers={"User-Agent": UA})
    jobs = []
    for j in data[1:] if isinstance(data, list) else []:   # first item is their legal notice
        jobs.append({
            "source": "RemoteOK", "via": "Remote OK",
            "title": j.get("position") or "",
            "company": j.get("company") or "",
            "location": j.get("location") or "Remote",
            "is_remote": True,
            "salary": money(j.get("salary_min"), j.get("salary_max"), "YEAR"),
            "posted_at": iso_from_ts(j.get("epoch")) or iso_from_str(j.get("date")),
            "url": j.get("url") or j.get("apply_url") or "",
            "description": html_to_text(j.get("description"))[:6000],
        })
    db.cache_put("remoteok", jobs)
    return jobs


SOURCES = {
    "JSearch": fetch_jsearch,
    "Adzuna": fetch_adzuna,
    "Greenhouse": fetch_greenhouse,
    "Lever": fetch_lever,
    "Remotive": fetch_remotive,
    "RemoteOK": fetch_remoteok,
}


async def fetch_all() -> tuple[list[dict], list[dict]]:
    """Run every source in parallel. Returns (jobs, report) where report has one entry per source."""
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True) as client:
        names = list(SOURCES)
        results = await asyncio.gather(*(SOURCES[n](client) for n in names), return_exceptions=True)

    jobs, report = [], []
    for name, res in zip(names, results):
        entry = {"source": name, "status": "ok", "fetched": 0, "note": None}
        if isinstance(res, PartialResult):
            jobs.extend(res.jobs)
            entry.update(fetched=len(res.jobs), note=res.note)
        elif isinstance(res, SourceSkipped):
            entry.update(status="skipped", note=str(res))
        elif isinstance(res, SourceError):
            entry.update(status="error", note=str(res))
        elif isinstance(res, Exception):
            entry.update(status="error", note=str(friendly_http_error(name, res)))
        else:
            jobs.extend(res)
            entry["fetched"] = len(res)
        report.append(entry)
    return jobs, report
