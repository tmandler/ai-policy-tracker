# AI Policy Tracker

A website that shows what leading business and marketing journals allow when it comes to generative AI. It updates itself every week.

## What happens each week

Every Monday morning (05:17 UTC), GitHub runs the pipeline. It:

1. **Refreshes the journal lists.** It re-reads the FT50 and MktBig15 pages. Journals added or dropped are picked up, and Crossref is checked for publisher changes.
2. **Finds missing policy pages.** For new journals or publishers, Claude searches the web for the right policy page. If a known page stops working three weeks in a row, it searches for the new address.
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
5. **Run it once now.** In GitHub, go to *Actions → Weekly policy check → Run workflow*. The first run reads all 22 pages and takes about 10 minutes.

## Costs (rough)

- **Claude API:** The first run is about $1–2. Later weeks only re-read pages that changed, usually a few cents.
- **Firecrawl:** About 25 pages a week, which fits the free tier.
- **GitHub Actions and Netlify:** Free at this size.

## Everyday maintenance

You shouldn't need to touch it. When an issue appears:

- **To confirm an automatically found page:** In `data/policy_sources.csv`, set its `status` to `verified`.
- **To fix a wrong URL or publisher:** Edit `data/policy_sources.csv` or `data/journals.csv` directly.
- **To close the item:** Delete its entry from `data/review_queue.json`. The issue updates on the next run.
- **To add another journal list:** Add an entry to `data/lists.json` (URL, short description, expected size range).

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
