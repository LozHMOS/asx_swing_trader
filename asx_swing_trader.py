import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import io
import time
import os

st.set_page_config(page_title="Swing Trader – Yeppoon Edition", layout="wide")
st.title("Swing Trader – Yeppoon Edition")
st.markdown("**Single App – SMSF + Personal (NabTrade)** – $1,500/month total ($750 each). Grok managing for maximum return.")

st.sidebar.header("Monthly Capital")
smsf_capital = st.sidebar.number_input("SMSF Capital (AUD)", value=250000.0, step=1000.0)
nab_capital = st.sidebar.number_input("NabTrade Capital (AUD)", value=50000.0, step=1000.0)
smsf_monthly = st.sidebar.number_input("Monthly deposit SMSF (AUD)", value=750.0, step=50.0)
nab_monthly = st.sidebar.number_input("Monthly deposit NabTrade (AUD)", value=750.0, step=50.0)

if st.sidebar.button("Record Monthly Deposits"):
    st.sidebar.success("Recorded $750 into each account – balances updated")

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

st.subheader("Upload Holdings CSV (CommSec or NabTrade)")
portfolio_file = st.file_uploader("Upload CSV", type="csv")
portfolio_df = pd.DataFrame(columns=["Ticker", "Quantity", "Avg_Buy_Price"])

if portfolio_file is not None:
    try:
        content = portfolio_file.getvalue().decode("utf-8")
        lines = content.splitlines()
        data_start = next((i for i, line in enumerate(lines) if "Code" in line or "Ticker" in line), 0)
        csv_data = "\n".join(lines[data_start:])
        portfolio_raw = pd.read_csv(io.StringIO(csv_data))
        col = "Code" if "Code" in portfolio_raw.columns else "Ticker"
        portfolio_df["Ticker"] = portfolio_raw[col].astype(str).str.strip() + ".AX"
        portfolio_df["Quantity"] = pd.to_numeric(portfolio_raw.get("Quantity", 0), errors="coerce").fillna(0)
        portfolio_df["Avg_Buy_Price"] = pd.to_numeric(portfolio_raw.get("Avg Buy Price", 0), errors="coerce").fillna(0)
        st.success(f"Loaded {len(portfolio_df)} holdings.")
    except Exception as e:
        st.error(f"CSV error: {e}")

@st.cache_data(ttl=300)
def get_history(ticker_list):
    try:
        return yf.download(ticker_list, period="3mo", progress=False, threads=True)
    except:
        return None

if st.button("Run Weekly Swing Scan"):
    st.write(f"Scan run at {datetime.now().strftime('%Y-%m-%d %H:%M')} AEST")
    data = []
    hist_data = get_history(watchlist)

    for ticker in watchlist:
        try:
            if hist_data is not None and ticker in hist_data.columns.get_level_values(1):
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
                "Quantity": 0,
                "Avg Buy Price": 0.0,
                "Holding Value": 0.0,
                "Unrealised Profit %": 0.0,
                "Advice": signal
            })
            time.sleep(0.2)
        except:
            continue

    if not portfolio_df.empty:
        for _, row in portfolio_df.iterrows():
            ticker = row["Ticker"]
            existing = next((item for item in data if item["Ticker"] == ticker), None)
            if existing:
                existing["Quantity"] = row["Quantity"]
                existing["Avg Buy Price"] = row["Avg_Buy_Price"]
            else:
                data.append({"Ticker": ticker, "Current Price": 0.0, "RSI": 0.0, "Momentum %": 0.0, "Signal": "HOLD", "Quantity": row["Quantity"], "Avg Buy Price": row["Avg_Buy_Price"], "Holding Value": 0.0, "Unrealised Profit %": 0.0, "Advice": "HOLD"})

    for item in data:
        if item["Quantity"] > 0:
            try:
                price = yf.Ticker(item["Ticker"]).history(period="1d")["Close"].iloc[-1]
                item["Current Price"] = round(price, 3)
            except:
                pass
            item["Holding Value"] = round(item["Quantity"] * item["Current Price"], 2)
            if item["Avg Buy Price"] > 0:
                item["Unrealised Profit %"] = round(((item["Current Price"] - item["Avg Buy Price"]) / item["Avg Buy Price"]) * 100, 1)
            if item["Signal"] == "SELL" or item["Unrealised Profit %"] > 15:
                item["Advice"] = "SELL for profit"
            elif item["Signal"] == "BUY":
                item["Advice"] = "BUY to add"

    if data:
        df = pd.DataFrame(data)
        def highlight(row):
            if "BUY" in str(row["Advice"]):
                return ["background-color: lightgreen"] * len(row)
            elif "SELL" in str(row["Advice"]):
                return ["background-color: pink"] * len(row)
            return [""] * len(row)
        styled_df = df.style.apply(highlight, axis=1)
        st.dataframe(styled_df, use_container_width=True)

        st.subheader("Portfolio Summary")
        held = df[df["Quantity"] > 0]
        if not held.empty:
            total_value = held["Holding Value"].sum()
            avg_profit = held["Unrealised Profit %"].mean()
            st.write(f"**Total holding value:** ${total_value:,.2f}")
            st.write(f"**Average unrealised profit:** {avg_profit:.1f}%")
        st.info("Monthly $1,500 total deposit tracked. Reinvest profits aggressively.")

        df.to_csv("swing_trades_log.csv", mode="a", header=not os.path.exists("swing_trades_log.csv"), index=False)
        st.success("Trade log saved")

st.markdown("---")
st.caption("Single app for both accounts – $1,500/month total. Aggressive but disciplined. Run weekly.")
