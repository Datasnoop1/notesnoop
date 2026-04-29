"""Quick inspect for elaboration_benchmark JSONL output."""
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/smoke_results.jsonl"
with open(path) as f:
    for line in f:
        r = json.loads(line)
        if r.get("error") and not r.get("path"):
            print(f"ERROR cbe={r.get('cbe')}: {r['error']}")
            continue
        text = r.get("text") or ""
        parsed_ok = bool(r.get("parsed"))
        print(
            f"cbe={r.get('cbe')} path={r.get('path')} "
            f"ok={r.get('ok')} latency={r.get('latency_ms')}ms "
            f"in={r.get('input_tokens')} out={r.get('output_tokens')} "
            f"text_len={len(text)} parsed={parsed_ok} "
            f"pages={r.get('scraped_pages')} "
            f"input_chars={r.get('input_chars')} "
            f"err={r.get('error')}"
        )
