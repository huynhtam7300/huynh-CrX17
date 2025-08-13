from pathlib import Path
from utils.io_utils import read_json, write_json
from utils.time_utils import now_utc_iso

PATH = Path("data/trade_history.json")

def log_trade(event: dict):
    history = read_json(PATH, [])
    item = {"timestamp": now_utc_iso(), **event}
    history.append(item)
    write_json(PATH, history)