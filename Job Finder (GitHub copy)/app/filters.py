"""Rules that drop jobs you'd never want: wrong location, clearance, 7+ years, ABAP, stale."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

STATE_NAMES = {"NC": "north carolina", "SC": "south carolina"}

US_HINT = re.compile(r"\b(us|usa|u\.s\.a?\.?|united states|north america|americas|anywhere|worldwide|global)\b", re.I)
NON_US = re.compile(
    r"\b(canada|uk|united kingdom|england|london|ireland|europe|emea|eu|germany|berlin|france|paris|spain|"
    r"portugal|netherlands|amsterdam|poland|romania|ukraine|india|bangalore|bengaluru|pakistan|philippines|"
    r"apac|asia|singapore|japan|australia|new zealand|latam|latin america|mexico|brazil|argentina|colombia|"
    r"israel|south africa|nigeria|kenya|toronto|vancouver|dubai|uae|sweden|denmark|norway|finland|switzerland|"
    r"italy|czech|hungary|serbia|turkey|vietnam|indonesia|malaysia|china|korea|costa rica)\b", re.I)
REGION_LOCK = re.compile(
    r"(?:within|based in|located in|residents? of|must (?:live|reside) in|only (?:hiring|open) in)\s+(?:the\s+)?"
    r"([A-Z][A-Za-z ]{2,30})")

CLEARANCE = re.compile(
    r"top[\s-]secret|ts\s*/\s*sci|\bts-sci\b|secret clearance|security clearance|active clearance|"
    r"clearance (?:is )?required|public trust|\bq clearance|polygraph|full[\s-]scope poly|\bci poly|"
    r"dod clearance|doe clearance|(?:active|current|interim)\s+(?:dod\s+)?secret\b", re.I)

WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15}
YEARS = re.compile(
    r"\b(\d{1,2}|" + "|".join(WORD_NUMS) + r")\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*"
    r"(?:\(\d{1,2}\)\s*)?(?:years?|yrs?)\b([^.;\n]{0,70})", re.I)
PREFERRED = re.compile(r"prefer|nice to have|a plus|is a bonus|ideal", re.I)


def place_matchers(places: list[str]) -> list[re.Pattern]:
    out = []
    for p in places:
        city, _, st = [x.strip() for x in p.partition(",")]
        st_name = STATE_NAMES.get(st.upper(), st.lower())
        out.append(re.compile(
            rf"\b{re.escape(city)}\b.*\b({re.escape(st)}|{re.escape(st_name)})\b", re.I))
    return out


def classify_location(job: dict, matchers: list[re.Pattern]) -> Optional[str]:
    """Returns 'local', 'remote', or None (drop)."""
    loc = job.get("location") or ""
    if any(m.search(loc) for m in matchers):
        return "local"
    remote = job.get("is_remote") or re.search(r"\bremote\b", f"{loc} {job.get('title', '')}", re.I)
    if not remote:
        return None
    # Remote, but is it open to people in the US?
    if NON_US.search(loc) and not US_HINT.search(loc):
        return None
    if not loc.strip() or loc.strip().lower() in ("remote", "anywhere"):
        head = (job.get("description") or "")[:600]
        lock = REGION_LOCK.search(head)
        if lock and NON_US.search(lock.group(1)) and not US_HINT.search(lock.group(1)):
            return None
    return "remote"


def required_years(job: dict) -> Optional[int]:
    """Largest 'N+ years ... experience' requirement that isn't marked preferred."""
    best = job.get("min_years")
    for m in YEARS.finditer(job.get("description") or ""):
        raw, tail = m.group(1).lower(), m.group(2)
        n = WORD_NUMS.get(raw) or (int(raw) if raw.isdigit() else 0)
        if not (1 <= n <= 15) or "experience" not in tail.lower():
            continue
        window = (job["description"][max(0, m.start() - 40):m.end()])
        if PREFERRED.search(window):
            continue
        best = max(best or 0, n)
    return best


def is_stale(job: dict, days: int = 30) -> bool:
    if not job.get("posted_at"):
        return False
    try:
        posted = datetime.fromisoformat(job["posted_at"])
    except ValueError:
        return False
    return posted < datetime.now(timezone.utc) - timedelta(days=days)


def exclusion_reason(job: dict, profile: dict, matchers: list[re.Pattern]) -> Optional[str]:
    title = (job.get("title") or "").lower()
    text = f"{job.get('title', '')}\n{job.get('description', '')}"
    if not title or not job.get("url"):
        return "incomplete"
    if any(re.search(rf"(?<![a-z]){re.escape(k.strip())}(?![a-z])", title)
           for k in profile.get("exclude_title_keywords", [])):
        return "off-target title"
    if is_stale(job):
        return "older than 30 days"
    if re.search(r"\babap\b", text, re.I):
        return "SAP ABAP"
    if CLEARANCE.search(text):
        return "needs clearance"
    yrs = required_years(job)
    if yrs and yrs >= 7:
        return "7+ years required"
    job["_required_years"] = yrs
    where = classify_location(job, matchers)
    if not where:
        return "outside your area"
    job["_where"] = where
    return None
