"""Is this job legit? Picks the safest place to apply and looks for scam warning signs.

Every job ends up as one of:
  - hidden   (no trusted place to apply, only on a pay-to-use site, or asks for a fee)
  - verified (company career page or major job board, no warning signs)  -> green badge
  - caution  (trusted place to apply, but something looks off)             -> yellow badge + reason
The site lists live in config/sites.json.
"""
from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urlparse

from .config import ROOT

SITES_PATH = ROOT / "config" / "sites.json"


# ---------- site lists ----------

def load_sites() -> dict:
    return json.loads(SITES_PATH.read_text(encoding="utf-8"))


def save_sites(sites: dict) -> None:
    SITES_PATH.write_text(json.dumps(sites, indent=2), encoding="utf-8")


def host_of(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def base_domain(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _matches(host: str, domains: list) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _lookup(host: str, table: dict) -> Optional[str]:
    for name, domains in table.items():
        if _matches(host, domains if isinstance(domains, list) else domains.get("domains", [])):
            return name
    return None


JOBBY_DOMAIN = re.compile(r"job|career|hire|hiring|talent|recruit|staff|work", re.I)
# Free/shared hosting where anyone can get a sub-address, so "same domain as the employer" proves nothing.
SHARED_HOSTS = {"dedyn.io", "github.io", "wixsite.com", "herokuapp.com", "blogspot.com", "weebly.com",
                "netlify.app", "vercel.app", "square.site", "godaddysites.com", "wordpress.com",
                "carrd.co", "webflow.io", "notion.site", "sites.google.com", "google.com"}


def looks_like_company_site(host: str, emp_host: str) -> bool:
    if not (host and emp_host) or base_domain(host) != base_domain(emp_host):
        return False
    if base_domain(emp_host) in SHARED_HOSTS:
        return False
    # The employer's "website" shouldn't itself be a job site (e.g. remotejobs.example.io).
    name = re.sub(r"^(www|careers?|jobs)\.", "", emp_host)
    return not JOBBY_DOMAIN.search(name)


def possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def classify_option(opt: dict, job: dict, sites: dict) -> dict:
    """Returns {kind: company|board|blocked|untrusted, site, domain, url, reason?}."""
    url = opt.get("url") or ""
    host = host_of(url)
    publisher = (opt.get("publisher") or "").strip()
    out = {"url": url, "domain": host, "site": publisher or host}

    blocked = _lookup(host, sites.get("blocked_sites", {}))
    if not blocked:
        blocked = next((n for n in sites.get("blocked_sites", {}) if n.lower() == publisher.lower()), None)
    if blocked:
        info = sites["blocked_sites"][blocked]
        return {**out, "kind": "blocked", "site": blocked,
                "reason": info.get("reason", "is on your blocked list") if isinstance(info, dict) else "is on your blocked list"}

    company = job.get("company") or "the company"
    if opt.get("official"):   # pulled straight from the company's own Greenhouse/Lever job board
        return {**out, "kind": "company", "site": f"{possessive(company)} site"}
    ats = _lookup(host, sites.get("company_hiring_systems", {}))
    if ats:
        return {**out, "kind": "company", "site": f"{possessive(company)} site", "system": ats}

    # The company's own careers page: same domain as the employer's website.
    if looks_like_company_site(host, host_of(job.get("employer_website") or "")):
        return {**out, "kind": "company", "site": f"{possessive(company)} site"}

    board = _lookup(host, sites.get("trusted_job_boards", {}))
    if board:
        return {**out, "kind": "board", "site": board}

    return {**out, "kind": "untrusted"}


def apply_options(job: dict) -> list:
    opts = list(job.get("apply_options") or [])
    if not opts and job.get("url"):
        opts = [{"url": job["url"], "publisher": job.get("via") or "", "official": bool(job.get("official"))}]
    return opts


def pick_apply(job: dict, sites: dict) -> dict:
    """Best place to apply: company site first, then a trusted board. Otherwise explains why not."""
    classified = [classify_option(o, job, sites) for o in apply_options(job)]
    trusted = [c for kind in ("company", "board") for c in classified if c["kind"] == kind]
    if trusted:
        return {**trusted[0], "options": trusted}
    blocked = [c for c in classified if c["kind"] == "blocked"]
    if blocked:
        return {"kind": "hidden", "why": "paid", "site": blocked[0]["site"], "reason": blocked[0]["reason"]}
    names = [c["site"] for c in classified if c.get("site")]
    return {"kind": "hidden", "why": "untrusted", "site": names[0] if names else "unknown site"}


# ---------- scam warning signs ----------

FEE = re.compile(
    r"(application|processing|registration|training|onboarding|enrollment|certification|placement|"
    r"background[- ]check|equipment|membership|interview|starter[- ]kit)\s+fees?\b"
    r"|\bfees?\s+(is|are)\s+(required|due|payable)"
    r"|\bpay\s+(a|an|the|us|our)\s+(small\s+|one[- ]time\s+|refundable\s+)?(fee|deposit)"
    r"|\b(you|candidates?|applicants?)\s+(will\s+)?(need|have|are required)\s+to\s+pay\b"
    r"|\btraining\s+costs?\b|\bstarter\s+kit\b|\brefundable\s+deposit\b|\bsecurity\s+deposit\b"
    r"|\bsend\s+(us\s+)?(money|payment)\b|\bpurchase\s+(the\s+|a\s+)?(training|course|kit)\b"
    r"|\b(buy|purchase)\s+(your\s+own\s+)?(equipment|laptop|software)\s+(from|through)\s+(our|an?\s+approved|the)\s+vendor",
    re.I)

WARNINGS = [
    (re.compile(r"\b(telegram|whats\s?app)\b|\b(on|via|through|using)\s+signal\b|\bsignal\s+app\b", re.I),
     "Wants to talk over a chat app (Telegram, WhatsApp or Signal)."),
    (re.compile(r"interview(ed|s)?\s+(will\s+be\s+)?(conducted\s+)?(via|by|over|through)\s+(text|chat|sms|instant\s+messag)|text[- ]only\s+interview", re.I),
     "Interviews by text message only."),
    (re.compile(r"[\w.+-]+@(gmail|yahoo|outlook|hotmail|aol|icloud|protonmail|proton)\.(com|me)\b", re.I),
     "Contact is a personal email address ({m})."),
    (re.compile(r"(send|provide|submit|share|email)\s+(us\s+)?(your\s+)?(bank\s+account|routing\s+number|social\s+security|ssn|driver'?s\s+licen[cs]e|passport|photo\s+id)", re.I),
     "Asks for your bank details, SSN or ID."),
    (re.compile(r"\b(cash(ing)?\s+(a\s+|the\s+)?checks?|deposit\s+(a|the)\s+check|reship(ping)?|package\s+forwarding|forward(ing)?\s+packages)\b", re.I),
     "Mentions cashing checks or reshipping packages."),
    (re.compile(r"\b(bitcoin|crypto\s?currency|usdt|crypto\s+wallet)\b", re.I),
     "Mentions crypto payments."),
]

FAKE_COMPANY = {"", "confidential", "company", "hiring", "employer", "n/a", "na", "private", "undisclosed",
                "hiring company", "our client", "client"}


def scam_check(job: dict) -> tuple:
    """Returns (hide_reason or None, [warnings])."""
    text = f"{job.get('title', '')}\n{job.get('description', '')}"
    m = FEE.search(text)
    if m:
        return f"asks for a fee or payment (“{m.group(0).strip()}”)", []

    warnings = []
    for pat, msg in WARNINGS:
        hit = pat.search(text)
        if hit:
            warnings.append(msg.format(m=hit.group(0)))

    company = (job.get("company") or "").strip().lower()
    if company in FAKE_COMPANY:
        warnings.append("No real company name is listed.")

    annual = job.get("salary_max_annual")
    if annual:
        senior = re.search(r"\b(senior|sr|lead|principal|staff|architect|manager|director)\b", job.get("title", ""), re.I)
        if annual > (300000 if senior else 200000):
            warnings.append("Pay looks unusually high for this kind of role.")

    desc = (job.get("description") or "").strip()
    if len(desc) < 250:
        warnings.append("The job description is very short or vague.")
    return None, warnings


def evaluate(job: dict, sites: dict) -> dict:
    """Full check. Returns {hidden: bool, hide_reason, hide_site, apply: {...}, trust, warnings}."""
    company = (job.get("company") or "").strip().lower()
    if company and company in {c.lower() for c in sites.get("blocked_companies", [])}:
        return {"hidden": True, "hide_reason": "reported", "hide_site": job.get("company")}

    choice = pick_apply(job, sites)
    if choice["kind"] == "hidden":
        return {"hidden": True, "hide_reason": choice["why"], "hide_site": choice["site"]}

    fee, warnings = scam_check(job)
    if fee:
        return {"hidden": True, "hide_reason": "fee", "hide_site": choice["site"], "detail": fee}

    return {"hidden": False, "apply": choice, "options": choice["options"], "warnings": warnings,
            "trust": "caution" if warnings else "verified"}
