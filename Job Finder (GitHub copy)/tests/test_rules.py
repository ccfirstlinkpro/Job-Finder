"""Quick checks for the filtering and scoring rules. Run: python -m tests.test_rules"""
from datetime import datetime, timedelta, timezone

from app.config import load_profile, parse_company_input
from app.filters import exclusion_reason, place_matchers
from app.pipeline import dedupe_key
from app.scoring import is_relevant, score_job

P = load_profile()
M = place_matchers(P["nearby_places"])
NOW = datetime.now(timezone.utc).isoformat()


def job(**kw):
    base = dict(title="EDI Analyst", company="Acme", location="Charlotte, NC", is_remote=False,
                url="https://x", posted_at=NOW,
                description="Manage EDI X12 204 210 214 trading partner onboarding using Cleo, AS2, SFTP and SQL.")
    base.update(kw)
    return base


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    return ok


results = [
    check("Charlotte on-site kept", exclusion_reason(job(), P, M), None),
    check("Hickory kept", exclusion_reason(job(location="Hickory, North Carolina"), P, M), None),
    check("Concord, CA dropped", exclusion_reason(job(location="Concord, CA"), P, M), "outside your area"),
    check("Denver, CO dropped", exclusion_reason(job(location="Denver, CO"), P, M), "outside your area"),
    check("Raleigh dropped", exclusion_reason(job(location="Raleigh, NC"), P, M), "outside your area"),
    check("Remote US kept", exclusion_reason(job(location="Remote - USA", is_remote=True), P, M), None),
    check("Remote Canada dropped", exclusion_reason(job(location="Remote, Canada"), P, M), "outside your area"),
    check("Remote US or Canada kept", exclusion_reason(job(location="Remote - US or Canada"), P, M), None),
    check("Remote 'within Germany' dropped",
          exclusion_reason(job(location="", is_remote=True, description="Mostly remote (within Germany). EDI SQL"), P, M),
          "outside your area"),
    check("TS/SCI dropped", exclusion_reason(job(description="Must hold an active TS/SCI. EDI"), P, M), "needs clearance"),
    check("Public Trust dropped", exclusion_reason(job(description="Ability to obtain Public Trust"), P, M), "needs clearance"),
    check("'secret sauce' not clearance", exclusion_reason(job(description="Our secret sauce is EDI X12 and SQL."), P, M), None),
    check("8+ years dropped", exclusion_reason(job(description="8+ years of experience with EDI"), P, M), "7+ years required"),
    check("seven years dropped", exclusion_reason(job(description="Seven (7) years of relevant experience required"), P, M), "7+ years required"),
    check("3-5 years kept", exclusion_reason(job(description="3-5 years of EDI experience"), P, M), None),
    check("10 years preferred kept", exclusion_reason(job(description="10+ years of experience preferred"), P, M), None),
    check("ABAP dropped", exclusion_reason(job(title="SAP ABAP Developer"), P, M), "SAP ABAP"),
    check("Stale dropped", exclusion_reason(job(posted_at=(datetime.now(timezone.utc) - timedelta(days=45)).isoformat()), P, M),
          "older than 30 days"),
    check("Director dropped", exclusion_reason(job(title="Director of Integration"), P, M), "off-target title"),
    check("Salesforce not caught by 'sales'", exclusion_reason(job(title="Salesforce Integration Developer"), P, M), None),
    check("Internal not caught by 'intern'", exclusion_reason(job(title="Internal Systems Analyst"), P, M), None),
]

j = job(); exclusion_reason(j, P, M); s = score_job(j, P)
print(f"     EDI Analyst score={s['score']} badge={s['badge']} matched={s['matched']} missing={s['missing']}")
results.append(check("EDI analyst is Strong fit", s["badge"], "Strong fit"))

j = job(title="Senior Systems Analyst", description="SQL, Power BI, Azure, C# .NET, Java required. Troubleshooting.")
exclusion_reason(j, P, M); s = score_job(j, P)
print(f"     Sr Systems Analyst score={s['score']} badge={s['badge']} missing={s['missing']}")
results.append(check("Sr systems analyst w/ gaps not strong", s["badge"] != "Strong fit", True))

j = job(title="SOC Analyst I", location="Remote", is_remote=True,
        description="Monitor SIEM alerts (Splunk), incident response, networking, firewall, Windows, cybersecurity. Security+ preferred.")
exclusion_reason(j, P, M); s = score_job(j, P)
print(f"     SOC Analyst I score={s['score']} badge={s['badge']} matched={s['matched']} missing={s['missing']}")
results.append(check("SOC analyst relevant", is_relevant(s), True))

j = job(title="Software Engineer", description="React, TypeScript, Kubernetes.")
exclusion_reason(j, P, M)
results.append(check("Generic SWE not relevant", is_relevant(score_job(j, P)), False))

results.append(check("dedupe same job", dedupe_key(job(company="Acme, Inc.", title="Sr. EDI Analyst (Remote)")),
                     dedupe_key(job(company="ACME", title="Senior EDI Analyst"))))
results.append(check("company link parse", parse_company_input("https://jobs.lever.co/palantir/abc"),
                     {"ats": "lever", "slug": "palantir"}))

print(f"\n{sum(results)}/{len(results)} passed")
