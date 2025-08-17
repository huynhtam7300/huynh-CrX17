#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/what_is_running.py
Mục tiêu: In ra "bản khai runtime" để so sánh máy cá nhân (VS Code) và VPS.
- Lấy commit SHA/branch/dirty từ git
- Tính fingerprint code (SHA256 toàn bộ *.py, *.yaml, *.yml)
- Đọc summary cấu hình (hash 11 YAML) qua config_loader.py (nếu có)
- Kiểm tra biến môi trường then chốt, tiến trình auto_runner, systemd service
- Có chế độ so sánh với JSON trước đó: --compare file.json

Cách dùng:
  python tools/what_is_running.py --config ./config --service crx > state_local.json
  # trên VPS (trong thư mục repo)
  python tools/what_is_running.py --config ./config --service crx > state_vps.json
  # so sánh:
  python tools/what_is_running.py --compare state_local.json < state_vps.json
"""
import os, sys, json, subprocess, hashlib, time, platform
from pathlib import Path
from typing import Dict, List, Optional

def sh(cmd: List[str], cwd: Optional[str]=None, timeout: int=10) -> str:
    try:
        out = subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT, timeout=timeout)
        return out.decode("utf-8", "ignore").strip()
    except Exception as e:
        return f"__ERR__ {e}"

def get_git_info(repo: Path) -> Dict[str, str]:
    info = {"commit": None, "commit_short": None, "branch": None, "dirty": None, "remote": None}
    if not (repo/".git").exists():
        return info
    info["commit"] = sh(["git", "rev-parse", "HEAD"], cwd=str(repo))
    info["commit_short"] = sh(["git", "rev-parse", "--short", "HEAD"], cwd=str(repo))
    info["branch"] = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo))
    status = sh(["git", "status", "--porcelain"], cwd=str(repo))
    info["dirty"] = "yes" if (isinstance(status, str) and status and not status.startswith("__ERR__")) else "no"
    info["remote"] = sh(["git", "remote", "-v"], cwd=str(repo))
    return info

def file_iter(root: Path, exts=(".py",".yaml",".yml")):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            # bỏ qua thư mục ảo thường gặp
            if any(seg in p.parts for seg in (".venv", "__pycache__", ".git", "node_modules", "logs", "data/reports")):
                continue
            yield p

def hash_files(root: Path) -> Dict[str, str]:
    h = hashlib.sha256()
    files = sorted([str(p.relative_to(root)) for p in file_iter(root)])
    for rel in files:
        full = root / rel
        try:
            h.update(rel.encode())
            h.update(open(full, "rb").read())
        except Exception as e:
            h.update(f"__ERR__{rel}".encode())
    return {"files_count": str(len(files)), "sha256": h.hexdigest()}

def try_config_summary(config_dir: Path) -> Dict:
    # Cố gắng import config_loader trong repo hiện tại
    try:
        sys.path.insert(0, str(Path.cwd()))
        from config.config_loader import load_bundle  # ưu tiên cấu trúc repo: config/config_loader.py
    except Exception:
        try:
            from config_loader import load_bundle  # fallback nếu đặt cạnh
        except Exception:
            return {"summary": None, "error": "Không import được config_loader.py"}
    try:
        b = load_bundle(str(config_dir))
        return {"summary": b.summary(), "error": None}
    except Exception as e:
        return {"summary": None, "error": f"Load bundle lỗi: {e}"}

def get_env_info() -> Dict[str, str]:
    keys = [
        "CRX_CONFIG_DIR","CRX_ENABLE_ORDER_EXECUTOR",
        "BINANCE_API_KEY","BINANCE_API_SECRET",
        "OKX_API_KEY","OKX_API_SECRET","OKX_PASSPHRASE",
        "PYTHONPATH"
    ]
    out = {}
    for k in keys:
        v = os.getenv(k)
        if not v:
            out[k] = None
        elif "SECRET" in k or "KEY" in k or "PASSPHRASE" in k:
            out[k] = f"set(len={len(v)})"
        else:
            out[k] = v
    return out

def get_systemd_info(service: str) -> Dict[str, str]:
    if platform.system().lower() != "linux":
        return {"active": None, "execstart": None, "since": None, "note": "not linux"}
    if not service:
        return {"active": None, "execstart": None, "since": None}
    active = sh(["bash","-lc", f"systemctl is-active {service}"])
    execstart = sh(["bash","-lc", f"systemctl show {service} -p ExecStart | sed 's/ExecStart=//'"])
    since = sh(["bash","-lc", f"systemctl show {service} -p ActiveEnterTimestamp | sed 's/.*=//'"])
    return {"active": active, "execstart": execstart, "since": since}

def get_processes() -> Dict[str, str]:
    if platform.system().lower() == "windows":
        return {"ps": "Windows: dùng Task Manager/Process Explorer để xem python auto_runner.py"}
    cmd = "ps -ef | grep -i 'auto_runner.py' | grep -v grep"
    return {"ps": sh(["bash","-lc", cmd])}

def python_info() -> Dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "cwd": str(Path.cwd()),
    }

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.getenv("CRX_CONFIG_DIR","./config"), help="Thư mục chứa YAML (default: ./config)")
    ap.add_argument("--service", default="crx", help="Tên systemd service để kiểm tra (default: crx).")
    ap.add_argument("--compare", default=None, help="So sánh với file JSON trước đó (state_local.json). Đọc state hiện tại từ stdin.")
    args = ap.parse_args()

    repo = Path.cwd()
    config_dir = Path(args.config)

    state = {
        "ts": int(time.time()),
        "host": platform.node(),
        "platform": platform.platform(),
        "python": python_info(),
        "git": get_git_info(repo),
        "code_fingerprint": hash_files(repo),
        "config_dir": str(config_dir.resolve()),
        "config_summary": try_config_summary(config_dir),
        "env": get_env_info(),
        "systemd": get_systemd_info(args.service),
        "processes": get_processes(),
    }

    if not args.compare:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return

    # Compare mode: --compare old.json  (new từ stdin)
    try:
        with open(args.compare, "r", encoding="utf-8") as f:
            old = json.load(f)
        new = json.load(sys.stdin)
    except Exception as e:
        print(json.dumps({"error": f"Không đọc được dữ liệu so sánh: {e}"}))
        return

    diff = {}
    def pick(d, path):
        cur = d
        for k in path:
            if cur is None: return None
            cur = cur.get(k) if isinstance(cur, dict) else None
        return cur

    fields = [
        ("git.commit_short", ["git","commit_short"]),
        ("git.branch", ["git","branch"]),
        ("git.dirty", ["git","dirty"]),
        ("code.sha256", ["code_fingerprint","sha256"]),
        ("config.hashes", ["config_summary","summary","hashes"]),
        ("env.CRX_ENABLE_ORDER_EXECUTOR", ["env","CRX_ENABLE_ORDER_EXECUTOR"]),
        ("systemd.active", ["systemd","active"]),
    ]
    for label, path in fields:
        ov, nv = pick(old, path), pick(new, path)
        if ov != nv:
            diff[label] = {"old": ov, "new": nv}

    print(json.dumps({"diff": diff, "left_file": args.compare}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()