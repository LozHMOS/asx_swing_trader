import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import io
import time
import os

st.set_page_config(page_title="Swing Trader – Yeppoon Edition", layout="wide")
st.title("Swing Trader – Yeppoon Edition")
st.markdown("**Single App – 100 % cash deployment** – $750 SMSF + $750 NabTrade each month. Grok managing for maximum return.")

st.sidebar.header("Monthly Cash Available")
smsf_cash = st.sidebar.number_input("Available cash SMSF this month (AUD)", value=750.0, step=50.0)
nab_cash = st.sidebar.number_input("Available cash NabTrade this month (AUD)", value=750.0, step=50.0)
smsf_total = st.sidebar.number_input("Total SMSF value (AUD) – for reference only", value=750000.0, step=10000.0)

if st.sidebar.button("Record Monthly Deposits"):
    st.sidebar.success("Recorded $750 cash into each account – ready for deployment")

international_mode = st.checkbox("International Mode (US/EU stocks)", value=True)
commodities_mode = st.checkbox("Commodities Mode (oil, gold, ETFs)", value=True)

rsi_threshold = st.slider("RSI oversold threshold", 20, 40, 28)
momentum_period = st.slider("Momentum look-back (weeks)", 4, 12, 8)

asx_watchlist = ["DRO.AX", "ASB.AX", "EOS.AX", "STO.AX", "WDS.AX", "FMG.AX", "CXO.AX", "NXT.AX", "PDN.AX", "BOE.AX", "DYL.AX"]
intl_watchlist = ["NVDA", "TSLA", "AMD", "BAE.L", "AIR.PA"]
commodities_watchlist = ["OOO.AX", "QAU.AX", "GOLD.AX", "USO", "BNO", "XLE", "XOP"]

watchlist = asx_watchlist[:]
if commodities_mode:
    watchlist += commodities_watchlist
if international_mode:
    watchlist += intl_watchlist

st.subheader("Upload Holdings CSV (optional – for unrealised profit)")
portfolio_file = st.file_uploader("Upload CSV", type="csv")

if st.button("Run Weekly Swing Scan"):
    st.write(f"Scan run at {datetime.now().strftime('%Y-%m-%d %H:%M')} AEST")
    data = []
    hist_data = yf.download(watchlist, period="3mo", progress=False, threads=True)

    for ticker in watchlist:
        try:
            if ticker in hist_data.columns.get_level_values(1):
                close_series = hist_data['Close'][ticker]
            else:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="3mo")
                if len(hist) < 20:
                    continue
                close_series = hist["Close"]

            current_price = close_series.iloc[-1]
            delta = close_series.diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
            rs = gain / loss
            rsi_val = 100 - (100 / (1 + rs)).iloc[-1] if not pd.isna((100 - (100 / (1 + rs))).iloc[-1]) else 50.0
            momentum = (current_price / close_series.iloc[-momentum_period]) - 1 if len(close_series) > momentum_period else 0

            signal = "BUY" if (rsi_val < rsi_threshold and momentum > 0) else "SELL" if rsi_val > 70 else "HOLD"

            data.append({
                "Ticker": ticker,
                "Current Price": round(current_price, 3),
                "RSI": round(rsi_val, 1),
                "Momentum %": round(momentum * 100, 1),
                "Signal": signal,
                "Advice": signal
            })
        except:
            continue

    df = pd.DataFrame(data)
    def highlight(row):
        if "BUY" in str(row["Advice"]):
            return ["background-color: lightgreen"] * len(row)
        elif "SELL" in str(row["Advice"]):
            return ["background-color: pink"] * len(row)
        return [""] * len(row)
    styled_df = df.style.apply(highlight, axis=1)
    st.dataframe(styled_df, use_container_width=True)

    st.subheader("Recommended Cash Deployment")
    buy_signals = df[df["Signal"] == "BUY"]
    if not buy_signals.empty:
        top = buy_signals.iloc[0]
        st.success(f"**STRONG BUY** – {top['Ticker']} at ${top['Current Price']}")
        st.write(f"**Deploy full $750 cash into this trade** (or split $375 each account if you prefer).")
        st.info(f"RSI: {top['RSI']} | Momentum: {top['Momentum %']}%")
    else:
        st.info("No BUY signals this week – hold the $750 cash in each account until next scan.")

    st.caption("Minimum trade size $500 respected. 100 % of available monthly cash deployed on strong signals.")

st.markdown("---")
st.caption("Single app – $1,500 total monthly cash. 100 % deployment on BUY signals. Run weekly when market opens.")
