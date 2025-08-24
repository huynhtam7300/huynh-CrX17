cd /home/crx/CrX17

tee tools/append_latest_and_export.py >/dev/null <<'PY'
import json, pathlib

H = pathlib.Path('data/decision_history.json')
J = pathlib.Path('data/decision_history.jsonl')
L = pathlib.Path('data/decision_latest.json')

def read_last_object():
    raw = H.read_text(encoding='utf-8') if H.exists() else ''
    last = None
    # (1) nếu file là JSON list
    try:
        j = json.loads(raw)
        if isinstance(j, list) and j:
            last = j[-1]
    except Exception:
        pass
    # (2) fallback: JSON-lines/mixed
    if last is None:
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        for ln in reversed(lines):
            try:
                obj = json.loads(ln.strip())
                if isinstance(obj, dict):
                    last = obj
                    break
            except Exception:
                continue
    if not isinstance(last, dict):
        raise SystemExit("No valid JSON object found in decision_history")
    return last

def atomic_write(p: pathlib.Path, content: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(content, encoding='utf-8')
    tmp.replace(p)

def main():
    last = read_last_object()
    # append JSONL
    J.parent.mkdir(parents=True, exist_ok=True)
    with J.open('a', encoding='utf-8') as f:
        f.write(json.dumps(last, ensure_ascii=False) + '\n')
    # export latest (atomic)
    atomic_write(L, json.dumps(last, ensure_ascii=False))
    print(f"[sync] latest: {last.get('timestamp')} {last.get('decision')} {last.get('confidence')}")

if __name__ == "__main__":
    main()
PY