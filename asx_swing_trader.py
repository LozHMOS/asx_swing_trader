import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
from datetime import datetime
import time

# --- CONFIG ---
st.set_page_config(page_title="Yeppoon Strategic Command", layout="wide", page_icon="🌊")

# --- HELPERS ---
@st.cache_data(ttl=86400)
def get_sector_and_alternatives(ticker):
    alts = {
        "ENERGY": ["WDS.AX", "STO.AX"],
        "FINANCIAL SERVICES": ["CBA.AX", "NAB.AX"],
        "TECHNOLOGY": ["XRO.AX", "WTC.AX"],
        "BASIC MATERIALS": ["BHP.AX", "RIO.AX"],
        "URANIUM": ["PDN.AX", "BOE.AX", "DYL.AX"]
    }
    try:
        t_info = yf.Ticker(ticker).info
        sec = t_info.get('sector', 'Other').upper()
        return sec, alts.get(sec, ["Sector ETF"])
    except:
        return "Other", []

# --- SESSION INIT ---
if 'trade_ledger' not in st.session_state:
    st.session_state.trade_ledger = pd.DataFrame(columns=['Date','Ticker','Type','Units','Price','Total','Strategy','Sector'])

# --- UI HEADER ---
st.title("🌊 Yeppoon Strategic Command")
st.caption("Hybrid Swing + Core Buy-and-Hold | CBA/SMSF & NAB Personal")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Trading Parameters")
    capital = st.number_input("Current Capital ($)", value=10000.0, step=50.0)
    rsi_threshold = st.slider("RSI Oversold Threshold", 20, 40, 30)
    momentum_period = st.slider("Momentum Look-back (weeks)", 4, 12, 8)
    st.divider()
    intl_mode = st.checkbox("International Mode (NAB personal)", value=False)
    comm_mode = st.checkbox("Commodities Mode", value=True)

# --- WATCHLIST LOGIC ---
asx_watchlist = ["DRO.AX", "ASB.AX", "EOS.AX", "STO.AX", "WDS.AX", "FMG.AX", "CXO.AX", "NXT.AX", "PDN.AX", "BOE.AX", "DYL.AX", "SDR.AX", "JHX.AX"]
intl_watchlist = ["NVDA", "TSLA", "AMD", "BAE.L", "AIR.PA"]
comm_watchlist = ["OOO.AX", "QAU.AX", "GOLD.AX", "USO", "XLE"]

watchlist = asx_watchlist
if intl_mode: watchlist += intl_watchlist
if comm_mode: watchlist += comm_watchlist

core_thesis = {
    "PDN.AX": "Uranium producer. AI power demand + supply shortage.",
    "DRO.AX": "Counter-drone leader. Your original winner. High volatility.",
    "QAU.AX": "Currency-hedged gold. Safe-haven play.",
    "SDR.AX": "Hotel software. 70% discount to FV. ARR growth.",
    "JHX.AX": "James Hardie. Wide moat. US housing repair pipeline."
}

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["📊 Portfolio & Scan", "📜 Ledger", "🛠️ Risk Tools"])

with tab2:
    st.subheader("Manual Trade Entry")
    with st.form("trade"):
        c1, c2, c3, c4 = st.columns(4)
        t = c1.text_input("Ticker", "EOS.AX").upper()
        ty = c2.selectbox("Type", ["BUY", "SELL"])
        q = c3.number_input("Units", 1)
        p = c4.number_input("Price", 0.001)
        if st.form_submit_button("Log Trade"):
            sec, _ = get_sector_and_alternatives(t)
            row = pd.DataFrame([{'Date': datetime.now().strftime("%Y-%m-%d"), 'Ticker': t, 'Type': ty, 'Units': q, 'Price': p, 'Total': q*p, 'Strategy': 'Core' if t in core_thesis else 'Swing', 'Sector': sec}])
            st.session_state.trade_ledger = pd.concat([st.session_state.trade_ledger, row], ignore_index=True)
            st.success(f"Logged {ty} {t}")
    
    st.divider()
    st.subheader("Trade History")
    st.dataframe(st.session_state.trade_ledger, use_container_width=True)
    
    # DOWNLOAD BUTTON FOR PERSISTENCE
    if not st.session_state.trade_ledger.empty:
        csv = st.session_state.trade_ledger.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Ledger (CSV)",
            data=csv,
            file_name=f"yeppoon_ledger_{datetime.now().strftime('%Y%m%d')}.csv",
            mime='text/csv'
        )

with tab1:
    if not st.session_state.trade_ledger.empty:
        df_l = st.session_state.trade_ledger
        realized = df_l[df_l['Type'] == 'SELL']['Total'].sum() - df_l[df_l['Type'] == 'BUY']['Total'].sum()
        st.metric("Realized P/L (Ledger Cash)", f"${realized:,.2f}")

    if st.button("🚀 Run Weekly Scan"):
        st.write(f"Scanning at {datetime.now().strftime('%Y-%m-%d %H:%M')} AEST")
        data = []
        progress = st.progress(0)
        
        for i, ticker in enumerate(watchlist):
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="3mo")
                if len(hist) < 20: continue
                
                curr_p = hist["Close"].iloc[-1]
                delta = hist["Close"].diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = -delta.where(delta < 0, 0).rolling(14).mean()
                rsi = 100 - (100 / (1 + (gain / loss)))
                rsi_val = rsi.iloc[-1]
                momentum = (curr_p / hist["Close"].iloc[-momentum_period]) - 1
                
                signal = "BUY" if rsi_val < rsi_threshold and momentum > 0 else "SELL" if rsi_val > 70 else "HOLD"
                
                data.append({
                    "Ticker": ticker, "Price": round(curr_p, 3), "RSI": round(rsi_val, 1),
                    "Momentum %": round(momentum * 100, 1), "Signal": signal,
                    "Thesis": core_thesis.get(ticker, "Swing Play")
                })
            except: continue
            progress.progress((i + 1) / len(watchlist))
            time.sleep(0.05)

        if data:
            scan_df = pd.DataFrame(data)
            st.subheader("Scan Results")
            
            def highlight_signal(val):
                if val == 'BUY': return 'background-color: #90ee90; color: black'
                if val == 'SELL': return 'background-color: #ffcccb; color: black'
                return ''

            # Updated for Pandas 2.1.0+ Compatibility
            if hasattr(scan_df.style, 'map'):
                styled_df = scan_df.style.map(highlight_signal, subset=['Signal'])
            else:
                styled_df = scan_df.style.applymap(highlight_signal, subset=['Signal'])
                
            st.dataframe(styled_df, use_container_width=True)
            
            fig = px.treemap(scan_df, path=['Signal', 'Ticker'], values='RSI', color='RSI', color_continuous_scale='RdYlGn_r')
            st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("Position Sizing")
    entry = st.number_input("Entry Price", value=1.0)
    stop = st.number_input("Stop Loss", value=0.9)
    if entry > stop:
        risk_amt = capital * 0.02
        units = int(risk_amt / abs(entry - stop))
        st.success(f"To risk 2% (${risk_amt:,.0f}), buy **{units} units**.")
