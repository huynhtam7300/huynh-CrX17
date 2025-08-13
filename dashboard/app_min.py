import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
from pathlib import Path
from utils.io_utils import read_json

st.set_page_config(page_title="CrX Dashboard (Core)", layout="wide")
st.title("CrX Dashboard — Phase CORE")

dec = read_json(Path("data/decision_history.json"), [])
trd = read_json(Path("data/trade_history.json"), [])

st.subheader("Decision History")
st.json(dec[-10:] if dec else [])

st.subheader("Trade History")
st.json(trd[-10:] if trd else [])

st.caption("Phase CORE scaffold — realtime PnL sẽ bổ sung ở Phase A/B.")