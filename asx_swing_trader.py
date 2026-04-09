# =============================================================================
# YEPPOON STRATEGIC COMMAND — Streamlit App v2.0
# Hybrid Swing + Buy-and-Hold Trading System | Rulebook v2.0 | April 2026
# =============================================================================
# DEPLOYMENT: Streamlit Community Cloud via GitHub
# DEPENDENCIES: See requirements.txt
# DEBUG: Toggle "Debug Mode" in the sidebar to expose raw data & logs
# =============================================================================

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import traceback

# =============================================================================
# PAGE CONFIGURATION — must be the first Streamlit call
# =============================================================================
st.set_page_config(
    page_title="Yeppoon Strategic Command",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# CONSTANTS & WATCHLISTS (Rulebook Section 8)
# =============================================================================

CORE_PORTFOLIO = {
    "PDN.AX": {
        "name": "Paladin Energy",
        "thesis": "Uranium producer. AI data-centre power demand driving nuclear renaissance. Supply shortage structural.",
        "catalyst": "Production ramp at Langer Heinrich. Offtake agreements.",
        "stop_type": "50MA",
    },
    "DRO.AX": {
        "name": "DroneShield",
        "thesis": "Counter-drone technology leader. NATO/Five Eyes procurement accelerating.",
        "catalyst": "New government contracts. NATO framework deals.",
        "stop_type": "trailing25",
    },
    "QAU.AX": {
        "name": "Betashares Gold (AUD Hedged)",
        "thesis": "Currency-hedged gold. Safe-haven demand. AUD/USD hedge removes FX drag.",
        "catalyst": "Gold price momentum. Geopolitical risk premium.",
        "stop_type": "50MA",
    },
    "SDR.AX": {
        "name": "SiteMinder",
        "thesis": "Hotel software platform. ~70% discount to Morningstar fair value. ARR compounding.",
        "catalyst": "ARR acceleration. Profitability inflection. Analyst upgrades.",
        "stop_type": "50MA",
    },
    "JHX.AX": {
        "name": "James Hardie Industries",
        "thesis": "Wide-moat building materials. Dominant US fibre cement. Housing repair pipeline.",
        "catalyst": "US housing cycle recovery. Margin expansion.",
        "stop_type": "trailing25",
    },
}

ASX_WATCHLIST = [
    "DRO.AX","ASB.AX","EOS.AX","STO.AX","WDS.AX",
    "FMG.AX","CXO.AX","NXT.AX","PDN.AX","BOE.AX",
    "DYL.AX","SDR.AX","JHX.AX",
]
INTL_WATCHLIST  = ["NVDA","TSLA","AMD","BAE.L","AIR.PA"]
COMMODITY_WATCHLIST = ["OOO.AX","QAU.AX","GOLD.AX","USO","XLE"]

REGIME_TICKERS = {"ASX 200":"^AXJO","S&P 500":"^GSPC","VIX":"^VIX"}

LEDGER_COLUMNS = [
    "Date","Ticker","Strategy_Type","Direction","Quantity",
    "Price","Total_Value","Brokerage","Stop_Level",
    "Profit_Loss_Dollar","Profit_Loss_Pct","Rationale","Rule_Reference",
]

# =============================================================================
# SESSION STATE INITIALISATION
# =============================================================================

def init_session_state():
    defaults = {
        "debug_log": [],
        "trade_ledger": pd.DataFrame(columns=LEDGER_COLUMNS),
        "core_entries": {
            t: {"entry_price":0.0,"peak_price":0.0,"quantity":0}
            for t in CORE_PORTFOLIO
        },
        "last_scan_results": None,
        "regime_result": None,
        "core_results": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_session_state()

# =============================================================================
# DEBUG LOGGING
# =============================================================================

def dlog(message: str, level: str = "INFO"):
    """Append entry to in-session debug log."""
    st.session_state.debug_log.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "message": str(message),
    })

# =============================================================================
# DATA FETCHING — cached (production) and uncached (debug bypass)
# =============================================================================

def _fetch_raw(ticker: str, period: str = "1y"):
    """
    Core yfinance fetch. NOT cached — called directly by the debug panel.
    Returns (DataFrame | None, error_str | None).
    """
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period, auto_adjust=True)
        if df is None or df.empty:
            return None, f"No data returned for {ticker}"
        required = ["Open","High","Low","Close","Volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            return None, f"Missing columns {missing} for {ticker}"
        # Strip timezone — prevents AEST vs EST comparison errors
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df.dropna(subset=["Close"])
        if len(df) < 15:
            return None, f"Insufficient data for {ticker}: only {len(df)} rows (need ≥15)"
        return df, None
    except Exception as e:
        return None, f"yfinance exception for {ticker}: {type(e).__name__}: {e}"


@st.cache_data(ttl=900, show_spinner=False)
def fetch_ticker_data(ticker: str, period: str = "1y"):
    """Cached wrapper. TTL=15 min. Use _fetch_raw() in debug panel to bypass."""
    return _fetch_raw(ticker, period)

# =============================================================================
# TECHNICAL INDICATOR CALCULATIONS
# =============================================================================

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI using Wilder's smoothing (EWM alpha=1/period)."""
    if len(close) < period + 1:
        return pd.Series(np.nan, index=close.index)
    delta   = close.diff()
    gain    = delta.clip(lower=0)
    loss    = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig  = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig


def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    Derive all required indicators from an OHLCV DataFrame.
    Returns a flat dict of latest-bar values. Never raises — errors captured.
    """
    out = {
        "price":None,"prev_price":None,"price_change_pct":None,
        "ma_20":None,"ma_50":None,"ma_200":None,
        "above_50ma":None,"above_200ma":None,"days_below_50ma":0,
        "rsi":None,"rsi_prev":None,"rsi_turning":False,
        "macd_hist":None,"macd_hist_prev":None,"macd_inflecting":False,
        "volume":None,"volume_ma20":None,"volume_ratio":None,
        "high_52w":None,"low_52w":None,"peak_price":None,
        "errors":[],
    }
    try:
        close  = df["Close"]
        volume = df["Volume"]
        n = len(close)

        out["price"] = float(close.iloc[-1])
        if n >= 2:
            out["prev_price"] = float(close.iloc[-2])
            out["price_change_pct"] = (out["price"]-out["prev_price"])/out["prev_price"]*100

        if n >= 20:  out["ma_20"]  = float(close.rolling(20).mean().iloc[-1])
        if n >= 50:
            out["ma_50"]      = float(close.rolling(50).mean().iloc[-1])
            out["above_50ma"] = out["price"] > out["ma_50"]
        if n >= 200:
            out["ma_200"]      = float(close.rolling(200).mean().iloc[-1])
            out["above_200ma"] = out["price"] > out["ma_200"]

        # Consecutive closes below 50MA (Rule 6.1 — need 2 to trigger)
        if out["ma_50"] is not None:
            ma50s = close.rolling(50).mean()
            count = 0
            for i in range(1, min(6, n+1)):
                if close.iloc[-i] < ma50s.iloc[-i]: count += 1
                else: break
            out["days_below_50ma"] = count

        # RSI
        rsi_s = calc_rsi(close)
        if not rsi_s.dropna().empty:
            out["rsi"] = float(rsi_s.iloc[-1])
            if n >= 2: out["rsi_prev"] = float(rsi_s.iloc[-2])

        # RSI momentum turning up
        if out["rsi"] and out["rsi_prev"]:
            out["rsi_turning"] = (out["rsi"] > out["rsi_prev"]) and (out["rsi"] < 45)

        # MACD histogram
        _,_,hist = calc_macd(close)
        if not hist.dropna().empty:
            out["macd_hist"] = float(hist.iloc[-1])
            if n >= 2: out["macd_hist_prev"] = float(hist.iloc[-2])

        # MACD inflecting positive from negative (momentum confirmation)
        if out["macd_hist"] and out["macd_hist_prev"]:
            out["macd_inflecting"] = (
                out["macd_hist"] > out["macd_hist_prev"] and out["macd_hist"] < 0
            )

        # Volume
        out["volume"] = float(volume.iloc[-1])
        if n >= 20:
            vol_ma = float(volume.rolling(20).mean().iloc[-1])
            out["volume_ma20"] = vol_ma
            if vol_ma > 0: out["volume_ratio"] = out["volume"]/vol_ma

        # 52-week range and all-time peak
        w = min(252, n)
        out["high_52w"]   = float(close.rolling(w).max().iloc[-1])
        out["low_52w"]    = float(close.rolling(w).min().iloc[-1])
        out["peak_price"] = float(close.max())

    except Exception as e:
        out["errors"].append(f"Indicator error: {type(e).__name__}: {e}")
    return out

# =============================================================================
# MARKET REGIME (Rulebook Section 2)
# =============================================================================

def get_market_regime(debug: bool = False) -> dict:
    """
    Determine RISK-ON / RISK-CAUTION / RISK-OFF / UNKNOWN.
    Section 2 logic: ASX 200 vs 200MA, S&P 500 vs 200MA, VIX > 25 override.
    """
    result = {
        "regime":"UNKNOWN","parcel_size":500,"stop_pct":0.07,
        "signals":{},"errors":[],"raw_data":{},
    }
    for name, ticker in REGIME_TICKERS.items():
        df, err = fetch_ticker_data(ticker, "1y")
        if err:
            result["errors"].append(f"{name} ({ticker}): {err}")
            dlog(f"Regime fetch error — {name}: {err}","ERROR")
            continue
        if debug: result["raw_data"][ticker] = df
        ind = calculate_indicators(df)
        if name == "VIX":
            result["signals"]["VIX"] = {
                "value": ind["price"],
                "above_25": ind["price"] is not None and ind["price"] > 25,
            }
        else:
            result["signals"][name] = {
                "price":ind["price"],"ma_200":ind["ma_200"],
                "above_200ma":ind["above_200ma"],"indicator_errors":ind["errors"],
            }

    asx_above = result["signals"].get("ASX 200",{}).get("above_200ma")
    sp_above  = result["signals"].get("S&P 500",{}).get("above_200ma")
    vix_high  = result["signals"].get("VIX",{}).get("above_25",False)

    if asx_above is None or sp_above is None:
        result.update({"regime":"UNKNOWN","parcel_size":500,"stop_pct":0.07})
    elif vix_high or (not asx_above and not sp_above):
        result.update({"regime":"RISK-OFF","parcel_size":0,"stop_pct":0.05})
    elif not asx_above or not sp_above:
        result.update({"regime":"RISK-CAUTION","parcel_size":500,"stop_pct":0.06})
    else:
        result.update({"regime":"RISK-ON","parcel_size":1000,"stop_pct":0.09})

    dlog(f"Regime determined: {result['regime']}","INFO")
    return result

# =============================================================================
# SWING SCANNER — single ticker (Rulebook Rule 3.2)
# =============================================================================

def scan_single_ticker(ticker: str, regime: dict, debug: bool = False) -> dict:
    """Evaluate one ticker against Rule 3.2 entry criteria."""
    row = {
        "ticker":ticker,"price":None,"price_change_pct":None,
        "rsi":None,"rsi_prev":None,"rsi_turning":False,
        "volume_ratio":None,"macd_inflecting":False,
        "above_50ma":None,"ma_50":None,
        "high_52w":None,"low_52w":None,
        "buy_signal":False,"signal_strength":0,
        "signal_notes":[],"error":None,
    }
    df, err = fetch_ticker_data(ticker, "6mo")
    if err:
        row["error"] = err
        dlog(f"Scan fetch error {ticker}: {err}","WARN")
        return row
    try:
        ind = calculate_indicators(df)
        row.update({
            "price":         round(ind["price"],3)          if ind["price"] else None,
            "price_change_pct": round(ind["price_change_pct"],2) if ind["price_change_pct"] else None,
            "rsi":           round(ind["rsi"],1)            if ind["rsi"] is not None else None,
            "rsi_prev":      round(ind["rsi_prev"],1)       if ind["rsi_prev"] is not None else None,
            "rsi_turning":   ind["rsi_turning"],
            "volume_ratio":  round(ind["volume_ratio"],2)   if ind["volume_ratio"] else None,
            "macd_inflecting": ind["macd_inflecting"],
            "above_50ma":    ind["above_50ma"],
            "ma_50":         round(ind["ma_50"],3)          if ind["ma_50"] else None,
            "high_52w":      round(ind["high_52w"],3)       if ind["high_52w"] else None,
            "low_52w":       round(ind["low_52w"],3)        if ind["low_52w"] else None,
        })
        if ind["errors"]: row["error"] = " | ".join(ind["errors"])

        strength = 0
        notes    = []

        # Criterion 1: RSI <= 35 (REQUIRED)
        rsi_ok = row["rsi"] is not None and row["rsi"] <= 35
        if rsi_ok:
            strength += 3
            notes.append(f"✅ RSI {row['rsi']} ≤ 35 (oversold)")
        elif row["rsi"] and row["rsi"] <= 42:
            notes.append(f"⚠️ RSI {row['rsi']} — approaching oversold")
        else:
            notes.append(f"❌ RSI {row['rsi']} — not oversold")

        # Criterion 2: Momentum turning (REQUIRED)
        momentum_ok = ind["rsi_turning"] or ind["macd_inflecting"]
        if ind["rsi_turning"]:
            strength += 2
            notes.append("✅ RSI curling up from low")
        if ind["macd_inflecting"]:
            strength += 1
            notes.append("✅ MACD histogram inflecting positive")
        if not momentum_ok:
            notes.append("❌ No momentum confirmation yet")

        # Criterion 3: Volume >= 1.5x (quality confirmation)
        vol_ok = row["volume_ratio"] is not None and row["volume_ratio"] >= 1.5
        if vol_ok:
            strength += 2
            notes.append(f"✅ Volume {row['volume_ratio']}× avg (≥1.5× required)")
        elif row["volume_ratio"]:
            notes.append(f"⚠️ Volume {row['volume_ratio']}× avg (need ≥1.5×)")
        else:
            notes.append("⚠️ Volume data unavailable")

        row["buy_signal"]      = rsi_ok and momentum_ok
        row["signal_strength"] = strength
        row["signal_notes"]    = notes

        if regime["regime"] == "RISK-OFF":
            row["buy_signal"] = False
            row["signal_notes"].append("🔴 RISK-OFF regime: no new swing entries (Section 2)")

    except Exception as e:
        row["error"] = f"Processing error: {type(e).__name__}: {e}"
        if debug: row["error"] += f"\n{traceback.format_exc()}"
        dlog(f"Scan processing error {ticker}: {e}","ERROR")

    dlog(f"Scanned {ticker}: RSI={row['rsi']} | Signal={row['buy_signal']}","INFO")
    return row

# =============================================================================
# CORE PORTFOLIO CHECK (Rulebook Rule 6.1)
# =============================================================================

def check_core_position(ticker: str, entry_price: float, peak_price: float, debug: bool = False) -> dict:
    """Check a core position against Rule 6.1 exit triggers."""
    result = {
        "ticker":ticker,"action":"HOLD","action_colour":"green","status":"UNKNOWN",
        "price":None,"entry_price":entry_price,"gain_loss_pct":None,"rsi":None,
        "ma_50":None,"above_50ma":None,"days_below_50ma":0,
        "trailing_stop_level":None,"trailing_stop_breached":False,
        "peak_price_used":peak_price,"stop_type":CORE_PORTFOLIO[ticker]["stop_type"],
        "alerts":[],"error":None,"high_52w":None,
    }
    df, err = fetch_ticker_data(ticker, "1y")
    if err:
        result.update({"error":err,"status":"DATA ERROR"})
        dlog(f"Core check fetch error {ticker}: {err}","ERROR")
        return result
    try:
        ind = calculate_indicators(df)
        result.update({
            "price":      round(ind["price"],3),
            "ma_50":      round(ind["ma_50"],3)      if ind["ma_50"]    else None,
            "above_50ma": ind["above_50ma"],
            "days_below_50ma": ind["days_below_50ma"],
            "high_52w":   round(ind["high_52w"],3)   if ind["high_52w"] else None,
            "rsi":        round(ind["rsi"],1)         if ind["rsi"] is not None else None,
        })
        effective_peak = peak_price if peak_price > 0 else ind["peak_price"]
        result["peak_price_used"] = round(effective_peak,3) if effective_peak else None

        if effective_peak and effective_peak > 0:
            ts = effective_peak * 0.75
            result["trailing_stop_level"]   = round(ts,3)
            result["trailing_stop_breached"] = result["price"] < ts

        if entry_price and entry_price > 0:
            result["gain_loss_pct"] = round((result["price"]-entry_price)/entry_price*100,2)

        # Rule 6.1 logic
        alerts = []
        action = "HOLD"
        status = "OK — HOLD"

        if result["trailing_stop_breached"]:
            action = "EXIT"
            status = "TRAILING STOP BREACHED"
            alerts.append(
                f"🔴 RULE 6.1: 25% trailing stop breached. "
                f"Stop: ${result['trailing_stop_level']:.3f} | "
                f"Price: ${result['price']:.3f} | Peak: ${effective_peak:.3f}"
            )

        if result["stop_type"] == "50MA" and result["ma_50"]:
            if result["days_below_50ma"] >= 2:
                if action != "EXIT": action = "REDUCE 50%"
                status = "2 CONSECUTIVE CLOSES BELOW 50MA"
                alerts.append(
                    f"🟠 RULE 6.1: {result['days_below_50ma']} consecutive closes below 50MA. "
                    f"Reduce position 50% and reassess."
                )
            elif result["days_below_50ma"] == 1:
                if action == "HOLD": status = "WATCHING — 1 CLOSE BELOW 50MA"
                alerts.append("⚠️ RULE 6.1: 1 close below 50MA. Watch for second consecutive close.")

        if result["rsi"] and result["rsi"] >= 70:
            alerts.append(f"⚠️ RSI={result['rsi']} — overbought. Check 35% drift cap (Rule 6.1).")

        if not alerts: status = "✅ OK — HOLD"
        result.update({
            "action":action,"status":status,"alerts":alerts,
            "action_colour": {"EXIT":"red","REDUCE 50%":"orange"}.get(action,"green"),
        })
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        if debug: result["error"] += f"\n{traceback.format_exc()}"
        dlog(f"Core check error {ticker}: {e}","ERROR")

    dlog(f"Core {ticker}: {result['action']} | {result['status']}","INFO")
    return result

# =============================================================================
# CHART BUILDER
# =============================================================================

def build_price_chart(ticker: str, entry_price: float = 0, peak_price: float = 0):
    """Candlestick with 50MA, 200MA, entry line, trailing stop. Returns (fig|None, err|None)."""
    df, err = fetch_ticker_data(ticker, "1y")
    if err: return None, err
    try:
        close = df["Close"]
        ma50  = close.rolling(50).mean()
        ma200 = close.rolling(200).mean()

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            name=ticker, showlegend=False,
            increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        ))
        fig.add_trace(go.Scatter(x=df.index, y=ma50,  name="50MA",  line=dict(color="orange",width=1.5)))
        if ma200.dropna().shape[0] > 0:
            fig.add_trace(go.Scatter(x=df.index, y=ma200, name="200MA", line=dict(color="#5c9bd6",width=1.5,dash="dot")))

        if peak_price > 0:
            ts = peak_price * 0.75
            fig.add_hline(y=ts, line_dash="dash", line_color="red", line_width=1.5,
                          annotation_text=f"25% Trail Stop ${ts:.3f}", annotation_position="bottom right")
        if entry_price > 0:
            fig.add_hline(y=entry_price, line_dash="dot", line_color="#26a69a", line_width=1,
                          annotation_text=f"Entry ${entry_price:.3f}", annotation_position="top right")

        name = CORE_PORTFOLIO.get(ticker,{}).get("name",ticker)
        fig.update_layout(
            title=dict(text=f"{ticker} — {name}", font=dict(size=14)),
            height=380, template="plotly_dark", xaxis_rangeslider_visible=False,
            legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
            margin=dict(l=40,r=20,t=60,b=40),
        )
        return fig, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

# =============================================================================
# SIDEBAR
# =============================================================================

today = datetime.now()
is_tuesday       = today.weekday() == 1
is_first_tuesday = is_tuesday and today.day <= 7

with st.sidebar:
    st.title("🎯 Yeppoon SC")
    st.caption("Strategic Command v2.0")

    debug_mode = st.toggle(
        "🐛 Debug Mode", value=False,
        help="Expose raw data, indicator tables, and session log throughout the app.",
    )
    st.divider()

    st.write(f"**{today.strftime('%A, %d %B %Y')}**")
    if is_tuesday:
        st.success("✅ Tuesday — Scan Day")
    else:
        days = (1 - today.weekday()) % 7 or 7
        st.info(f"Next Tuesday: {(today+timedelta(days=days)).strftime('%d %b')}")
    if is_first_tuesday:
        st.warning("📅 First Tuesday — Full Monthly Core Review due")

    st.divider()
    st.subheader("📤 Trade Ledger")

    if not st.session_state.trade_ledger.empty:
        st.download_button(
            "⬇️ Export Ledger (CSV)",
            st.session_state.trade_ledger.to_csv(index=False).encode(),
            file_name=f"yeppoon_ledger_{today.strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )

    up_ledger = st.file_uploader("⬆️ Import Ledger (CSV)", type="csv",
        help="Upload a previously exported ledger to restore trade history.")
    if up_ledger:
        try:
            imp = pd.read_csv(up_ledger)
            missing = [c for c in LEDGER_COLUMNS if c not in imp.columns]
            if missing:
                st.error(f"Import failed — missing columns: {missing}")
            else:
                st.session_state.trade_ledger = imp
                st.success(f"✅ Imported {len(imp)} trades")
                dlog(f"Ledger imported: {len(imp)} rows","INFO")
        except Exception as e:
            st.error(f"Import error: {e}")

    st.divider()
    st.subheader("💾 Core Entry Prices")
    st.caption("Export/import between sessions — session state does not persist on refresh.")

    core_exp = pd.DataFrame(st.session_state.core_entries).T.reset_index()
    core_exp.columns = ["ticker","entry_price","peak_price","quantity"]
    st.download_button(
        "⬇️ Export Core Entries",
        core_exp.to_csv(index=False).encode(),
        file_name=f"yeppoon_core_{today.strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

    up_core = st.file_uploader("⬆️ Import Core Entries (CSV)", type="csv")
    if up_core:
        try:
            ci = pd.read_csv(up_core)
            for _, row in ci.iterrows():
                t = str(row.get("ticker",""))
                if t in st.session_state.core_entries:
                    st.session_state.core_entries[t].update({
                        "entry_price": float(row.get("entry_price",0)),
                        "peak_price":  float(row.get("peak_price",0)),
                        "quantity":    int(row.get("quantity",0)),
                    })
            st.success("✅ Core entries imported")
            dlog("Core entries imported","INFO")
        except Exception as e:
            st.error(f"Core import error: {e}")

    st.divider()
    st.subheader("🔄 Cache")
    st.caption("Data cached 15 min per ticker.")
    if st.button("🗑️ Clear Data Cache"):
        fetch_ticker_data.clear()
        st.session_state.regime_result   = None
        st.session_state.last_scan_results = None
        st.session_state.core_results    = None
        st.success("Cache cleared")
        dlog("Cache cleared by user","INFO")

# =============================================================================
# MAIN HEADER & TABS
# =============================================================================

st.title("🎯 Yeppoon Strategic Command")
st.caption(
    f"Rulebook v2.0 | {today.strftime('%A, %d %B %Y')} | "
    "Hybrid Swing + Buy-and-Hold | SMSF Compliant"
)
if debug_mode:
    st.warning("🐛 DEBUG MODE ACTIVE — raw data and calculation details visible throughout.", icon="🐛")
st.divider()

tab_dash, tab_regime, tab_swing, tab_core, tab_ledger, tab_debug = st.tabs([
    "📋 Dashboard","🌐 Market Regime","🔍 Swing Scanner",
    "💼 Core Portfolio","📝 Trade Ledger","🐛 Debug",
])

# =============================================================================
# TAB 1 — DASHBOARD
# =============================================================================

with tab_dash:
    st.header("📋 Weekly Dashboard")

    col_chk, col_prices, col_rules = st.columns([1.2,1,1])

    with col_chk:
        st.subheader("🗓️ Tuesday Checklist")
        weekly = [
            ("Determine Market Regime (Section 2)",              "w0"),
            ("Run Swing Watchlist Scan (Rule 3.2)",              "w1"),
            ("Review open swing positions — P&L & stops (Rule 3.5)", "w2"),
            ("Core Portfolio — trailing stop & 50MA check (Rule 6.1)", "w3"),
            ("Core Portfolio — Red Team Kill Switch (Rule 6.2)", "w4"),
            ("Log all trades / no-trade rationale (Rule 10)",    "w5"),
        ]
        monthly = [
            ("📅 MONTHLY: Full core re-score — all 10 criteria (Rule 5.1)", "m0"),
            ("📅 MONTHLY: Capital allocation review 70/80 split (Section 1)","m1"),
            ("📅 MONTHLY: Watchlist review — add/remove names (Section 8)",  "m2"),
            ("📅 MONTHLY: Reconcile ledger vs broker statements",            "m3"),
        ]
        for label, key in weekly:
            st.checkbox(label, key=f"chk_{key}")
        if is_first_tuesday:
            st.divider()
            st.caption("**First Tuesday — Monthly items also due:**")
            for label, key in monthly:
                st.checkbox(label, key=f"chk_{key}")

    with col_prices:
        st.subheader("💼 Core Prices")
        for ticker in CORE_PORTFOLIO:
            df, err = fetch_ticker_data(ticker, "5d")
            if err:
                st.warning(f"**{ticker}**: {err}")
            elif df is not None and not df.empty:
                price = df["Close"].iloc[-1]
                chg   = (df["Close"].iloc[-1]-df["Close"].iloc[-2])/df["Close"].iloc[-2]*100 if len(df)>=2 else 0
                arrow = "▲" if chg >= 0 else "▼"
                col   = "green" if chg >= 0 else "red"
                st.markdown(
                    f"**{ticker}** — ${price:.3f} "
                    f"<span style='color:{col}'>{arrow} {abs(chg):.2f}%</span>",
                    unsafe_allow_html=True,
                )

    with col_rules:
        st.subheader("⚡ Quick Reference")
        st.markdown("""
**Swing Entry (Rule 3.2)**
- RSI ≤ 35
- Momentum turning ↑
- Volume ≥ 1.5× 20-day avg
- Regime ≠ RISK-OFF

**Core Exit (Rule 6.1)**
- 2 closes below 50MA → Reduce 50%
- 25% trailing stop → Exit 100%

**Kill Switch (Rule 6.2)**
- Capital raise announced
- Binary risk event
- Thesis breach
- Insider selling surge

**Parcel Sizes**
- 🟢 Risk-On: $1,000
- 🟠 Risk-Caution: $500
- 🔴 Risk-Off: No entries
        """)

    st.divider()
    st.subheader("🌐 Regime Snapshot")
    if st.button("🔄 Load Regime", key="dash_regime"):
        with st.spinner("Fetching..."):
            st.session_state.regime_result = get_market_regime(debug=debug_mode)

    if st.session_state.regime_result:
        r = st.session_state.regime_result
        emj = {"RISK-ON":"🟢","RISK-CAUTION":"🟠","RISK-OFF":"🔴","UNKNOWN":"⚪"}
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Regime", f"{emj.get(r['regime'],'⚪')} {r['regime']}")
        m2.metric("Parcel",  f"${r['parcel_size']}" if r["parcel_size"]>0 else "NO ENTRY")
        m3.metric("Stop %",  f"{r['stop_pct']*100:.0f}%")
        vix = r["signals"].get("VIX",{})
        if vix and vix.get("value"):
            m4.metric("VIX", f"{vix['value']:.1f}",
                      delta="HIGH ⚠️" if vix["above_25"] else "OK ✅",
                      delta_color="inverse" if vix["above_25"] else "normal")
        for name, sig in r["signals"].items():
            if name=="VIX": continue
            p = sig.get("price"); m = sig.get("ma_200"); ab = sig.get("above_200ma")
            if p and m:
                diff = (p-m)/m*100
                st.write(f"• **{name}:** ${p:,.0f} vs 200MA ${m:,.0f} "
                         f"({'🟢 ABOVE' if ab else '🔴 BELOW'}, {diff:+.1f}%)")
        for err_msg in r["errors"]:
            st.warning(f"⚠️ {err_msg}")
    else:
        st.info("Click 'Load Regime' to see current market regime.")

# =============================================================================
# TAB 2 — MARKET REGIME
# =============================================================================

with tab_regime:
    st.header("🌐 Market Regime Filter")
    st.caption("Rulebook Section 2 — Master on/off switch for swing trade aggression")

    st.markdown("""
| Signal | Regime | Parcel | Stop |
|---|---|---|---|
| Both ASX 200 & S&P 500 above 200MA | **RISK-ON** | $1,000 | 8–10% |
| One index below 200MA | **RISK-CAUTION** | $500 | 5–7% |
| Both below 200MA **or** VIX > 25 | **RISK-OFF** | No new entries | 5% |
    """)

    if st.button("🔄 Run Regime Analysis", key="regime_full"):
        with st.spinner("Fetching ASX 200, S&P 500 and VIX..."):
            st.session_state.regime_result = get_market_regime(debug=debug_mode)

    if st.session_state.regime_result:
        r   = st.session_state.regime_result
        emj = {"RISK-ON":"🟢","RISK-CAUTION":"🟠","RISK-OFF":"🔴","UNKNOWN":"⚪"}
        e   = emj.get(r["regime"],"⚪")
        st.markdown(f"## {e} Regime: **{r['regime']}**")

        c1,c2,c3 = st.columns(3)
        c1.metric("Parcel Size", f"${r['parcel_size']}" if r["parcel_size"]>0 else "NO NEW ENTRIES")
        c2.metric("Stop Loss",   f"{r['stop_pct']*100:.0f}%")
        vix = r["signals"].get("VIX",{})
        if vix and vix.get("value"):
            c3.metric("VIX", f"{vix['value']:.1f}",
                      delta="ABOVE 25 ⚠️" if vix["above_25"] else "Normal ✅",
                      delta_color="inverse" if vix["above_25"] else "normal")

        st.divider()
        idx_cols = st.columns(2)
        for i,(name,sig) in enumerate([(k,v) for k,v in r["signals"].items() if k!="VIX"]):
            with idx_cols[i%2]:
                above = sig.get("above_200ma")
                if above is True:     st.success(f"**{name} — 🟢 ABOVE 200MA**")
                elif above is False:  st.error(f"**{name} — 🔴 BELOW 200MA**")
                else:                 st.warning(f"**{name} — ⚪ DATA UNAVAILABLE**")
                p = sig.get("price"); m = sig.get("ma_200")
                if p and m:
                    diff = (p-m)/m*100
                    st.metric("Price", f"{p:,.0f}",
                              delta=f"{diff:+.1f}% vs 200MA",
                              delta_color="normal" if above else "inverse")
                    st.write(f"200-day MA: {m:,.0f}")
                for ie in sig.get("indicator_errors",[]):
                    st.warning(f"⚠️ {ie}")

        st.subheader("📈 12-Month Index Charts")
        for name, ticker in [("ASX 200","^AXJO"),("S&P 500","^GSPC")]:
            df, err = fetch_ticker_data(ticker,"1y")
            if err:
                st.error(f"Chart error {name}: {err}"); continue
            close = df["Close"]; ma200 = close.rolling(200).mean()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df.index,y=close, name=name,  line=dict(color="#26a69a",width=2)))
            fig.add_trace(go.Scatter(x=df.index,y=ma200, name="200MA",line=dict(color="orange",width=1.5,dash="dash")))
            fig.update_layout(title=f"{name} vs 200MA", height=300, template="plotly_dark",
                              xaxis_rangeslider_visible=False,
                              legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
                              margin=dict(l=40,r=20,t=50,b=30))
            st.plotly_chart(fig, use_container_width=True)

        if r["errors"]:
            st.subheader("⚠️ Data Errors")
            for em in r["errors"]: st.error(em)

        if debug_mode and r.get("raw_data"):
            st.subheader("🐛 Raw Data")
            for ticker, df in r["raw_data"].items():
                st.write(f"**{ticker}** | Shape: {df.shape}")
                st.dataframe(df.tail(5), use_container_width=True)
    else:
        st.info("👆 Click **Run Regime Analysis** to fetch live data.")

# =============================================================================
# TAB 3 — SWING SCANNER
# =============================================================================

with tab_swing:
    st.header("🔍 Swing Watchlist Scanner")
    st.caption("Rulebook Rule 3.2 — Entry: RSI ≤ 35 + Momentum turning + Volume ≥ 1.5× avg")

    sel1,sel2,sel3 = st.columns(3)
    scan_asx   = sel1.checkbox(f"ASX Watchlist ({len(ASX_WATCHLIST)})", value=True)
    scan_intl  = sel2.checkbox(f"International ({len(INTL_WATCHLIST)})", value=True)
    scan_comms = sel3.checkbox(f"Commodities/ETFs ({len(COMMODITY_WATCHLIST)})", value=True)

    to_scan = []
    if scan_asx:   to_scan += ASX_WATCHLIST
    if scan_intl:  to_scan += INTL_WATCHLIST
    if scan_comms: to_scan += COMMODITY_WATCHLIST
    to_scan = list(dict.fromkeys(to_scan))
    st.write(f"**{len(to_scan)} tickers queued**")

    if st.button("🚀 Run Full Swing Scan", key="swing_scan", type="primary"):
        if not st.session_state.regime_result:
            with st.spinner("Loading regime first..."):
                st.session_state.regime_result = get_market_regime(debug=debug_mode)
        regime = st.session_state.regime_result
        emj = {"RISK-ON":"🟢","RISK-CAUTION":"🟠","RISK-OFF":"🔴","UNKNOWN":"⚪"}
        st.info(
            f"Regime: {emj.get(regime['regime'],'⚪')} **{regime['regime']}** | "
            f"Parcel: ${regime['parcel_size']} | Stop: {regime['stop_pct']*100:.0f}%"
        )
        scan_results = []
        prog = st.progress(0, text="Scanning...")
        for i, ticker in enumerate(to_scan):
            prog.progress((i+1)/len(to_scan), text=f"Scanning {ticker}... ({i+1}/{len(to_scan)})")
            scan_results.append(scan_single_ticker(ticker, regime, debug=debug_mode))
        prog.empty()
        st.session_state.last_scan_results = scan_results
        st.success(f"✅ Scan complete — {len(scan_results)} tickers processed")

    if st.session_state.last_scan_results:
        results     = st.session_state.last_scan_results
        buy_signals = [r for r in results if r["buy_signal"]]
        approaching = [r for r in results if not r["buy_signal"] and not r["error"]
                       and r["rsi"] and 35 < r["rsi"] <= 45]
        errors      = [r for r in results if r["error"]]

        # BUY SIGNALS
        st.subheader(f"🟢 BUY SIGNALS — {len(buy_signals)} found")
        if buy_signals:
            regime = st.session_state.regime_result or {"parcel_size":1000,"stop_pct":0.09}
            for r in sorted(buy_signals, key=lambda x: x["rsi"] or 999):
                with st.expander(
                    f"✅ **{r['ticker']}** — RSI: {r['rsi']} | Price: ${r['price']} | Vol: {r['volume_ratio']}×",
                    expanded=True
                ):
                    m1,m2,m3,m4 = st.columns(4)
                    m1.metric("RSI",        r["rsi"], delta="OVERSOLD ✅", delta_color="off")
                    m2.metric("Price",      f"${r['price']}")
                    m3.metric("Volume",     f"{r['volume_ratio']}×" if r["volume_ratio"] else "N/A")
                    m4.metric("Day Chg",    f"{r['price_change_pct']:+.2f}%" if r["price_change_pct"] else "N/A")
                    st.write("**Signal Checklist:**")
                    for note in r["signal_notes"]: st.write(f"  {note}")

                    if r["price"] and regime:
                        sp   = regime["stop_pct"]
                        parc = regime["parcel_size"]
                        stop = round(r["price"]*(1-sp),3)
                        t15  = round(r["price"]*1.15,3)
                        t25  = round(r["price"]*1.25,3)
                        qty  = int(parc/r["price"]) if r["price"]>0 else 0
                        st.divider()
                        st.write("**📐 Suggested Parameters (Rules 3.3–3.5):**")
                        p1,p2,p3,p4,p5 = st.columns(5)
                        p1.metric("Parcel",       f"${parc}")
                        p2.metric("Approx Qty",   qty)
                        p3.metric(f"Stop ({sp*100:.0f}%)", f"${stop:.3f}",
                                  delta=f"-{sp*100:.0f}%", delta_color="inverse")
                        p4.metric("Target 15%",   f"${t15:.3f}")
                        p5.metric("Target 25%",   f"${t25:.3f}")
                    if debug_mode:
                        with st.expander("🐛 Raw row data"):
                            st.json({k:v for k,v in r.items() if k!="signal_notes"})
        else:
            st.info("No RSI ≤ 35 + momentum signals found on the current scan.")

        st.divider()
        st.subheader(f"⚠️ Approaching Oversold — RSI 35–45 ({len(approaching)} names)")
        if approaching:
            adf = pd.DataFrame([{
                "Ticker":r["ticker"],"Price":r["price"],"RSI":r["rsi"],
                "Vol Ratio":r["volume_ratio"],"50MA":r["ma_50"],
                "Above 50MA":"✅" if r["above_50ma"] else "❌",
                "Day Chg %":r["price_change_pct"],
                "MACD ↑":"✅" if r["macd_inflecting"] else "—",
                "RSI ↑":"✅" if r["rsi_turning"] else "—",
            } for r in sorted(approaching, key=lambda x: x["rsi"] or 999)])
            st.dataframe(adf, use_container_width=True, hide_index=True)
        else:
            st.info("No tickers in the 35–45 RSI watch zone.")

        st.divider()
        with st.expander("📊 Full Scan Results Table", expanded=False):
            all_ok = [r for r in results if not r["error"]]
            if all_ok:
                fdf = pd.DataFrame([{
                    "Ticker":r["ticker"],"Price":r["price"],"RSI":r["rsi"],
                    "Vol Ratio":r["volume_ratio"],"50MA":r["ma_50"],
                    "Above 50MA":"✅" if r["above_50ma"] else ("❌" if r["above_50ma"] is not None else "—"),
                    "Day Chg %":r["price_change_pct"],
                    "52W High":r["high_52w"],"52W Low":r["low_52w"],
                    "MACD ↑":"✅" if r["macd_inflecting"] else "—",
                    "RSI ↑":"✅" if r["rsi_turning"] else "—",
                    "Signal":"🟢 BUY" if r["buy_signal"] else ("⚠️ WATCH" if r["rsi"] and r["rsi"]<=45 else "—"),
                    "Strength":r["signal_strength"],
                } for r in sorted(all_ok, key=lambda x: x["rsi"] or 999)])
                st.dataframe(fdf, use_container_width=True, hide_index=True)

        if errors:
            with st.expander(f"⚠️ Data Errors ({len(errors)} tickers)", expanded=False):
                for r in errors: st.warning(f"**{r['ticker']}:** {r['error']}")
    else:
        st.info("👆 Click **Run Full Swing Scan** to start.")

# =============================================================================
# TAB 4 — CORE PORTFOLIO
# =============================================================================

with tab_core:
    st.header("💼 Core Portfolio Review")
    st.caption("Rule 6.1 — Trailing stop & 50MA exits | Rule 6.2 — Red Team Kill Switch (manual)")

    with st.expander("⚙️ Set Entry Prices & Position Details", expanded=False):
        st.caption("Set actual entry prices for accurate stop calculations. Export via sidebar to persist.")
        hdr = st.columns([1,1,1,1,2])
        hdr[0].write("**Ticker**"); hdr[1].write("**Entry $**")
        hdr[2].write("**Peak $ (0=auto)**"); hdr[3].write("**Qty**"); hdr[4].write("**Name**")

        for ticker, info in CORE_PORTFOLIO.items():
            ce = st.session_state.core_entries[ticker]
            c0,c1,c2,c3,c4 = st.columns([1,1,1,1,2])
            c0.write(f"**{ticker}**")
            ep  = c1.number_input("EP",  key=f"ep_{ticker}",  label_visibility="collapsed",
                                   value=float(ce["entry_price"]), min_value=0.0, step=0.001, format="%.3f")
            pp  = c2.number_input("PP",  key=f"pp_{ticker}",  label_visibility="collapsed",
                                   value=float(ce["peak_price"]),  min_value=0.0, step=0.001, format="%.3f")
            qty = c3.number_input("QTY", key=f"qty_{ticker}", label_visibility="collapsed",
                                   value=int(ce["quantity"]), min_value=0, step=1)
            c4.write(info["name"])
            st.session_state.core_entries[ticker].update(
                {"entry_price":ep,"peak_price":pp,"quantity":qty}
            )

    if st.button("🔄 Run Core Portfolio Check", key="core_check", type="primary"):
        all_cr = {}
        prog = st.progress(0, text="Checking...")
        for i, ticker in enumerate(CORE_PORTFOLIO):
            ce = st.session_state.core_entries[ticker]
            all_cr[ticker] = check_core_position(
                ticker, ce["entry_price"], ce["peak_price"], debug=debug_mode
            )
            prog.progress((i+1)/len(CORE_PORTFOLIO), text=f"Checked {ticker}")
        prog.empty()
        st.session_state.core_results = all_cr

    if st.session_state.core_results:
        cr = st.session_state.core_results
        actions  = [r["action"] for r in cr.values()]
        exits_n  = actions.count("EXIT")
        reduces_n= actions.count("REDUCE 50%")
        holds_n  = actions.count("HOLD")

        sm1,sm2,sm3,sm4 = st.columns(4)
        sm1.metric("🔴 EXIT Signals",   exits_n)
        sm2.metric("🟠 REDUCE Signals", reduces_n)
        sm3.metric("🟢 Hold",           holds_n)
        sm4.metric("Total Positions",   len(cr))
        st.divider()

        action_emj = {"EXIT":"🔴","REDUCE 50%":"🟠","HOLD":"🟢"}

        for ticker, result in cr.items():
            info = CORE_PORTFOLIO[ticker]
            emj  = action_emj.get(result["action"],"⚪")

            with st.expander(
                f"{emj} **{ticker}** — {info['name']} | **{result['action']}** | {result['status']}",
                expanded=(result["action"] != "HOLD")
            ):
                if result.get("error"):
                    st.error(f"⚠️ Data error: {result['error']}")
                    continue

                m1,m2,m3,m4,m5,m6 = st.columns(6)
                m1.metric("Price", f"${result['price']:.3f}" if result["price"] else "N/A")
                m2.metric("Entry", f"${result['entry_price']:.3f}" if result["entry_price"]>0 else "Not set")
                if result["gain_loss_pct"] is not None:
                    m3.metric("P&L", f"{result['gain_loss_pct']:+.1f}%",
                              delta_color="normal" if result["gain_loss_pct"]>=0 else "inverse")
                else:
                    m3.metric("P&L","—")
                m4.metric("50MA", f"${result['ma_50']:.3f}" if result["ma_50"] else "N/A",
                          delta="ABOVE ✅" if result["above_50ma"] else "BELOW ❌",
                          delta_color="normal" if result["above_50ma"] else "inverse")
                m5.metric("Trail Stop",
                          f"${result['trailing_stop_level']:.3f}" if result["trailing_stop_level"] else "N/A",
                          delta="BREACHED 🔴" if result["trailing_stop_breached"] else "Safe ✅",
                          delta_color="inverse" if result["trailing_stop_breached"] else "normal")
                m6.metric("RSI", result["rsi"] if result["rsi"] else "N/A")

                for alert in result.get("alerts",[]):
                    if "🔴" in alert:   st.error(alert)
                    elif "🟠" in alert: st.warning(alert)
                    else:               st.info(alert)

                d1,d2 = st.columns(2)
                with d1:
                    st.write(f"**Thesis:** {info['thesis']}")
                    st.write(f"**Catalyst:** {info['catalyst']}")
                    st.write(f"**Stop type:** {result['stop_type']}")
                    st.write(f"**Days below 50MA:** {result['days_below_50ma']}")
                with d2:
                    if result["peak_price_used"]:
                        st.write(f"**Peak (trail stop):** ${result['peak_price_used']:.3f}")
                    qty = st.session_state.core_entries[ticker]["quantity"]
                    if qty>0 and result["price"]:
                        st.write(f"**Qty:** {qty} | **Mkt value:** ${qty*result['price']:,.2f}")
                    if result["high_52w"]:
                        st.write(f"**52W High:** ${result['high_52w']:.3f}")

                fig, cerr = build_price_chart(
                    ticker,
                    entry_price=result["entry_price"],
                    peak_price=result["peak_price_used"] or 0
                )
                if fig:   st.plotly_chart(fig, use_container_width=True)
                elif cerr: st.caption(f"Chart unavailable: {cerr}")

                if debug_mode:
                    with st.expander("🐛 Raw result"):
                        st.json({k:v for k,v in result.items() if k!="alerts"})

        # Kill Switch manual checklist
        st.divider()
        st.subheader("🔴 Red Team Kill Switch — Manual Review (Rule 6.2)")
        st.warning(
            "These **cannot be automated**. Review manually every Tuesday. "
            "If ANY apply → exit within 2 trading days. No debate.", icon="⚠️"
        )
        kill_items = [
            "Capital raise announced or strongly rumoured within 3–6 months",
            "Binary risk event: single ruling/decision could wipe 50%+ overnight",
            "Thesis breach: original reason for owning no longer holds",
            "Insider selling surge: key executives selling >20% of holdings without benign reason",
            "Liquidity collapse: daily volume consistently <$2M (can't exit without moving price)",
            "Debt covenant breach or going-concern note in accounts",
        ]
        for idx, item in enumerate(kill_items):
            st.checkbox(
                f"✅ Confirmed — **{item}** does NOT apply",
                key=f"ks_{idx}"
            )
    else:
        st.info("👆 Click **Run Core Portfolio Check** to analyse positions.")

# =============================================================================
# TAB 5 — TRADE LEDGER
# =============================================================================

with tab_ledger:
    st.header("📝 Trade Ledger")
    st.caption(
        "Rulebook Rule 10 — Every trade logged same-day for SMSF compliance. "
        "Export CSV from the sidebar after each session — data does not persist on refresh."
    )

    col_form, col_table = st.columns([1,2])

    with col_form:
        st.subheader("➕ Log New Trade")
        with st.form("trade_form", clear_on_submit=True):
            f_date      = st.date_input("Date", value=today.date())
            f_ticker    = st.text_input("Ticker (e.g. DRO.AX)").strip().upper()
            f_strategy  = st.selectbox("Strategy Type", ["Swing","Core","Promotion"])
            f_direction = st.selectbox("Direction",     ["Buy","Sell","Partial Sell"])
            f_qty       = st.number_input("Quantity (units)", min_value=0, step=1)
            f_price     = st.number_input("Price ($)", min_value=0.0, step=0.001, format="%.4f")
            f_brokerage = st.number_input("Brokerage ($)", min_value=0.0, value=9.50, step=0.01)
            f_stop      = st.number_input("Stop Level ($ — buys only, 0 to skip)",
                                          min_value=0.0, step=0.001, format="%.4f")
            f_pl        = st.number_input("Realised P&L $ (sells only, 0 to skip)",
                                          step=0.01, format="%.2f")
            f_rationale = st.text_area("Rationale (≤3 sentences)", height=80)
            f_rule_ref  = st.text_input("Rule Reference (e.g. Rule 3.2)")
            submitted   = st.form_submit_button("✅ Log Trade", type="primary")

            if submitted:
                errs = []
                if not f_ticker: errs.append("Ticker required")
                if f_qty <= 0:   errs.append("Quantity must be > 0")
                if f_price <= 0: errs.append("Price must be > 0")
                if errs:
                    for e in errs: st.error(e)
                else:
                    total = round(f_qty*f_price,2)
                    pl_pct = 0.0
                    if f_pl and total > 0:
                        cost = total-f_pl
                        pl_pct = (f_pl/cost*100) if cost>0 else 0.0
                    new_row = pd.DataFrame([{
                        "Date":       f_date.strftime("%d/%m/%Y"),
                        "Ticker":     f_ticker,
                        "Strategy_Type": f_strategy,
                        "Direction":  f_direction,
                        "Quantity":   f_qty,
                        "Price":      f_price,
                        "Total_Value":total,
                        "Brokerage":  f_brokerage,
                        "Stop_Level": f_stop if f_direction=="Buy" and f_stop>0 else "",
                        "Profit_Loss_Dollar": f_pl if f_direction in ["Sell","Partial Sell"] and f_pl!=0 else "",
                        "Profit_Loss_Pct":    round(pl_pct,2) if f_direction in ["Sell","Partial Sell"] else "",
                        "Rationale":  f_rationale,
                        "Rule_Reference": f_rule_ref,
                    }])
                    st.session_state.trade_ledger = pd.concat(
                        [st.session_state.trade_ledger, new_row], ignore_index=True
                    )
                    dlog(f"Trade: {f_direction} {f_qty}x {f_ticker} @${f_price:.4f} ({f_strategy})","INFO")
                    st.success(f"✅ Logged: {f_direction} {f_qty}× {f_ticker} @${f_price:.4f}")

    with col_table:
        st.subheader("📊 Trade History")
        if st.session_state.trade_ledger.empty:
            st.info("No trades logged. Use the form on the left to record your first trade.")
        else:
            ledger = st.session_state.trade_ledger.copy()
            sells  = ledger[ledger["Direction"].isin(["Sell","Partial Sell"])]
            if not sells.empty:
                try:
                    pl_s  = pd.to_numeric(sells["Profit_Loss_Dollar"],errors="coerce").dropna()
                    total_pl = pl_s.sum()
                    wins  = (pl_s>0).sum(); losses = (pl_s<0).sum()
                    wr    = wins/(wins+losses)*100 if (wins+losses)>0 else 0
                    aw    = pl_s[pl_s>0].mean() if wins>0 else 0
                    al    = pl_s[pl_s<0].mean() if losses>0 else 0
                    s1,s2,s3,s4,s5 = st.columns(5)
                    s1.metric("Total Trades",  len(ledger))
                    s2.metric("Realised P&L",  f"${total_pl:,.2f}",
                              delta_color="normal" if total_pl>=0 else "inverse")
                    s3.metric("Win Rate",       f"{wr:.0f}%")
                    s4.metric("Avg Winner",     f"${aw:,.2f}")
                    s5.metric("Avg Loser",      f"${al:,.2f}")
                except Exception as e:
                    st.caption(f"Stats error: {e}")

            st.divider()
            fc1,fc2 = st.columns(2)
            f_strat = fc1.multiselect("Filter Strategy",
                                       ledger["Strategy_Type"].unique().tolist(),
                                       default=ledger["Strategy_Type"].unique().tolist())
            f_dir   = fc2.multiselect("Filter Direction",
                                       ledger["Direction"].unique().tolist(),
                                       default=ledger["Direction"].unique().tolist())
            filtered = ledger[ledger["Strategy_Type"].isin(f_strat) &
                               ledger["Direction"].isin(f_dir)]
            st.dataframe(filtered, use_container_width=True, hide_index=True)

            dc1,dc2 = st.columns(2)
            if dc1.button("🗑️ Remove Last Entry"):
                st.session_state.trade_ledger = st.session_state.trade_ledger.iloc[:-1].reset_index(drop=True)
                dlog("Last trade deleted","WARN")
                st.rerun()
            if dc2.button("🗑️ Clear All Trades"):
                st.session_state.trade_ledger = pd.DataFrame(columns=LEDGER_COLUMNS)
                dlog("All trades cleared","WARN")
                st.rerun()

# =============================================================================
# TAB 6 — DEBUG
# =============================================================================

with tab_debug:
    st.header("🐛 Debug Panel")
    st.caption(
        "Diagnostic tools for troubleshooting yfinance data, indicator calculations, "
        "and session state. Always available regardless of the debug mode toggle."
    )

    # Ticker connection test
    st.subheader("🔌 Ticker Connection Test")
    st.caption("Uses _fetch_raw() — **bypasses the 15-minute cache** to get live data immediately.")
    tc1,tc2 = st.columns([2,1])
    test_ticker = tc1.text_input("Test Ticker", value="CBA.AX",
                                  help="ASX: CBA.AX | US: NVDA | London: BAE.L | Paris: AIR.PA")
    test_period = tc2.selectbox("Period", ["1mo","3mo","6mo","1y","2y"], index=2)

    if st.button("🧪 Test Fetch (uncached)", key="debug_test"):
        with st.spinner(f"Fetching {test_ticker}..."):
            df_t, err_t = _fetch_raw(test_ticker, test_period)
        if err_t:
            st.error(f"❌ FAILED: {err_t}")
            dlog(f"Debug test failed: {test_ticker}: {err_t}","ERROR")
        else:
            st.success(f"✅ SUCCESS — {len(df_t)} rows returned")
            dlog(f"Debug test OK: {test_ticker} ({len(df_t)} rows)","INFO")
            dc1,dc2,dc3,dc4 = st.columns(4)
            dc1.metric("Rows",      len(df_t))
            dc2.metric("Columns",   len(df_t.columns))
            dc3.metric("From",      str(df_t.index[0].date()))
            dc4.metric("To",        str(df_t.index[-1].date()))

            ind_t = calculate_indicators(df_t)
            st.write("**Calculated Indicators:**")
            ind_rows = [{"Indicator":k,"Value":str(round(v,4)) if isinstance(v,float) else str(v)}
                        for k,v in ind_t.items() if k!="errors"]
            st.dataframe(pd.DataFrame(ind_rows), use_container_width=True, hide_index=True)
            if ind_t["errors"]:
                for ei in ind_t["errors"]: st.warning(f"Indicator warning: {ei}")
            with st.expander("📋 Raw OHLCV (last 20 rows)"):
                st.dataframe(df_t.tail(20), use_container_width=True)

    st.divider()

    # Bulk validation
    st.subheader("🔍 Bulk Ticker Validation")
    st.caption("Tests all watchlist tickers. Run this first if the swing scan returns many errors.")

    if st.button("🧪 Validate All Watchlist Tickers", key="bulk_validate"):
        all_t = list(dict.fromkeys(
            ASX_WATCHLIST + INTL_WATCHLIST + COMMODITY_WATCHLIST +
            list(CORE_PORTFOLIO.keys()) + list(REGIME_TICKERS.values())
        ))
        val_results = []
        vprog = st.progress(0, text="Validating...")
        for i,t in enumerate(all_t):
            vprog.progress((i+1)/len(all_t), text=f"Testing {t}...")
            df_v, err_v = _fetch_raw(t,"3mo")
            if err_v:
                val_results.append({"Ticker":t,"Status":"❌ FAIL","Rows":0,
                                    "Latest Close":"—","RSI":"—","200MA":"—","Error":err_v})
            else:
                iv = calculate_indicators(df_v)
                val_results.append({
                    "Ticker":t,"Status":"✅ OK","Rows":len(df_v),
                    "Latest Close":f"${df_v['Close'].iloc[-1]:.3f}",
                    "RSI":   round(iv["rsi"],1) if iv["rsi"] else "N/A",
                    "200MA": "✅" if iv["ma_200"] else "⚠️ Need more data",
                    "Error": " | ".join(iv["errors"]) if iv["errors"] else "",
                })
        vprog.empty()
        vdf = pd.DataFrame(val_results)
        fail_n = (vdf["Status"]=="❌ FAIL").sum()
        ok_n   = (vdf["Status"]=="✅ OK").sum()
        st.write(f"**Results: {ok_n} OK | {fail_n} Failed** out of {len(all_t)} tickers")
        st.dataframe(vdf, use_container_width=True, hide_index=True)

    st.divider()

    # Session log
    st.subheader("📋 Session Activity Log")
    logc1, logc2 = st.columns([3,1])
    if logc2.button("🗑️ Clear Log"):
        st.session_state.debug_log = []
        st.rerun()
    if st.session_state.debug_log:
        ldf = pd.DataFrame(list(reversed(st.session_state.debug_log)))
        st.dataframe(ldf, use_container_width=True, hide_index=True)
    else:
        st.info("Log is empty. Run a scan, regime check, or core check to generate entries.")

    st.divider()

    # Session state inspector
    st.subheader("💾 Session State Inspector")
    with st.expander("View Session State Keys"):
        safe = {k:v for k,v in st.session_state.items()
                if k not in ("trade_ledger","last_scan_results","core_results","debug_log")}
        for k,v in safe.items():
            st.write(f"**{k}:** `{v}`")
        st.write(f"**trade_ledger rows:** {len(st.session_state.trade_ledger)}")
        st.write(f"**last_scan_results:** "
                 f"{len(st.session_state.last_scan_results)} items"
                 if st.session_state.last_scan_results else "**last_scan_results:** None")
        st.write(f"**core_results:** "
                 f"{list(st.session_state.core_results.keys())}"
                 if st.session_state.core_results else "**core_results:** None")

    st.divider()

    # Known issues guide
    st.subheader("⚠️ Common Issues & Fixes")
    issues = {
        "yfinance returns empty DataFrame": (
            "**Fix:** Check ticker format. ASX = `.AX` suffix (e.g. `PDN.AX`). "
            "US = plain symbol (`NVDA`). London = `.L` (`BAE.L`). Paris = `.PA` (`AIR.PA`). "
            "Verify on finance.yahoo.com."
        ),
        "200MA shows N/A": (
            "**Fix:** Need ≥200 trading days. The app uses `period='1y'` (~252 days). "
            "Newly listed stocks won't have 200MA — expected, noted in validation report."
        ),
        "RSI shows None/NaN": (
            "**Fix:** Need ≥15 bars. Use the Ticker Connection Test above to check data length."
        ),
        "Volume Ratio N/A": (
            "**Fix:** Some ETFs (QAU.AX, OOO.AX) report zero/NaN volume intermittently. "
            "Scan still runs but volume confirmation is missing. Cross-check on broker platform."
        ),
        "Timezone/index comparison errors": (
            "**Fix:** `_fetch_raw()` strips timezone with `tz_localize(None)`. "
            "If you still see errors, enable debug mode and inspect raw data."
        ),
        "Stale cached prices": (
            "**Fix:** Click '🗑️ Clear Data Cache' in the sidebar. "
            "The Debug Ticker Test always bypasses cache."
        ),
        "Trade ledger lost on refresh": (
            "**Fix:** Streamlit Cloud uses in-memory session state. "
            "Export CSV from sidebar after every session. Re-import at start of next session."
        ),
        "Streamlit Cloud deployment fails": (
            "**Fix:** Check the build log for the missing package. "
            "Ensure `requirements.txt` has exact versions. App requires Python ≥3.10."
        ),
        "BAE.L or AIR.PA returning no data": (
            "**Fix:** London/Paris tickers are intermittently unavailable via yfinance. "
            "If consistently failing, verify the exact symbol on finance.yahoo.com."
        ),
        "ASB.AX showing errors": (
            "**Fix:** ASB.AX (Austal) can have thin data. "
            "Try the Ticker Connection Test to check availability."
        ),
    }
    for issue, fix in issues.items():
        with st.expander(f"❓ {issue}"):
            st.markdown(fix)

# =============================================================================
# FOOTER
# =============================================================================

st.divider()
st.caption(
    "🎯 Yeppoon Strategic Command v2.0 | Data: yfinance (Yahoo Finance) | "
    "Cache: 15 min | Not financial advice — all decisions follow the Rulebook and your judgement. | "
    "SMSF compliance is your responsibility — export the ledger after every session."
)
