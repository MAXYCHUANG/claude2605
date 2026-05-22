#!/usr/bin/env python3
"""Generate US bond-market daily / weekly / monthly Markdown reports.

The pipeline uses:
- Vanguard BND as the bond ETF proxy
- Yahoo chart history for BND, QQQ, and SPY overlays
- FRED H.15 / spread series for the Treasury curve, real yields, and breakevens

Reports are written into docs/26US_BOND_doc so they can be archived and mailed
as Markdown attachments.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import statistics
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DOC_DIR = PROJECT_DIR / "docs" / "26US_BOND_doc"

FRED_SERIES = {
    "DGS2": "2Y nominal Treasury yield",
    "DGS10": "10Y nominal Treasury yield",
    "DGS30": "30Y nominal Treasury yield",
    "DGS3MO": "3M Treasury bill yield",
    "T10Y2Y": "10Y minus 2Y slope",
    "T10Y3M": "10Y minus 3M slope",
    "DFII10": "10Y real yield",
    "T10YIE": "10Y breakeven inflation",
    "T5YIE": "5Y breakeven inflation",
    "BAMLH0A0HYM2": "HY credit spread",
    "BAMLC0A0CM": "IG credit spread",
}

BOND_PROXY_SYMBOL = "BND"
EQUITY_OVERLAY_SYMBOLS = ("QQQ", "SPY")
YAHOO_RANGE = "1y"


@dataclass(frozen=True)
class Bar:
    date: dt.date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


@dataclass(frozen=True)
class ReportContext:
    mode: str
    anchor_date: dt.date
    window_start: dt.date
    window_end: dt.date


def fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url: str, timeout: int = 20) -> dict[str, Any]:
    return json.loads(fetch_text(url, timeout=timeout))


def fetch_fred_series(series: str) -> list[tuple[dt.date, float]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series)}"
    text = fetch_text(url)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    date_key = next((name for name in reader.fieldnames if name.lower() in {"date", "observation_date"}), None)
    value_key = next((name for name in reader.fieldnames if name != date_key), None)
    if not value_key:
        return []
    points: list[tuple[dt.date, float]] = []
    for row in reader:
        raw_date = row.get(date_key or "DATE")
        raw_value = row.get(value_key)
        if not raw_date or raw_value in {"", ".", None}:
            continue
        try:
            point_date = dt.date.fromisoformat(raw_date)
            point_value = float(raw_value)
        except ValueError:
            continue
        points.append((point_date, point_value))
    points.sort(key=lambda item: item[0])
    return points


def fetch_yahoo_history(symbol: str, range_: str = YAHOO_RANGE) -> list[Bar]:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(symbol, safe='')}?interval=1d&range={range_}&includePrePost=false"
    )
    data = fetch_json(url)
    result = data.get("chart", {}).get("result") or []
    if not result:
        return []
    payload = result[0]
    timestamps = payload.get("timestamp") or []
    quote = (payload.get("indicators", {}) or {}).get("quote") or []
    if not quote:
        return []
    quote = quote[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    bars: list[Bar] = []
    for idx, ts in enumerate(timestamps):
        close = closes[idx] if idx < len(closes) else None
        if close is None:
            continue
        bar_date = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
        bars.append(
            Bar(
                date=bar_date,
                open=(float(opens[idx]) if idx < len(opens) and opens[idx] is not None else None),
                high=(float(highs[idx]) if idx < len(highs) and highs[idx] is not None else None),
                low=(float(lows[idx]) if idx < len(lows) and lows[idx] is not None else None),
                close=float(close),
                volume=(float(volumes[idx]) if idx < len(volumes) and volumes[idx] is not None else None),
            )
        )
    bars.sort(key=lambda item: item.date)
    return bars


def fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "NA"
    return f"{value:.{digits}f}"


def fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "NA"
    return f"{value:+.{digits}f}%"


def fmt_bp(value: float | None, digits: int = 1) -> str:
    if value is None or not math.isfinite(value):
        return "NA"
    return f"{value * 100:+.{digits}f} bp"


def fmt_m(value: float | None, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "NA"
    return f"{value / 1_000_000:.{digits}f}M"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def get_series_value_on_or_before(series: list[tuple[dt.date, float]], target: dt.date) -> tuple[dt.date | None, float | None]:
    selected: tuple[dt.date, float] | None = None
    for date_value, value in series:
        if date_value <= target:
            selected = (date_value, value)
        else:
            break
    return selected if selected else (None, None)


def get_previous_value(series: list[tuple[dt.date, float]], target: dt.date) -> tuple[dt.date | None, float | None]:
    previous: tuple[dt.date, float] | None = None
    for date_value, value in series:
        if date_value < target:
            previous = (date_value, value)
        else:
            break
    return previous if previous else (None, None)


def get_bar_on_or_before(bars: list[Bar], target: dt.date) -> Bar | None:
    selected: Bar | None = None
    for bar in bars:
        if bar.date <= target:
            selected = bar
        else:
            break
    return selected


def get_previous_bar(bars: list[Bar], target: dt.date) -> Bar | None:
    previous: Bar | None = None
    for bar in bars:
        if bar.date < target:
            previous = bar
        else:
            break
    return previous


def last_n_bars(bars: list[Bar], n: int) -> list[Bar]:
    return bars[-n:] if len(bars) >= n else list(bars)


def latest_common_date(*series: list[Any]) -> dt.date:
    latest_dates: list[dt.date] = []
    for item in series:
        if not item:
            continue
        if isinstance(item[0], Bar):
            latest_dates.append(item[-1].date)
        else:
            latest_dates.append(item[-1][0])
    if not latest_dates:
        raise ValueError("No data available to determine report date")
    return min(latest_dates)


def bar_change_pct(current: Bar | None, previous: Bar | None) -> float | None:
    if current is None or previous is None or current.close is None or previous.close is None or previous.close == 0:
        return None
    return (current.close / previous.close - 1.0) * 100.0


def point_change(current: tuple[dt.date, float] | None, previous: tuple[dt.date, float] | None) -> float | None:
    if not current or not previous or previous[1] == 0:
        return None
    return (current[1] / previous[1] - 1.0) * 100.0


def yield_delta_text(snapshot: dict[str, float | None], series: str) -> str:
    current = snapshot.get(series)
    previous = snapshot.get(f"{series}_prev")
    if current is None or previous is None:
        return "NA"
    return fmt_bp(current - previous)


def build_context(mode: str, anchor_date: dt.date, bars: list[Bar]) -> ReportContext:
    if mode == "weekly":
        window = last_n_bars(bars, 5)
        return ReportContext(mode=mode, anchor_date=anchor_date, window_start=window[0].date, window_end=window[-1].date)
    if mode == "monthly":
        first_day = anchor_date.replace(day=1)
        month_bars = [bar for bar in bars if bar.date >= first_day and bar.date <= anchor_date]
        if not month_bars:
            month_bars = [bars[-1]]
        return ReportContext(mode=mode, anchor_date=anchor_date, window_start=month_bars[0].date, window_end=month_bars[-1].date)
    return ReportContext(mode=mode, anchor_date=anchor_date, window_start=anchor_date, window_end=anchor_date)


def score_regime(
    snapshot: dict[str, float | None],
    bnd_close: float | None,
    bnd_sma20: float | None,
    bnd_sma60: float | None,
    qqq_change: float | None,
    spy_change: float | None,
) -> tuple[int, str]:
    score = 0
    dgs10 = snapshot.get("DGS10")
    dgs30 = snapshot.get("DGS30")
    dgs2 = snapshot.get("DGS2")
    dgs3mo = snapshot.get("DGS3MO")
    t10y2y = snapshot.get("T10Y2Y")
    dfii10 = snapshot.get("DFII10")
    t10yie = snapshot.get("T10YIE")
    hy = snapshot.get("BAMLH0A0HYM2")

    if dgs10 is not None:
        if dgs10 >= 4.50:
            score += 2
        elif dgs10 >= 4.30:
            score += 1
    if dgs30 is not None and dgs30 >= 5.00:
        score += 1
    if dgs2 is not None and dgs2 >= 4.00:
        score += 1
    if dgs3mo is not None and dgs10 is not None and dgs10 - dgs3mo >= 0.90:
        score += 1
    if t10y2y is not None and t10y2y <= 0.40:
        score += 1
    if dfii10 is not None and dfii10 >= 2.00:
        score += 1
    if t10yie is not None and t10yie >= 2.30:
        score += 1
    if hy is not None and hy >= 4.75:
        score += 1
    if bnd_close is not None and bnd_sma20 is not None and bnd_close < bnd_sma20:
        score += 1
    if bnd_close is not None and bnd_sma60 is not None and bnd_close < bnd_sma60:
        score += 1
    if qqq_change is not None and qqq_change < -0.50:
        score += 1
    if spy_change is not None and spy_change < -0.30:
        score += 1

    if score <= 2:
        return score, "綠燈"
    if score <= 4:
        return score, "黃燈"
    if score <= 6:
        return score, "橘燈"
    return score, "紅燈"


def transmission_read(
    snapshot: dict[str, float | None],
    bnd_change: float | None,
    qqq_change: float | None,
    spy_change: float | None,
) -> str:
    dgs10_change = snapshot.get("DGS10_change")
    if bnd_change is not None and qqq_change is not None and spy_change is not None and dgs10_change is not None:
        if bnd_change < 0 and qqq_change < 0 and spy_change < 0 and dgs10_change >= 0:
            return "利率上行 + 債券走弱 + 成長股承壓：屬於折現率壓力主導。"
        if bnd_change > 0 and qqq_change > 0 and spy_change > 0 and dgs10_change <= 0:
            return "利率回落 + 債券轉強 + 成長股同步修復：屬於估值壓力緩和。"
        if bnd_change < 0 and (qqq_change > 0 or spy_change > 0) and dgs10_change >= 0:
            return "債券走弱但股票仍撐：屬於局部輪動或風險偏好暫時未同步。"
    return "變化混合，需觀察 10Y、BND、QQQ 與 SPY 是否在同一方向同步。"


def interpret_curve(snapshot: dict[str, float | None]) -> str:
    dgs10 = snapshot.get("DGS10")
    dgs2 = snapshot.get("DGS2")
    dgs30 = snapshot.get("DGS30")
    t10y2y = snapshot.get("T10Y2Y")
    t10y3m = snapshot.get("T10Y3M")
    dfii10 = snapshot.get("DFII10")
    t10yie = snapshot.get("T10YIE")

    parts = []
    if dgs10 is not None and dgs2 is not None:
        parts.append(f"2s10s = {dgs10 - dgs2:+.2f} pct pts")
    if dgs10 is not None and dgs30 is not None:
        parts.append(f"10s30s = {dgs30 - dgs10:+.2f} pct pts")
    if t10y2y is not None:
        parts.append(f"T10Y2Y = {t10y2y:+.2f}")
    if t10y3m is not None:
        parts.append(f"T10Y3M = {t10y3m:+.2f}")
    if dfii10 is not None:
        parts.append(f"10Y real yield = {dfii10:.2f}%")
    if t10yie is not None:
        parts.append(f"10Y breakeven = {t10yie:.2f}%")
    return "；".join(parts) if parts else "NA"


def build_snapshot(
    anchor_date: dt.date,
    fred_histories: dict[str, list[tuple[dt.date, float]]],
    bnd_bars: list[Bar],
    qqq_bars: list[Bar],
    spy_bars: list[Bar],
) -> dict[str, float | None]:
    snapshot: dict[str, float | None] = {}
    for series, history in fred_histories.items():
        _, value = get_series_value_on_or_before(history, anchor_date)
        snapshot[series] = value
        prev_date, prev_value = get_previous_value(history, anchor_date)
        snapshot[f"{series}_prev"] = prev_value
        snapshot[f"{series}_change"] = ((value / prev_value - 1.0) * 100.0) if value is not None and prev_value not in {None, 0} else None
        snapshot[f"{series}_prev_date"] = prev_date.toordinal() if prev_date else None
    bnd = get_bar_on_or_before(bnd_bars, anchor_date)
    bnd_prev = get_previous_bar(bnd_bars, anchor_date)
    qqq = get_bar_on_or_before(qqq_bars, anchor_date)
    qqq_prev = get_previous_bar(qqq_bars, anchor_date)
    spy = get_bar_on_or_before(spy_bars, anchor_date)
    spy_prev = get_previous_bar(spy_bars, anchor_date)
    snapshot["BND_close"] = bnd.close if bnd else None
    snapshot["BND_volume"] = bnd.volume if bnd else None
    snapshot["BND_change"] = bar_change_pct(bnd, bnd_prev)
    snapshot["BND_prev_close"] = bnd_prev.close if bnd_prev else None
    snapshot["QQQ_close"] = qqq.close if qqq else None
    snapshot["QQQ_volume"] = qqq.volume if qqq else None
    snapshot["QQQ_change"] = bar_change_pct(qqq, qqq_prev)
    snapshot["QQQ_prev_close"] = qqq_prev.close if qqq_prev else None
    snapshot["SPY_close"] = spy.close if spy else None
    snapshot["SPY_volume"] = spy.volume if spy else None
    snapshot["SPY_change"] = bar_change_pct(spy, spy_prev)
    snapshot["SPY_prev_close"] = spy_prev.close if spy_prev else None

    if bnd is not None:
        closes = [bar.close for bar in bnd_bars if bar.close is not None and bar.date <= anchor_date]
        closes = [value for value in closes if value is not None]
        snapshot["BND_SMA20"] = statistics.fmean(closes[-20:]) if len(closes) >= 20 else None
        snapshot["BND_SMA60"] = statistics.fmean(closes[-60:]) if len(closes) >= 60 else None
    else:
        snapshot["BND_SMA20"] = None
        snapshot["BND_SMA60"] = None
    return snapshot


def make_daily_report(ctx: ReportContext, snapshot: dict[str, float | None], gaps: list[str]) -> str:
    rows = [
        ["BND", fmt_num(snapshot.get("BND_close")), fmt_pct(snapshot.get("BND_change")), fmt_m(snapshot.get("BND_volume")), fmt_num(snapshot.get("BND_SMA20")), fmt_num(snapshot.get("BND_SMA60")), "債券 ETF 代理；下破均線代表久期壓力仍重"],
        ["QQQ", fmt_num(snapshot.get("QQQ_close")), fmt_pct(snapshot.get("QQQ_change")), fmt_m(snapshot.get("QQQ_volume")), "NA", "NA", "成長股估值壓力的股市側對照"],
        ["SPY", fmt_num(snapshot.get("SPY_close")), fmt_pct(snapshot.get("SPY_change")), fmt_m(snapshot.get("SPY_volume")), "NA", "NA", "廣泛市場風險偏好對照"],
        ["DGS2", fmt_num(snapshot.get("DGS2")), yield_delta_text(snapshot, "DGS2"), "NA", "NA", "NA", "短端政策預期"],
        ["DGS10", fmt_num(snapshot.get("DGS10")), yield_delta_text(snapshot, "DGS10"), "NA", "NA", "NA", "中期折現率錨"],
        ["DGS30", fmt_num(snapshot.get("DGS30")), yield_delta_text(snapshot, "DGS30"), "NA", "NA", "NA", "長端期限溢價"],
        ["DGS3MO", fmt_num(snapshot.get("DGS3MO")), yield_delta_text(snapshot, "DGS3MO"), "NA", "NA", "NA", "短券利率與現金替代"],
        ["T10Y2Y", fmt_num(snapshot.get("T10Y2Y")), yield_delta_text(snapshot, "T10Y2Y"), "NA", "NA", "NA", "曲線斜率"],
        ["T10Y3M", fmt_num(snapshot.get("T10Y3M")), yield_delta_text(snapshot, "T10Y3M"), "NA", "NA", "NA", "曲線前端壓力"],
        ["DFII10", fmt_num(snapshot.get("DFII10")), yield_delta_text(snapshot, "DFII10"), "NA", "NA", "NA", "10Y real yield"],
        ["T10YIE", fmt_num(snapshot.get("T10YIE")), yield_delta_text(snapshot, "T10YIE"), "NA", "NA", "NA", "10Y breakeven"],
        ["T5YIE", fmt_num(snapshot.get("T5YIE")), yield_delta_text(snapshot, "T5YIE"), "NA", "NA", "NA", "5Y breakeven"],
        ["BAMLH0A0HYM2", fmt_num(snapshot.get("BAMLH0A0HYM2")), yield_delta_text(snapshot, "BAMLH0A0HYM2"), "NA", "NA", "NA", "HY credit spread"],
        ["BAMLC0A0CM", fmt_num(snapshot.get("BAMLC0A0CM")), yield_delta_text(snapshot, "BAMLC0A0CM"), "NA", "NA", "NA", "IG credit spread"],
    ]

    score, label = score_regime(snapshot, snapshot.get("BND_close"), snapshot.get("BND_SMA20"), snapshot.get("BND_SMA60"), snapshot.get("QQQ_change"), snapshot.get("SPY_change"))
    body = [
        f"# US Bond Market Daily Report",
        "",
        f"- As of: `{ctx.anchor_date.isoformat()}`",
        f"- Window: `{ctx.window_start.isoformat()}` to `{ctx.window_end.isoformat()}`",
        f"- Risk level: **{label}** (`score={score}`)",
        "",
        "## 1. Executive Summary",
        f"- Bond-stock read: {transmission_read(snapshot, snapshot.get('BND_change'), snapshot.get('QQQ_change'), snapshot.get('SPY_change'))}",
        f"- Equity overlay read: QQQ `{fmt_pct(snapshot.get('QQQ_change'))}`, SPY `{fmt_pct(snapshot.get('SPY_change'))}`",
        f"- Curve read: {interpret_curve(snapshot)}",
        f"- BND vs moving averages: close `{fmt_num(snapshot.get('BND_close'))}` vs MA20 `{fmt_num(snapshot.get('BND_SMA20'))}` / MA60 `{fmt_num(snapshot.get('BND_SMA60'))}`",
        "",
        "## 2. Daily Dashboard",
        md_table(["指標", "最新值", "日變化", "成交量", "MA20", "MA60", "解讀"], rows),
        "",
        "## 3. Warning Notes",
        "- 10Y / 30Y 殖利率若維持在高檔，長久期股票的折現率壓力仍在。",
        "- BND 若連續跌破 MA20 / MA60，代表債券價格弱勢不是一天噪音，而是再定價。",
        "- QQQ / SPY 若與殖利率同向下跌，通常代表估值壓力與風險偏好降溫同時存在。",
        "",
        "## 4. Manual Checks",
        "- TreasuryDirect recent auction results: bid-to-cover, indirect bidder share, stop-out yield.",
        "- Treasury refunding / quarterly auction schedule.",
        "- TIC flows and Fed balance-sheet changes when monthly data are released.",
        "",
        "## 5. Data Gaps",
    ]
    if gaps:
        body.extend(f"- {gap}" for gap in gaps)
    else:
        body.append("- None")
    body.extend(
        [
            "",
            "## 6. Source Notes",
            "- BND: Yahoo Finance chart history, used as the broad bond ETF proxy.",
            "- Treasury curve: FRED H.15 series (`DGS2`, `DGS10`, `DGS30`, `DGS3MO`, `T10Y2Y`, `T10Y3M`).",
            "- Real rate / breakeven: FRED (`DFII10`, `T10YIE`, `T5YIE`).",
            "- Credit spread proxies: FRED (`BAMLH0A0HYM2`, `BAMLC0A0CM`) when available.",
        ]
    )
    return "\n".join(body) + "\n"


def make_weekly_report(
    ctx: ReportContext,
    snapshot: dict[str, float | None],
    bars: list[Bar],
    qqq_bars: list[Bar],
    spy_bars: list[Bar],
    gaps: list[str],
) -> str:
    window = [bar for bar in bars if ctx.window_start <= bar.date <= ctx.window_end]
    if not window:
        window = last_n_bars(bars, 5)
    rows = []
    for bar in window:
        prev = get_previous_bar(bars, bar.date)
        qqq_bar = get_bar_on_or_before(qqq_bars, bar.date)
        spy_bar = get_bar_on_or_before(spy_bars, bar.date)
        dgs10 = snapshot.get("DGS10")
        dgs2 = snapshot.get("DGS2")
        dgs30 = snapshot.get("DGS30")
        t10y2y = snapshot.get("T10Y2Y")
        rows.append(
            [
                bar.date.isoformat(),
                fmt_num(bar.close),
                fmt_pct(bar_change_pct(bar, prev)),
                fmt_m(bar.volume),
                fmt_num(qqq_bar.close if qqq_bar else None),
                fmt_num(spy_bar.close if spy_bar else None),
                fmt_num(dgs2),
                fmt_num(dgs10),
                fmt_num(dgs30),
                fmt_num(t10y2y),
            ]
        )

    start_bar = window[0]
    end_bar = window[-1]
    weekly_bnd_change = ((end_bar.close / start_bar.close - 1.0) * 100.0) if start_bar.close and end_bar.close else None
    weekly_bnd_volume = sum(bar.volume or 0 for bar in window) if window else None
    weekly_qqq_change = None
    if ctx.window_start <= ctx.window_end:
        qqq_window = [bar for bar in qqq_bars if ctx.window_start <= bar.date <= ctx.window_end]
        if qqq_window:
            weekly_qqq_change = ((qqq_window[-1].close / qqq_window[0].close - 1.0) * 100.0) if qqq_window[0].close and qqq_window[-1].close else None
    weekly_spy_change = None
    if ctx.window_start <= ctx.window_end:
        spy_window = [bar for bar in spy_bars if ctx.window_start <= bar.date <= ctx.window_end]
        if spy_window:
            weekly_spy_change = ((spy_window[-1].close / spy_window[0].close - 1.0) * 100.0) if spy_window[0].close and spy_window[-1].close else None

    score, label = score_regime(snapshot, snapshot.get("BND_close"), snapshot.get("BND_SMA20"), snapshot.get("BND_SMA60"), snapshot.get("QQQ_change"), snapshot.get("SPY_change"))
    body = [
        "# US Bond Market Weekly Report",
        "",
        f"- Period: `{ctx.window_start.isoformat()}` to `{ctx.window_end.isoformat()}`",
        f"- As of latest session: `{ctx.anchor_date.isoformat()}`",
        f"- Risk level: **{label}** (`score={score}`)",
        "",
        "## 1. Weekly Summary",
        f"- BND change over window: `{fmt_pct(weekly_bnd_change)}`",
        f"- QQQ change over window: `{fmt_pct(weekly_qqq_change)}`",
        f"- SPY change over window: `{fmt_pct(weekly_spy_change)}`",
        f"- BND total volume over window: `{fmt_m(weekly_bnd_volume)}`",
        f"- Curve read: {interpret_curve(snapshot)}",
        f"- Transmission read: {transmission_read(snapshot, snapshot.get('BND_change'), snapshot.get('QQQ_change'), snapshot.get('SPY_change'))}",
        "",
        "## 2. Daily Trail",
        md_table(["日期", "BND", "BND 日變化", "BND 量", "QQQ", "SPY", "DGS2", "DGS10", "DGS30", "T10Y2Y"], rows),
        "",
        "## 3. Week-to-Week Notes",
        "- 若 BND 仍低於 MA20 / MA60，代表債券端尚未完成修復，股市估值端仍受壓。",
        "- 若 10Y / 30Y 高位持續，成長股與長 duration 股票的反彈通常會比較脆。",
        "- 若曲線逐步變平而 real yield 未回落，通常不是寬鬆，而是高利率長尾。",
        "",
        "## 4. Manual Checks",
        "- TreasuryDirect recent auction results and upcoming auction schedule。",
        "- TIC / Fed / FOMC / CPI / PCE / payrolls before the next weekly summary。",
        "- If a Treasury refunding announcement lands during the week, mark it here.",
        "",
        "## 5. Data Gaps",
    ]
    if gaps:
        body.extend(f"- {gap}" for gap in gaps)
    else:
        body.append("- None")
    body.extend(
        [
            "",
            "## 6. Source Notes",
            "- Same source set as the daily report.",
        ]
    )
    return "\n".join(body) + "\n"


def make_monthly_report(
    ctx: ReportContext,
    snapshot: dict[str, float | None],
    bars: list[Bar],
    qqq_bars: list[Bar],
    spy_bars: list[Bar],
    gaps: list[str],
) -> str:
    month_bars = [bar for bar in bars if bar.date >= ctx.window_start and bar.date <= ctx.window_end]
    if not month_bars:
        month_bars = [bars[-1]]
    start_bar = month_bars[0]
    end_bar = month_bars[-1]
    monthly_bnd_change = ((end_bar.close / start_bar.close - 1.0) * 100.0) if start_bar.close and end_bar.close else None
    qqq_window = [bar for bar in qqq_bars if bar.date >= ctx.window_start and bar.date <= ctx.window_end]
    monthly_qqq_change = ((qqq_window[-1].close / qqq_window[0].close - 1.0) * 100.0) if len(qqq_window) >= 2 and qqq_window[0].close and qqq_window[-1].close else None
    spy_window = [bar for bar in spy_bars if bar.date >= ctx.window_start and bar.date <= ctx.window_end]
    monthly_spy_change = ((spy_window[-1].close / spy_window[0].close - 1.0) * 100.0) if len(spy_window) >= 2 and spy_window[0].close and spy_window[-1].close else None
    score, label = score_regime(snapshot, snapshot.get("BND_close"), snapshot.get("BND_SMA20"), snapshot.get("BND_SMA60"), snapshot.get("QQQ_change"), snapshot.get("SPY_change"))
    rows = []
    for bar in month_bars:
        prev = get_previous_bar(bars, bar.date)
        qqq_bar = get_bar_on_or_before(qqq_bars, bar.date)
        spy_bar = get_bar_on_or_before(spy_bars, bar.date)
        rows.append(
            [
                bar.date.isoformat(),
                fmt_num(bar.close),
                fmt_pct(bar_change_pct(bar, prev)),
                fmt_m(bar.volume),
                fmt_num(qqq_bar.close if qqq_bar else None),
                fmt_num(spy_bar.close if spy_bar else None),
            ]
        )

    body = [
        "# US Bond Market Monthly Report",
        "",
        f"- Period: `{ctx.window_start.isoformat()}` to `{ctx.window_end.isoformat()}`",
        f"- As of latest session: `{ctx.anchor_date.isoformat()}`",
        f"- Risk level: **{label}** (`score={score}`)",
        "",
        "## 1. Monthly Summary",
        f"- BND month-to-date change: `{fmt_pct(monthly_bnd_change)}`",
        f"- QQQ month-to-date change: `{fmt_pct(monthly_qqq_change)}`",
        f"- SPY month-to-date change: `{fmt_pct(monthly_spy_change)}`",
        f"- Curve read: {interpret_curve(snapshot)}",
        f"- Transmission read: {transmission_read(snapshot, snapshot.get('BND_change'), snapshot.get('QQQ_change'), snapshot.get('SPY_change'))}",
        "",
        "## 2. Month-to-Date Trail",
        md_table(["日期", "BND", "BND 日變化", "BND 量", "QQQ", "SPY"], rows),
        "",
        "## 3. Monthly Watchlist",
        "- CPI / PCE: confirm whether inflation is cooling enough for the long end to de-rate.",
        "- FOMC / Fed balance sheet: check whether policy expectations are still tight.",
        "- TIC / foreign demand: watch whether foreign buying is still cushioning duration supply.",
        "- Treasury refunding / supply calendar: supply pressure can reprice the long end even without macro surprises.",
        "- Credit spreads: if HY / IG spreads widen together with weak BND, the bond signal is more than duration repricing.",
        "",
        "## 4. Manual Checks",
        "- TreasuryDirect auction result quality (bid-to-cover, indirect share, stop-out yield).",
        "- Treasury quarterly refunding announcement and auction calendar.",
        "- Fed / BEA / BLS release calendar for the next month.",
        "",
        "## 5. Data Gaps",
    ]
    if gaps:
        body.extend(f"- {gap}" for gap in gaps)
    else:
        body.append("- None")
    body.extend(
        [
            "",
            "## 6. Source Notes",
            "- Same source set as the daily report.",
        ]
    )
    return "\n".join(body) + "\n"


def write_report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_data() -> tuple[dict[str, list[tuple[dt.date, float]]], list[Bar], list[Bar], list[Bar], list[str]]:
    fred_histories = {series: fetch_fred_series(series) for series in FRED_SERIES}
    bnd_bars = fetch_yahoo_history(BOND_PROXY_SYMBOL)
    qqq_bars = fetch_yahoo_history(EQUITY_OVERLAY_SYMBOLS[0])
    spy_bars = fetch_yahoo_history(EQUITY_OVERLAY_SYMBOLS[1])
    gaps: list[str] = []
    for series, history in fred_histories.items():
        if not history:
            gaps.append(f"FRED series missing: {series} ({FRED_SERIES[series]})")
    if not bnd_bars:
        gaps.append("BND Yahoo chart history missing")
    if not qqq_bars:
        gaps.append("QQQ Yahoo chart history missing")
    if not spy_bars:
        gaps.append("SPY Yahoo chart history missing")
    return fred_histories, bnd_bars, qqq_bars, spy_bars, gaps


def default_output_path(mode: str, ctx: ReportContext) -> Path:
    if mode == "daily":
        return DOC_DIR / f"cc_us_bond_daily_{ctx.anchor_date.isoformat()}.md"
    if mode == "weekly":
        return DOC_DIR / f"cc_us_bond_weekly_{ctx.window_start.isoformat()}_to_{ctx.window_end.isoformat()}.md"
    if mode == "monthly":
        return DOC_DIR / f"cc_us_bond_monthly_{ctx.anchor_date:%Y-%m}.md"
    raise ValueError(f"Unsupported mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "weekly", "monthly"), default="daily")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    fred_histories, bnd_bars, qqq_bars, spy_bars, gaps = load_data()
    anchor_date = latest_common_date(bnd_bars, qqq_bars, spy_bars, fred_histories["DGS10"], fred_histories["DGS2"], fred_histories["DGS30"], fred_histories["DGS3MO"])
    ctx = build_context(args.mode, anchor_date, bnd_bars)
    snapshot = build_snapshot(anchor_date, fred_histories, bnd_bars, qqq_bars, spy_bars)

    # Populate the manual spread comparisons that depend on the latest snapshot.
    if snapshot.get("DGS10") is not None and snapshot.get("DGS2") is not None:
        snapshot["2s10s"] = snapshot["DGS10"] - snapshot["DGS2"]
    if snapshot.get("DGS30") is not None and snapshot.get("DGS10") is not None:
        snapshot["10s30s"] = snapshot["DGS30"] - snapshot["DGS10"]
    if snapshot.get("DGS10") is not None and snapshot.get("DGS3MO") is not None:
        snapshot["T10Y3M"] = snapshot["DGS10"] - snapshot["DGS3MO"]

    if args.mode == "daily":
        report = make_daily_report(ctx, snapshot, gaps)
    elif args.mode == "weekly":
        report = make_weekly_report(ctx, snapshot, bnd_bars, qqq_bars, spy_bars, gaps)
    else:
        report = make_monthly_report(ctx, snapshot, bnd_bars, qqq_bars, spy_bars, gaps)

    output_path = args.output or default_output_path(args.mode, ctx)
    write_report(output_path, report)
    print(f"REPORT_PATH={output_path}")
    print(f"AS_OF_DATE={anchor_date.isoformat()}")
    print(f"MODE={args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
