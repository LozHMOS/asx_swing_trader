import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Yeppoon Strategic Command", layout="wide", page_icon="🌊")

# --- SESSION INIT ---
if 'trade_ledger' not in st.session_state:
    st.session_state.trade_ledger = pd.DataFrame(
        columns=['Date', 'Ticker', 'Type', 'Units', 'Price', 'Total', 'Strategy', 'Sector']
    )

# --- HELPERS ---
@st.cache_data(ttl=300)
def get_market_data(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        if hist.empty:
            return 0, 0
        price = hist['Close'].iloc[-1]
        atr = (hist['High'] - hist['Low']).mean()
        return round(price, 3), round(atr, 3)
    except:
        return 0, 0

@st.cache_data(ttl=86400)
def get_sector_and_alternatives(ticker):
    alts_map = {
        "ENERGY": ["WDS.AX", "STO.AX"],
        "FINANCIAL SERVICES": ["CBA.AX", "NAB.AX"],
        "TECHNOLOGY": ["XRO.AX", "WTC.AX"],
        "BASIC MATERIALS": ["BHP.AX", "RIO.AX"]
    }
    try:
        sec = yf.Ticker(ticker).info.get('sector', 'Other').upper()
        return sec, alts_map.get(sec, ["Sector ETF"])
    except:
        return "OTHER", []

# --- CORE ENGINE ---
def calculate_portfolio(df):
    positions = {}
    realized_pnl = 0

    for _, row in df.iterrows():
        t, q, p = row['Ticker'], row['Units'], row['Price']

        if t not in positions:
            positions[t] = {'units': 0, 'avg': 0}

        pos = positions[t]

        if row['Type'] == 'BUY':
            total_units = pos['units'] + q
            if total_units > 0:
                pos['avg'] = ((pos['units'] * pos['avg']) + (q * p)) / total_units
            pos['units'] = total_units

        elif row['Type'] == 'SELL' and pos['units'] > 0:
            sell_qty = min(q, pos['units'])
            realized_pnl += sell_qty * (p - pos['avg'])
            pos['units'] -= sell_qty

    holdings = []
    for t, data in positions.items():
        if data['units'] > 0:
            price, atr = get_market_data(t)
            unreal = (price - data['avg']) * data['units']
            sec, alts = get_sector_and_alternatives(t)

            holdings.append({
                "Ticker": t,
                "Units": data['units'],
                "Avg Cost": round(data['avg'], 3),
                "Price": price,
                "Unrealized": round(unreal, 2),
                "Sector": sec,
                "ATR": atr,
                "Alts": alts
            })

    return realized_pnl, pd.DataFrame(holdings)

# --- STRATEGY ENGINE ---
def generate_plan(holdings, capital):
    recs = []

    for _, row in holdings.iterrows():
        if row['ATR'] > 0 and row['Price'] < (row['Avg Cost'] - 2 * row['ATR']):
            recs.append({"Action": "🚨 EXIT", "Ticker": row['Ticker'], "Reason": "Volatility breakdown"})

        elif row['Unrealized'] < -(capital * 0.02):
            recs.append({"Action": "✂️ HARVEST", "Ticker": row['Ticker'], "Reason": "Tax loss", "Alt": ", ".join(row['Alts'])})

    sector_perf = holdings.groupby('Sector')['Unrealized'].sum()

    for sec, perf in sector_perf.items():
        if perf > 0:
            pick = holdings[holdings['Sector'] == sec].sort_values(by='Unrealized', ascending=False).iloc[0]
            recs.append({"Action": "📈 ADD", "Ticker": pick['Ticker'], "Reason": "Sector strength"})

    return pd.DataFrame(recs)

# --- UI ---
st.title("🌊 Yeppoon Strategic Command")

tab1, tab2, tab3 = st.tabs(["📊 Portfolio", "📜 Ledger", "🎯 Risk"])

# --- ENTRY ---
with tab2:
    with st.form("trade"):
        t = st.text_input("Ticker", "DRO.AX").upper()
        ty = st.selectbox("Type", ["BUY","SELL"])
        q = st.number_input("Units", 1)
        p = st.number_input("Price", 0.001)

        if st.form_submit_button("Log"):
            sec, _ = get_sector_and_alternatives(t)
            row = pd.DataFrame([{
                'Date': datetime.now().strftime("%Y-%m-%d"),
                'Ticker': t,
                'Type': ty,
                'Units': q,
                'Price': p,
                'Total': q*p,
                'Sector': sec
            }])
            st.session_state.trade_ledger = pd.concat([st.session_state.trade_ledger, row], ignore_index=True)

# --- PORTFOLIO ---
with tab1:
    cap = st.sidebar.number_input("Capital", 10000)

    pnl, holdings = calculate_portfolio(st.session_state.trade_ledger)

    st.metric("Realized P/L", f"${pnl:,.2f}")
    st.metric("Tax Shield", f"${abs(min(pnl,0))*0.325:,.2f}")

    if not holdings.empty:
        st.dataframe(holdings)

        fig = px.treemap(holdings, path=['Sector','Ticker'], values='Unrealized',
                         color='Unrealized', color_continuous_scale='RdYlGn')
        st.plotly_chart(fig, use_container_width=True)

        # Equity curve
        df = st.session_state.trade_ledger.copy()
        df['Signed'] = df.apply(lambda x: x['Total'] if x['Type']=='SELL' else -x['Total'], axis=1)
        df['Cum'] = df['Signed'].cumsum()
        st.plotly_chart(px.line(df, x='Date', y='Cum', title="Equity Curve"), use_container_width=True)

        if st.button("🔁 Rebalance"):
            st.dataframe(generate_plan(holdings, cap))

# --- RISK ---
with tab3:
    entry = st.number_input("Entry", 1.0)
    stop = st.number_input("Stop", 0.9)

    if entry > stop:
        units = int((cap * 0.02) / (entry - stop))
        st.success(f"Trade size: {units} units")
