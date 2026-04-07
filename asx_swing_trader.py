import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
from datetime import datetime
import io
import time

st.set_page_config(page_title="Yeppoon Strategic Command", layout="wide", page_icon="🌊")

st.title("🌊 Yeppoon Strategic Command")
st.caption("Hybrid Swing + Core Buy-and-Hold | CBA/SMSF & NAB Personal")

# Session ledger for manual trades
if 'trade_ledger' not in st.session_state:
    st.session_state.trade_ledger = pd.DataFrame(columns=['Date', 'Ticker', 'Type', 'Units', 'Price', 'Total', 'Strategy', 'Sector'])

# Sidebar parameters
with st.sidebar:
    st.header("Trading Parameters")
    capital = st.number_input("Current Capital ($)", value=2500.0, step=50.0)
    position_size = st.slider("Target Position Size ($)", 500, 2000, 500)
    rsi_threshold = st.slider("RSI Oversold Threshold", 20, 40, 30)
    momentum_period = st.slider("Momentum Look-back (weeks)", 4, 12, 8)

international_mode = st.checkbox("International Mode (NAB personal)", value=False)
commodities_mode = st.checkbox("Commodities Mode (oil/gold ETFs)", value=True)

# Watchlists + 5 core names
asx_watchlist = ["DRO.AX", "ASB.AX", "EOS.AX", "STO.AX", "WDS.AX", "FMG.AX", "CXO.AX", "NXT.AX", "PDN.AX", "BOE.AX", "DYL.AX", "SDR.AX", "JHX.AX"]
intl_watchlist = ["NVDA", "TSLA", "AMD", "BAE.L", "AIR.PA"]
commodities_watchlist = ["OOO.AX", "QAU.AX", "GOLD.AX", "USO", "BNO", "XLE", "XOP"]

if commodities_mode:
    watchlist = commodities_watchlist + asx_watchlist
    if international_mode:
        watchlist += intl_watchlist
else:
    watchlist = asx_watchlist if not international_mode else intl_watchlist + asx_watchlist

core_thesis = {
    "PDN.AX": "Uranium producer with Langer Heinrich ramping. ~40% discount to FV. AI power demand + supply shortage = structural tailwind.",
    "DRO.AX": "Counter-drone leader with European manufacturing scale-up. Your original winner. High volatility, multi-year runway.",
    "QAU.AX": "Currency-hedged gold ETF. Safe-haven play amid wars, inflation, and uncertainty. Clean commodities exposure.",
    "SDR.AX": "Hotel software platform. ~70% discount to FV. Strong ARR growth + AI efficiency tailwind.",
    "JHX.AX": "James Hardie – wide moat building materials. ~33% discount to FV. US housing repair pipeline + Azek synergies."
}

# Trade ledger form
with st.expander("Log a manual trade"):
    with st.form("trade"):
        t = st.text_input("Ticker", "EOS.AX").upper()
        ty = st.selectbox("Type", ["BUY", "SELL"])
        q = st.number_input("Units", 1)
        p = st.number_input("Price", 0.001)
        if st.form_submit_button("Log Trade"):
            sec, _ = get_sector_and_alternatives(t)
            row = pd.DataFrame([{'Date': datetime.now().strftime("%Y-%m-%d"), 'Ticker': t, 'Type': ty, 'Units': q, 'Price': p, 'Total': q*p, 'Strategy': 'Core' if t in core_thesis else 'Swing', 'Sector': sec}])
            st.session_state.trade_ledger = pd.concat([st.session_state.trade_ledger, row], ignore_index=True)
            st.success("Trade logged")

if st.button("🚀 Run Weekly Scan & Portfolio Review"):
    st.write(f"Scanning at {datetime.now().strftime('%Y-%m-%d %H:%M')} AEST")
    data = []
    for ticker in watchlist:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="3mo")
            if len(hist) < 20:
                continue
            current_price = hist["Close"].iloc[-1]
            delta = hist["Close"].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            rsi_val = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
            momentum = (current_price / hist["Close"].iloc[-momentum_period]) - 1 if len(hist) > momentum_period else 0
            signal = "BUY" if rsi_val < rsi_threshold and momentum > 0 else "SELL" if rsi_val > 70 else "HOLD"
            thesis = core_thesis.get(ticker, "Swing only")
            data.append({
                "Ticker": ticker,
                "Current Price": round(current_price, 3),
                "RSI": round(rsi_val, 1),
                "Momentum %": round(momentum * 100, 1),
                "Signal": signal,
                "Quantity": 0,
                "Avg Buy Price": 0.0,
                "Holding Value": 0.0,
                "Unrealised Profit %": 0.0,
                "Advice": signal,
                "Core Thesis": thesis
            })
            time.sleep(0.15)
        except:
            continue

    # Portfolio merge and profit calculations
    if not portfolio_df.empty:  # (your CSV upload code can be added here if needed)
        pass  # placeholder for now

    if data:
        df = pd.DataFrame(data)
        core_names = ["PDN.AX", "DRO.AX", "QAU.AX", "SDR.AX", "JHX.AX"]
        core_df = df[df["Ticker"].isin(core_names)].copy()
        swing_df = df[~df["Ticker"].isin(core_names)].copy()

        st.subheader("Swing Scan Results (Week-to-Week Aggressive Parcels)")
        if not swing_df.empty:
            st.dataframe(swing_df, use_container_width=True)
        else:
            st.write("No swing names in this scan.")

        st.subheader("Core Buy-and-Hold Review (Next DRO-type names)")
        if not core_df.empty:
            st.dataframe(core_df, use_container_width=True)
            st.caption("These 5 names are reviewed weekly for long-term potential. Rebalance into the best performers as needed.")
        else:
            st.write("Core names not loaded in this scan.")

        # Your new ledger and visuals can be added below if you want them in the same tab

st.caption("Run weekly. Swing parcels for short-term gains, Core names for long-term DRO-style runs. Trade small, stay disciplined from Yeppoon.")
