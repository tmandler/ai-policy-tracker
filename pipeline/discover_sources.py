import re

from common import (JOURNAL_FIELDS, JOURNALS, MOCK, SOURCE_FIELDS, SOURCES, STATE, FetchError, claude_search_json,
                    fetch_markdown, load_json, log_change, queue_review, read_csv, save_json, today, write_csv)

RETRY_DAYS = 30

PROMPT = """Find the official, current web page that states {what}.
Prefer the publisher's or journal's own site over third-party summaries. {extra}
Answer with only a JSON object: {{"found": true/false, "url": "...", "note": "one short sentence"}}"""


def slug(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())[:10] or "X"


def recently_tried(state, key):
    last = state.setdefault("_discovery", {}).get(key)
    if not last:
        return False
    from datetime import date
    return (date.today() - date.fromisoformat(last)).days < RETRY_DAYS


def search(state, key, what, extra=""):
    state.setdefault("_discovery", {})[key] = today()
    if MOCK:
        print(f"  [mock] would search: {what}")
        return None
    try:
        ans = claude_search_json(PROMPT.format(what=what, extra=extra))
    except Exception as e:
        print(f"  discovery failed {key}: {e}")
        return None
    if not ans.get("found") or not ans.get("url", "").startswith("http"):
        return None
    try:
        fetch_markdown(ans["url"])
    except FetchError as e:
        print(f"  discovered url not fetchable {ans['url']}: {e}")
        return None
    return ans


def run():
    journals = read_csv(JOURNALS)
    sources = read_csv(SOURCES)
    state = load_json(STATE, {})
    by_id = {s["source_id"]: s for s in sources}
    pub_sources = {s["entity"]: s["source_id"] for s in sources if s["level"] == "publisher"}

    for s in sources:
        st = state.get(s["source_id"], {})
        if st.get("needs_rediscovery") and not recently_tried(state, f"moved:{s['source_id']}"):
            ans = search(state, f"moved:{s['source_id']}", f"the generative AI policy of {s['entity']}",
                         f"The old URL {s['url']} no longer works.")
            if ans and ans["url"] != s["url"]:
                log_change("source_moved", source_id=s["source_id"], old=s["url"], new=ans["url"])
                s["url"], s["status"] = ans["url"], "auto_found"
                st.update(failures=0, needs_rediscovery=False)
                queue_review(f"moved:{s['source_id']}", "policy URL replaced automatically; please confirm", url=ans["url"])

    for j in journals:
        if j.get("active") != "yes":
            continue
        pub = j.get("publisher", "")
        if not j.get("publisher_policy") and pub:
            if pub in pub_sources:
                j["publisher_policy"] = pub_sources[pub]
            elif not recently_tried(state, f"pub:{pub}"):
                ans = search(state, f"pub:{pub}", f"the generative AI policy for journal authors of the publisher {pub}")
                if ans:
                    sid = f"P-{slug(pub)}"
                    while sid in by_id:
                        sid += "X"
                    sources.append({"source_id": sid, "entity": pub, "level": "publisher", "url": ans["url"],
                                    "status": "auto_found", "notes": ans.get("note", "")})
                    pub_sources[pub] = sid
                    by_id[sid] = sources[-1]
                    j["publisher_policy"] = sid
                    log_change("source_discovered", source_id=sid, entity=pub, url=ans["url"])
                    queue_review(f"new:{sid}", "auto-discovered publisher policy; please confirm", url=ans["url"])
        if j.get("coverage_note", "").startswith("new") and not recently_tried(state, f"jrnl:{j['journal']}"):
            pub_url = by_id.get(j.get("publisher_policy"), {}).get("url", "")
            ans = search(state, f"jrnl:{j['journal']}",
                         f"journal-specific rules on generative AI use (authors or reviewers) for the journal "
                         f"'{j['journal']}'", f"Ignore the generic publisher policy at {pub_url}. If the journal has "
                         "no rules of its own, answer found=false.")
            if ans and ans["url"] != pub_url:
                sid = f"J-{slug(j['abbrev'])}"
                while sid in by_id:
                    sid += "X"
                by_id[sid] = {"url": ans["url"]}
                sources.append({"source_id": sid, "entity": j["journal"], "level": "journal", "url": ans["url"],
                                "status": "auto_found", "notes": ans.get("note", "")})
                j["extra_policy"] = sid
                log_change("source_discovered", source_id=sid, entity=j["journal"], url=ans["url"])
                queue_review(f"new:{sid}", "auto-discovered journal policy; please confirm", url=ans["url"])
            if not MOCK:
                j["coverage_note"] = ""

    write_csv(SOURCES, sources, SOURCE_FIELDS)
    write_csv(JOURNALS, journals, JOURNAL_FIELDS)
    save_json(STATE, state)


if __name__ == "__main__":
    run()
