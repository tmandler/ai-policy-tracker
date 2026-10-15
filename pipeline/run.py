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


def write_review_md():
    queue = load_json(REVIEW, [])
    lines = ["# Review queue", "",
             "Items the pipeline could not settle on its own. Fix the CSVs in `data/` (or confirm the URL by setting "
             "its status to `verified`), then delete the item from `data/review_queue.json`.", ""]
    for q in queue:
        extra = " ".join(f"{k}={v}" for k, v in q.items() if k not in ("key", "reason", "added"))
        lines.append(f"- [ ] **{q['key']}** ({q['added']}): {q['reason']} {extra}".rstrip())
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
