"""Fetch → filter → dedupe → score → save."""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from . import db
from .config import load_profile
from .filters import exclusion_reason, place_matchers
from .scoring import is_relevant, score_job
from .sources import fetch_all
from .linkcheck import verify_jobs
from .trust import evaluate, load_sites

HIDE_LABELS = {
    "paid": "only listed on a site that charges job seekers",
    "untrusted": "not on a trusted website",
    "fee": "asked for a fee or payment",
    "reported": "from a company you reported",
    "gone": "the posting was already taken down",
}

_CO_SUFFIX = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|company|group|holdings|plc|lp|usa|us)\b\.?")


def dedupe_key(job: dict) -> str:
    company = _CO_SUFFIX.sub("", job["company"].lower())
    company = re.sub(r"[^a-z0-9]", "", company)
    title = re.sub(r"\(.*?\)|\bremote\b|\bhybrid\b|-\s*[a-z ,]+$", "", job["title"].lower())
    title = re.sub(r"\bsr\b\.?", "senior", title)
    title = re.sub(r"[^a-z0-9]", "", title)
    return hashlib.sha1(f"{company}|{title}".encode()).hexdigest()[:16]


def _richness(job: dict) -> tuple:
    return (job.get("apply_kind") == "company", job.get("trust") == "verified",
            bool(job.get("salary")), len(job.get("description") or ""))


async def run_search() -> dict:
    profile = load_profile()
    matchers = place_matchers(profile["nearby_places"])
    raw, report = await fetch_all()
    sites = load_sites()

    dropped = Counter()
    hidden = Counter()          # why jobs were hidden by the safety checks
    hidden_sites = Counter()    # which websites those hidden jobs were on
    kept_by_source = Counter()
    merged: dict[str, dict] = {}
    for job in raw:
        reason = exclusion_reason(job, profile, matchers)
        if reason:
            dropped[reason] += 1
            continue
        scored = score_job(job, profile)
        if not is_relevant(scored):
            dropped["not a match for your target roles"] += 1
            continue
        job.update(scored)

        check = evaluate(job, sites)
        if check["hidden"]:
            hidden[HIDE_LABELS[check["hide_reason"]]] += 1
            hidden_sites[check["hide_site"]] += 1
            continue
        a = check["apply"]
        job.update(url=a["url"], via=a["site"], apply_site=a["site"], apply_kind=a["kind"],
                   apply_domain=a["domain"], trust=check["trust"], warnings=check["warnings"],
                   removed_reason=None, _trusted_options=check["options"])

        key = dedupe_key(job)
        job["id"] = key
        via = job.get("via") or job["source"]
        if key in merged:
            prev = merged[key]
            vias = prev["sources"] + [v for v in [via] if v not in prev["sources"]]
            srcs = prev["_srcs"] | {job["source"]}
            # Keep every trusted place to apply from all copies, best first (company site, then boards).
            seen, opts = set(), []
            for o in sorted((job.get("_trusted_options") or []) + (prev.get("_trusted_options") or []),
                            key=lambda o: o.get("kind") != "company"):
                if o["url"] not in seen:
                    seen.add(o["url"])
                    opts.append(o)
            job["_trusted_options"] = prev["_trusted_options"] = opts
            if _richness(job) > _richness(prev):
                job["sources"], job["_srcs"] = vias, srcs
                merged[key] = job
            else:
                prev["sources"], prev["_srcs"] = vias, srcs
            dropped["duplicate"] += 1
        else:
            job["sources"], job["_srcs"] = [via], {job["source"]}
            merged[key] = job

    # Make sure each Apply link still works. Jobs pulled straight from a company's own
    # job board are live by definition, so only the ones from job boards need checking.
    dead = await verify_jobs([j for j in merged.values() if not j.get("official")])
    for job_id in dead:
        job = merged.pop(job_id)
        hidden[HIDE_LABELS["gone"]] += 1
        hidden_sites[job.get("apply_site") or "unknown site"] += 1

    for job in merged.values():
        job["alt_options"] = [{k: o.get(k) for k in ("url", "site", "kind", "domain")}
                              for o in job.get("_trusted_options") or [] if o.get("url") != job["url"]]
        for s in job["_srcs"]:
            kept_by_source[s] += 1
        job["snippet"] = (job.get("description") or "")[:700]
        loc = (job.get("location") or "").strip()
        if job["_where"] == "remote" and loc.lower() in ("", "anywhere", "remote", "united states", "us", "usa"):
            loc = "Remote (US)"
        job["location"] = loc
        job["is_remote"] = job["_where"] == "remote"

    for r in report:
        r["kept"] = kept_by_source.get(r["source"], 0)

    safety = {"hidden_total": sum(hidden.values()), "reasons": dict(hidden.most_common()),
              "sites": dict(hidden_sites.most_common(8))}
    search = db.save_search_results(merged.values(), report, safety)
    search["dropped"] = dict(dropped.most_common())
    search["hidden"] = dict(hidden.most_common())
    search["hidden_sites"] = dict(hidden_sites.most_common())
    return search
