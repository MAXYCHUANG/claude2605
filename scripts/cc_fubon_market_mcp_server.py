#!/usr/bin/env python3
"""Fubon Market MCP Server — stdio transport.

Exposes Fubon Neo SDK market-data capabilities as MCP tools for Claude Code.
Runs under .venv-fubon (has both fubon_neo and mcp).

Tools:
  get_stock_quote       — 個股即時報價（盤中，需 Fubon 登入）
  get_stock_candles     — 個股 K 棒（盤中 / 歷史）
  get_futopt_quote      — 期貨 / 選擇權即時報價
  get_market_snapshot   — 多股快照（snapshot.quotes）
  get_bigorder_log      — 查詢本機大單 JSONL 紀錄
  get_tw_market_report  — 讀取最新台股日終報告 Markdown
  run_tw_market_report  — 執行完整台股日終報告 pipeline

Usage (stdio, registered in .claude/settings.json):
  .venv-fubon/bin/python3 scripts/cc_fubon_market_mcp_server.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

PROJECT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_DIR / "log"
DOC_DIR = PROJECT_DIR / "docs" / "26TW_MARKET_doc"
ENV_FILE = PROJECT_DIR / ".env.fubon"

DEFAULT_SYMBOLS = ["TWII", "0050", "2330", "00830", "00891", "2881", "2891"]

mcp = FastMCP("fubon-market")

# ---------------------------------------------------------------------------
# Fubon SDK — lazy singleton
# ---------------------------------------------------------------------------

_sdk: Any = None
_sdk_error: str | None = None


def _load_env() -> None:
    """Load .env.fubon into os.environ if not already set."""
    if not ENV_FILE.exists():
        return
    with ENV_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


def _get_sdk() -> Any:
    global _sdk, _sdk_error
    if _sdk is not None:
        return _sdk
    if _sdk_error is not None:
        raise RuntimeError(_sdk_error)

    _load_env()
    required = ("FUBON_ID", "FUBON_PASSWORD", "FUBON_CERT_PATH", "FUBON_CERT_PASSWORD")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        _sdk_error = f"Missing env vars: {', '.join(missing)}"
        raise RuntimeError(_sdk_error)

    try:
        from fubon_neo.sdk import FubonSDK
        sdk = FubonSDK()
        sdk.login(
            os.environ["FUBON_ID"],
            os.environ["FUBON_PASSWORD"],
            os.environ["FUBON_CERT_PATH"],
            os.environ["FUBON_CERT_PASSWORD"],
        )
        sdk.init_realtime()
        _sdk = sdk
        return _sdk
    except Exception as exc:
        _sdk_error = f"Fubon SDK init failed: {exc}"
        raise RuntimeError(_sdk_error) from exc


def _sdk_stock_rest():
    return _get_sdk().marketdata.rest_client.stock


def _sdk_futopt_rest():
    return _get_sdk().marketdata.rest_client.futopt


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_stock_quote(symbols: list[str]) -> str:
    """取得個股即時報價（盤中可用，需 Fubon 登入）。

    symbols: 股票代號清單，例如 ["2330", "0050"]
    回傳 JSON：{symbol: {lastPrice, previousClose, change, changePercent, volume, bid, ask, name}}
    """
    try:
        rest = _sdk_stock_rest()
    except RuntimeError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    result: dict[str, Any] = {}
    for sym in symbols:
        try:
            q = rest.intraday.quote(symbol=sym)
            total = q.get("total") or {}
            result[sym] = {
                "name": q.get("name"),
                "lastPrice": q.get("lastPrice"),
                "previousClose": q.get("previousClose"),
                "change": q.get("change"),
                "changePercent": q.get("changePercent"),
                "volume": total.get("tradeVolume"),
                "bid": q.get("bid"),
                "ask": q.get("ask"),
                "lastUpdated": q.get("lastUpdated"),
            }
        except Exception as exc:
            result[sym] = {"error": str(exc)}

    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_stock_candles(symbol: str, source: str = "intraday", limit: int = 10) -> str:
    """取得個股 K 棒資料。

    symbol: 股票代號，例如 "2330"
    source: "intraday"（盤中分鐘棒）或 "historical"（日 K）
    limit: 回傳筆數（historical 有效，intraday 回傳當日全部）
    回傳 JSON：[{open, high, low, close, volume, date/time}]
    """
    try:
        rest = _sdk_stock_rest()
    except RuntimeError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    try:
        if source == "historical":
            raw = rest.historical.candles(symbol=symbol, limit=limit)
        else:
            raw = rest.intraday.candles(symbol=symbol)
        candles = raw.get("data", raw) if isinstance(raw, dict) else raw
        return json.dumps({"symbol": symbol, "source": source, "candles": candles},
                          ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def get_futopt_quote(symbol: str) -> str:
    """取得期貨 / 選擇權即時報價（盤中可用，需 Fubon 登入）。

    symbol: 期貨或選擇權代號，例如 "TXFB6"、"TXO20260620C19000"
    回傳 JSON：{price, change, changePercent, volume, openInterest, bid, ask}
    """
    try:
        rest = _sdk_futopt_rest()
    except RuntimeError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    try:
        q = rest.intraday.quote(symbol=symbol)
        total = q.get("total") or {}
        result = {
            "symbol": symbol,
            "name": q.get("name"),
            "lastPrice": q.get("lastPrice"),
            "previousClose": q.get("previousClose"),
            "change": q.get("change"),
            "changePercent": q.get("changePercent"),
            "volume": total.get("tradeVolume"),
            "openInterest": q.get("openInterest"),
            "bid": q.get("bid"),
            "ask": q.get("ask"),
            "lastUpdated": q.get("lastUpdated"),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def get_market_snapshot(symbols: list[str] | None = None) -> str:
    """取得多股快照報價（snapshot.quotes，速度快）。

    symbols: 股票代號清單；省略時使用預設追蹤標的
             ["TWII","0050","2330","00830","00891","2881","2891"]
    回傳 JSON：{symbol: {lastPrice, change, changePercent, volume}}
    """
    if not symbols:
        symbols = DEFAULT_SYMBOLS

    try:
        rest = _sdk_stock_rest()
    except RuntimeError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    try:
        raw = rest.snapshot.quotes(symbol=",".join(symbols))
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        result: dict[str, Any] = {}
        items = data if isinstance(data, list) else [data]
        for item in items:
            sym = item.get("symbol", "")
            result[sym] = {
                "name": item.get("name"),
                "lastPrice": item.get("lastPrice") or item.get("closePrice"),
                "change": item.get("change"),
                "changePercent": item.get("changePercent"),
                "volume": (item.get("total") or {}).get("tradeVolume"),
            }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def get_bigorder_log(
    date: str | None = None,
    symbol: str | None = None,
    direction: str | None = None,
    limit: int = 50,
) -> str:
    """查詢本機大單 JSONL 紀錄（不需 Fubon 登入）。

    date: "YYYY-MM-DD"，省略時使用今日（台北時間）
    symbol: 過濾特定代號，例如 "2330"
    direction: "ask"（主動買）或 "bid"（主動賣），省略不過濾
    limit: 最多回傳筆數，預設 50
    回傳 JSON：[{ts, symbol, type, price, size, direction}]
    """
    if date is None:
        tz_offset = dt.timezone(dt.timedelta(hours=8))
        date = dt.datetime.now(tz=tz_offset).strftime("%Y%m%d")
    else:
        date = date.replace("-", "")

    log_file = LOG_DIR / f"bigorder_{date}.jsonl"
    if not log_file.exists():
        return json.dumps({"error": f"Log not found: {log_file.name}",
                           "available": sorted(p.name for p in LOG_DIR.glob("bigorder_*.jsonl"))},
                          ensure_ascii=False)

    records: list[dict] = []
    with log_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if symbol and rec.get("symbol") != symbol:
                continue
            if direction and rec.get("direction") != direction:
                continue
            records.append(rec)

    return json.dumps({"date": date, "count": len(records),
                       "records": records[-limit:]}, ensure_ascii=False, indent=2)


@mcp.tool()
def get_tw_market_report(date: str | None = None) -> str:
    """讀取本機台股日終報告 Markdown（不需 Fubon 登入）。

    date: "YYYY-MM-DD"，省略時取最新一份報告
    回傳報告的 Markdown 文字內容
    """
    if date:
        candidates = [
            DOC_DIR / f"cc_tw_market_fubon_daily_{date}.md",
            DOC_DIR / f"tw_market_fubon_daily_{date}.md",
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            available = sorted(p.name for p in DOC_DIR.glob("*.md")) if DOC_DIR.exists() else []
            return json.dumps({"error": f"Report not found for {date}",
                               "available": available}, ensure_ascii=False)
    else:
        if not DOC_DIR.exists():
            return json.dumps({"error": f"Report directory not found: {DOC_DIR}"},
                              ensure_ascii=False)
        candidates = sorted(DOC_DIR.glob("*.md"), reverse=True)
        if not candidates:
            return json.dumps({"error": "No reports found"}, ensure_ascii=False)
        path = candidates[0]

    return path.read_text(encoding="utf-8")


@mcp.tool()
def run_tw_market_report(date: str | None = None) -> str:
    """執行台股日終報告 pipeline（呼叫 cc_run_tw_market_fubon.py）。

    date: "YYYY-MM-DD"，省略時使用今日
    回傳 JSON：{report_path, preview（前 500 字）}
    注意：僅產生報告，不寄信。
    """
    cmd = [sys.executable, str(PROJECT_DIR / "scripts" / "cc_run_tw_market_fubon.py")]
    if date:
        cmd += ["--date", date]

    _load_env()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ},
        )
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

    return json.dumps({"report_path": report_path, "preview": preview},
                      ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
