# -*- coding: utf-8 -*-
"""
Gửi Telegram an toàn:
- Không đặt parse_mode mặc định (tránh lỗi Markdown).
- Trả True chỉ khi HTTP 200 và body.ok == True.
- In status/resp để debug nhanh.
ENV: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (hoặc TELEGRAM_USER_ID)
"""
from __future__ import annotations
import os, json
from typing import Optional
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass

import requests  # pip install requests

def _get_env():
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat  = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_USER_ID") or "").strip()
    return token, chat

def send_telegram_message(
    text: str,
    *,
    chat_id: Optional[str] = None,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = True,
    timeout: int = 12,
) -> bool:
    token, default_chat = _get_env()
    chat = chat_id or default_chat
    if not token or not chat:
        print("[notify_telegram] ⚠️ Thiếu TELEGRAM_BOT_TOKEN/CHAT_ID trong .env")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat, "text": text}
    # Chỉ thêm parse_mode nếu người gọi CHỦ ĐỘNG truyền vào
    if parse_mode:
        data["parse_mode"] = parse_mode
    if disable_web_page_preview:
        data["disable_web_page_preview"] = True

    try:
        r = requests.post(url, data=data, timeout=timeout)
        body = None
        ok = False
        try:
            body = r.json()
            ok = bool(r.ok and body.get("ok") is True)
        except Exception:
            body = r.text
            ok = bool(r.ok)
        body_preview = json.dumps(body)[:200] if isinstance(body, dict) else repr(body)[:200]
        print(f"[notify_telegram] status={r.status_code} ok={ok} resp={body_preview}")
        return ok
    except Exception as e:
        print(f"[notify_telegram] ❌ HTTP error: {e}")
        return False