"""Loads your profile and the company list from the config/ folder."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "config" / "profile.json"
COMPANIES_PATH = ROOT / "config" / "companies.json"
ENV_PATH = ROOT / ".env"


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def load_companies() -> list[dict]:
    if not COMPANIES_PATH.exists():
        return []
    return json.loads(COMPANIES_PATH.read_text(encoding="utf-8")).get("companies", [])


def save_companies(companies: list[dict]) -> None:
    COMPANIES_PATH.write_text(json.dumps({"companies": companies}, indent=2), encoding="utf-8")


def parse_company_input(text: str, ats: str = "") -> dict:
    """Accepts a slug ('cloudflare') or a board URL
    ('https://boards.greenhouse.io/cloudflare', 'https://jobs.lever.co/palantir')."""
    text = text.strip()
    m = re.search(r"greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)", text)
    if m:
        return {"ats": "greenhouse", "slug": m.group(1).lower()}
    m = re.search(r"lever\.co/([A-Za-z0-9_-]+)", text)
    if m:
        return {"ats": "lever", "slug": m.group(1).lower()}
    slug = re.sub(r"[^a-z0-9_-]", "", text.lower().replace(" ", ""))
    return {"ats": ats or "greenhouse", "slug": slug}


def set_env_value(name: str, value: str) -> None:
    """Write NAME=value into .env (replacing any old line) and apply it right away."""
    if not ENV_PATH.exists():
        example = ROOT / ".env.example"
        if example.exists():
            shutil.copy(example, ENV_PATH)
        else:
            ENV_PATH.write_text("", encoding="utf-8")
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    out, done = [], False
    for line in lines:
        if re.match(rf"\s*{re.escape(name)}\s*=", line):
            if not done:
                out.append(f"{name}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"{name}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_PATH, 0o600)   # only you can read your keys
    except OSError:
        pass
    os.environ[name] = value
