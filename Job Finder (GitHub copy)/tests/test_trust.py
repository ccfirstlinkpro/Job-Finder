"""Checks for the trusted-site and scam rules. Run: .venv/bin/python -m tests.test_trust"""
from app.trust import evaluate, load_sites

SITES = load_sites()
LONG = " We are hiring an EDI analyst to manage X12 trading partner onboarding, mapping and SFTP/AS2 connections." * 4


def job(opts, company="Acme Health", desc=LONG, website="https://www.acmehealth.com", **kw):
    j = {"title": "EDI Analyst", "company": company, "description": desc, "employer_website": website,
         "apply_options": [{"url": u, "publisher": p} for p, u in opts]}
    j.update(kw)
    return j


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    return ok


def show(j):
    r = evaluate(j, SITES)
    if r["hidden"]:
        return ("hidden", r["hide_reason"])
    return (r["trust"], r["apply"]["site"])


R = []
R.append(check("Virtual Vocations only -> hidden (paid)",
               show(job([("Virtual Vocations", "https://www.virtualvocations.com/job/x.html")], website=None)), ("hidden", "paid")))
R.append(check("FlexJobs only -> hidden (paid)",
               show(job([("FlexJobs", "https://www.flexjobs.com/x")])), ("hidden", "paid")))
R.append(check("Ladders + Indeed -> Indeed",
               show(job([("Ladders", "https://www.theladders.com/job/1"), ("Indeed", "https://www.indeed.com/viewjob?jk=1")])), ("verified", "Indeed")))
R.append(check("LinkedIn + company careers page -> company first",
               show(job([("LinkedIn", "https://www.linkedin.com/jobs/view/1"), ("Acme Careers", "https://careers.acmehealth.com/job/1")])), ("verified", "Acme Health's site")))
R.append(check("Workday -> company site",
               show(job([("Acme", "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/1")], website=None)), ("verified", "Acme Health's site")))
R.append(check("Learn4Good only -> hidden (untrusted)",
               show(job([("Learn4Good", "https://www.learn4good.com/jobs/1")])), ("hidden", "untrusted")))
R.append(check("Fake 'remotejobs' employer site doesn't count as company page",
               show(job([("Remote Quest Jobs", "https://us.remotejobs.dedyn.io/job/1")], website="https://us.remotejobs.dedyn.io")), ("hidden", "untrusted")))
R.append(check("Application fee -> hidden",
               show(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], desc=LONG + " A $45 application fee is required.")), ("hidden", "fee")))
R.append(check("Starter kit -> hidden",
               show(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], desc=LONG + " You must buy a starter kit.")), ("hidden", "fee")))
R.append(check("Direct deposit / payment files are fine",
               show(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], desc=LONG + " Process 810 invoice and payment files. Direct deposit available.")), ("verified", "Indeed")))
R.append(check("'signal processing' is fine",
               show(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], desc=LONG + " Some signal processing background helps.")), ("verified", "Indeed")))

r = evaluate(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], desc=LONG + " Email resumes to hr.acme.jobs@gmail.com"), SITES)
R.append(check("Gmail contact -> caution", (r["trust"], r["warnings"][0]), ("caution", "Contact is a personal email address (hr.acme.jobs@gmail.com).")))
r = evaluate(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], desc=LONG + " Interviews are held on Telegram."), SITES)
R.append(check("Telegram -> caution", r["trust"], "caution"))
r = evaluate(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], company="Confidential"), SITES)
R.append(check("No company name -> caution", r["warnings"], ["No real company name is listed."]))
r = evaluate(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], desc="Great job! Apply now."), SITES)
R.append(check("Vague description -> caution", r["warnings"], ["The job description is very short or vague."]))
r = evaluate(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], salary_max_annual=320000), SITES)
R.append(check("Pay way too high -> caution", r["warnings"], ["Pay looks unusually high for this kind of role."]))
r = evaluate(job([("Indeed", "https://www.indeed.com/viewjob?jk=1")], desc=LONG + " Send us your SSN and bank account to get started."), SITES)
R.append(check("Asks for SSN/bank -> caution", r["warnings"], ["Asks for your bank details, SSN or ID."]))

print(f"\n{sum(R)}/{len(R)} passed")
