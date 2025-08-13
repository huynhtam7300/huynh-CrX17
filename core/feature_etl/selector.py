import pandas as pd

def select_features(df: pd.DataFrame) -> pd.DataFrame:
    # Giữ các cột cơ bản Phase CORE
    cols = [c for c in df.columns if c in ("open","high","low","close","volume")]
    return df[cols].copy()