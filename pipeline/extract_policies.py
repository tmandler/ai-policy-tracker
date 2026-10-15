import re

from common import (EXTR, MOCK, MODEL, SNAP, SOURCES, STATE, claude_json, load_json, log_change, now,
                    queue_review, read_csv, save_json)

USE = ["allowed", "allowed_with_conditions", "prohibited", "not_stated"]
YN = ["yes", "no", "partial", "not_stated"]

FIELDS = {
    "author_use": ("Authors may use generative AI in preparing manuscripts", USE),
    "disclosure_required": ("Authors must disclose AI use ('partial' = only some uses, e.g. not copy-editing)", YN),
    "ai_as_author": ("AI tools may be listed as authors", ["allowed", "prohibited", "not_stated"]),
    "ai_images": ("AI-generated images/figures", USE),
    "reviewer_use": ("Reviewers may use generative AI in reviewing", USE),
    "reviewer_upload": ("Reviewers may upload manuscripts or parts of them into AI tools", USE),
    "editor_use": ("Editors may use generative AI in editorial work", USE),
}
KEY_FIELDS = list(FIELDS)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": KEY_FIELDS + ["disclosure_location", "summary", "evidence", "page_last_updated", "confidence",
                              "is_ai_policy"],
    "properties": {
        **{k: {"type": "string", "enum": v[1], "description": v[0]} for k, v in FIELDS.items()},
        "disclosure_location": {"type": "array", "items": {"type": "string", "enum": [
            "methods", "acknowledgements", "cover_letter", "submission_system", "dedicated_statement", "other"]}},
        "summary": {"type": "string", "description": "2-3 sentence plain-language summary in your own words"},
        "evidence": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["field", "quote"],
            "properties": {"field": {"type": "string", "enum": KEY_FIELDS},
                           "quote": {"type": "string", "description": "verbatim, max 20 words"}}}},
        "page_last_updated": {"type": "string", "description": "date stated on the page, or empty string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "is_ai_policy": {"type": "boolean", "description": "false if the page no longer contains an AI policy"},
    },
}

SYSTEM = (
    "You extract academic publishing AI policies into structured fields. Use only what the page states. "
    "If a topic is not addressed, use 'not_stated' — never infer from general ethics language. "
    "'allowed_with_conditions' means allowed subject to limits (disclosure, human verification, restricted tasks). "
    "Evidence quotes must be verbatim and at most 20 words. Write the summary in your own words."
)


def mock_extract(text):
    t = text.lower()

    def pick(prohibit, allow):
        if re.search(prohibit, t):
            return "prohibited"
        if re.search(allow, t):
            return "allowed_with_conditions"
        return "not_stated"
    return {
        "author_use": pick(r"authors (must not|may not) use", r"authors may use"),
        "disclosure_required": "yes" if "disclos" in t else "not_stated",
        "ai_as_author": "prohibited" if "not be listed as an author" in t else "not_stated",
        "ai_images": pick(r"images? (are|is) not permitted", r"images? (are|is) permitted"),
        "reviewer_use": pick(r"reviewers (must not|should not|may not) use", r"reviewers may use"),
        "reviewer_upload": "prohibited" if re.search(r"(must not|should not|not) upload", t) else "not_stated",
        "editor_use": pick(r"editors (must not|should not) use", r"editors may use"),
        "disclosure_location": ["acknowledgements"] if "acknowledg" in t else [],
        "summary": "Mock summary.",
        "evidence": [],
        "page_last_updated": "",
        "confidence": "high",
        "is_ai_policy": "ai" in t,
    }


def run(changed_ids=None):
    sources = {s["source_id"]: s for s in read_csv(SOURCES) if s["status"] != "retired"}
    state = load_json(STATE, {})
    todo = []
    for sid, s in sources.items():
        prev = load_json(EXTR / f"{sid}.json", None)
        h = state.get(sid, {}).get("hash")
        if h and (SNAP / f"{sid}.md").exists() and (prev is None or prev.get("content_hash") != h):
            todo.append(sid)
    for sid in todo:
        s = sources[sid]
        text = (SNAP / f"{sid}.md").read_text(encoding="utf-8")[:80000]
        prev = load_json(EXTR / f"{sid}.json", None)
        try:
            if MOCK:
                out = mock_extract(text)
            else:
                out = claude_json(SYSTEM, f"Policy owner: {s['entity']} ({s['level']})\nURL: {s['url']}\n\n"
                                          f"PAGE CONTENT:\n{text}", SCHEMA)
        except Exception as e:
            print(f"  extract failed {sid}: {e}")
            queue_review(f"extract:{sid}", "extraction failed", error=str(e)[:200])
            continue
        out.update(source_id=sid, content_hash=state[sid]["hash"], extracted_at=now(),
                   model="mock" if MOCK else MODEL)
        if not out["is_ai_policy"]:
            queue_review(f"notpolicy:{sid}", "page no longer looks like an AI policy", url=s["url"])
        if out["confidence"] == "low":
            queue_review(f"lowconf:{sid}:{out['content_hash']}", "low-confidence extraction", url=s["url"])
        if prev is None:
            log_change("policy_added", source_id=sid, entity=s["entity"])
        else:
            diff = {k: [prev.get(k), out[k]] for k in KEY_FIELDS if prev.get(k) != out[k]}
            if diff:
                log_change("policy_changed", source_id=sid, entity=s["entity"], fields=diff)
                state[sid]["last_policy_change"] = out["extracted_at"][:10]
            else:
                print(f"  {sid}: wording changed, policy fields unchanged")
        save_json(EXTR / f"{sid}.json", out)
    save_json(STATE, state)
    print(f"extract: {len(todo)} sources re-read")


if __name__ == "__main__":
    run()
