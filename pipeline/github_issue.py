import os
import sys

import requests

from common import DATA, REVIEW, STATE, load_json, save_json

API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPOSITORY", "")
OWNER = os.getenv("GITHUB_REPOSITORY_OWNER", REPO.split("/")[0])
TOKEN = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN", "")
LABEL = "tracker-review"


def enabled():
    return bool(REPO and TOKEN)


def gh(method, path, **kw):
    r = requests.request(method, f"{API}/repos/{REPO}{path}", timeout=30, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}, **kw)
    r.raise_for_status()
    return r.json() if r.text else None


def open_issues():
    return [i for i in gh("GET", f"/issues?labels={LABEL}&state=open&per_page=10") if "pull_request" not in i]


def comments(number):
    out, page = [], 1
    while True:
        batch = gh("GET", f"/issues/{number}/comments?per_page=100&page={page}")
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def comment(number, body):
    gh("POST", f"/issues/{number}/comments", json={"body": body})


def react(comment_id, content):
    gh("POST", f"/issues/comments/{comment_id}/reactions", json={"content": content})


def sync(notify=False):
    if not enabled():
        print("issue sync skipped (no GitHub token)")
        return
    queue = load_json(REVIEW, [])
    failed = [k for k, v in load_json(DATA / "last_run.json", {}).get("steps", {}).items() if v != "ok"]
    body = (DATA / "REVIEW.md").read_text(encoding="utf-8")
    title = f"Policy tracker: {len(queue)} item(s) to review" + (f", failed steps: {','.join(failed)}" if failed else "")
    state = load_json(STATE, {})
    keys = [q["key"] for q in queue]
    issues = open_issues()
    if not queue and not failed:
        for i in issues:
            comment(i["number"], "Nothing left to review, so I'm closing this issue. A new one opens when something comes up.")
            gh("PATCH", f"/issues/{i['number']}", json={"state": "closed"})
        state["_notified_keys"] = []
        save_json(STATE, state)
        return
    if not issues:
        try:
            gh("POST", "/labels", json={"name": LABEL, "color": "FBCA04"})
        except requests.HTTPError:
            pass
        gh("POST", "/issues", json={"title": title, "body": f"@{OWNER}, some items need a look.\n\n{body}",
                                     "labels": [LABEL]})
    else:
        n = issues[0]["number"]
        gh("PATCH", f"/issues/{n}", json={"title": title, "body": body})
        new = [k for k in keys if k not in set(state.get("_notified_keys", []))]
        if notify and (new or failed):
            parts = [f"{len(new)} new item(s) to review"] if new else []
            parts += [f"failed steps: {', '.join(failed)}"] if failed else []
            comment(n, f"@{OWNER} {'; '.join(parts)}. The list above is up to date.")
    state["_notified_keys"] = keys
    save_json(STATE, state)


if __name__ == "__main__":
    sync(notify="--notify" in sys.argv)
