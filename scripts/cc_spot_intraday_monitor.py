#!/usr/bin/env python3
"""
cc_spot_intraday_monitor.py

Fetch 1m OHLCV for NVDA, SMH, QQQ, SPY, analyze up to the specified window after market open.
Parses the latest static OC reports for NVDA, QQQ, SPY to extract G1, Max Pain, Call Wall, Put Wall.
Generates a combined HTML email showing the 3-Layer Spot + OC Alignment.

Usage:
  set -a && source .env.weather_email && set +a
  python3 scripts/cc_spot_intraday_monitor.py --window 30
"""

import argparse
import datetime
import json
import os
import smtplib
import sys
import re
import urllib.request
import glob
from datetime import timedelta
from email.message import EmailMessage

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
    _TPE = ZoneInfo("Asia/Taipei")
except ImportError:
    from datetime import timezone as _tz
    _ET = _tz(timedelta(hours=-4))
    _TPE = _tz(timedelta(hours=8))

# ── Constants ────────────────────────────────────────────────────────────────
SYMBOLS = ["NVDA", "QQQ", "SPY", "SMH"]
AVG_DAILY_VOL = {
    "NVDA": 250_000_000,
    "QQQ":   40_000_000,
    "SPY":   50_000_000,
    "SMH":    5_000_000,
}
EXPECTED_VOL_PCT = {5: 9, 15: 19, 30: 28, 90: 48, 150: 62}
MOMENTUM_THRESHOLD = {5: 0.4, 15: 0.7, 30: 0.9, 90: 1.3, 150: 1.8}

# ── OC Metadata Parsing ──────────────────────────────────────────────────────
def get_latest_oc_metadata(symbol: str) -> dict:
    if symbol == "SMH":
        return {} # User requested to skip SMH OC data

    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.abspath(os.path.join(script_dir, "..", "reports"))
    sym_lower = symbol.lower()
    report_dir = os.path.join(base_dir, f"{sym_lower}_options")
    
    if not os.path.exists(report_dir):
        return {}

    files = glob.glob(os.path.join(report_dir, f"{sym_lower}_options_4expiry_*.md"))
    if not files:
        return {}
    
    latest_file = sorted(files)[-1]
    
    metadata = {}
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            content = f.read()
            
            # Extract G1
            m_g1 = re.search(r"G1:\s+\$?(\d+(\.\d+)?)", content)
            if m_g1: metadata["G1"] = float(m_g1.group(1))
                
            # Extract Max Pain
            m_mp = re.search(r"Estimated max pain\s*\|\s*(\d+(\.\d+)?)", content)
            if m_mp: metadata["Max Pain"] = float(m_mp.group(1))
                
            # Extract Call Wall
            m_cw = re.search(r"Call wall by OI\s*\|\s*(\d+(\.\d+)?)", content)
            if m_cw: metadata["Call Wall"] = float(m_cw.group(1))
                
            # Extract Put Wall
            m_pw = re.search(r"Put wall by OI\s*\|\s*(\d+(\.\d+)?)", content)
            if m_pw: metadata["Put Wall"] = float(m_pw.group(1))
            
            metadata["_date"] = latest_file.split("_")[-1].replace(".md", "")
    except Exception as e:
        print(f"Failed to parse OC for {symbol}: {e}")
        
    return metadata

# ── Data fetch ───────────────────────────────────────────────────────────────
def _fetch_1m(symbol: str) -> dict:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?interval=1m&range=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def _parse_bars(data: dict) -> tuple:
    result  = data["chart"]["result"][0]
    meta    = result["meta"]
    ts      = result.get("timestamp", [])
    q       = result["indicators"]["quote"][0]
    closes  = q.get("close",  [])
    volumes = q.get("volume", [])
    highs   = q.get("high",   [])
    lows    = q.get("low",    [])
    opens_  = q.get("open",   [])

    bars = []
    for i, t in enumerate(ts):
        if i >= len(closes) or closes[i] is None:
            continue
        c = closes[i]
        bars.append({
            "dt":     datetime.datetime.fromtimestamp(t, tz=_ET),
            "open":   opens_[i]  if (i < len(opens_)  and opens_[i]  is not None) else c,
            "high":   highs[i]   if (i < len(highs)   and highs[i]   is not None) else c,
            "low":    lows[i]    if (i < len(lows)     and lows[i]    is not None) else c,
            "close":  c,
            "volume": (volumes[i] or 0) if i < len(volumes) else 0,
        })
    return meta, bars

def _vwap(bars: list) -> float:
    num = sum(b["close"] * b["volume"] for b in bars)
    den = sum(b["volume"] for b in bars)
    return num / den if den else 0.0

def _analyze(meta: dict, all_bars: list, window_min: int, symbol: str) -> dict:
    # Find first regular-session bar (09:30+ ET)
    open_idx = 0
    for i, b in enumerate(all_bars):
        if b["dt"].hour > 9 or (b["dt"].hour == 9 and b["dt"].minute >= 30):
            open_idx = i
            break

    open_bar  = all_bars[open_idx]
    open_dt   = open_bar["dt"]
    cutoff_dt = open_dt + timedelta(minutes=window_min)

    w = [b for b in all_bars[open_idx:] if b["dt"] <= cutoff_dt]
    if not w:
        w = all_bars[open_idx: open_idx + 1]

    price_open = open_bar["open"]
    price_prev = meta.get("previousClose") or 0.0
    price_w    = w[-1]["close"]
    high_w     = max(b["high"] for b in w)
    low_w      = min(b["low"]  for b in w)

    vol_w  = sum(b["volume"] for b in w)
    vwap_w = _vwap(w)

    up_vol   = sum(b["volume"] for b in w if b["close"] >= b["open"])
    down_vol = sum(b["volume"] for b in w if b["close"] <  b["open"])
    mf_in    = sum(b["close"] * b["volume"] for b in w if b["close"] >= b["open"])
    mf_out   = sum(b["close"] * b["volume"] for b in w if b["close"] <  b["open"])
    mf_net_m = (mf_in - mf_out) / 1_000_000

    actual_pct   = vol_w / AVG_DAILY_VOL.get(symbol, 250_000_000) * 100
    expected_pct = EXPECTED_VOL_PCT.get(window_min, 30)
    vol_pace     = actual_pct / expected_pct if expected_pct else 1.0

    if   vol_pace >= 1.5: pace_label = f"⚡ 極強量 ({vol_pace:.1f}x)"
    elif vol_pace >= 1.2: pace_label = f"🔥 強量 ({vol_pace:.1f}x)"
    elif vol_pace >= 0.8: pace_label = f"✅ 正常 ({vol_pace:.1f}x)"
    else:                 pace_label = f"📉 縮量 ({vol_pace:.1f}x)"

    sig_momentum = (price_w - price_open) / price_open * 100 if price_open else 0.0
    sig_vwap     = price_w - vwap_w
    threshold    = MOMENTUM_THRESHOLD.get(window_min, 1.0)

    def _dir(up_cond, dn_cond): return "⬆" if up_cond else ("⬇" if dn_cond else "↔")

    up_pct   = up_vol   / vol_w * 100 if vol_w else 0.0
    down_pct = down_vol / vol_w * 100 if vol_w else 0.0

    signals = [
        (_dir(sig_momentum >  threshold, sig_momentum < -threshold), f"動能: {sig_momentum:+.2f}%"),
        (_dir(sig_vwap >  0.15, sig_vwap < -0.15), f"VWAP: {'高於' if sig_vwap >= 0 else '低於'} VWAP"),
        (_dir(mf_net_m >  100, mf_net_m < -100), f"MF: {mf_net_m:+.0f}M (↑{up_pct:.1f}%)"),
    ]

    bull = sum(1 for s in signals if s[0] == "⬆")
    bear = sum(1 for s in signals if s[0] == "⬇")

    if   bull == 3: direction = "多方主導 ⬆"
    elif bear == 3: direction = "空方主導 ⬇"
    elif bull == 2: direction = "偏多 ⬆"
    elif bear == 2: direction = "偏弱 ⬇"
    else:           direction = "多空拉鋸 ↔"

    return {
        "symbol":        meta.get("symbol", symbol),
        "window":        window_min,
        "trade_date":    open_bar["dt"].strftime("%Y-%m-%d"),
        "snap_time":     w[-1]["dt"].strftime("%H:%M ET"),
        "price_w":       price_w,
        "price_open":    price_open,
        "price_prev":    price_prev,
        "chg_prev":      price_w - price_prev,
        "pct_prev":      (price_w - price_prev) / price_prev * 100 if price_prev else 0.0,
        "vol_w":         vol_w,
        "vol_pace":      vol_pace,
        "pace_label":    pace_label,
        "vwap_w":        vwap_w,
        "sig_vwap":      sig_vwap,
        "mf_net_m":      mf_net_m,
        "signals":       signals,
        "direction":     direction,
        "oc":            get_latest_oc_metadata(symbol)
    }

# ── HTML ─────────────────────────────────────────────────────────────────────
def _td(v, bold=False, color="#1e293b", bg="#ffffff", align="left", size="13px"):
    w = "font-weight:bold;" if bold else ""
    return (f'<td style="padding:4px 8px;border-bottom:1px solid #e2e8f0;'
            f'color:{color};background-color:{bg};text-align:{align};font-size:{size};{w}">{v}</td>')

def render_html(results: list, window: int) -> str:
    trade_date = results[0]["trade_date"]
    snap = results[0]["snap_time"]

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="utf-8"><title>3-Layer Spot Monitor {window}m</title></head>
<body style="font-family:Arial,sans-serif;background:#f1f5f9;margin:0;padding:16px;">
<div style="max-width:800px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
<div style="background:#0f172a;color:#e2e8f0;padding:12px 16px;">
  <span style="font-size:18px;font-weight:bold;">3-Layer Spot Monitor ({window}m)</span>
  <span style="font-size:12px;color:#94a3b8;margin-left:12px;">{trade_date} {snap}</span>
</div>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
"""

    for a in results:
        sym = a["symbol"]
        if "⬆" in a["direction"]: dc = "#dcfce7"; txt_c = "#16a34a"
        elif "⬇" in a["direction"]: dc = "#fee2e2"; txt_c = "#dc2626"
        else: dc = "#f3f4f6"; txt_c = "#4b5563"

        html += f"""
        <tr>
            <td colspan="4" style="background:{dc};padding:8px;font-weight:bold;color:{txt_c};border-top:2px solid #cbd5e1;">
                {sym} - ${a['price_w']:.2f} ({a['pct_prev']:+.2f}%) | {a['direction']} | {a['pace_label']}
            </td>
        </tr>
        <tr>
            {_td("VWAP", bold=True, color="#64748b")}
            {_td(f"${a['vwap_w']:.2f} ({'高' if a['sig_vwap']>=0 else '低'})")}
            {_td("MF / 動能", bold=True, color="#64748b")}
            {_td(f"{a['mf_net_m']:+.0f}M | {a['signals'][0][1]}")}
        </tr>
        """
        if a["oc"]:
            oc = a["oc"]
            # Visual line: PW --- Spot --- VWAP --- MP --- G1 --- CW
            # Simplify to text
            html += f"""
            <tr>
                {_td(f"OC ({oc.get('_date','')})", bold=True, color="#64748b")}
                <td colspan="3" style="padding:4px 8px;font-size:12px;color:#334155;border-bottom:1px solid #e2e8f0;">
                    <b>Put Wall:</b> ${oc.get('Put Wall', 0)} | 
                    <b>Max Pain:</b> ${oc.get('Max Pain', 0)} | 
                    <b>G1:</b> ${oc.get('G1', 0)} | 
                    <b>Call Wall:</b> ${oc.get('Call Wall', 0)}
                </td>
            </tr>
            """

    html += """
</table>
<div style="font-size:11px;color:#94a3b8;padding:8px;text-align:center;">cc_ 3-Layer Spot Monitor | claude2605</div>
</div></body></html>
"""
    return html

# ── Send ─────────────────────────────────────────────────────────────────────
def _send(subject: str, html: str, to_addr: str):
    host   = os.environ.get("WEATHER_SMTP_HOST")
    port   = int(os.environ.get("WEATHER_SMTP_PORT", "587"))
    user   = os.environ.get("WEATHER_SMTP_USER")
    passwd = os.environ.get("WEATHER_SMTP_PASSWORD")
    from_  = os.environ.get("WEATHER_MAIL_FROM", user)

    if not host or not user or not passwd:
        print("ERROR: SMTP credentials missing")
        return None

    if "@" not in to_addr:
        to_addr = to_addr + "@gmail.com"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = from_
    msg["To"]      = to_addr
    msg.set_content(subject)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, passwd)
        s.send_message(msg)

    return to_addr

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="3-Layer Spot Intraday Monitor")
    parser.add_argument("--window",   type=int,   choices=[5, 15, 30, 90, 150], default=30)
    parser.add_argument("--to",       default="yc5780")
    parser.add_argument("--dry-run",  action="store_true")
    args = parser.parse_args()

    results = []
    for sym in SYMBOLS:
        print(f"Fetching {sym}...")
        try:
            raw = _fetch_1m(sym)
            meta, bars = _parse_bars(raw)
            if bars:
                a = _analyze(meta, bars, args.window, sym)
                results.append(a)
        except Exception as e:
            print(f"ERROR: {sym} fetch failed: {e}")

    if not results:
        print("ERROR: No data fetched")
        sys.exit(1)

    html = render_html(results, args.window)
    nvda_res = next((r for r in results if r["symbol"] == "NVDA"), results[0])
    
    subject = (
        f"[3-Layer] NVDA {args.window}m"
        f" | ${nvda_res['price_w']:.2f} ({nvda_res['pct_prev']:+.2f}%)"
        f" | {nvda_res['direction']}"
    )

    if args.dry_run:
        print(f"SUBJECT: {subject}")
        print(html[:1000], "\n...[truncated]")
        print("DRY_RUN: email not sent")
        return

    print(f"Sending to {args.to} ...")
    _send(subject, html, args.to)
    print("Done")

if __name__ == "__main__":
    main()
