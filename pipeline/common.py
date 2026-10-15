import csv
import datetime
import hashlib
import json
import os
import pathlib
import re
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SNAP = DATA / "snapshots"
EXTR = DATA / "extracted"
FIXTURES = ROOT / "tests" / "fixtures"
SITE_DATA = ROOT / "site" / "src" / "data"

JOURNALS = DATA / "journals.csv"
SOURCES = DATA / "policy_sources.csv"
STATE = DATA / "state.json"
CHANGELOG = DATA / "changelog.jsonl"
REVIEW = DATA / "review_queue.json"
LISTS = DATA / "lists.json"

MOCK = os.getenv("MOCK") == "1"
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY", "")
CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO", "")
USER_AGENT = "ai-policy-tracker/1.0 (+academic research; weekly check)"

JOURNAL_FIELDS = ["journal", "abbrev", "source_list", "publisher", "owner_society", "field", "issn",
                  "publisher_policy", "extra_policy", "coverage_note", "active", "added_on"]
SOURCE_FIELDS = ["source_id", "entity", "level", "url", "status", "notes"]


def today():
    return datetime.date.today().isoformat()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def norm_title(t):
    t = t.lower().replace("&", "and")
    t = re.sub(r"^the\s+", "", t.strip())
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def content_hash(text):
    t = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]


def log_change(kind, **fields):
    entry = {"date": today(), "type": kind, **fields}
    with open(CHANGELOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"  [change] {kind}: {fields}")


def queue_review(key, reason, **fields):
    queue = load_json(REVIEW, [])
    if any(q["key"] == key for q in queue):
        return
    queue.append({"key": key, "reason": reason, "added": today(), **fields})
    save_json(REVIEW, queue)
    print(f"  [review] {key}: {reason}")


class FetchError(Exception):
    pass


def fetch_markdown(url, fixture_key=None):
    if MOCK:
        p = FIXTURES / f"{fixture_key}.md"
        if (FIXTURES / f"{fixture_key}.missing").exists():
            raise FetchError(f"fixture {fixture_key} marked missing")
        if not p.exists():
            p = FIXTURES / "_default.md"
        return p.read_text(encoding="utf-8").replace("{key}", fixture_key or "")
    if FIRECRAWL_KEY:
        r = requests.post(
            "https://api.firecrawl.dev/v2/scrape",
            headers={"Authorization": f"Bearer {FIRECRAWL_KEY}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            timeout=180,
        )
        if r.status_code != 200:
            raise FetchError(f"firecrawl http {r.status_code}")
        body = r.json()
        data = body.get("data") or {}
        status = (data.get("metadata") or {}).get("statusCode", 200)
        md = data.get("markdown") or ""
        if not body.get("success") or status >= 400 or len(md) < 200:
            raise FetchError(f"firecrawl failed (page status {status}, {len(md)} chars)")
        return md
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    if r.status_code >= 400:
        raise FetchError(f"http {r.status_code}")
    if "pdf" in r.headers.get("content-type", ""):
        raise FetchError("PDF needs FIRECRAWL_API_KEY")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) < 200:
        raise FetchError("page too short")
    return text


def _client():
    import anthropic
    return anthropic.Anthropic()


def claude_json(system, user, schema, max_tokens=3000):
    r = _client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    if r.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"claude stop_reason={r.stop_reason}")
    text = next(b.text for b in r.content if b.type == "text")
    return json.loads(text)


def claude_search_json(prompt, max_uses=5):
    r = _client().messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}],
    )
    text = "".join(b.text for b in r.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("no JSON in search answer")
    return json.loads(m.group(0))


def polite_pause():
    if not MOCK:
        time.sleep(2)
