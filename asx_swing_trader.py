import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import io

st.title("ASX & International Swing Trader – Yeppoon Edition")
st.markdown("CBA/SMSF: keep International Mode off. NAB personal: turn International Mode on for global exposure. Commodities Mode adds oil/gold ETFs for extra boost. Not financial advice.")

capital = st.number_input("Current capital in dollars", value=2500.0, step=50.0)
position_size = min(500.0, capital)

international_mode = st.checkbox("International Mode (NAB personal account - US/EU/global tickers)", value=False)
commodities_mode = st.checkbox("Commodities Mode (oil, gold, precious-metals ETFs)", value=True)

st.write(f"Recommended initial buy per new stock or ETF: ${position_size:.0f}.")

rsi_threshold = st.slider("RSI oversold threshold for buy signals (lower = stricter)", 20, 40, 30)
momentum_period = st.slider("Momentum look-back in weeks", 4, 12, 8)

# Watchlists
asx_watchlist = ["DRO.AX", "ASB.AX", "EOS.AX", "STO.AX", "WDS.AX", "FMG.AX", "CXO.AX", "NXT.AX", "PDN.AX", "BOE.AX", "DYL.AX"]
intl_watchlist = ["NVDA", "TSLA", "AMD", "BAE.L", "AIR.PA"]
commodities_watchlist = ["OOO.AX", "QAU.AX", "GOLD.AX", "USO", "BNO", "XLE", "XOP"]

if commodities_mode:
    watchlist = commodities_watchlist + asx_watchlist
    if international_mode:
        watchlist += intl_watchlist
else:
    watchlist = asx_watchlist if not international_mode else intl_watchlist + asx_watchlist

st.subheader("Upload Holdings CSV (CommSec for ASX side)")
portfolio_file = st.file_uploader("Upload your CommSec holdings CSV", type="csv")

portfolio_df = pd.DataFrame(columns=["Ticker", "Quantity", "Avg_Buy_Price"])

if portfolio_file is not None:
    try:
        content = portfolio_file.getvalue().decode("utf-8")
        lines = content.splitlines()
        data_start = 0
        for i, line in enumerate(lines):
            if line.startswith("Code,") or "Code" in line and "Avail Units" in line:
                data_start = i
                break
        csv_data = "\n".join(lines[data_start:])
        portfolio_raw = pd.read_csv(io.StringIO(csv_data))
        if "Code" in portfolio_raw.columns:
            portfolio_df["Ticker"] = portfolio_raw["Code"].astype(str).str.strip()
            portfolio_df["Ticker"] = portfolio_df["Ticker"].apply(lambda x: x if x.endswith(".AX") else x + ".AX")
            if "Avail Units" in portfolio_raw.columns:
                portfolio_df["Quantity"] = pd.to_numeric(portfolio_raw["Avail Units"], errors="coerce").fillna(0)
            if "Purchase $" in portfolio_raw.columns:
                portfolio_df["Avg_Buy_Price"] = pd.to_numeric(portfolio_raw["Purchase $"], errors="coerce").fillna(0)
            st.success(f"Loaded {len(portfolio_df)} holdings.")
    except Exception as e:
        st.error(f"Error reading CSV: {e}")

if st.button("Run Weekly Scan & Portfolio Review"):
    st.write(f"Scanning at {datetime.now().strftime('%Y-%m-%d %H:%M')} AEST")
    data = []
    for ticker in watchlist:
        stock = yfinance.Ticker(ticker)
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
        if rsi_val < rsi_threshold and momentum > 0:
            signal = "BUY"
        elif rsi_val > 70:
            signal = "SELL"
        else:
            signal = "HOLD"
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
    if not portfolio_df.empty:
        for _, row in portfolio_df.iterrows():
            ticker = row["Ticker"]
            qty = row["Quantity"]
            avg_price = row["Avg_Buy_Price"]
            existing = next((item for item in data if item["Ticker"] == ticker), None)
            if existing:
                existing["Quantity"] = qty
                existing["Avg Buy Price"] = avg_price
            else:
                data.append({"Ticker": ticker, "Current Price": 0.0, "RSI": 0.0, "Momentum %": 0.0, "Signal": "HOLD", "Quantity": qty, "Avg Buy Price": avg_price, "Holding Value": 0.0, "Unrealised Profit %": 0.0, "Advice": "HOLD"})
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
            else:
                item["Advice"] = "HOLD"
    if data:
        df = pd.DataFrame(data)
        def highlight(row):
            styles = []
            for val in row:
                if isinstance(val, str):
                    if "BUY" in val:
                        styles.append("background-color: lightgreen")
                    elif "SELL" in val:
                        styles.append("background-color: pink")
                    else:
                        styles.append("")
                else:
                    styles.append("")
            return styles
        styled_df = df.style.apply(highlight, axis=1)
        st.dataframe(styled_df, use_container_width=True)
        st.subheader("Profit Summary")
        held = df[df["Quantity"] > 0]
        if not held.empty:
            total_value = held["Holding Value"].sum()
            avg_profit = held["Unrealised Profit %"].mean()
            st.write(f"Total holding value: ${total_value:,.2f}")
            st.write(f"Average unrealised profit on holdings: {avg_profit:.1f}%")
        else:
            st.write("No holdings loaded yet.")
        st.write("Reinvest any realised profits into the next $500 position to compound steadily.")
        st.subheader("Risk and Execution Rules")
        st.write("CommSec $500 minimum for first purchase. Aim for 15–25 percent gross gain per aggressive swing.")
        st.write("Always set 8–10 percent stop-loss. Risk no more than 20–25 percent of capital per trade.")
        st.write("CBA/SMSF: International Mode off. NAB personal: turn International Mode on for global exposure.")
    else:
        st.write("No data returned – check internet and try again.")

st.markdown("---")
st.caption("Run weekly for both accounts. Defence, uranium and commodities (oil/gold) remain the strongest max-gain streams in the current global environment. Trade small, stay disciplined, and compound steadily from Yeppoon.")
