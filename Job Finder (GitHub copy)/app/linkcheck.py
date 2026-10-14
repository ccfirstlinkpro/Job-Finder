"""Makes sure each job's Apply link still works before you see it.

"gone"    -> the page is missing, or says the job is closed / no longer accepting applications
"alive"   -> the page loaded and looks like an open posting
"unknown" -> the site blocks automatic checks (Indeed, Monster…) or didn't answer; we keep the job
"""
from __future__ import annotations

import asyncio
import re

import httpx

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

CLOSED = re.compile(
    r"no longer accepting applications|this job is no longer available|job (posting )?(has )?expired|"
    r"this (job|position|posting) (has been|is) (closed|filled|removed)|position has been filled|"
    r"job is no longer (open|active|available)|posting (is )?no longer (available|active)|"
    r"the job you are looking for (is no longer|was not found)|this requisition is no longer", re.I)


async def check_url(client: httpx.AsyncClient, url: str) -> str:
    if not url:
        return "gone"
    try:
        r = await client.get(url)
    except (httpx.HTTPError, ValueError):
        return "unknown"
    if r.status_code in (404, 410):
        return "gone"
    if r.status_code != 200:
        return "unknown"            # 401/403/429/999 = the site blocks robots; can't tell
    # Greenhouse sends closed jobs back to the company's job list with ?error=true
    if "error=true" in str(r.url) and "greenhouse" in str(r.url):
        return "gone"
    return "gone" if CLOSED.search(r.text[:300000]) else "alive"


async def verify_jobs(jobs: list, concurrency: int = 8) -> dict:
    """For each job, walk its trusted apply options until one is open.
    Updates job['url'/'apply_*'] to the first working option. Returns {job_id: 'gone'} for dead jobs."""
    sem = asyncio.Semaphore(concurrency)
    dead = {}

    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(12.0, connect=6.0),
                                 headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}) as client:
        async def one(job):
            options = job.get("_trusted_options") or [{"url": job["url"], "site": job.get("apply_site"),
                                                       "kind": job.get("apply_kind"), "domain": job.get("apply_domain")}]
            for opt in options:
                async with sem:
                    status = await check_url(client, opt["url"])
                if status != "gone":
                    job.update(url=opt["url"], apply_site=opt["site"], apply_kind=opt["kind"],
                               apply_domain=opt["domain"], via=opt["site"])
                    return
            dead[job["id"]] = "gone"

        await asyncio.gather(*(one(j) for j in jobs))
    return dead


async def inspect_url(url: str) -> dict:
    """Detailed look at one link, saved with your 'Link didn't work' report for later review."""
    info = {"url": url, "status": None, "final_url": None, "page_title": None, "closed_text": None, "verdict": "unknown"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(15.0, connect=8.0),
                                 headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}) as client:
        try:
            r = await client.get(url)
        except (httpx.HTTPError, ValueError) as e:
            info["error"] = type(e).__name__
            return info
        info.update(status=r.status_code, final_url=str(r.url))
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text[:200000], re.I | re.S)
        if m:
            info["page_title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:200]
        c = CLOSED.search(r.text[:300000])
        if c:
            info["closed_text"] = c.group(0)
        info["verdict"] = await check_url(client, url) if r.status_code == 200 else (
            "gone" if r.status_code in (404, 410) else "unknown")
    return info


async def first_working(options: list) -> tuple:
    """Returns (working_option or None, statuses) trying each backup apply link in order."""
    statuses, maybe = [], None
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(12.0, connect=6.0),
                                 headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}) as client:
        for opt in options:
            st = await check_url(client, opt.get("url"))
            statuses.append({"site": opt.get("site"), "status": st})
            if st == "alive":
                return opt, statuses
            if st == "unknown" and maybe is None:
                maybe = opt     # site blocks checks (e.g. Indeed); better than nothing
    return maybe, statuses
