"""Optional: Claude writes a 2-sentence 'why this fits you' for your top jobs.
Only runs when ANTHROPIC_API_KEY is set in .env. Summaries are cached in the database."""
from __future__ import annotations

import asyncio
import os

from . import db
from .config import load_profile

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")


def enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def _prompt(job: dict, profile: dict) -> str:
    return (
        f"Candidate: {profile['summary']}\n"
        f"Candidate skills: {', '.join(profile['skills'])}.\n"
        f"Known gaps: {', '.join(list(profile['gaps'])[:4])}.\n\n"
        f"Job: {job['title']} at {job['company']} ({job['location']}).\n"
        f"Skills that matched: {', '.join(job['matched']) or 'none'}. "
        f"Skills they'd be missing: {', '.join(job['missing']) or 'none'}.\n"
        f"Posting excerpt: {(job.get('snippet') or '')[:1500]}\n\n"
        "Write exactly two short sentences, addressed to the candidate as 'you', explaining why this job "
        "fits them and the one thing to brush up on or highlight. Plain text, no preamble."
    )


async def summarize_top(jobs: list[dict], limit: int = 20) -> int:
    """Fill in summaries for the top N jobs that don't have one yet. Returns how many were written."""
    if not enabled():
        return 0
    import anthropic

    todo = [j for j in jobs[:limit] if not j.get("summary")]
    if not todo:
        return 0
    profile = load_profile()
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip(), timeout=60.0, max_retries=2)
    sem = asyncio.Semaphore(4)

    async def one(job):
        async with sem:
            try:
                resp = await client.beta.messages.create(
                    model=MODEL,
                    max_tokens=2000,
                    betas=["server-side-fallback-2026-07-01"],
                    extra_body={"fallbacks": "default", "output_config": {"effort": "low"}},
                    messages=[{"role": "user", "content": _prompt(job, profile)}],
                )
            except anthropic.AuthenticationError:
                raise
            except anthropic.APIError:
                return False
            if resp.stop_reason == "refusal":
                return False
            text = " ".join(b.text for b in resp.content if b.type == "text").strip()
            if text:
                db.set_summary(job["id"], text)
                job["summary"] = text
                return True
            return False

    try:
        results = await asyncio.gather(*(one(j) for j in todo))
    except anthropic.AuthenticationError:
        return -1
    finally:
        await client.close()
    return sum(1 for r in results if r)
