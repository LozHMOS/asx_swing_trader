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
            "price_change_pct": round(ind["
