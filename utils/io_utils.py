import json
from pathlib import Path

def ensure_file(path: Path, default):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)

def read_json(path: Path, default):
    ensure_file(path, default)
    with path.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return default

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)