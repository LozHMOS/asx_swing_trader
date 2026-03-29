import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import io

st.title("ASX Weekly Swing Trader – Yeppoon Edition")
st.markdown("Built for disciplined week-to-week trading from your CommSec account (account 2926986 shown today). Handles native CommSec holdings CSV. $500 minimum initial buy respected. Not financial advice.")

# Capital
capital = st.number_input("Current capital in dollars", value=1000.0, step=50.0)
position_size = min(500.0, capital)

st.write(f"Recommended initial buy per new stock: ${position_size:.0f} (CommSec $500 minimum). Future top-ups to existing holdings can be smaller.")

# Sliders
rsi_threshold = st.slider("RSI oversold threshold for buy signals (lower = stricter)", 20, 40, 30)
momentum_period = st.slider("Momentum look-back in weeks", 4, 12, 8)

# Core watchlist (volatile sectors you like)
watchlist = ["DRO.AX", "ASB.AX", "EOS.AX", "STO.AX", "WDS.AX", "FMG.AX", "CXO.AX", "NXT.AX"]

# Portfolio upload – now handles native CommSec format
st.subheader("Upload CommSec Holdings CSV")
portfolio_file = st.file_uploader("Upload your CommSec holdings CSV (e.g. Holdings_2926986_27-03-2026.csv)", type="csv")

portfolio_df = pd.DataFrame(columns=["Ticker", "Quantity", "Avg_Buy_Price"])

if portfolio_file is not None:
    try:
        # Read the raw text and skip header lines until we find the data
        content = portfolio_file.getvalue().decode("utf-8")
        lines = content.splitlines()
        
        data_start = 0
        for i, line in enumerate(lines):
            if line.startswith("Code,") or "Code" in line and "Avail Units" in line:
                data_start = i
                break
        
        # Read from the data row onward
        csv_data = "\n".join(lines[data_start:])
        portfolio_raw = pd.read_csv(io.StringIO(csv_data))
        
        # Clean and map columns
        if "Code" in portfolio_raw.columns:
            portfolio_df["Ticker"] = portfolio_raw["Code"].astype(str).str.strip()
            # Ensure .AX suffix
            portfolio_df["Ticker"] = portfolio_df["Ticker"].apply(lambda x: x if x.endswith(".AX") else x + ".AX")
            
            if "Avail Units" in portfolio_raw.columns:
                portfolio_df["Quantity"] = pd.to_numeric(portfolio_raw["Avail Units"], errors="coerce").fillna(0)
            if "Purchase $" in portfolio_raw.columns:
                portfolio_df["Avg_Buy_Price"] = pd.to_numeric(portfolio_raw["Purchase $"], errors="coerce").fillna(0)
            
            st.success(f"Loaded {len(portfolio_df)} holdings from CommSec CSV.")
        else:
            st.warning("Could not detect standard CommSec columns. Please check the file.")
    except Exception as e:
        st.error(f"Error reading CSV: {e}")

if st.button("Run Weekly Scan & Portfolio Review"):
    st.write(f"Scanning at {datetime.now().strftime('%Y-%m-%d %H:%M')} AEST")
    data = []
    
    # Process watchlist (same logic as before)
    for ticker in watchlist:
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
    
    # Add or merge portfolio holdings
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
                # Add held ticker not in watchlist
                data.append({
                    "Ticker": ticker,
                    "Current Price": 0.0,
                    "RSI": 0.0,
                    "Momentum %": 0.0,
                    "Signal": "HOLD",
                    "Quantity": qty,
                    "Avg Buy Price": avg_price,
                    "Holding Value": 0.0,
                    "Unrealised Profit %": 0.0,
                    "Advice": "HOLD"
                })
    
    # Refresh prices and calculate profits for held positions
    for item in data:
        if item["Quantity"] > 0:
            try:
                price = yf.Ticker(item["Ticker"]).history(period="1d")["Close"].iloc[-1]
                item["Current Price"] = round(price, 3)
            except:
                pass  # keep existing price if fetch fails
            
            item["Holding Value"] = round(item["Quantity"] * item["Current Price"], 2)
            if item["Avg Buy Price"] > 0:
                item["Unrealised Profit %"] = round(((item["Current Price"] - item["Avg Buy Price"]) / item["Avg Buy Price"]) * 100, 1)
            
            # Set advice for held stocks
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
            st.write("No holdings loaded yet – portfolio is empty (as in today's CommSec export).")
        st.write("Reinvest any realised profits into the next $500 position to compound steadily.")
        
        st.subheader("Risk and Execution Rules")
        st.write("CommSec $500 minimum for first purchase of any stock. Aim for 10–15 percent gross gain per swing.")
        st.write("Always set 8–10 percent stop-loss below entry. Risk no more than 20–25 percent of capital per trade.")
        st.write("Plan: build toward five positions over the next two months while compounding profits.")
    else:
        st.write("No data returned – check internet connection and try again.")

st.markdown("---")
st.caption("Run weekly. Upload the latest CommSec CSV each time. Current-events review (defence momentum, energy/oil, nuclear/AI power themes, gold) provided manually in our chat. Trade small and disciplined from Yeppoon.")
