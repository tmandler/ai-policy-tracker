from common import (SNAP, SOURCES, STATE, FetchError, content_hash, fetch_markdown, load_json, log_change,
                    now, polite_pause, queue_review, read_csv, resolve_review, save_json, today)

FAIL_LIMIT = 3


def run():
    sources = [s for s in read_csv(SOURCES) if s["status"] != "retired"]
    state = load_json(STATE, {})
    changed = []
    for s in sources:
        sid = s["source_id"]
        st = state.setdefault(sid, {"hash": "", "failures": 0})
        st["last_checked"] = now()
        try:
            text = fetch_markdown(s["url"], fixture_key=sid, require_ai=True)
        except (FetchError, Exception) as e:
            st["failures"] = st.get("failures", 0) + 1
            st["last_error"] = str(e)[:200]
            print(f"  fetch failed {sid}: {e}")
            if st["failures"] >= FAIL_LIMIT:
                st["needs_rediscovery"] = True
                queue_review(f"fetch:{sid}", f"fetch failed {st['failures']} runs in a row", url=s["url"],
                             error=st["last_error"])
                if st["failures"] == FAIL_LIMIT:
                    log_change("fetch_failing", source_id=sid, url=s["url"])
            polite_pause()
            continue
        st["failures"] = 0
        resolve_review(f"fetch:{sid}")
        st.pop("last_error", None)
        st.pop("needs_rediscovery", None)
        h = content_hash(text)
        if h != st.get("hash"):
            (SNAP / f"{sid}.md").write_text(text, encoding="utf-8")
            st["previous_hash"] = st.get("hash", "")
            st["hash"] = h
            st["last_text_change"] = today()
            changed.append(sid)
            print(f"  text changed: {sid}")
        polite_pause()
    save_json(STATE, state)
    print(f"fetch: {len(sources)} sources, {len(changed)} with new text")
    return changed


if __name__ == "__main__":
    run()
