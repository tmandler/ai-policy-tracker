# AI Policy Tracker

A website that shows what leading business and marketing journals allow when it comes to generative AI. It updates itself every week.

## What happens each week

Every Monday morning (05:17 UTC), GitHub runs the pipeline. It:

1. **Refreshes the journal lists.** The sample is every journal graded 3, 4 or 4* in the AJG 2024 (`data/journals.csv`, column `ajg`). The FT50 and UTD24 pages are re-read each week to keep those filter tags current, and Crossref is checked for publisher changes.
2. **Finds missing policy pages.** For new journals or publishers, Claude searches the web for the right policy page. Journal searches are capped at 50 per run (FT50/UTD24 first, then by AJG grade), so after a list change the backlog clears over a few weeks. Set the variable `MAX_JOURNAL_SEARCHES` to change the cap. If a known page stops working three weeks in a row, it searches for the new address.
3. **Downloads every policy page.** A page whose text is unchanged is skipped.
4. **Reads changed pages.** Claude records seven points (author use, disclosure, AI as author, AI images, reviewer use, reviewer upload, editor use), with short quotes as evidence. A change is logged only when one of those seven points changes.
5. **Rebuilds the website data.** The results are committed to the repository, and Netlify then publishes the updated site.

If something needs a human decision, the pipeline opens (or updates) a GitHub issue labelled `tracker-review`. Examples: a page that keeps failing, an automatically found URL, a publisher change, or a list that suddenly looks wrong. You get the usual GitHub email.

## One-time setup

1. **Create a GitHub repository** and upload this folder to it.
2. **Add two secrets.** Go to *Settings → Secrets and variables → Actions → New repository secret*:
   - `ANTHROPIC_API_KEY`: your Claude API key.
   - `FIRECRAWL_API_KEY`: needed for Wiley, the FT page and the PDF policies, which block plain downloads.
3. **Add one variable.** On the same page, under the *Variables* tab, add `CROSSREF_MAILTO` = your email address. Crossref asks for this to give polite, faster access.
4. **Connect Netlify.** *Add new site → Import from GitHub*, then pick the repository. The settings are read from `netlify.toml`, so just click deploy.
5. **Run it once now.** In GitHub, go to *Actions → Weekly policy check → Run workflow*. The first run reads all policy pages and starts the journal-level searches; it can take up to two hours.

## Costs (rough)

- **Claude API:** While the journal-level backlog is being worked through (about 9 weekly runs after the switch to the AJG sample), each run does up to 50 web searches, roughly $3–8 a week. After that, only changed pages are re-read, usually under $1 a week.
- **Firecrawl:** Pages are first fetched directly; Firecrawl is only used when that fails (e.g. Wiley, PDFs). Expect a few dozen to a few hundred credits a week as journal pages are added, which may exceed the free tier.
- **GitHub Actions and Netlify:** Free at this size.

## Everyday maintenance

You shouldn't need to touch it. When an issue appears:

- **To confirm an automatically found page:** In `data/policy_sources.csv`, set its `status` to `verified`.
- **To fix a wrong URL or publisher:** Edit `data/policy_sources.csv` or `data/journals.csv` directly.
- **To close the item:** Delete its entry from `data/review_queue.json`. The issue updates on the next run.
- **To add another filter list:** Add an entry to `data/lists.json` (URL, short description, expected size range).
- **When a new AJG edition appears (next due 2027):** Update the `ajg` column in `data/journals.csv`. New journals need a row with `coverage_note` = `new: journal-level check pending`; the pipeline does the rest.

## Files

| Path | What it is |
|---|---|
| `data/journals.csv` | The journals, their lists, publishers and which policy pages apply |
| `data/policy_sources.csv` | The policy pages being watched |
| `data/lists.json` | Where the journal lists are read from |
| `data/snapshots/` | The latest text of each policy page (git history keeps every version) |
| `data/extracted/` | What Claude read from each page |
| `data/changelog.jsonl` | Every change detected |
| `data/REVIEW.md` | Current items needing a human look |
| `pipeline/` | The Python scripts (`run.py` runs them all in order) |
| `site/` | The Astro website |

## Running it on your own machine

```
pip install -r requirements.txt
cd pipeline
MOCK=1 python run.py    # test run with sample data, no API calls
python run.py           # real run (needs the API keys as environment variables)
cd ../site && npm install && npm run dev
```

`MOCK=1` uses placeholder pages from `tests/fixtures/`. Never commit the output of a mock run. Delete `data/state.json`, `data/extracted/*`, `data/snapshots/*` and `data/changelog.jsonl` afterwards.
