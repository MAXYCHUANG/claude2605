#!/usr/bin/env python3
"""US Bond MCP Server — stdio transport.

Exposes FRED / Yahoo Finance US-bond market data as MCP tools for Claude Code.
Runs under .venv-fubon (has mcp; us-bond script itself uses only stdlib).

Tools:
  get_fred_series       — 單一 FRED 系列最新 N 筆資料
  get_yield_curve       — 完整殖利率曲線快照（所有追蹤系列）
  get_yahoo_history     — Yahoo Finance OHLCV K 棒
  get_bond_regime_score — 風險評分 + 殖利率曲線解讀
  get_us_bond_report    — 讀取本機美債報告 Markdown
  run_us_bond_report    — 執行美債報告 pipeline（daily/weekly/monthly）

Usage (stdio, registered in .mcp.json):
  .venv-fubon/bin/python3 scripts/cc_us_bond_mcp_server.py
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
DOC_DIR = PROJECT_DIR / "docs" / "26US_BOND_doc"

mcp = FastMCP("us-bond")

# ---------------------------------------------------------------------------
# Import helper functions from cc_run_us_bond_tracking.py
# ---------------------------------------------------------------------------

def _load_bond_module():
    spec = importlib.util.spec_from_file_location(
        "cc_run_us_bond_tracking",
        SCRIPTS_DIR / "cc_run_us_bond_tracking.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod  # dataclass decorator needs this
    spec.loader.exec_module(mod)
    return mod

_bond = _load_bond_module()

FRED_SERIES: dict[str, str] = _bond.FRED_SERIES


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_fred_series(series: str, limit: int = 20) -> str:
    """取得單一 FRED 系列的最新 N 筆資料。

    series: FRED 系列代碼，例如 "DGS10"、"T10Y2Y"、"BAMLH0A0HYM2"
            可用系列：DGS2, DGS10, DGS30, DGS3MO, T10Y2Y, T10Y3M,
                      DFII10, T10YIE, T5YIE, BAMLH0A0HYM2, BAMLC0A0CM
    limit: 回傳筆數（從最新往回算），預設 20
    回傳 JSON：{series, description, data: [{date, value}]}
    """
    try:
        history = _bond.fetch_fred_series(series)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    if not history:
        return json.dumps({"error": f"No data for series: {series}"}, ensure_ascii=False)

    tail = history[-limit:]
    return json.dumps({
        "series": series,
        "description": FRED_SERIES.get(series, series),
        "latest_date": tail[-1][0].isoformat() if tail else None,
        "latest_value": tail[-1][1] if tail else None,
        "data": [{"date": d.isoformat(), "value": v} for d, v in tail],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_yield_curve(date: str | None = None) -> str:
    """取得完整殖利率曲線快照（所有 FRED 追蹤系列的最新值）。

    date: "YYYY-MM-DD"，省略時使用各系列最新可用資料
    回傳 JSON：
      {anchor_date, yields: {DGS2, DGS10, DGS30, DGS3MO},
       spreads: {T10Y2Y, T10Y3M},
       real_inflation: {DFII10, T10YIE, T5YIE},
       credit: {BAMLH0A0HYM2, BAMLC0A0CM},
       curve_summary: str}
    """
    try:
        fred_histories = {s: _bond.fetch_fred_series(s) for s in FRED_SERIES}
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    # 決定 anchor date
    if date:
        try:
            anchor = dt.date.fromisoformat(date)
        except ValueError:
            return json.dumps({"error": f"Invalid date: {date}"}, ensure_ascii=False)
    else:
        # 找所有有資料的系列中最新的共同日期
        dates = []
        for h in fred_histories.values():
            if h:
                dates.append(h[-1][0])
        anchor = min(dates) if dates else dt.date.today()

    # 建立 snapshot
    dummy_bars: list = []
    snapshot = _bond.build_snapshot(anchor, fred_histories, dummy_bars, dummy_bars, dummy_bars)

    def _pick(keys: list[str]) -> dict[str, Any]:
        return {k: snapshot.get(k) for k in keys if k in snapshot}

    curve_summary = _bond.interpret_curve(snapshot)

    return json.dumps({
        "anchor_date": anchor.isoformat(),
        "yields": _pick(["DGS3MO", "DGS2", "DGS10", "DGS30"]),
        "spreads": _pick(["T10Y2Y", "T10Y3M"]),
        "real_inflation": _pick(["DFII10", "T10YIE", "T5YIE"]),
        "credit": _pick(["BAMLH0A0HYM2", "BAMLC0A0CM"]),
        "curve_summary": curve_summary,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_yahoo_history(symbol: str, range_: str = "3mo") -> str:
    """取得 Yahoo Finance OHLCV 日 K 棒。

    symbol: 代號，例如 "BND"、"QQQ"、"SPY"、"TLT"、"HYG"
    range_: 時間範圍，例如 "1d"、"5d"、"1mo"、"3mo"、"6mo"、"1y"、"2y"
    回傳 JSON：{symbol, range, bars: [{date, open, high, low, close, volume}]}
    """
    try:
        bars = _bond.fetch_yahoo_history(symbol, range_)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    if not bars:
        return json.dumps({"error": f"No data for symbol: {symbol}"}, ensure_ascii=False)

    return json.dumps({
        "symbol": symbol,
        "range": range_,
        "count": len(bars),
        "latest_date": bars[-1].date.isoformat(),
        "latest_close": bars[-1].close,
        "bars": [
            {
                "date": b.date.isoformat(),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_bond_regime_score(date: str | None = None) -> str:
    """計算當前美債市場風險評分與殖利率曲線解讀。

    date: "YYYY-MM-DD"，省略時使用各系列最新可用日期
    回傳 JSON：
      {anchor_date, score, label, curve_summary,
       bnd: {close, sma20, sma60, vs_sma20_pct, vs_sma60_pct},
       qqq_change_pct, spy_change_pct,
       snapshot: {DGS10, DGS2, T10Y2Y, ...}}
    評分規則：0-3 低風險 / 4-6 中風險 / 7-10 高風險 / 11+ 極高風險
    """
    try:
        fred_histories, bnd_bars, qqq_bars, spy_bars, gaps = _bond.load_data()
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    if date:
        try:
            anchor = dt.date.fromisoformat(date)
        except ValueError:
            return json.dumps({"error": f"Invalid date: {date}"}, ensure_ascii=False)
    else:
        anchor = _bond.latest_common_date(
            fred_histories.get("DGS10", []),
            bnd_bars,
        )

    snapshot = _bond.build_snapshot(anchor, fred_histories, bnd_bars, qqq_bars, spy_bars)

    bnd = _bond.get_bar_on_or_before(bnd_bars, anchor)
    bnd_sma20_bars = _bond.last_n_bars(bnd_bars, 20)
    bnd_sma60_bars = _bond.last_n_bars(bnd_bars, 60)
    bnd_sma20 = (sum(b.close for b in bnd_sma20_bars if b.close) / len(bnd_sma20_bars)) if bnd_sma20_bars else None
    bnd_sma60 = (sum(b.close for b in bnd_sma60_bars if b.close) / len(bnd_sma60_bars)) if bnd_sma60_bars else None

    qqq = _bond.get_bar_on_or_before(qqq_bars, anchor)
    qqq_prev = _bond.get_previous_bar(qqq_bars, anchor)
    spy = _bond.get_bar_on_or_before(spy_bars, anchor)
    spy_prev = _bond.get_previous_bar(spy_bars, anchor)

    qqq_chg = _bond.bar_change_pct(qqq, qqq_prev)
    spy_chg = _bond.bar_change_pct(spy, spy_prev)

    score, label = _bond.score_regime(
        snapshot,
        bnd.close if bnd else None,
        bnd_sma20,
        bnd_sma60,
        qqq_chg,
        spy_chg,
    )

    curve_summary = _bond.interpret_curve(snapshot)

    bnd_close = bnd.close if bnd else None
    return json.dumps({
        "anchor_date": anchor.isoformat(),
        "score": score,
        "label": label,
        "curve_summary": curve_summary,
        "bnd": {
            "close": bnd_close,
            "sma20": round(bnd_sma20, 4) if bnd_sma20 else None,
            "sma60": round(bnd_sma60, 4) if bnd_sma60 else None,
            "vs_sma20_pct": round((bnd_close / bnd_sma20 - 1) * 100, 2) if bnd_close and bnd_sma20 else None,
            "vs_sma60_pct": round((bnd_close / bnd_sma60 - 1) * 100, 2) if bnd_close and bnd_sma60 else None,
        },
        "qqq_change_pct": round(qqq_chg, 4) if qqq_chg is not None else None,
        "spy_change_pct": round(spy_chg, 4) if spy_chg is not None else None,
        "snapshot": {k: snapshot.get(k) for k in FRED_SERIES if k in snapshot},
        "data_gaps": gaps,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_us_bond_report(mode: str = "daily", date: str | None = None) -> str:
    """讀取本機美債報告 Markdown（不需網路）。

    mode: "daily"、"weekly" 或 "monthly"
    date: "YYYY-MM-DD"，省略時取該 mode 最新一份報告
    回傳報告的 Markdown 文字內容
    """
    if not DOC_DIR.exists():
        return json.dumps({"error": f"Report directory not found: {DOC_DIR}"}, ensure_ascii=False)

    prefix_map = {
        "daily": ("cc_us_bond_daily_", "us_bond_daily_"),
        "weekly": ("cc_us_bond_weekly_", "us_bond_weekly_"),
        "monthly": ("cc_us_bond_monthly_", "us_bond_monthly_"),
    }
    prefixes = prefix_map.get(mode)
    if not prefixes:
        return json.dumps({"error": f"Unknown mode: {mode}. Use daily, weekly, or monthly."},
                          ensure_ascii=False)

    if date:
        candidates = []
        for prefix in prefixes:
            for p in DOC_DIR.glob(f"{prefix}*{date}*.md"):
                candidates.append(p)
        path = candidates[0] if candidates else None
        if path is None:
            available = sorted(p.name for p in DOC_DIR.glob("*.md"))
            return json.dumps({"error": f"No {mode} report found for {date}",
                               "available": available}, ensure_ascii=False)
    else:
        all_candidates = []
        for prefix in prefixes:
            all_candidates.extend(DOC_DIR.glob(f"{prefix}*.md"))
        if not all_candidates:
            return json.dumps({"error": f"No {mode} reports found in {DOC_DIR}"},
                              ensure_ascii=False)
        path = sorted(all_candidates, reverse=True)[0]

    return path.read_text(encoding="utf-8")


@mcp.tool()
def run_us_bond_report(mode: str = "daily", date: str | None = None) -> str:
    """執行美債報告 pipeline（呼叫 cc_run_us_bond_tracking.py）。

    mode: "daily"（預設）、"weekly" 或 "monthly"
    date: "YYYY-MM-DD"，省略時使用今日
    回傳 JSON：{report_path, mode, preview（前 500 字）}
    注意：僅產生報告，不寄信。
    """
    valid_modes = {"daily", "weekly", "monthly"}
    if mode not in valid_modes:
        return json.dumps({"error": f"mode must be one of: {', '.join(valid_modes)}"},
                          ensure_ascii=False)

    cmd = [sys.executable, str(SCRIPTS_DIR / "cc_run_us_bond_tracking.py"), "--mode", mode]
    if date:
        cmd += ["--date", date]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Timeout after 120s"}, ensure_ascii=False)

    report_path: str | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("REPORT_PATH="):
            report_path = line.split("=", 1)[1].strip()
            break

    if proc.returncode != 0 and not report_path:
        return json.dumps({"error": proc.stderr[-500:] or "Unknown error",
                           "stdout": proc.stdout[-500:]}, ensure_ascii=False)

    preview = ""
    if report_path:
        p = Path(report_path)
        if p.exists():
            preview = p.read_text(encoding="utf-8")[:500]

    return json.dumps({"report_path": report_path, "mode": mode, "preview": preview},
                      ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
