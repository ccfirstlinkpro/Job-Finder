# Job Finder

Your personal job search page. It runs on your own Mac, only when you open it.

## Open it
Double-click **Job Finder** in this folder. Your browser opens to the site in a few seconds. Nothing else to do.

- The first time ever, it takes about a minute to get set up.
- If it's already open, double-clicking again just brings the page back up.
- When you're done, open **Menu** (top right) and click **⏻ Close Job Finder**. Closing the browser tab alone leaves it running quietly until you click Close or restart your Mac.

**If your Mac says "Job Finder can't be opened"** (this can happen if the folder was copied from somewhere else):
1. Right-click (or Control-click) **Job Finder** and choose **Open**.
2. Click **Open** in the box that appears.

If there's no Open button, go to  menu → **System Settings** → **Privacy & Security**, scroll down, and click **Open Anyway** next to Job Finder. You only have to do this once.

## Get LinkedIn, Indeed and Glassdoor jobs
Open **Menu** → **🔑 JSearch key**, paste your key, and click **Save**. It's remembered from then on.

To get the key:
1. Go to rapidapi.com and make a free account.
2. Search for **JSearch** and open it.
3. Click **Pricing** and subscribe to the free **Basic** plan. The key won't work without this.
4. Open the **Headers** tab and copy the value next to **X-RapidAPI-Key**.

The free plan only allows a limited number of searches each month. Each Search uses up to 10 of them (about 20 Searches a month), but searching again within 4 hours is free.

## Using it
- The top bar always shows **Jobs** and **My jobs**. Everything else (key, companies, review notes, Close) is under **Menu**.
- Use the tabs above the list to see **Integration & EDI**, **IT & Systems** or **Cybersecurity** jobs. Tap **New**, **Entry level**, **Remote** or **Near me** to narrow it down.
- **Search** pulls fresh jobs and puts the best fits first. Jobs you haven't seen before get a **New** tag.
- Each card has a fit badge: **Strong fit**, **In reach** or **Stretch**. It also shows which of your skills the job matches. Click **Details** to see the skills you'd be missing too.
- **Open job** takes you to the posting, and the card then gets a **Viewed** tag.
- **Save** and **Mark applied** add the job to the **My jobs** tab, along with the date you applied.
- **Not interested** hides the job for good.
- Everything is saved, so it's all still there next time.

## Staying safe
- Jobs only appear if you can apply on the company's own career page or on a trusted job board (LinkedIn, Indeed, Glassdoor and others). The Apply button names the site and goes straight there.
- Jobs listed only on sites that charge job seekers (FlexJobs, Virtual Vocations, Ladders) are never shown. Neither are jobs that ask for any fee, deposit or starter kit.
- **✓ Verified source** means a trusted site with no warning signs. **⚠ Check carefully** means something looks off, like a Gmail contact or interviews over Telegram. The reason is shown on the card.
- **Report as sketchy** (inside a job's Details) hides a job for good and blocks where it came from. On big sites like LinkedIn it blocks just that company.
- Both lists are in `config/sites.json` if you ever want to change them.

## For tinkering (optional)
- To change your skills, target titles, nearby towns and search words, edit `config/profile.json`.
- To change which companies are checked directly, use Menu → Companies I check.
- Your saved jobs live in `data/jobs.db`. Your key lives in `.env`.
- If you change `app/JobFinder.applescript`, run `./build_app.sh` to rebuild the Job Finder app.
- Optional extra sources: you can add `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` (free at developer.adzuna.com) or `ANTHROPIC_API_KEY` (for short "why this fits you" notes) to `.env`.
