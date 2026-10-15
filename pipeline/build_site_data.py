import json

from common import CHANGELOG, EXTR, JOURNALS, REVIEW, SITE_DATA, SOURCES, STATE, load_json, now, read_csv, save_json
from extract_policies import FIELDS, KEY_FIELDS

LABELS = {k: v[0] for k, v in FIELDS.items()}


def run():
    sources = {s["source_id"]: s for s in read_csv(SOURCES)}
    state = load_json(STATE, {})
    extracted = {sid: load_json(EXTR / f"{sid}.json", None) for sid in sources}
    review_keys = {q["key"].split(":", 1)[1].split(":")[0] for q in load_json(REVIEW, [])}

    src_out = {}
    for sid, s in sources.items():
        e = extracted.get(sid) or {}
        st = state.get(sid, {})
        src_out[sid] = {
            "id": sid, "entity": s["entity"], "level": s["level"], "url": s["url"],
            "verified": s["status"] == "verified",
            "status": s["status"],
            "summary": e.get("summary", ""), "evidence": e.get("evidence", []),
            "fields": {k: e.get(k, "unknown") for k in KEY_FIELDS},
            "disclosure_location": e.get("disclosure_location", []),
            "confidence": e.get("confidence", ""), "page_last_updated": e.get("page_last_updated", ""),
            "last_checked": (st.get("last_checked") or "")[:10],
            "last_policy_change": st.get("last_policy_change", ""),
            "fetch_ok": st.get("failures", 0) == 0 and bool(e),
        }

    journals = []
    for j in read_csv(JOURNALS):
        if j.get("active") != "yes":
            continue
        layers = [x for x in (j.get("publisher_policy"), j.get("extra_policy")) if x and x in src_out]
        effective = {}
        for k in KEY_FIELDS:
            val, by = "unknown", ""
            for sid in layers:
                v = src_out[sid]["fields"].get(k, "unknown")
                if v not in ("not_stated", "unknown") or val == "unknown":
                    val, by = v, sid
            effective[k] = {"value": val, "source": by}
        journals.append({
            "journal": j["journal"], "abbrev": j["abbrev"], "lists": [x for x in j["source_list"].split("|") if x],
            "publisher": j["publisher"], "society": j["owner_society"], "field": j["field"],
            "layers": layers, "effective": effective, "note": j.get("coverage_note", ""),
            "needs_review": any(sid in review_keys for sid in layers),
        })
    journals.sort(key=lambda x: x["journal"].lower())

    changes = []
    if CHANGELOG.exists():
        changes = [json.loads(line) for line in CHANGELOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    changes = list(reversed(changes))[:300]

    save_json(SITE_DATA / "tracker.json", {
        "generated": now(), "labels": LABELS, "journals": journals, "sources": src_out, "changes": changes,
        "stats": {"journals": len(journals), "sources": len(src_out),
                  "verified": sum(s["verified"] for s in src_out.values())},
    })
    print(f"site data: {len(journals)} journals, {len(src_out)} sources")


if __name__ == "__main__":
    run()
