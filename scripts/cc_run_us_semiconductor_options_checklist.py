#!/usr/bin/env python3
"""Generate a semiconductor options/futures/PEG checklist report."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_DIR / "reports" / "us_semiconductor_options_checklist"

WATCHLIST = {
    "NVDA": "核心 AI call momentum",
    "TSM": "核心供應鏈高位避險",
    "SMH": "半導體 ETF 高位避險",
    "AMD": "Momentum + call exposure",
    "INTC": "高風險轉機 squeeze",
    "MU": "強基本面 + peak-cycle 疑慮",
}

CONTEXT_SYMBOLS = ["QQQ", "SOXX", "NQ=F", "ES=F", "^VIX"]
ETF_SYMBOLS = {"SMH", "QQQ", "SOXX"}


@dataclass
class Row:
    symbol: str
    role: str
    price: float | None = None
    change_pct: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    forward_pe: float | None = None
    trailing_pe: float | None = None
    peg: float | None = None
    beta: float | None = None
    peg_source: str | None = None
    expiry: str | None = None
    pcr_volume: float | None = None
    pcr_oi: float | None = None
    iv_mean: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    atm_skew: float | None = None
    warnings: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


def fetch_json(url: str, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None or not math.isfinite(value):
        return "NA"
    return f"{value:.{digits}f}{suffix}"


def ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def pct_from_high(price: float | None, high: float | None) -> float | None:
    if price is None or high is None or high <= 0:
        return None
    return (price / high - 1.0) * 100.0


def quote_url(symbols: list[str]) -> str:
    encoded = ",".join(urllib.parse.quote(s, safe="") for s in symbols)
    return f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={encoded}"


def get_quotes(symbols: list[str], dry_run: bool) -> dict[str, dict[str, Any]]:
    if dry_run:
        return sample_quotes()
    try:
        data = fetch_json(quote_url(symbols))
        results = data.get("quoteResponse", {}).get("result", [])
        quotes = {item.get("symbol"): item for item in results if item.get("symbol")}
    except Exception as exc:
        print(f"WARNING: Yahoo quote fetch failed, using Stooq fallback: {exc}", file=sys.stderr)
        quotes = {}
    quotes.update({k: v for k, v in get_stooq_quotes(symbols).items() if k not in quotes})
    return quotes


def get_stooq_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    symbol_map = {
        "NVDA": "nvda.us",
        "TSM": "tsm.us",
        "SMH": "smh.us",
        "AMD": "amd.us",
        "INTC": "intc.us",
        "MU": "mu.us",
        "QQQ": "qqq.us",
        "SOXX": "soxx.us",
    }
    quotes: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        stooq_symbol = symbol_map.get(symbol)
        if not stooq_symbol:
            continue
        url = f"https://stooq.com/q/l/?s={urllib.parse.quote(stooq_symbol)}&f=sd2t2ohlcv&h&e=csv"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8")
        except Exception as exc:
            print(f"WARNING: Stooq quote fetch failed for {symbol}: {exc}", file=sys.stderr)
            continue
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows or rows[0].get("Close") in {"N/D", None, ""}:
            continue
        item = rows[0]
        close = float(item["Close"])
        open_ = float(item["Open"]) if item.get("Open") not in {"N/D", None, ""} else None
        high = float(item["High"]) if item.get("High") not in {"N/D", None, ""} else None
        low = float(item["Low"]) if item.get("Low") not in {"N/D", None, ""} else None
        change_pct = ((close / open_ - 1.0) * 100.0) if open_ else None
        quotes[symbol] = {
            "symbol": symbol,
            "regularMarketPrice": close,
            "regularMarketChangePercent": change_pct,
            "dayHigh": high,
            "dayLow": low,
            "source": "Stooq",
        }
    return quotes


def option_url(symbol: str) -> str:
    return f"https://query2.finance.yahoo.com/v7/finance/options/{urllib.parse.quote(symbol, safe='')}"


def get_option_chain(symbol: str, dry_run: bool) -> dict[str, Any] | None:
    if dry_run:
        return sample_options(symbol)
    data = fetch_json(option_url(symbol))
    results = data.get("optionChain", {}).get("result", [])
    return results[0] if results else None


def fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def alphaquery_metric(symbol: str, period: str, identifier: str) -> tuple[float | None, str | None]:
    url = f"https://www.alphaquery.com/stock/{urllib.parse.quote(symbol)}/volatility-option-statistics/{period}/{identifier}"
    try:
        text = fetch_text(url)
    except Exception as exc:
        return None, f"AlphaQuery {identifier} fetch failed: {exc}"
    match = re.search(r"had\s+[^<]*?\s+of\s+<strong>([-+]?\d+(?:\.\d+)?)</strong>\s+for\s+<strong>(\d{4}-\d{2}-\d{2})</strong>", text)
    if not match:
        return None, f"AlphaQuery {identifier} value unavailable"
    return float(match.group(1)), None


def alphaquery_price(symbol: str) -> tuple[float | None, str | None]:
    url = f"https://www.alphaquery.com/stock/{urllib.parse.quote(symbol)}/volatility-option-statistics/30-day/iv-mean"
    try:
        text = fetch_text(url)
    except Exception as exc:
        return None, f"AlphaQuery price fetch failed: {exc}"
    match = re.search(r'Last Closing Price:\s*<span id="quote-price-container">([-+]?\d+(?:\.\d+)?)</span>', text)
    if not match:
        return None, "AlphaQuery price unavailable"
    return float(match.group(1)), None


def fill_alphaquery_options(row: Row) -> None:
    period = "30-day"
    pcr_oi, gap_oi = alphaquery_metric(row.symbol, period, "put-call-ratio-oi")
    pcr_volume, gap_vol = alphaquery_metric(row.symbol, period, "put-call-ratio-volume")
    iv_mean, gap_iv = alphaquery_metric(row.symbol, period, "iv-mean")
    if pcr_oi is not None:
        row.pcr_oi = pcr_oi
    if pcr_volume is not None:
        row.pcr_volume = pcr_volume
    if iv_mean is not None:
        row.iv_mean = iv_mean * 100.0 if iv_mean < 5 else iv_mean
    if row.pcr_oi is not None or row.pcr_volume is not None or row.iv_mean is not None:
        row.gaps = [
            gap
            for gap in row.gaps
            if gap != "options chain unavailable" and not gap.startswith("options fetch failed:")
        ]
        row.gaps.append("Yahoo strike-level options chain unavailable; AlphaQuery aggregate PCR/IV used")
        row.gaps.append("call wall / put wall unavailable without strike-level chain")
    for gap in (gap_oi, gap_vol, gap_iv):
        if gap:
            row.gaps.append(gap)
    if row.price is None:
        price, gap_price = alphaquery_price(row.symbol)
        if price is not None:
            row.price = price
        elif gap_price:
            row.gaps.append(gap_price)


def stats_url(symbol: str) -> str:
    modules = "defaultKeyStatistics,financialData,summaryDetail,earningsTrend"
    return f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(symbol, safe='')}?modules={modules}"


def get_stats(symbol: str, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return sample_stats().get(symbol, {})
    try:
        data = fetch_json(stats_url(symbol))
    except Exception:
        return {}
    results = data.get("quoteSummary", {}).get("result") or []
    return results[0] if results else {}


def raw_value(node: Any) -> float | None:
    if isinstance(node, dict):
        value = node.get("raw")
        return float(value) if isinstance(value, (int, float)) else None
    if isinstance(node, (int, float)):
        return float(node)
    return None


def fill_quote(row: Row, quote: dict[str, Any]) -> None:
    row.price = raw_value(quote.get("regularMarketPrice"))
    row.change_pct = raw_value(quote.get("regularMarketChangePercent"))
    row.week52_high = raw_value(quote.get("fiftyTwoWeekHigh"))
    row.week52_low = raw_value(quote.get("fiftyTwoWeekLow"))
    row.forward_pe = raw_value(quote.get("forwardPE"))
    row.trailing_pe = raw_value(quote.get("trailingPE"))
    row.beta = raw_value(quote.get("beta"))
    if row.price is None:
        row.gaps.append("price unavailable")


def fill_stats(row: Row, stats: dict[str, Any]) -> None:
    default = stats.get("defaultKeyStatistics", {})
    financial = stats.get("financialData", {})
    summary = stats.get("summaryDetail", {})
    earnings_trend = stats.get("earningsTrend", {})
    row.peg = raw_value(default.get("pegRatio"))
    row.forward_pe = row.forward_pe or raw_value(summary.get("forwardPE")) or raw_value(default.get("forwardPE"))
    row.trailing_pe = row.trailing_pe or raw_value(summary.get("trailingPE"))
    row.beta = row.beta or raw_value(summary.get("beta"))
    if row.forward_pe is None:
        row.forward_pe = raw_value(financial.get("forwardPE"))
    if row.peg is None:
        fallback_growth = fallback_growth_rate(earnings_trend)
        if fallback_growth is not None and fallback_growth > 0 and row.forward_pe is not None:
            row.peg = row.forward_pe / fallback_growth
            row.peg_source = "forward PE / Yahoo earningsTrend growth"


def nearest_atm_pair(calls: list[dict[str, Any]], puts: list[dict[str, Any]], price: float | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if price is None:
        return None, None
    call_by_strike = {raw_value(c.get("strike")): c for c in calls}
    put_by_strike = {raw_value(p.get("strike")): p for p in puts}
    common = [s for s in call_by_strike.keys() & put_by_strike.keys() if s is not None]
    if not common:
        return None, None
    strike = min(common, key=lambda value: abs(value - price))
    return call_by_strike[strike], put_by_strike[strike]


def fill_options(row: Row, chain: dict[str, Any] | None) -> None:
    if not chain:
        row.gaps.append("options chain unavailable")
        return
    options = chain.get("options") or []
    if not options:
        row.gaps.append("options chain empty")
        return
    expiry_ts = options[0].get("expirationDate")
    if isinstance(expiry_ts, int):
        row.expiry = dt.datetime.fromtimestamp(expiry_ts, tz=dt.timezone.utc).date().isoformat()
    calls = options[0].get("calls") or []
    puts = options[0].get("puts") or []
    if not calls or not puts:
        row.gaps.append("calls or puts unavailable")
        return

    call_vol = sum(raw_value(c.get("volume")) or 0 for c in calls)
    put_vol = sum(raw_value(p.get("volume")) or 0 for p in puts)
    call_oi = sum(raw_value(c.get("openInterest")) or 0 for c in calls)
    put_oi = sum(raw_value(p.get("openInterest")) or 0 for p in puts)
    ivs = [raw_value(item.get("impliedVolatility")) for item in calls + puts]
    ivs = [value for value in ivs if value is not None and value > 0]

    row.pcr_volume = ratio(put_vol, call_vol)
    row.pcr_oi = ratio(put_oi, call_oi)
    row.iv_mean = (sum(ivs) / len(ivs) * 100.0) if ivs else None

    row.call_wall = max(calls, key=lambda c: raw_value(c.get("openInterest")) or 0).get("strike")
    row.put_wall = max(puts, key=lambda p: raw_value(p.get("openInterest")) or 0).get("strike")
    row.call_wall = raw_value(row.call_wall)
    row.put_wall = raw_value(row.put_wall)

    atm_call, atm_put = nearest_atm_pair(calls, puts, row.price)
    if atm_call and atm_put:
        call_iv = raw_value(atm_call.get("impliedVolatility"))
        put_iv = raw_value(atm_put.get("impliedVolatility"))
        if call_iv is not None and put_iv is not None:
            row.atm_skew = (put_iv - call_iv) * 100.0


def add_warning(row: Row, condition: bool, text: str) -> None:
    if condition:
        row.warnings.append(text)


def evaluate(row: Row) -> None:
    near_high = pct_from_high(row.price, row.week52_high)
    is_etf = row.symbol in ETF_SYMBOLS
    high_iv_level = 45.0 if is_etf else 60.0

    add_warning(row, row.iv_mean is not None and row.iv_mean >= 80.0, "警示：IV >= 80%，市場定價極高波動")
    add_warning(row, row.iv_mean is not None and high_iv_level <= row.iv_mean < 80.0, f"警示：IV >= {high_iv_level:.0f}%，波動偏高")
    add_warning(row, row.pcr_volume is not None and row.pcr_volume > 1.5, "警示：PCR volume > 1.5，短線 put demand 明顯")
    add_warning(row, row.pcr_oi is not None and row.pcr_oi > 1.5, "警示：PCR OI > 1.5，存量避險或 bearish 部位偏重")
    add_warning(
        row,
        row.pcr_volume is not None and row.pcr_oi is not None and row.pcr_volume < 0.5 and row.pcr_oi < 0.7,
        "警示：call crowding，追漲部位擁擠",
    )
    add_warning(
        row,
        near_high is not None and near_high >= -5.0 and row.pcr_oi is not None and row.pcr_oi > 1.0,
        "警示：接近 52 週高且 PCR OI > 1，高位避險累積",
    )
    add_warning(row, row.forward_pe is not None and row.forward_pe > 60.0, "警示：Forward P/E > 60，估值兌現壓力高")
    add_warning(
        row,
        row.peg is not None and row.iv_mean is not None and row.peg < 0.5 and row.iv_mean > 60.0,
        "警示：PEG 極低但 IV 很高，可能是 peak earnings / 週期高峰疑慮",
    )
    if row.peg is None:
        row.gaps.append("PEG unavailable")
    elif row.peg_source:
        row.gaps.append(f"PEG fallback used: {row.peg_source}")


def fallback_growth_rate(earnings_trend: dict[str, Any]) -> float | None:
    trends = earnings_trend.get("trend") or []
    if not isinstance(trends, list):
        return None
    preferred_periods = ("0y", "+1y", "currentYear", "nextYear")
    candidates: list[float] = []
    for item in trends:
        if not isinstance(item, dict):
            continue
        period = str(item.get("period") or "")
        growth = raw_value(item.get("growth"))
        if growth is None or growth <= 0:
            continue
        if growth <= 1.0:
            growth *= 100.0
        if period in preferred_periods:
            return growth
        candidates.append(growth)
    return candidates[0] if candidates else None


def context_warnings(quotes: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    qqq = raw_value(quotes.get("QQQ", {}).get("regularMarketChangePercent"))
    soxx = raw_value(quotes.get("SOXX", {}).get("regularMarketChangePercent"))
    nq = raw_value(quotes.get("NQ=F", {}).get("regularMarketChangePercent"))
    vix = raw_value(quotes.get("^VIX", {}).get("regularMarketChangePercent"))
    if qqq is not None and soxx is not None and soxx < qqq - 1.0:
        warnings.append("警示：SOXX 明顯弱於 QQQ，半導體 beta 轉弱")
    if nq is not None and nq < -1.5:
        warnings.append("警示：NQ futures 下跌超過 1.5%，科技股 beta 壓力升高")
    if vix is not None and vix > 8.0:
        warnings.append("警示：VIX 單日上升超過 8%，volatility market 預警")
    return warnings


def risk_level(rows: list[Row], market_warnings: list[str]) -> str:
    score = len(market_warnings) + sum(len(row.warnings) for row in rows)
    if score >= 12:
        return "紅"
    if score >= 7:
        return "橘"
    if score >= 3:
        return "黃"
    return "綠"


def row_table(rows: list[Row]) -> str:
    lines = [
        "| 標的 | 型態 | 價格 | 距 52 週高 | PCR Vol | PCR OI | IV mean | Call wall | Put wall | Fwd PE | PEG | 警示 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        near_high = pct_from_high(row.price, row.week52_high)
        warnings = "<br>".join(row.warnings) if row.warnings else ""
        lines.append(
            "| {symbol} | {role} | {price} | {near_high} | {pcrv} | {pcroi} | {iv} | {call_wall} | {put_wall} | {fpe} | {peg} | {warnings} |".format(
                symbol=row.symbol,
                role=row.role,
                price=fmt(row.price),
                near_high=fmt(near_high, 1, "%"),
                pcrv=fmt(row.pcr_volume, 3),
                pcroi=fmt(row.pcr_oi, 3),
                iv=fmt(row.iv_mean, 1, "%"),
                call_wall=fmt(row.call_wall, 2),
                put_wall=fmt(row.put_wall, 2),
                fpe=fmt(row.forward_pe, 1),
                peg=fmt(row.peg, 2),
                warnings=warnings,
            )
        )
    return "\n".join(lines)


def context_table(quotes: dict[str, dict[str, Any]]) -> str:
    lines = [
        "| 標的 | 價格 | 日變化 | 52 週高 | 資料源 |",
        "|---|---:|---:|---:|---|",
    ]
    for symbol in CONTEXT_SYMBOLS:
        quote = quotes.get(symbol, {})
        lines.append(
            f"| {symbol} | {fmt(raw_value(quote.get('regularMarketPrice')))} | {fmt(raw_value(quote.get('regularMarketChangePercent')), 2, '%')} | {fmt(raw_value(quote.get('fiftyTwoWeekHigh')))} | {quote.get('source', 'Yahoo')} |"
        )
    return "\n".join(lines)


def render_report(rows: list[Row], quotes: dict[str, dict[str, Any]], market_warnings: list[str], run_date: str, dry_run: bool) -> str:
    gaps = []
    for row in rows:
        for gap in row.gaps:
            gaps.append(f"- {row.symbol}: {gap}")
    if not gaps:
        gaps.append("- 無重大資料缺口。")

    warning_lines = market_warnings[:]
    for row in rows:
        for warning in row.warnings:
            warning_lines.append(f"- {row.symbol}: {warning}")
    if not warning_lines:
        warning_lines = ["- 無重大警示。"]

    return f"""# 美股半導體 Options / Futures / PEG Checklist

執行日期：{run_date}  
資料模式：{"DRY_RUN sample data" if dry_run else "live fetch"}  
總燈號：{risk_level(rows, market_warnings)}

## 1. 一句話總評

本報告用 PCR、IV、call/put wall、PEG、forward PE、NQ / ES futures、QQQ / SOXX 與 VIX 檢查半導體高位多頭是否出現擁擠、避險或估值兌現壓力。

## 2. 個股 Checklist

{row_table(rows)}

## 3. Futures / ETF Context

{context_table(quotes)}

## 4. 警示

{chr(10).join(warning_lines)}

## 5. 資料缺口

{chr(10).join(gaps)}

## 6. 人工確認清單

- [ ] 若任一標的 IV >= 80%，確認是否有財報、產品發表、政策或訴訟事件。
- [ ] 若 PCR volume > 1.5，檢查是否為保護性 put、bearish spread，或單日雜訊。
- [ ] 若 PCR volume < 0.5 且 PCR OI < 0.7，檢查是否為 call crowding 與 gamma squeeze。
- [ ] 若 PEG < 0.5 且 IV 很高，確認是否為 memory / cyclical peak earnings。
- [ ] 若 SOXX 弱於 QQQ，檢查 SMH / SOX 是否跌破近期支撐。

## 7. 參考框架

- docs/us_semiconductor_options_futures_peg_playbook.md
- docs/us_stock_capital_flows_ai_ipo_macro_summary_2026-05-07.md
- docs/meta_peg_ai_saas_adjustment_summary.md
"""


def sample_quotes() -> dict[str, dict[str, Any]]:
    values = {
        "NVDA": (214.0, 1.2, 219.0, 92.0, 42.0, 49.0, 1.6),
        "TSM": (332.0, -0.3, 340.0, 155.0, 28.0, 31.0, 1.2),
        "SMH": (540.1, 0.7, 549.9, 210.0, 51.0, 52.0, 1.7),
        "AMD": (405.0, 3.8, 412.0, 130.0, 47.0, 56.0, 1.9),
        "INTC": (109.5, 5.0, 112.0, 19.0, 108.0, None, 1.4),
        "MU": (643.0, 4.5, 650.0, 98.0, 6.2, 22.0, 1.5),
        "QQQ": (650.0, 0.5, 655.0, 390.0, None, None, 1.0),
        "SOXX": (410.0, 0.1, 418.0, 170.0, None, None, 1.5),
        "NQ=F": (23500.0, 0.4, 23650.0, 16000.0, None, None, None),
        "ES=F": (7100.0, 0.2, 7150.0, 4800.0, None, None, None),
        "^VIX": (18.0, 3.2, 38.0, 10.0, None, None, None),
    }
    return {
        symbol: {
            "symbol": symbol,
            "regularMarketPrice": price,
            "regularMarketChangePercent": change,
            "fiftyTwoWeekHigh": high,
            "fiftyTwoWeekLow": low,
            "forwardPE": fpe,
            "trailingPE": tpe,
            "beta": beta,
        }
        for symbol, (price, change, high, low, fpe, tpe, beta) in values.items()
    }


def sample_stats() -> dict[str, dict[str, Any]]:
    pegs = {"NVDA": 1.2, "TSM": 1.1, "SMH": None, "AMD": 1.4, "INTC": 1.54, "MU": 0.04}
    return {symbol: {"defaultKeyStatistics": {"pegRatio": value}} for symbol, value in pegs.items()}


def option_item(strike: float, oi: int, volume: int, iv: float) -> dict[str, Any]:
    return {"strike": strike, "openInterest": oi, "volume": volume, "impliedVolatility": iv}


def sample_options(symbol: str) -> dict[str, Any]:
    profile = {
        "NVDA": (220, 180000, 120000, 55000, 18000, 0.46),
        "TSM": (335, 70000, 45000, 125000, 56500, 0.45),
        "SMH": (545, 40000, 30000, 51000, 41000, 0.43),
        "AMD": (410, 95000, 86000, 76000, 87000, 0.66),
        "INTC": (110, 50000, 42000, 85000, 76500, 0.84),
        "MU": (650, 62000, 65000, 75500, 55000, 0.81),
    }.get(symbol, (100, 100, 100, 100, 100, 0.4))
    strike, call_oi, call_vol, put_oi, put_vol, iv = profile
    calls = [
        option_item(strike - 10, call_oi // 4, call_vol // 4, iv * 0.95),
        option_item(strike, call_oi, call_vol, iv),
        option_item(strike + 10, call_oi * 2, call_vol // 2, iv * 1.05),
    ]
    puts = [
        option_item(strike - 10, put_oi * 2, put_vol // 2, iv * 1.08),
        option_item(strike, put_oi, put_vol, iv * 1.02),
        option_item(strike + 10, put_oi // 4, put_vol // 4, iv * 0.97),
    ]
    expiry = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)).timestamp())
    return {"options": [{"expirationDate": expiry, "calls": calls, "puts": puts}]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_date = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    output = args.output or REPORT_DIR / f"cc_us_semiconductor_options_checklist_{run_date}.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    all_symbols = list(WATCHLIST) + CONTEXT_SYMBOLS
    try:
        quotes = get_quotes(all_symbols, args.dry_run)
    except Exception as exc:
        print(f"WARNING: quote fetch failed: {exc}", file=sys.stderr)
        quotes = {}

    rows: list[Row] = []
    for symbol, role in WATCHLIST.items():
        row = Row(symbol=symbol, role=role)
        fill_quote(row, quotes.get(symbol, {}))
        fill_stats(row, get_stats(symbol, args.dry_run))
        try:
            chain = get_option_chain(symbol, args.dry_run)
        except Exception as exc:
            row.gaps.append(f"options fetch failed: {exc}")
            chain = None
        fill_options(row, chain)
        if not args.dry_run and (row.pcr_volume is None or row.pcr_oi is None or row.iv_mean is None):
            fill_alphaquery_options(row)
        evaluate(row)
        rows.append(row)

    market_warnings = context_warnings(quotes)
    report = render_report(rows, quotes, market_warnings, run_date, args.dry_run)
    output.write_text(report, encoding="utf-8")
    print(f"REPORT_PATH={output.resolve()}")
    print(f"RISK_LEVEL={risk_level(rows, market_warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
