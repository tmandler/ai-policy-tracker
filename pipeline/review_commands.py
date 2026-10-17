import re
import sys

import build_site_data
import extract_policies
import fetch_policies
import github_issue as ghi
from common import (JOURNAL_FIELDS, JOURNALS, REVIEW, SOURCE_FIELDS, SOURCES, STATE, load_json, norm_title, read_csv,
                    save_json, today, write_csv)

SOURCE_KINDS = {"new", "moved", "notpolicy", "fetch", "lowconf", "extract"}
VERBS = {"verify", "url", "reject", "publisher", "done", "help"}

HELP = """**Commands** (one per line; reply here or answer the notification email):

- `verify P-XYZ` – the page is right. Several at once: `verify P-XYZ J-ABC`
- `url P-XYZ https://...` – use this link instead (it is read straight away)
- `reject P-XYZ` – no usable page; stop showing it
- `publisher Journal Title = Publisher Name` – fix a journal's publisher
- `done <item key>` – dismiss any other item without changes
- `help` – show this list"""


class Ctx:
    def __init__(self):
        self.sources = read_csv(SOURCES)
        self.journals = read_csv(JOURNALS)
        self.state = load_json(STATE, {})
        self.queue = load_json(REVIEW, [])
        self.by_id = {s["source_id"].upper(): s for s in self.sources}
        self.refetch = set()

    def resolve(self, pred):
        before = len(self.queue)
        self.queue = [q for q in self.queue if not pred(q["key"])]
        return before - len(self.queue)

    def resolve_source(self, sid):
        return self.resolve(lambda k: k.split(":")[0] in SOURCE_KINDS and k.split(":")[1].upper() == sid.upper())

    def source(self, sid):
        s = self.by_id.get(sid.upper())
        if not s:
            raise ValueError(f"unknown source ID `{sid}`")
        return s


def cmd_verify(ctx, rest):
    out = []
    for sid in rest.split():
        s = ctx.source(sid)
        s["status"] = "verified"
        ctx.resolve_source(s["source_id"])
        out.append(f"verified {s['source_id']} ({s['entity']})")
    if not out:
        raise ValueError("`verify` needs at least one source ID")
    return out


def cmd_url(ctx, rest):
    parts = rest.split()
    if len(parts) != 2 or not parts[1].startswith("http"):
        raise ValueError("use `url <ID> <https://link>`")
    s = ctx.source(parts[0])
    s["url"], s["status"] = parts[1].strip("<>"), "verified"
    st = ctx.state.setdefault(s["source_id"], {})
    st.update(failures=0, hash="")
    st.pop("needs_rediscovery", None)
    ctx.resolve_source(s["source_id"])
    ctx.refetch.add(s["source_id"])
    return [f"new link saved for {s['source_id']} ({s['entity']})"]


def cmd_reject(ctx, rest):
    out = []
    for sid in rest.split():
        s = ctx.source(sid)
        s["status"] = "retired"
        s["notes"] = (s["notes"] + f" | rejected {today()}: {s['url']}").strip(" |")
        n = 0
        for j in ctx.journals:
            if j.get("publisher_policy") == s["source_id"]:
                j["publisher_policy"], n = "-", n + 1
            if j.get("extra_policy") == s["source_id"]:
                j["extra_policy"], n = "", n + 1
        ctx.resolve_source(s["source_id"])
        out.append(f"rejected {s['source_id']} ({s['entity']}); removed from {n} journal(s)")
    if not out:
        raise ValueError("`reject` needs at least one source ID")
    return out


def cmd_publisher(ctx, rest):
    title, sep, pub = rest.partition("=")
    title, pub = title.strip(), pub.strip()
    if not sep or not title or not pub:
        raise ValueError("use `publisher Journal Title = Publisher Name`")
    j = next((j for j in ctx.journals if norm_title(j["journal"]) == norm_title(title)
              or j["abbrev"].lower() == title.lower()), None)
    if not j:
        raise ValueError(f"journal not found: {title}")
    srcs = {s["entity"].lower(): s for s in ctx.sources if s["level"] == "publisher" and s["status"] != "retired"}
    j["publisher"] = pub
    j["publisher_policy"] = srcs[pub.lower()]["source_id"] if pub.lower() in srcs else ""
    ctx.resolve(lambda k: k.startswith(f"publisher:{j['journal']}") or k.startswith(f"pubchange:{j['journal']}:"))
    tail = f"uses {j['publisher_policy']}" if j["publisher_policy"] else "its policy page will be searched on the next weekly run"
    return [f"{j['journal']}: publisher set to {pub}; {tail}"]


def cmd_done(ctx, rest):
    key = rest.strip()
    if not key or key.lower() == "all":
        raise ValueError("`done` needs an item key from the list")
    n = ctx.resolve(lambda k: k.lower() == key.lower() or k.lower().startswith(key.lower() + ":"))
    if not n:
        raise ValueError(f"no open item with key `{key}`")
    return [f"dismissed {key}"]


HANDLERS = {"verify": cmd_verify, "url": cmd_url, "reject": cmd_reject, "publisher": cmd_publisher, "done": cmd_done}


def parse(body):
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith(">"):
            continue
        line = re.sub(r"^[-*]\s+", "", line).strip().strip("`").strip()
        verb, _, rest = line.partition(" ")
        if verb.lower() in VERBS:
            yield verb.lower(), rest.strip()


def pending_comments():
    out = []
    for issue in ghi.open_issues():
        for c in ghi.comments(issue["number"]):
            if c["user"]["login"] == ghi.OWNER and c["user"].get("type") != "Bot":
                out.append((issue["number"], c))
    return out


def run(defer=False):
    if not ghi.enabled():
        print("review commands skipped (no GitHub token)")
        return False
    ctx = Ctx()
    done_ids = set(ctx.state.get("_processed_comments", []))
    todo = [(n, c) for n, c in pending_comments() if c["id"] not in done_ids]
    if not todo:
        print("review commands: nothing new")
        return False
    if defer:
        for n, c in todo:
            ghi.react(c["id"], "eyes")
        ghi.comment(todo[-1][0], "The weekly check is running right now. I'll apply your reply as soon as it finishes.")
        return False

    replies = {}
    for n, c in todo:
        lines, ok = [], True
        cmds = list(parse(c["body"] or ""))
        if not cmds:
            lines.append("I didn't find a command in this reply.\n\n" + HELP)
            ok = False
        for verb, rest in cmds:
            if verb == "help":
                lines.append(HELP)
                continue
            try:
                lines += [f"✓ {m}" for m in HANDLERS[verb](ctx, rest)]
            except Exception as e:
                ok = False
                lines.append(f"✗ `{verb} {rest}`: {e}")
        ghi.react(c["id"], "+1" if ok else "confused")
        first = next((ln.strip() for ln in (c["body"] or "").splitlines() if ln.strip()), "")[:80]
        replies.setdefault(n, []).append(f"> {first}\n\n" + "\n".join(f"- {x}" if x[:1] in "✓✗" else x for x in lines))
        done_ids.add(c["id"])

    write_csv(SOURCES, ctx.sources, SOURCE_FIELDS)
    write_csv(JOURNALS, ctx.journals, JOURNAL_FIELDS)
    save_json(REVIEW, ctx.queue)
    ctx.state["_processed_comments"] = sorted(done_ids)[-1000:]
    save_json(STATE, ctx.state)

    if ctx.refetch:
        fetch_policies.run(only=ctx.refetch)
        extract_policies.run()
        state = load_json(STATE, {})
        for sid in ctx.refetch:
            st = state.get(sid, {})
            msg = f"✗ {sid}: the new link could not be loaded ({st.get('last_error')})" if st.get("failures") else \
                f"✓ {sid}: new page read"
            for n in replies:
                replies[n][-1] += f"\n- {msg}"
                break
    build_site_data.run()
    from run import write_review_md
    left = write_review_md()
    for n, parts in replies.items():
        ghi.comment(n, "\n\n---\n\n".join(parts) + f"\n\n{left} item(s) left. The website updates in a few minutes.")
    return True


if __name__ == "__main__":
    run(defer="--defer" in sys.argv)
