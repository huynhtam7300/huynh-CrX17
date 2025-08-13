def safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        return a / b if b else default
    except Exception:
        return defaults