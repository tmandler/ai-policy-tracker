import sys
import traceback

import build_site_data
import discover_sources
import extract_policies
import fetch_policies
import refresh_lists
from common import DATA, REVIEW, load_json, now, save_json

STEPS = [("refresh_lists", refresh_lists.run), ("discover_sources", discover_sources.run),
         ("fetch_policies", fetch_policies.run), ("extract_policies", extract_policies.run),
         ("build_site_data", build_site_data.run)]


GROUPS = [
    ("Confirm new or moved policy pages", {"new", "moved"}),
    ("Check how a page was read", {"notpolicy", "lowconf", "extract"}),
    ("Pages that keep failing to load", {"fetch"}),
    ("Publisher questions", {"publisher", "pubchange"}),
    ("Journal lists", {"list"}),
]


def _item_md(q, sources):
    kind, _, rest = q["key"].partition(":")
    url = q.get("url", "")
    if kind in {"new", "moved", "notpolicy", "lowconf", "extract", "fetch"}:
        sid = rest.split(":")[0]
        s = sources.get(sid, {})
        link = url or s.get("url", "")
        head = f"**{s.get('entity', sid)}** ({s.get('level', 'source')}, `{sid}`)"
        head += f" · [open page]({link})" if link else ""
        cmds = [f"verify {sid}", f"url {sid} <correct link>", f"reject {sid}"]
        if kind == "fetch":
            cmds = cmds[1:]
    elif kind in {"publisher", "pubchange"}:
        journal = rest.split(":")[0]
        head = f"**{journal}**"
        cmds = [f"publisher {journal} = <publisher name>", f"done {q['key']}"]
    else:
        head = f"**{rest}**"
        cmds = [f"done {q['key']}"]
    note = q["reason"] + (f" ({q['error']})" if q.get("error") else "")
    return f"- {head}: {note}\n  " + " · ".join(f"`{c}`" for c in cmds)


def write_review_md():
    from common import SOURCES, read_csv
    queue = load_json(REVIEW, [])
    sources = {s["source_id"]: s for s in read_csv(SOURCES)}
    lines = ["# Review queue", "",
             "Reply to this issue with one command per line (or answer the notification email). Copy a command "
             "from below, e.g. `verify P-XYZ`. Several IDs per line work: `verify P-XYZ J-ABC`. "
             "Changes are applied within a few minutes; reply `help` for all commands.", ""]
    seen = set()
    for title, kinds in GROUPS:
        items = [q for q in queue if q["key"].split(":")[0] in kinds]
        if items:
            lines += [f"## {title} ({len(items)})", ""] + [_item_md(q, sources) for q in items] + [""]
            seen.update(q["key"] for q in items)
    other = [q for q in queue if q["key"] not in seen]
    if other:
        lines += [f"## Other ({len(other)})", ""] + [_item_md(q, sources) for q in other] + [""]
    if not queue:
        lines.append("Nothing to review.")
    (DATA / "REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(queue)


def main():
    only = sys.argv[1:]
    results = {}
    for name, fn in STEPS:
        if only and name not in only:
            continue
        print(f"== {name}")
        try:
            fn()
            results[name] = "ok"
        except Exception:
            traceback.print_exc()
            results[name] = "failed"
    n = write_review_md()
    save_json(DATA / "last_run.json", {"finished": now(), "steps": results, "review_items": n})
    print(f"done: {results}; review items: {n}")
    if results.get("build_site_data") == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
