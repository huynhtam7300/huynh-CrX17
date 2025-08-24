#!/usr/bin/env python3
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
H = ROOT / "data" / "decision_history.json"
J = ROOT / "data" / "decision_history.jsonl"
L = ROOT / "data" / "decision_latest.json"

def _read_last_object() -> dict:
    raw = H.read_text(encoding="utf-8") if H.exists() else ""
    # A) cả file là JSON (list|object)
    try:
        obj = json.loads(raw)
        if isinstance(obj, list) and obj:
            if isinstance(obj[-1], dict):
                return obj[-1]
        elif isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # B) JSON-lines: lấy dòng hợp lệ cuối cùng
    for ln in reversed([ln for ln in raw.splitlines() if ln.strip()]):
        try:
            o = json.loads(ln)
            if isinstance(o, dict):
                return o
        except Exception:
            continue
    raise SystemExit("No valid JSON object found in decision_history.json")

def _atomic_write(p: pathlib.Path, content: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(p)

def main():
    last = _read_last_object()
    # append JSONL
    J.parent.mkdir(parents=True, exist_ok=True)
    with J.open("a", encoding="utf-8") as f:
        f.write(json.dumps(last, ensure_ascii=False) + "\n")
    # export latest (atomic)
    _atomic_write(L, json.dumps(last, ensure_ascii=False))
    print(f"[sync] latest: {last.get('timestamp')} {last.get('decision')} {last.get('confidence')}")

if __name__ == "__main__":
    main()