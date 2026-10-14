"""0–100 fit score: skills (45) + title (30) + seniority (15) + location (10)."""
from __future__ import annotations

import re
from functools import lru_cache


def _pat(alias: str) -> re.Pattern:
    return re.compile(rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])")


@lru_cache(maxsize=4)
def _compiled(profile_json: str):
    import json
    p = json.loads(profile_json)
    skills = [(name, s["weight"], [_pat(a) for a in s["aliases"]]) for name, s in p["skills"].items()]
    gaps = [(name, [_pat(a) for a in aliases]) for name, aliases in p["gaps"].items()]
    return skills, gaps


def compile_profile(profile: dict):
    import json
    return _compiled(json.dumps({"skills": profile["skills"], "gaps": profile["gaps"]}, sort_keys=True))


def title_tier(title: str, profile: dict) -> str:
    t = f" {title.lower()} "
    kw = profile["title_keywords"]
    for tier in ("strong", "medium", "weak"):
        if any(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", t) for k in kw[tier]):
            return tier
    return "none"


ENTRY_TITLE = re.compile(r"\b(junior|jr\.?|entry|associate|apprentice|trainee|graduate|new grad|i|1|tier 1|level 1|l1)\b", re.I)
ENTRY_TEXT = re.compile(r"entry[- ]level|new grad(uate)?s?\b|recent (college )?graduates?|early[- ]career|"
                        r"\b(0|zero)\s*(-|–|to)\s*[1-3]\+?\s*years?|no (prior )?experience (is )?required|"
                        r"\b1\+?\s*years?\s+(of\s+)?(relevant\s+)?experience", re.I)
SENIOR_TITLE = re.compile(r"\b(senior|sr\.?|lead|staff|principal|architect|manager|director|iii|iv)\b", re.I)


def is_entry_level(title: str, description: str, req_years) -> bool:
    if SENIOR_TITLE.search(title):
        return False
    if ENTRY_TITLE.search(f" {title} "):
        return True
    if req_years is not None and req_years <= 2:
        return True
    return bool(ENTRY_TEXT.search(description or ""))


def category_of(title: str, profile: dict) -> str:
    t = f" {title.lower()} "
    for name, words in profile.get("categories", {}).items():
        if words and any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t) for w in words):
            return name
    return "IT & Systems"


def seniority_points(title: str, req_years, entry: bool = False) -> int:
    t = f" {title.lower()} "
    if re.search(r"\b(staff|principal|architect|manager)\b", t):
        pts = 3
    elif re.search(r"\b(senior|sr\.?|lead|iii|iv)\b", t):
        pts = 7
    elif re.search(r"\b(junior|jr\.?|entry|associate|i|ii|1|2|level 1|tier 1)\b", t):
        pts = 15
    else:
        pts = 12
    if entry:
        pts = max(pts, 15)
    if req_years:
        if req_years <= 5:
            pts = max(pts, 10)
        elif req_years == 6:
            pts -= 5
    return max(0, min(15, pts))


def score_job(job: dict, profile: dict) -> dict:
    skills, gaps = compile_profile(profile)
    text = f"{job.get('title', '')}\n{job.get('description', '')}".lower()

    matched, weight = [], 0
    for name, w, pats in skills:
        if any(p.search(text) for p in pats):
            matched.append(name)
            weight += w
    missing = [name for name, pats in gaps if any(p.search(text) for p in pats)]

    skill_pts = 45 * min(1.0, weight / 12) * (1 - min(0.5, 0.1 * len(missing)))
    tier = title_tier(job.get("title", ""), profile)
    title_pts = {"strong": 30, "medium": 22, "weak": 10, "none": 0}[tier]
    entry = is_entry_level(job.get("title", ""), job.get("description", ""), job.get("_required_years"))
    sen_pts = seniority_points(job.get("title", ""), job.get("_required_years"), entry)
    loc_pts = 10 if job.get("_where") in ("local", "remote") else 0

    score = int(round(skill_pts + title_pts + sen_pts + loc_pts))
    badge = "Strong fit" if score >= 70 else "In reach" if score >= 50 else "Stretch"
    return {"score": score, "badge": badge, "matched": matched, "missing": missing,
            "title_tier": tier, "skill_weight": weight, "entry_level": entry,
            "category": category_of(job.get("title", ""), profile)}


def is_relevant(scored: dict) -> bool:
    """Strong/medium titles always count; generic titles ('Analyst', 'Engineer') need real skill overlap."""
    tier = scored["title_tier"]
    if scored.get("entry_level") and tier in ("strong", "medium"):
        return True      # entry-level roles in your target areas: your CIS degree is the main qualification
    if tier in ("strong", "medium"):
        return scored["skill_weight"] >= 2
    if tier == "weak":
        return scored["skill_weight"] >= 7
    return False
