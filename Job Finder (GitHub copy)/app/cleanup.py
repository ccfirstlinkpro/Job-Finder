"""Re-run the trusted-site and scam checks on every job already in the database.
Jobs you saved or applied to are never removed; they get a "Check carefully" note instead."""
from __future__ import annotations

from collections import Counter

from . import db
from .pipeline import HIDE_LABELS
from .trust import evaluate, load_sites


def recheck_all() -> dict:
    db.init()
    sites = load_sites()
    removed, removed_sites, kept_with_warning = Counter(), Counter(), []
    verified = caution = 0
    for j in db.all_jobs():
        if j.get("removed_reason") or j.get("status") == "hidden":
            continue
        job = {"title": j["title"], "company": j["company"], "url": j["url"],
               "via": (j["sources"] or [""])[0], "description": j.get("snippet") or "",
               "official": any("careers site" in v for v in j["sources"] or [])}
        check = evaluate(job, sites)
        if check["hidden"]:
            label = HIDE_LABELS[check["hide_reason"]]
            if j.get("status") in ("saved", "applied"):
                db.update_job(j["id"], trust="caution",
                              warnings=[f"Couldn't confirm this job is legit: {label} ({check['hide_site']})."])
                kept_with_warning.append(j["title"])
            else:
                db.update_job(j["id"], removed_reason=label)
                removed[label] += 1
                removed_sites[check["hide_site"]] += 1
            continue
        a = check["apply"]
        # Short stored snippets aren't the full description, so don't flag "too short" here.
        warnings = [w for w in check["warnings"] if "very short" not in w]
        db.update_job(j["id"], url=a["url"], apply_site=a["site"], apply_kind=a["kind"],
                      apply_domain=a["domain"], trust="caution" if warnings else "verified", warnings=warnings)
        if warnings:
            caution += 1
        else:
            verified += 1
    return {"removed": dict(removed), "removed_sites": dict(removed_sites.most_common()),
            "kept_with_warning": kept_with_warning, "verified": verified, "caution": caution}
