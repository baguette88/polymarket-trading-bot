"""
Streamlit Dashboard for Polymarket Trading Bot

Run with: streamlit run dashboard/app.py
"""
import json
import sys
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Page config
st.set_page_config(
    page_title="Polymarket Bot Dashboard",
    page_icon="📊",
    layout="wide"
)

# Constants
BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / "state.json"
CONFIG_FILE = BASE_DIR / "config" / "bot_config.json"


def load_state():
    """Load bot state."""
    if STATE_FILE.exists():
        return json.load(open(STATE_FILE))
    return None


def load_config():
    """Load bot config."""
    if CONFIG_FILE.exists():
        return json.load(open(CONFIG_FILE))
    return {}


def main():
    st.title("📊 Polymarket Trading Bot")

    # Load data
    state = load_state()
    config = load_config()

    if not state:
        st.warning("No state file found. Is the bot running?")
        return

    # Sidebar - Config
    with st.sidebar:
        st.header("Configuration")
        st.json(config)

    # Main content
    col1, col2, col3, col4 = st.columns(4)

    totals = state.get('totals', {})

    with col1:
        pnl = totals.get('pnl', 0)
        st.metric("Total P&L", f"${pnl:.2f}", delta_color="normal")

    with col2:
        wins = totals.get('wins', 0)
        losses = totals.get('losses', 0)
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        st.metric("Win Rate", f"{win_rate:.1f}%", f"{wins}W / {losses}L")

    with col3:
        st.metric("Total Trades", totals.get('total_trades', 0))

    with col4:
        # Check heartbeat
        heartbeat_file = BASE_DIR / ".heartbeat"
        if heartbeat_file.exists():
            heartbeat = datetime.fromisoformat(heartbeat_file.read_text().strip())
            age = (datetime.now(heartbeat.tzinfo) - heartbeat).total_seconds()
            status = "🟢 Running" if age < 120 else "🟡 Stale"
        else:
            status = "🔴 Offline"
        st.metric("Status", status)

    st.divider()

    # Trade history
    st.header("Trade History")

    trades = state.get('trades', [])
    if trades:
        df = pd.DataFrame(trades)

        # Format columns
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M')

        if 'pnl' in df.columns:
            df['pnl'] = df['pnl'].apply(lambda x: f"${x:.2f}" if x else "-")

        # Display columns
        display_cols = ['timestamp', 'direction', 'outcome', 'entry_price', 'amount_usd', 'result', 'pnl']
        display_cols = [c for c in display_cols if c in df.columns]

        st.dataframe(
            df[display_cols].iloc[::-1],  # Reverse for newest first
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No trades yet")

    # Unresolved trades
    unresolved = [t for t in trades if not t.get('resolved', False)]
    if unresolved:
        st.header("Pending Resolutions")
        st.dataframe(pd.DataFrame(unresolved), use_container_width=True)


if __name__ == "__main__":
    main()
