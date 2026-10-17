import re

import requests

from common import (CROSSREF_MAILTO, JOURNAL_FIELDS, JOURNALS, LISTS, MOCK, SOURCES, USER_AGENT, claude_json,
                    fetch_markdown, load_json, log_change, norm_title, queue_review, read_csv, resolve_review, today,
                    write_csv)

PUBLISHER_ALIASES = [
    (r"\bsage\b", "SAGE"), (r"wiley|blackwell", "Wiley"), (r"elsevier", "Elsevier"),
    (r"informs|institute for operations research", "INFORMS"), (r"oxford university press|\boup\b",
                                                                 "Oxford University Press"),
    (r"springer|palgrave|nature", "Springer Nature"), (r"emerald", "Emerald"),
    (r"taylor|informa|routledge", "Taylor & Francis"), (r"cambridge university press", "Cambridge University Press"),
    (r"university of chicago press", "University of Chicago Press"), (r"academy of management", "Academy of Management"),
    (r"american economic association", "American Economic Association"),
    (r"american psychological association", "American Psychological Association"),
    (r"american accounting association", "American Accounting Association"),
]

LIST_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["journals"],
    "properties": {"journals": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["title", "abbrev"],
        "properties": {"title": {"type": "string"},
                       "abbrev": {"type": "string", "description": "abbreviation if shown, else empty"}}}}},
}


def lists_of(row):
    return set(x for x in row["source_list"].split("|") if x)


def canonical_publisher(raw):
    for pat, name in PUBLISHER_ALIASES:
        if re.search(pat, raw.lower()):
            return name
    return None


def crossref_lookup(title):
    params = {"query": title, "rows": 10}
    if CROSSREF_MAILTO:
        params["mailto"] = CROSSREF_MAILTO
    r = requests.get("https://api.crossref.org/journals", params=params, timeout=60,
                     headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    hits = [i for i in r.json()["message"]["items"] if norm_title(i.get("title", "")) == norm_title(title)]
    if not hits:
        return None
    item = max(hits, key=lambda i: (i.get("counts") or {}).get("current-dois", 0))
    return {"publisher": item.get("publisher", ""), "issn": (item.get("ISSN") or [""])[0]}


def extract_list(name, cfg):
    text = fetch_markdown(cfg["url"], fixture_key=f"list_{name}")
    if MOCK:
        return [{"title": m.group(1).strip(), "abbrev": ""} for m in re.finditer(r"^- (.+)$", text, re.M)]
    out = claude_json(
        "Extract the journals that make up the named journal list from the page. Return every journal exactly "
        "once with its full official title. Ignore journals mentioned only as removed or historical.",
        f"List: {cfg['description']}\nURL: {cfg['url']}\n\nPAGE:\n{text[:60000]}", LIST_SCHEMA)
    return out["journals"]


def make_abbrev(title):
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", title) if w.lower() not in {"of", "and", "the", "for"}).upper()


def run():
    cfg = load_json(LISTS, {})
    journals = read_csv(JOURNALS)
    aliases = {norm_title(k): norm_title(v) for k, v in cfg.get("_title_aliases", {}).items()}
    key = lambda t: aliases.get(norm_title(t), norm_title(t))
    by_key = {key(j["journal"]): j for j in journals}
    pub_sources = {s["entity"]: s["source_id"] for s in read_csv(SOURCES) if s["level"] == "publisher"}

    for name, lc in cfg.items():
        if name.startswith("_"):
            continue
        try:
            items = extract_list(name, lc)
        except Exception as e:
            queue_review(f"list:{name}:{today()}", f"could not read {name} list", error=str(e)[:200])
            continue
        if not lc["min"] <= len(items) <= lc["max"]:
            queue_review(f"list:{name}:{today()}", f"{name} returned {len(items)} journals; changes not applied")
            continue
        resolve_review(f"list:{name}:")
        found = {key(i["title"]): i for i in items}
        for k, j in by_key.items():
            if name in lists_of(j) and k not in found:
                ls = lists_of(j) - {name}
                j["source_list"] = "|".join(sorted(ls))
                log_change("journal_removed_from_list", journal=j["journal"], list=name)
                if not ls and not j.get("ajg"):
                    j["active"] = "no"
        for k, item in found.items():
            j = by_key.get(k)
            if j:
                if name not in lists_of(j):
                    j["source_list"] = "|".join(sorted(lists_of(j) | {name}))
                    j["active"] = "yes"
                    log_change("journal_added_to_list", journal=j["journal"], list=name)
                continue
            new = {"journal": item["title"], "abbrev": item["abbrev"] or make_abbrev(item["title"]),
                   "source_list": name, "active": "yes", "added_on": today(), "coverage_note": "new: check journal policy"}
            journals.append(new)
            by_key[k] = new
            log_change("journal_added_to_list", journal=item["title"], list=name, new=True)

    if not MOCK:
        for j in journals:
            if j.get("active") != "yes":
                continue
            try:
                hit = crossref_lookup(j["journal"])
            except Exception as e:
                print(f"  crossref failed {j['journal']}: {e}")
                continue
            if not hit:
                if not j.get("publisher"):
                    queue_review(f"publisher:{j['journal']}", "publisher unknown; set it in journals.csv")
                continue
            if hit["issn"] and not j.get("issn"):
                j["issn"] = hit["issn"]
            canon = canonical_publisher(hit["publisher"])
            if canon and canon != j.get("publisher"):
                old = j.get("publisher", "")
                j["publisher"] = canon
                j["publisher_policy"] = pub_sources.get(canon, "")
                if old:
                    log_change("publisher_changed", journal=j["journal"], old=old, new=canon)
                    queue_review(f"pubchange:{j['journal']}:{canon}", "publisher changed; check society/journal layer")
            elif not j.get("publisher"):
                j["publisher"] = hit["publisher"]
                queue_review(f"publisher:{j['journal']}", f"unmapped publisher '{hit['publisher']}'")
    write_csv(JOURNALS, journals, JOURNAL_FIELDS)
    print(f"lists: {sum(j.get('active') == 'yes' for j in journals)} active journals")


if __name__ == "__main__":
    run()
