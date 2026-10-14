"""Helper for the daily review of "Link didn't work" reports.

    .venv/bin/python -m app.review list                 # unreviewed reports, with a fresh re-check of each link
    .venv/bin/python -m app.review mark 3 4 "note"      # mark reports as reviewed with a short note
    .venv/bin/python -m app.review note "text"          # add an entry to data/review_notes.md (shown on the site)
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime

from . import db
from .config import ROOT
from .linkcheck import inspect_url

NOTES_PATH = ROOT / "data" / "review_notes.md"


def list_reports() -> list:
    db.init()
    reports = db.broken_links(unreviewed_only=True)

    async def recheck_all():
        return await asyncio.gather(*(inspect_url(r["url"]) for r in reports))

    for r, now in zip(reports, asyncio.run(recheck_all()) if reports else []):
        r["recheck_now"] = now
    return reports


def mark(ids: list, note: str) -> None:
    with db.connect() as c:
        for i in ids:
            c.execute("UPDATE broken_links SET reviewed_at=?, review_note=? WHERE id=?", (db.now(), note, int(i)))


def add_note(text: str) -> None:
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%A, %B %-d, %Y")
    old = NOTES_PATH.read_text(encoding="utf-8") if NOTES_PATH.exists() else ""
    NOTES_PATH.write_text(f"## {stamp}\n{text.strip()}\n\n{old}", encoding="utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        print(json.dumps(list_reports(), indent=2))
    elif cmd == "mark":
        mark(sys.argv[2:-1], sys.argv[-1])
        print("marked", sys.argv[2:-1])
    elif cmd == "note":
        add_note(sys.argv[2])
        print("note added")
