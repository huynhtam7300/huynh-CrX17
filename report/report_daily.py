from pathlib import Path
from utils.io_utils import read_json
from notifier.notify_report import send_daily_report

def run_daily_report():
    dec = read_json(Path("data/decision_history.json"), [])
    trd = read_json(Path("data/trade_history.json"), [])
    text = f"- Decisions: {len(dec)}\n- Trades: {len(trd)}\n"
    send_daily_report(text)