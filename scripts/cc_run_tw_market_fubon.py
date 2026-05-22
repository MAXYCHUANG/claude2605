#!/usr/bin/env python3
"""Generate a Taiwan market end-of-day report.

Data sources:
- TWSE daily market tables for TWII, daily closes, and institutional flow.
- Fubon Neo as optional live quote fallback/enrichment when available.

Default tracked symbols:
- TWII, 0050, 2330, 00830, 00891, 2881, 2891

The report is written as Markdown so it can be archived and emailed.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import math
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DOC_DIR = PROJECT_DIR / "docs" / "26TW_MARKET_doc"

DEFAULT_SYMBOLS = ["TWII", "0050", "2330", "00830", "00891", "2881", "2891"]
RISK_FREE_RATE = 0.015  # 台灣無風險利率（約 1.5%）


@dataclass(frozen=True)
class DailyRow:
    symbol: str
    name: str
    volume: float | None
    trades: int | None
    amount: float | None
    open_: float | None
    high: float | None
    low: float | None
    close: float | None
    change_sign: str | None
    change: float | None
    bid: float | None
    bid_size: float | None
    ask: float | None
    ask_size: float | None
    pe: float | None


@dataclass(frozen=True)
class FuturesRow:
    contract: str
    expiry: str
    open_: float | None
    high: float | None
    low: float | None
    last: float | None
    change: float | None
    change_pct: float | None
    post_volume: float | None
    day_volume: float | None
    total_volume: float | None
    settle: float | None
    open_interest: float | None
    bid: float | None
    ask: float | None
    hist_high: float | None
    hist_low: float | None


@dataclass(frozen=True)
class OptionContract:
    expiry: str
    strike: float
    high: float | None
    low: float | None
    last: float | None
    settle: float | None
    change: float | None
    volume: float | None
    open_interest: float | None


@dataclass(frozen=True)
class OptionSummary:
    label: str
    expiry: str
    call_volume: float
    call_open_interest: float
    put_volume: float
    put_open_interest: float
    call_pcr: float | None
    oi_pcr: float | None
    call_wall: float | None
    put_wall: float | None
    max_pain: float | None
    call_contracts: list[OptionContract]
    put_contracts: list[OptionContract]


@dataclass(frozen=True)
class FubonCandle:
    date: dt.date
    open_: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


@dataclass(frozen=True)
class FubonTechnical:
    symbol: str
    rsi: float | None
    macd: float | None
    kdj_k: float | None


@dataclass(frozen=True)
class FubonFutOptQuote:
    symbol: str
    last: float | None
    change: float | None
    volume: float | None
    open_interest: float | None


@dataclass(frozen=True)
class FubonAccount:
    total_value: float | None
    available: float | None
    stock_value: float | None
    unrealized_pnl: float | None


@dataclass(frozen=True)
class OptionGreeks:
    strike: float
    iv: float | None
    delta: float | None
    gamma: float | None
    vega: float | None
    theta: float | None


@dataclass(frozen=True)
class NextDayEstimate:
    bias: str
    change_range: str
    score: float
    notes: list[str]


def fail(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        fail(f"Invalid date {value!r}; expected YYYY-MM-DD. {exc}")


def taipei_today() -> dt.date:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()


def fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "*/*",
        },
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url: str, timeout: int = 20) -> dict[str, Any]:
    return json.loads(fetch_text(url, timeout=timeout))


def strip_html(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    return re.sub(r"<[^>]+>", "", text).strip()


def to_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    text = strip_html(value).replace(",", "")
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    if value in (None, "", "-", "--"):
        return None
    text = strip_html(value).replace(",", "")
    if not text or text in {"-", "--"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "NA"
    return f"{value:,.{digits}f}"


def fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "NA"
    return f"{value:+.{digits}f}%"


def fmt_m(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "NA"
    return f"{value / 1_000_000:,.{digits}f}M"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def fetch_twse_mi_index(date: dt.date) -> dict[str, Any] | None:
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
        f"?response=json&date={date:%Y%m%d}&type=ALLBUT0999&_=1"
    )
    try:
        data = fetch_json(url)
    except Exception:
        return None
    tables = data.get("tables") or []
    if not tables:
        return None
    return data


def fetch_twse_t86(date: dt.date) -> dict[str, dict[str, float]]:
    url = (
        "https://www.twse.com.tw/rwd/zh/fund/T86"
        f"?response=json&date={date:%Y%m%d}&selectType=ALLBUT0999&_=1"
    )
    try:
        data = fetch_json(url)
    except Exception:
        return {}

    fields = data.get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    out: dict[str, dict[str, float]] = {}
    for row in data.get("data") or []:
        symbol = row[idx.get("證券代號", -1)] if idx.get("證券代號", -1) >= 0 else None
        if not symbol:
            continue
        out[symbol] = {
            "foreign": to_float(row[idx.get("外陸資買賣超股數(不含外資自營商)", -1)] or 0) or 0.0,
            "trust": to_float(row[idx.get("投信買賣超股數", -1)] or 0) or 0.0,
            "dealer": to_float(row[idx.get("自營商買賣超股數", -1)] or 0) or 0.0,
            "dealer_hedge": to_float(row[idx.get("自營商買賣超股數(避險)", -1)] or 0) or 0.0,
            "dealer_self": to_float(row[idx.get("自營商買賣超股數(自行買賣)", -1)] or 0) or 0.0,
            "total": to_float(row[idx.get("三大法人買賣超股數", -1)] or 0) or 0.0,
        }
    return out


def fetch_twse_daily_rows(date: dt.date) -> tuple[dict[str, Any] | None, dict[str, DailyRow]]:
    data = fetch_twse_mi_index(date)
    if not data:
        return None, {}
    tables = data.get("tables") or []
    if len(tables) < 9:
        return data, {}
    sec = tables[8]
    fields = sec.get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    rows: dict[str, DailyRow] = {}
    for row in sec.get("data") or []:
        symbol = row[idx.get("證券代號", -1)] if idx.get("證券代號", -1) >= 0 else None
        if not symbol:
            continue
        rows[symbol] = DailyRow(
            symbol=symbol,
            name=strip_html(row[idx.get("證券名稱", -1)] if idx.get("證券名稱", -1) >= 0 else ""),
            volume=to_float(row[idx.get("成交股數", -1)] if idx.get("成交股數", -1) >= 0 else None),
            trades=to_int(row[idx.get("成交筆數", -1)] if idx.get("成交筆數", -1) >= 0 else None),
            amount=to_float(row[idx.get("成交金額", -1)] if idx.get("成交金額", -1) >= 0 else None),
            open_=to_float(row[idx.get("開盤價", -1)] if idx.get("開盤價", -1) >= 0 else None),
            high=to_float(row[idx.get("最高價", -1)] if idx.get("最高價", -1) >= 0 else None),
            low=to_float(row[idx.get("最低價", -1)] if idx.get("最低價", -1) >= 0 else None),
            close=to_float(row[idx.get("收盤價", -1)] if idx.get("收盤價", -1) >= 0 else None),
            change_sign=strip_html(row[idx.get("漲跌(+/-)", -1)] if idx.get("漲跌(+/-)", -1) >= 0 else None) or None,
            change=to_float(row[idx.get("漲跌價差", -1)] if idx.get("漲跌價差", -1) >= 0 else None),
            bid=to_float(row[idx.get("最後揭示買價", -1)] if idx.get("最後揭示買價", -1) >= 0 else None),
            bid_size=to_float(row[idx.get("最後揭示買量", -1)] if idx.get("最後揭示買量", -1) >= 0 else None),
            ask=to_float(row[idx.get("最後揭示賣價", -1)] if idx.get("最後揭示賣價", -1) >= 0 else None),
            ask_size=to_float(row[idx.get("最後揭示賣量", -1)] if idx.get("最後揭示賣量", -1) >= 0 else None),
            pe=to_float(row[idx.get("本益比", -1)] if idx.get("本益比", -1) >= 0 else None),
        )
    return data, rows


def find_latest_trading_day(target: dt.date) -> tuple[dt.date, dict[str, Any], dict[str, DailyRow]]:
    for delta in range(0, 10):
        probe = target - dt.timedelta(days=delta)
        data, rows = fetch_twse_daily_rows(probe)
        index_ok = False
        if data and data.get("tables"):
            try:
                index_rows = data["tables"][0].get("data") or []
                index_ok = any((strip_html(row[0]) == "發行量加權股價指數") for row in index_rows if row)
            except Exception:
                index_ok = False
        if index_ok and rows:
            return probe, data, rows
    fail("Unable to locate a recent TWSE trading day within 10 days.")


def _init_fubon_sdk() -> Any:
    """Initialize Fubon SDK and return it, or None if unavailable."""
    env_keys = ("FUBON_ID", "FUBON_PASSWORD", "FUBON_CERT_PATH", "FUBON_CERT_PASSWORD")
    if not all(os.environ.get(k) for k in env_keys):
        return None

    try:
        from fubon_neo.sdk import FubonSDK
    except Exception:
        return None

    try:
        sdk = FubonSDK()
        sdk.login(
            os.environ["FUBON_ID"],
            os.environ["FUBON_PASSWORD"],
            os.environ["FUBON_CERT_PATH"],
            os.environ["FUBON_CERT_PASSWORD"],
        )
        sdk.init_realtime()
        return sdk
    except Exception:
        return None


def fetch_fubon_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    env_keys = ("FUBON_ID", "FUBON_PASSWORD", "FUBON_CERT_PATH", "FUBON_CERT_PASSWORD")
    if not all(os.environ.get(k) for k in env_keys):
        return {}

    try:
        from fubon_neo.sdk import FubonSDK
    except Exception:
        return {}

    sdk = FubonSDK()
    sdk.login(
        os.environ["FUBON_ID"],
        os.environ["FUBON_PASSWORD"],
        os.environ["FUBON_CERT_PATH"],
        os.environ["FUBON_CERT_PASSWORD"],
    )
    sdk.init_realtime()
    reststock = sdk.marketdata.rest_client.stock

    out: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        try:
            quote = reststock.intraday.quote(symbol=symbol)
        except Exception as exc:
            out[symbol] = {"error": str(exc)}
            continue
        total = quote.get("total") or {}
        out[symbol] = {
            "symbol": quote.get("symbol", symbol),
            "name": quote.get("name"),
            "lastPrice": quote.get("lastPrice"),
            "previousClose": quote.get("previousClose"),
            "change": quote.get("change"),
            "changePercent": quote.get("changePercent"),
            "tradeVolume": total.get("tradeVolume"),
            "tradeValue": total.get("tradeValue"),
            "lastUpdated": quote.get("lastUpdated"),
        }
    return out


def _fetch_stock_quotes_extended(sdk: Any, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch stock quotes with extended fields (OHLC, bid/ask)."""
    if not sdk:
        return {}
    try:
        reststock = sdk.marketdata.rest_client.stock
        out: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            try:
                quote = reststock.intraday.quote(symbol=symbol)
            except Exception:
                continue
            total = quote.get("total") or {}
            out[symbol] = {
                "symbol": quote.get("symbol", symbol),
                "name": quote.get("name"),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "lastPrice": quote.get("lastPrice"),
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
                "bidSize": quote.get("bidSize"),
                "askSize": quote.get("askSize"),
                "tradeVolume": total.get("tradeVolume"),
                "tradeValue": total.get("tradeValue"),
            }
        return out
    except Exception:
        return {}


def _fetch_historical_candles(sdk: Any, symbols: list[str], limit: int = 5) -> dict[str, list[FubonCandle]]:
    """Fetch historical candles (K-line data) for the past N days."""
    if not sdk:
        return {}
    try:
        reststock = sdk.marketdata.rest_client.stock
        out: dict[str, list[FubonCandle]] = {}
        for symbol in symbols:
            try:
                candles = reststock.historical.candles(symbol=symbol, limit=limit)
            except Exception:
                continue
            if not candles:
                continue
            out[symbol] = []
            for candle in candles.get("data", []):
                date_str = candle.get("date", "")
                try:
                    candle_date = dt.date.fromisoformat(date_str) if isinstance(date_str, str) and date_str else None
                except (ValueError, AttributeError):
                    candle_date = None
                out[symbol].append(
                    FubonCandle(
                        date=candle_date,
                        open_=to_float(candle.get("open")),
                        high=to_float(candle.get("high")),
                        low=to_float(candle.get("low")),
                        close=to_float(candle.get("close")),
                        volume=to_float(candle.get("volume")),
                    )
                )
        return out
    except Exception:
        return {}


def _fetch_technical_indicators(sdk: Any, symbols: list[str]) -> dict[str, FubonTechnical]:
    """Fetch technical indicators (RSI, MACD, KDJ)."""
    if not sdk:
        return {}
    try:
        reststock = sdk.marketdata.rest_client.stock
        out: dict[str, FubonTechnical] = {}
        for symbol in symbols:
            try:
                rsi = reststock.technical.rsi(symbol=symbol)
                macd = reststock.technical.macd(symbol=symbol)
                kdj = reststock.technical.kdj(symbol=symbol)
            except Exception:
                continue
            rsi_val = to_float(rsi.get("data", [{}])[0].get("value")) if rsi.get("data") else None
            macd_val = to_float(macd.get("data", [{}])[0].get("value")) if macd.get("data") else None
            kdj_k = to_float(kdj.get("data", [{}])[0].get("k")) if kdj.get("data") else None
            out[symbol] = FubonTechnical(symbol=symbol, rsi=rsi_val, macd=macd_val, kdj_k=kdj_k)
        return out
    except Exception:
        return {}


def _fetch_futopt_quotes(sdk: Any, futopt_symbols: list[str]) -> dict[str, FubonFutOptQuote]:
    """Fetch futures/options quotes."""
    if not sdk:
        return {}
    try:
        restfutopt = sdk.marketdata.rest_client.futopt
        out: dict[str, FubonFutOptQuote] = {}
        for symbol in futopt_symbols:
            try:
                quote = restfutopt.intraday.quote(symbol=symbol)
            except Exception:
                continue
            total = quote.get("total") or {}
            out[symbol] = FubonFutOptQuote(
                symbol=symbol,
                last=to_float(quote.get("last")),
                change=to_float(quote.get("change")),
                volume=to_float(total.get("tradeVolume")),
                open_interest=to_float(quote.get("openInterest")),
            )
        return out
    except Exception:
        return {}


def _fetch_account_info(sdk: Any) -> FubonAccount | None:
    """Fetch account information (balance, equity, unrealized PnL)."""
    if not sdk:
        return None
    try:
        acct = sdk.accounting
        summary = acct.account_summary()
        return FubonAccount(
            total_value=to_float(summary.get("totalValue")),
            available=to_float(summary.get("available")),
            stock_value=to_float(summary.get("stockValue")),
            unrealized_pnl=to_float(summary.get("unrealizedPnL")),
        )
    except Exception:
        return None


def fetch_fubon_data(symbols: list[str], futopt_symbols: list[str] | None = None) -> dict[str, Any]:
    """Unified entry point: login once, fetch all data."""
    sdk = _init_fubon_sdk()
    if not sdk:
        return {}

    if futopt_symbols is None:
        futopt_symbols = []

    return {
        "quotes": _fetch_stock_quotes_extended(sdk, symbols),
        "historical": _fetch_historical_candles(sdk, symbols, limit=5),
        "technical": _fetch_technical_indicators(sdk, symbols),
        "futopt": _fetch_futopt_quotes(sdk, futopt_symbols),
        "account": _fetch_account_info(sdk),
    }


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, opt_type: str = "call") -> float | None:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "call":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _calc_iv(S: float, K: float, T: float, r: float, market_price: float, opt_type: str = "call", tol: float = 1e-4, max_iter: int = 200) -> float | None:
    if T <= 0 or S <= 0 or K <= 0 or market_price <= 0:
        return None
    sigma_low, sigma_high = 0.001, 2.0
    for _ in range(max_iter):
        sigma_mid = (sigma_low + sigma_high) / 2
        price = _bs_price(S, K, T, r, sigma_mid, opt_type)
        if price is None:
            return None
        if abs(price - market_price) < tol:
            return sigma_mid
        if price < market_price:
            sigma_low = sigma_mid
        else:
            sigma_high = sigma_mid
    return (sigma_low + sigma_high) / 2 if sigma_high - sigma_low < 0.01 else None


def _calc_greeks(S: float, K: float, T: float, r: float, sigma: float) -> dict[str, float | None]:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": None, "gamma": None, "vega": None, "theta": None}
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    sqrt_T = math.sqrt(T)
    delta = _norm_cdf(d1)
    gamma = math.exp(-0.5 * d1**2) / (S * sigma * sqrt_T * math.sqrt(2 * math.pi))
    vega = S * math.exp(-0.5 * d1**2) / sqrt_T / math.sqrt(2 * math.pi) / 100
    theta = (-S * math.exp(-0.5 * d1**2) * sigma / (2 * sqrt_T * math.sqrt(2 * math.pi))
             - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def calc_option_chain_greeks(contracts: list[OptionContract], underlying_price: float | None, expiry: str, today: dt.date, r: float = RISK_FREE_RATE, opt_type: str = "call") -> list[OptionGreeks]:
    if underlying_price is None or underlying_price <= 0:
        return []
    try:
        expiry_date = dt.datetime.strptime(expiry, "%Y%m%d").date()
    except (ValueError, TypeError):
        return []
    T = max((expiry_date - today).days, 0.5) / 365.0
    result = []
    for contract in contracts:
        if contract.last is None or contract.last <= 0:
            continue
        iv = _calc_iv(underlying_price, contract.strike, T, r, contract.last, opt_type)
        greeks_dict = _calc_greeks(underlying_price, contract.strike, T, r, iv or 0.2) if iv else {}
        result.append(OptionGreeks(
            strike=contract.strike,
            iv=iv,
            delta=greeks_dict.get("delta"),
            gamma=greeks_dict.get("gamma"),
            vega=greeks_dict.get("vega"),
            theta=greeks_dict.get("theta"),
        ))
    return result


def _render_option_chain_table(summary: OptionSummary, underlying_price: float | None, window: int = 10) -> str:
    if underlying_price is None or not summary.call_contracts or not summary.put_contracts:
        return ""
    call_dict = {c.strike: c for c in summary.call_contracts}
    put_dict = {p.strike: p for p in summary.put_contracts}
    all_strikes = sorted(set(call_dict.keys()) | set(put_dict.keys()))
    if not all_strikes:
        return ""
    atm_idx = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - underlying_price))
    start_idx = max(0, atm_idx - window)
    end_idx = min(len(all_strikes), atm_idx + window + 1)
    strikes = all_strikes[start_idx:end_idx]
    rows = [["Call OI", "Call Vol", "Call Last", "Strike", "Put Last", "Put Vol", "Put OI", ""]]
    for strike in strikes:
        c = call_dict.get(strike)
        p = put_dict.get(strike)
        call_oi = fmt_num(c.open_interest, 0) if c else "—"
        call_vol = fmt_num(c.volume, 0) if c else "—"
        call_last = fmt_num(c.last, 2) if c else "—"
        put_last = fmt_num(p.last, 2) if p else "—"
        put_vol = fmt_num(p.volume, 0) if p else "—"
        put_oi = fmt_num(p.open_interest, 0) if p else "—"
        marker = "← ATM" if abs(strike - underlying_price) < 10 else ""
        rows.append([call_oi, call_vol, call_last, str(int(strike)), put_last, put_vol, put_oi, marker])
    return md_table(rows[0], rows[1:])


def fetch_taifex_html(url: str, payload: dict[str, str] | None = None, timeout: int = 20) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = urllib.parse.urlencode(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_html_tables(text: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for table_html in re.findall(r"<table.*?>.*?</table>", text, flags=re.S | re.I):
        rows: list[list[str]] = []
        for tr in re.findall(r"<tr.*?>.*?</tr>", table_html, flags=re.S | re.I):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)
            cleaned = [strip_html(cell) for cell in cells]
            if cleaned:
                rows.append(cleaned)
        if rows:
            tables.append(rows)
    return tables


def parse_taifex_number(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    text = strip_html(value).replace(",", "")
    if not text:
        return None
    text = text.replace("▲+", "+").replace("▼-", "-").replace("▲", "+").replace("▼", "-")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_taifex_date(value: str) -> dt.date | None:
    text = re.sub(r"[^0-9]", "", value or "")
    if len(text) != 8:
        return None
    try:
        return dt.date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def fetch_bigorder_summary(date: dt.date) -> dict[str, Any]:
    """Read big order records from NDJSON log file and return summary."""
    bigorder_file = PROJECT_DIR / "log" / f"bigorder_{date:%Y%m%d}.jsonl"
    if not bigorder_file.exists():
        return {}

    call_buy = call_sell = put_buy = put_sell = 0
    stock_orders: dict[str, float] = {}

    try:
        with open(bigorder_file, "r") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                opt_type = record.get("type", "")
                direction = record.get("direction", "")
                symbol = record.get("symbol", "")
                price = record.get("price", 0)
                size = record.get("size", 0)

                if opt_type == "call" and direction == "ask":
                    call_buy += size
                elif opt_type == "call" and direction == "bid":
                    call_sell += size
                elif opt_type == "put" and direction == "ask":
                    put_buy += size
                elif opt_type == "put" and direction == "bid":
                    put_sell += size
                elif opt_type == "stock":
                    amount = price * size
                    stock_orders[symbol] = stock_orders.get(symbol, 0) + amount
    except Exception:
        return {}

    top_stocks = sorted(stock_orders.items(), key=lambda x: x[1], reverse=True)[:3]
    return {
        "call_buy": call_buy,
        "call_sell": call_sell,
        "put_buy": put_buy,
        "put_sell": put_sell,
        "top_stocks": [{"symbol": sym, "amount": amt} for sym, amt in top_stocks],
    }


def fetch_taifex_futures(date: dt.date) -> list[FuturesRow]:
    text = fetch_taifex_html(
        "https://www.taifex.com.tw/cht/3/futDailyMarketReport",
        {
            "queryDate": date.strftime("%Y/%m/%d"),
            "marketCode": "0",
            "commodity_id": "TX",
            "queryType": "",
            "dateaddcnt": "",
        },
    )
    tables = extract_html_tables(text)
    if not tables:
        return []
    rows = tables[0]
    out: list[FuturesRow] = []
    for row in rows[1:]:
        if len(row) < 17 or row[0] != "TX":
            continue
        out.append(
            FuturesRow(
                contract=row[0],
                expiry=row[1],
                open_=parse_taifex_number(row[2]),
                high=parse_taifex_number(row[3]),
                low=parse_taifex_number(row[4]),
                last=parse_taifex_number(row[5]),
                change=parse_taifex_number(row[6]),
                change_pct=parse_taifex_number(row[7]),
                post_volume=parse_taifex_number(row[8]),
                day_volume=parse_taifex_number(row[9]),
                total_volume=parse_taifex_number(row[10]),
                settle=parse_taifex_number(row[11]),
                open_interest=parse_taifex_number(row[12]),
                bid=parse_taifex_number(row[13]),
                ask=parse_taifex_number(row[14]),
                hist_high=parse_taifex_number(row[15]),
                hist_low=parse_taifex_number(row[16]),
            )
        )
    return out


def _parse_taifex_option_rows(rows: list[list[str]]) -> list[OptionContract]:
    out: list[OptionContract] = []
    for row in rows[1:]:
        if len(row) < 10:
            continue
        expiry = row[1]
        strike = parse_taifex_number(row[2])
        if strike is None:
            continue
        out.append(
            OptionContract(
                expiry=expiry,
                strike=strike,
                high=parse_taifex_number(row[3]),
                low=parse_taifex_number(row[4]),
                last=parse_taifex_number(row[5]),
                settle=parse_taifex_number(row[6]),
                change=parse_taifex_number(row[7]),
                volume=parse_taifex_number(row[8]),
                open_interest=parse_taifex_number(row[9]),
            )
        )
    return out


def _choose_option_expiry(calls: list[OptionContract], puts: list[OptionContract], current_date: dt.date) -> str | None:
    expiries = sorted({row.expiry for row in calls + puts if row.expiry})
    current_key = current_date.strftime("%Y%m%d")
    later = [expiry for expiry in expiries if expiry > current_key]
    if later:
        return later[0]
    return expiries[0] if expiries else None


def _summarize_option_chain(label: str, calls: list[OptionContract], puts: list[OptionContract], current_date: dt.date, spot: float | None) -> OptionSummary | None:
    expiry = _choose_option_expiry(calls, puts, current_date)
    if not expiry:
        return None
    call_subset = [row for row in calls if row.expiry == expiry]
    put_subset = [row for row in puts if row.expiry == expiry]
    if not call_subset and not put_subset:
        return None

    call_volume = sum(row.volume or 0.0 for row in call_subset)
    call_oi = sum(row.open_interest or 0.0 for row in call_subset)
    put_volume = sum(row.volume or 0.0 for row in put_subset)
    put_oi = sum(row.open_interest or 0.0 for row in put_subset)
    call_pcr = (put_volume / call_volume) if call_volume else None
    oi_pcr = (put_oi / call_oi) if call_oi else None
    call_wall = max(call_subset, key=lambda row: row.open_interest or 0.0).strike if call_subset else None
    put_wall = max(put_subset, key=lambda row: row.open_interest or 0.0).strike if put_subset else None

    strikes = sorted({row.strike for row in call_subset + put_subset})
    max_pain = None
    if strikes:
        best_loss = None
        for candidate in strikes:
            total_loss = 0.0
            for row in call_subset:
                if candidate > row.strike:
                    total_loss += (candidate - row.strike) * (row.open_interest or 0.0)
            for row in put_subset:
                if candidate < row.strike:
                    total_loss += (row.strike - candidate) * (row.open_interest or 0.0)
            if best_loss is None or total_loss < best_loss:
                best_loss = total_loss
                max_pain = candidate

    return OptionSummary(
        label=label,
        expiry=expiry,
        call_volume=call_volume,
        call_open_interest=call_oi,
        put_volume=put_volume,
        put_open_interest=put_oi,
        call_pcr=call_pcr,
        oi_pcr=oi_pcr,
        call_wall=call_wall,
        put_wall=put_wall,
        max_pain=max_pain,
        call_contracts=call_subset,
        put_contracts=put_subset,
    )


def fetch_taifex_option_summary(date: dt.date, commodity_id: str, commodity_id2: str, label: str, spot: float | None) -> OptionSummary | None:
    text = fetch_taifex_html(
        "https://www.taifex.com.tw/cht/3/optDailyMarketSummary",
        {
            "queryDate": date.strftime("%Y/%m/%d"),
            "MarketCode": "0",
            "commodity_id": commodity_id,
            "commodity_id2": commodity_id2,
            "queryType": "",
            "dateaddcnt": "",
        },
    )
    tables = extract_html_tables(text)
    if len(tables) < 4:
        return None
    call_rows = _parse_taifex_option_rows(tables[1])
    put_rows = _parse_taifex_option_rows(tables[3])
    return _summarize_option_chain(label, call_rows, put_rows, date, spot)


def select_option_lines(option_summary: OptionSummary | None, spot: float | None) -> list[str]:
    if not option_summary:
        return ["資料缺口"]
    lines = [
        f"{option_summary.label} 近月 `{option_summary.expiry}`：",
        f"- Call Vol `{fmt_num(option_summary.call_volume, 0)}` / Put Vol `{fmt_num(option_summary.put_volume, 0)}` / PCR vol `{fmt_num(option_summary.call_pcr, 2)}`",
        f"- Call OI `{fmt_num(option_summary.call_open_interest, 0)}` / Put OI `{fmt_num(option_summary.put_open_interest, 0)}` / PCR OI `{fmt_num(option_summary.oi_pcr, 2)}`",
    ]
    if option_summary.call_wall is not None or option_summary.put_wall is not None:
        lines.append(
            f"- Call wall `{fmt_num(option_summary.call_wall, 0)}` / Put wall `{fmt_num(option_summary.put_wall, 0)}` / Max pain `{fmt_num(option_summary.max_pain, 0)}`"
        )
    if spot is not None:
        notes = []
        if option_summary.call_wall is not None:
            notes.append(
                f"距 call wall {fmt_pct((option_summary.call_wall - spot) / spot * 100 if option_summary.call_wall else None, 2)}"
            )
        if option_summary.put_wall is not None:
            notes.append(
                f"距 put wall {fmt_pct((spot - option_summary.put_wall) / spot * 100 if option_summary.put_wall else None, 2)}"
            )
        if notes:
            lines.append("- " + "；".join(notes))
    return lines


def estimate_next_day_bias(
    twii_close: float | None,
    twii_change_pct: float | None,
    tx_front: FuturesRow | None,
    tx_prev_front: FuturesRow | None,
    txo: OptionSummary | None,
    cdo: OptionSummary | None,
    twii_volume_ratio: float | None,
    close_2330: float | None,
    close_2330_change_pct: float | None,
) -> NextDayEstimate | None:
    if twii_close is None or tx_front is None:
        return None

    score = 0.0
    notes: list[str] = []

    if tx_front.last is not None:
        basis = tx_front.last - twii_close
        basis_pct = basis / twii_close * 100.0 if twii_close else None
        notes.append(f"TX 基差 `{basis:+.2f}` 點（`{basis_pct:+.2f}%`）")
        if basis_pct is not None:
            if basis_pct > 0.08:
                score += 1.0
            elif basis_pct < -0.08:
                score -= 1.0

    if tx_front.change_pct is not None:
        notes.append(f"TX 近月日變動 `{tx_front.change:+.0f}` / `{tx_front.change_pct:+.2f}%`")
        if tx_front.change_pct > 0.35:
            score += 1.0
        elif tx_front.change_pct < -0.35:
            score -= 1.0

    if tx_prev_front and tx_front.open_interest is not None and tx_prev_front.open_interest is not None:
        oi_delta = tx_front.open_interest - tx_prev_front.open_interest
        oi_ratio = volume_ratio(tx_front.open_interest, tx_prev_front.open_interest)
        notes.append(
            f"TX 未平倉 `{fmt_num(tx_front.open_interest, 0)}`（前日 `{fmt_num(tx_prev_front.open_interest, 0)}`，變化 `{oi_delta:+.0f}`）"
        )
        if oi_delta > 0 and tx_front.change_pct is not None and tx_front.change_pct > 0:
            score += 0.5
        elif oi_delta > 0 and tx_front.change_pct is not None and tx_front.change_pct < 0:
            score -= 0.5
        elif oi_ratio is not None and oi_ratio < 0.97:
            score -= 0.25

    if txo and txo.call_pcr is not None and txo.oi_pcr is not None:
        notes.append(
            f"TXO 近月 PCR vol `{txo.call_pcr:.2f}` / PCR OI `{txo.oi_pcr:.2f}`，expiry `{txo.expiry}`"
        )
        if txo.oi_pcr < 0.9:
            score += 0.5
        elif txo.oi_pcr > 1.1:
            score -= 0.5

    if cdo and cdo.call_pcr is not None and cdo.oi_pcr is not None:
        notes.append(
            f"2330 選擇權 PCR vol `{cdo.call_pcr:.2f}` / PCR OI `{cdo.oi_pcr:.2f}`，expiry `{cdo.expiry}`"
        )
        if cdo.oi_pcr < 0.95:
            score += 0.5
        elif cdo.oi_pcr > 1.05:
            score -= 0.5

    if twii_volume_ratio is not None:
        notes.append(f"TWII 成交量比 `{twii_volume_ratio:.2f}x`")
        if twii_volume_ratio > 1.1 and twii_change_pct is not None and twii_change_pct < 0:
            score -= 0.25

    if close_2330 is not None and close_2330_change_pct is not None:
        notes.append(f"2330 日變動 `{close_2330_change_pct:+.2f}%`")
        if close_2330_change_pct > 0:
            score += 0.25
        elif close_2330_change_pct < 0:
            score -= 0.25

    if score >= 2.5:
        bias = "偏多"
        change_range = "+0.4% ~ +0.9%"
    elif score >= 1.0:
        bias = "偏多但有限"
        change_range = "+0.1% ~ +0.4%"
    elif score <= -2.5:
        bias = "偏空"
        change_range = "-0.9% ~ -0.4%"
    elif score <= -1.0:
        bias = "偏空但有限"
        change_range = "-0.4% ~ -0.1%"
    else:
        bias = "震盪偏中性"
        change_range = "-0.2% ~ +0.2%"

    return NextDayEstimate(bias=bias, change_range=change_range, score=score, notes=notes)


def pick_text(*values: Any) -> str:
    for value in values:
        if value not in (None, "", "NA"):
            return str(value)
    return "NA"


def infer_signal(change_pct: float | None, volume_ratio: float | None) -> str:
    if change_pct is None:
        return "資料缺口"
    if change_pct >= 2 and (volume_ratio is None or volume_ratio >= 1.0):
        return "放量上漲，偏強"
    if change_pct <= -2 and (volume_ratio is None or volume_ratio >= 1.0):
        return "放量下跌，偏弱"
    if change_pct <= -1 and (volume_ratio is None or volume_ratio >= 1.0):
        return "偏弱回檔"
    if change_pct < 0 and (volume_ratio is not None and volume_ratio < 1.0):
        return "縮量回檔"
    if change_pct > 0 and (volume_ratio is not None and volume_ratio < 1.0):
        return "漲中量縮"
    return "震盪整理"


def market_stat_lookup(rows: list[list[str]], label: str) -> dict[str, str]:
    for row in rows:
        if row and strip_html(row[0]) == label:
            return {
                "amount": row[1],
                "volume": row[2],
                "trades": row[3],
            }
    return {}


def volume_ratio(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous


def build_report(
    report_date: dt.date,
    current_date: dt.date,
    current_data: dict[str, Any],
    current_rows: dict[str, DailyRow],
    prev_date: dt.date,
    prev_data: dict[str, Any],
    prev_rows: dict[str, DailyRow],
    index_data: dict[str, Any],
    current_index_date: dt.date,
    t86: dict[str, dict[str, float]],
    fubon_quotes: dict[str, dict[str, Any]],
    taifex_futures_current: list[FuturesRow],
    taifex_futures_prev: list[FuturesRow],
    txo_summary: OptionSummary | None,
    txo_prev_summary: OptionSummary | None,
    cdo_summary: OptionSummary | None,
    cdo_prev_summary: OptionSummary | None,
    next_day_estimate: NextDayEstimate | None,
    symbols: list[str],
    fubon_data: dict[str, Any] | None = None,
    bigorder_summary: dict[str, Any] | None = None,
) -> str:
    tables = current_data.get("tables") or []
    prev_tables = prev_data.get("tables") or []
    index_rows = tables[0].get("data") or [] if len(tables) > 0 else []
    breadth_rows = tables[7].get("data") or [] if len(tables) > 7 else []
    market_stats_rows = tables[6].get("data") or [] if len(tables) > 6 else []
    prev_market_stats_rows = prev_tables[6].get("data") or [] if len(prev_tables) > 6 else []

    index_close = index_change = index_change_pct = "NA"
    for row in index_rows:
        if row and strip_html(row[0]) == "發行量加權股價指數":
            index_close = row[1]
            index_change = row[3]
            index_change_pct = row[4]
            break

    market_stats = {}
    market_total = market_stat_lookup(market_stats_rows, "總計(1~15)")
    market_stock = market_stat_lookup(market_stats_rows, "1.一般股票")
    market_etf = market_stat_lookup(market_stats_rows, "4.ETF")

    prev_market_total = market_stat_lookup(prev_market_stats_rows, "總計(1~15)")
    prev_market_stock = market_stat_lookup(prev_market_stats_rows, "1.一般股票")
    prev_market_etf = market_stat_lookup(prev_market_stats_rows, "4.ETF")

    breadth_map = {strip_html(row[0]): row[1:] for row in breadth_rows if row}

    lines: list[str] = []
    lines.append(f"# 台股日終量價與法人追蹤報告 - 收盤日 {current_date:%Y-%m-%d}")
    lines.append("")
    lines.append(f"- 報表生成日：{report_date:%Y-%m-%d}")
    lines.append(f"- 資料主體：TWII / 0050 / 2330 / 00830 / 00891 / 2881 / 2891")
    lines.append(f"- 實際交易日：{current_index_date:%Y-%m-%d}")
    lines.append(f"- 比對前一交易日：{prev_date:%Y-%m-%d}")
    if fubon_quotes:
        lines.append("- 資料來源：TWSE 日終資料 + Fubon Neo 即時備援")
    else:
        lines.append("- 資料來源：TWSE 日終資料")
    lines.append("")

    twii_signal = infer_signal(
        to_float(index_change_pct.replace("%", "")) if isinstance(index_change_pct, str) else None,
        None,
    )

    lines.append("## 1. 一句話結論")
    lines.append("")
    lines.append(
        f"- 加權指數收在 `{index_close}`，日變動 `{index_change}` / `{index_change_pct}%`；"
        f"整體屬於 `{twii_signal}`。"
    )
    if market_total or market_stock or market_etf:
        lines.append(
            f"- 全市場成交金額 `{market_total.get('amount', 'NA')}`，成交股數 `{market_total.get('volume', 'NA')}`，"
            f"成交筆數 `{market_total.get('trades', 'NA')}`。"
        )
        lines.append(
            f"- 一般股票成交金額 `{market_stock.get('amount', 'NA')}`，ETF 成交金額 `{market_etf.get('amount', 'NA')}`。"
        )
    if breadth_map:
        stock_breadth = breadth_map.get("上漲(漲停)", ["NA", "NA"])[0]
        stock_breadth_down = breadth_map.get("下跌(跌停)", ["NA", "NA"])[0]
        stock_breadth_eq = breadth_map.get("上漲(漲停)", ["NA", "NA"])[1]
        stock_breadth_down_eq = breadth_map.get("下跌(跌停)", ["NA", "NA"])[1]
        lines.append(
            f"- 股票廣度：整體市場上漲 `{stock_breadth}` / 下跌 `{stock_breadth_down}`；"
            f"股票上漲 `{stock_breadth_eq}` / 下跌 `{stock_breadth_down_eq}`。"
        )
    lines.append("")

    lines.append("## 2. TWII 與市場廣度")
    lines.append("")
    breadth_text = "NA"
    if breadth_map:
        up_row = breadth_map.get("上漲(漲停)") or []
        down_row = breadth_map.get("下跌(跌停)") or []
        if len(up_row) >= 2 and len(down_row) >= 2:
            breadth_text = (
                f"整體 上漲 {up_row[0]} / 下跌 {down_row[0]}；"
                f"股票 上漲 {up_row[1]} / 下跌 {down_row[1]}"
            )
    lines.append(
        md_table(
            ["指標", "數值", "對前日"],
            [
                ["TWII 收盤", str(index_close), "加權指數日終收盤"],
                ["TWII 漲跌", f"{index_change} / {index_change_pct}%", "當日漲跌"],
                ["總計成交金額", market_total.get("amount", "NA"), "TWSE 總計(1~15)"],
                ["總計成交股數", market_total.get("volume", "NA"), "TWSE 總計(1~15)"],
                ["一般股票成交金額", market_stock.get("amount", "NA"), "TWSE 1.一般股票"],
                ["ETF 成交金額", market_etf.get("amount", "NA"), "TWSE 4.ETF"],
                ["市場廣度", breadth_text, "TWSE 漲跌證券數合計"],
            ],
        )
    )
    lines.append("")

    quote_rows = []
    for symbol in symbols:
        if symbol == "TWII":
            prev_market_volume = prev_market_total.get("volume")
            curr_market_volume = market_total.get("volume")
            try:
                curr_market_volume_num = float(str(curr_market_volume).replace(",", "")) if curr_market_volume else None
            except ValueError:
                curr_market_volume_num = None
            try:
                prev_market_volume_num = float(str(prev_market_volume).replace(",", "")) if prev_market_volume else None
            except ValueError:
                prev_market_volume_num = None
            market_ratio = volume_ratio(curr_market_volume_num, prev_market_volume_num)
            quote_rows.append(
                [
                    "TWII",
                    "加權指數",
                    str(index_close),
                    f"{index_change} / {index_change_pct}%",
                    market_total.get("volume", "NA"),
                    prev_market_total.get("volume", "NA") if prev_market_total else "NA",
                    f"{market_ratio:.2f}x" if market_ratio is not None else "NA",
                    "指數壓回、廣度偏弱",
                ]
            )
            continue

        cur = current_rows.get(symbol)
        prev = prev_rows.get(symbol)
        fb = fubon_quotes.get(symbol, {})
        close = cur.close if cur and cur.close is not None else to_float(fb.get("lastPrice"))
        prev_close = prev.close if prev and prev.close is not None else to_float(fb.get("previousClose"))
        change = (close - prev_close) if close is not None and prev_close is not None else None
        change_pct = (change / prev_close * 100.0) if change is not None and prev_close not in (None, 0) else None
        vol = cur.volume if cur and cur.volume is not None else to_float(fb.get("tradeVolume"))
        prev_vol = prev.volume if prev and prev.volume is not None else None
        vol_ratio = volume_ratio(vol, prev_vol)
        signal = infer_signal(change_pct, vol_ratio)
        quote_rows.append(
            [
                symbol,
                cur.name if cur else pick_text(fb.get("name"), symbol),
                fmt_num(close, 2),
                f"{fmt_num(change, 2)} / {fmt_pct(change_pct, 2)}",
                fmt_m(vol, 2) if vol is not None else "NA",
                fmt_m(prev_vol, 2) if prev_vol is not None else "NA",
                f"{vol_ratio:.2f}x" if vol_ratio is not None else "NA",
                signal,
            ]
        )

    lines.append("## 3. 標的量價表")
    lines.append("")
    lines.append(
        md_table(
            ["標的", "名稱", "收盤", "漲跌", "成交股數", "前一日成交股數", "量比", "判讀"],
            quote_rows,
        )
    )
    lines.append("")

    flow_rows = []
    for symbol in symbols:
        if symbol == "TWII":
            flow_rows.append(["TWII", "NA", "NA", "NA", "市場指數，無單一法人買賣超"])
            continue
        flow = t86.get(symbol)
        if not flow:
            flow_rows.append([symbol, "NA", "NA", "NA", "資料缺口"])
            continue
        flow_rows.append(
            [
                symbol,
                fmt_m(flow.get("foreign"), 2),
                fmt_m(flow.get("trust"), 2),
                fmt_m(flow.get("dealer"), 2),
                "外資 / 投信 / 自營商三大法人",
            ]
        )

    lines.append("## 4. 三大法人買賣超")
    lines.append("")
    lines.append(
        md_table(
            ["標的", "外資", "投信", "自營商", "說明"],
            flow_rows,
        )
    )
    lines.append("")

    lines.append("## 5. 資金輪動觀察")
    lines.append("")
    observations: list[str] = []
    if current_rows.get("2330") and current_rows["2330"].close is not None and prev_rows.get("2330"):
        cur_2330 = current_rows["2330"]
        pre_2330 = prev_rows["2330"]
        if pre_2330 and pre_2330.close is not None and cur_2330.close is not None:
            if cur_2330.close < pre_2330.close:
                observations.append("台積電轉弱，半導體主軸短線有壓。")
            elif cur_2330.close > pre_2330.close:
                observations.append("台積電轉強，半導體主軸仍有支撐。")
    if current_rows.get("2881") and prev_rows.get("2881") and current_rows["2881"].close and prev_rows["2881"].close:
        if current_rows["2881"].close >= prev_rows["2881"].close:
            observations.append("金融股相對抗跌，資金有向防守 / 金融輪動的跡象。")
    if current_rows.get("00830") and current_rows.get("00891") and current_rows["00830"].close and current_rows["00891"].close:
        observations.append("半導體 ETF 與費半 ETF 提供高 beta 風險偏好觀察窗口。")
    if not observations:
        observations.append("今日資料尚不足以形成明確的跨族群輪動結論。")
    for item in observations:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 6. 台指期與 2330 期權")
    lines.append("")
    if taifex_futures_current:
        front = taifex_futures_current[0]
        prev_front = taifex_futures_prev[0] if taifex_futures_prev else None
        basis = front.last - to_float(index_close) if front.last is not None else None
        basis_pct = (basis / to_float(index_close) * 100.0) if basis is not None and to_float(index_close) else None
        front_oi_prev = prev_front.open_interest if prev_front and prev_front.open_interest is not None else None
        oi_change = (front.open_interest - front_oi_prev) if front.open_interest is not None and front_oi_prev is not None else None
        lines.append(
            md_table(
                ["指標", "今日", "前一交易日", "解讀"],
                [
                    [
                        "TX 近月",
                        f"{fmt_num(front.last, 0)}",
                        f"{fmt_num(prev_front.last, 0) if prev_front else 'NA'}",
                        f"基差 {fmt_num(basis, 0)} / {fmt_pct(basis_pct, 2)}",
                    ],
                    [
                        "TX 成交量",
                        f"{fmt_num(front.total_volume, 0)}",
                        f"{fmt_num(prev_front.total_volume, 0) if prev_front else 'NA'}",
                        "台指期短線活躍度",
                    ],
                    [
                        "TX 未平倉",
                        f"{fmt_num(front.open_interest, 0)}",
                        f"{fmt_num(front_oi_prev, 0) if front_oi_prev is not None else 'NA'}",
                        f"變化 {fmt_num(oi_change, 0)}",
                    ],
                ],
            )
        )
    else:
        lines.append("- TX 資料缺口。")
    lines.append("")

    txo_lines = select_option_lines(txo_summary, to_float(index_close))
    lines.append("### 6.1 台指選擇權（TXO）")
    for line in txo_lines:
        lines.append(line if line.startswith("-") or line == "資料缺口" else f"- {line}")
    lines.append("")

    # P0 完整選擇權鍊 + P1 Greeks（TXO）
    if txo_summary:
        twii_price = to_float(index_close) if index_close else None
        chain_table = _render_option_chain_table(txo_summary, twii_price, window=10)
        if chain_table:
            lines.append("#### TXO 完整選擇權鍊")
            lines.append(chain_table)
            lines.append("")

        # Greeks 表（ATM ±5）
        call_greeks = calc_option_chain_greeks(txo_summary.call_contracts, twii_price, txo_summary.expiry, current_date, opt_type="call")
        if call_greeks:
            atm_idx = min(range(len(call_greeks)), key=lambda i: abs(call_greeks[i].strike - (twii_price or 40000)))
            start_idx = max(0, atm_idx - 5)
            end_idx = min(len(call_greeks), atm_idx + 6)
            displayed_greeks = call_greeks[start_idx:end_idx]
            if displayed_greeks:
                lines.append("#### TXO Greeks（Call，ATM ±5）")
                greeks_rows = [[
                    str(int(g.strike)),
                    fmt_pct(g.iv * 100, 2) if g.iv else "NA",
                    fmt_num(g.delta, 3) if g.delta else "NA",
                    fmt_num(g.gamma, 4) if g.gamma else "NA",
                    fmt_num(g.vega, 3) if g.vega else "NA",
                    fmt_num(g.theta, 3) if g.theta else "NA",
                ] for g in displayed_greeks]
                lines.append(md_table(["執行價", "IV(%)", "Delta", "Gamma", "Vega", "Theta"], greeks_rows))
                lines.append("")

    cdo_lines = select_option_lines(cdo_summary, current_rows.get("2330").close if current_rows.get("2330") else None)
    lines.append("### 6.2 2330 台積電選擇權（近月）")
    for line in cdo_lines:
        lines.append(line if line.startswith("-") or line == "資料缺口" else f"- {line}")
    lines.append("")

    # P0 完整選擇權鍊 + P1 Greeks（CDO）
    if cdo_summary:
        stock_2330_price = current_rows.get("2330").close if current_rows.get("2330") else None
        chain_table = _render_option_chain_table(cdo_summary, stock_2330_price, window=10)
        if chain_table:
            lines.append("#### CDO 完整選擇權鍊")
            lines.append(chain_table)
            lines.append("")

        # Greeks 表（ATM ±5）
        call_greeks = calc_option_chain_greeks(cdo_summary.call_contracts, stock_2330_price, cdo_summary.expiry, current_date, opt_type="call")
        if call_greeks:
            atm_idx = min(range(len(call_greeks)), key=lambda i: abs(call_greeks[i].strike - (stock_2330_price or 2200)))
            start_idx = max(0, atm_idx - 5)
            end_idx = min(len(call_greeks), atm_idx + 6)
            displayed_greeks = call_greeks[start_idx:end_idx]
            if displayed_greeks:
                lines.append("#### CDO Greeks（Call，ATM ±5）")
                greeks_rows = [[
                    str(int(g.strike)),
                    fmt_pct(g.iv * 100, 2) if g.iv else "NA",
                    fmt_num(g.delta, 3) if g.delta else "NA",
                    fmt_num(g.gamma, 4) if g.gamma else "NA",
                    fmt_num(g.vega, 3) if g.vega else "NA",
                    fmt_num(g.theta, 3) if g.theta else "NA",
                ] for g in displayed_greeks]
                lines.append(md_table(["執行價", "IV(%)", "Delta", "Gamma", "Vega", "Theta"], greeks_rows))
                lines.append("")

    lines.append("## 7. 今日盤中大單彙總")
    lines.append("")
    if bigorder_summary:
        call_buy = bigorder_summary.get("call_buy", 0)
        call_sell = bigorder_summary.get("call_sell", 0)
        put_buy = bigorder_summary.get("put_buy", 0)
        put_sell = bigorder_summary.get("put_sell", 0)
        top_stocks = bigorder_summary.get("top_stocks", [])

        if call_buy or call_sell or put_buy or put_sell or top_stocks:
            lines.append("### 7.1 TXO 大單方向分佈（≥100 口）")
            lines.append(f"- Call 主動買：{call_buy} 口")
            lines.append(f"- Call 主動賣：{call_sell} 口")
            lines.append(f"- Put 主動買：{put_buy} 口")
            lines.append(f"- Put 主動賣：{put_sell} 口")
            lines.append("")

            if top_stocks:
                lines.append("### 7.2 個股大單前 3 名（≥500 張）")
                for stock in top_stocks:
                    symbol = stock.get("symbol", "N/A")
                    amount = stock.get("amount", 0)
                    lines.append(f"- {symbol}: {fmt_m(amount, 0)}")
                lines.append("")
        else:
            lines.append("- 無盤中大單記錄（監聽腳本未啟動或無符合條件的交易）")
            lines.append("")
    else:
        lines.append("- 無盤中大單記錄（監聽腳本未啟動）")
        lines.append("")

    lines.append("## 8. Fubon 即時擴展資料")
    lines.append("")
    if fubon_data:
        fubon_quotes_ext = fubon_data.get("quotes", {})
        fubon_hist = fubon_data.get("historical", {})
        fubon_tech = fubon_data.get("technical", {})
        fubon_account = fubon_data.get("account")

        # 7.1 K 線數據
        if fubon_hist:
            lines.append("### 7.1 近 5 日 K 線（Fubon）")
            for symbol in ["2330", "00891", "00830", "2881"]:
                if symbol in fubon_hist:
                    lines.append(f"- **{symbol}**:")
                    for candle in fubon_hist[symbol]:
                        if candle.date and candle.close is not None:
                            lines.append(
                                f"  {candle.date}: O={fmt_num(candle.open_, 2)} H={fmt_num(candle.high, 2)} "
                                f"L={fmt_num(candle.low, 2)} C={fmt_num(candle.close, 2)} V={fmt_m(candle.volume, 0)}"
                            )
            lines.append("")

        # 7.2 技術指標
        if fubon_tech:
            lines.append("### 7.2 技術指標（RSI / MACD / KDJ）")
            tech_rows = []
            for symbol in ["2330", "00891", "00830", "2881"]:
                if symbol in fubon_tech:
                    t = fubon_tech[symbol]
                    tech_rows.append([symbol, fmt_num(t.rsi, 2), fmt_num(t.macd, 4), fmt_num(t.kdj_k, 2)])
            if tech_rows:
                lines.append(md_table(["標的", "RSI(14)", "MACD", "KDJ-K"], tech_rows))
            lines.append("")

        # 7.3 期貨報價
        fubon_futopt = fubon_data.get("futopt", {})
        if fubon_futopt:
            lines.append("### 7.3 台股指數近月期貨（Fubon 即時）")
            tx_data = None
            for symbol in ["TXFB5", "TXF", "TX"]:
                if symbol in fubon_futopt:
                    tx_data = fubon_futopt[symbol]
                    break
            if tx_data:
                lines.append(
                    f"- TX 近月：last={fmt_num(tx_data.last, 0)}, change={fmt_num(tx_data.change, 2)}, "
                    f"vol={fmt_num(tx_data.volume, 0)}, OI={fmt_num(tx_data.open_interest, 0)}"
                )
            else:
                lines.append("- TX 近月期貨資料缺口")
            lines.append("")

        # 7.4 帳戶概況
        if fubon_account:
            lines.append("### 7.4 帳戶概況")
            lines.append(md_table(
                ["項目", "金額"],
                [
                    ["總資產", fmt_num(fubon_account.total_value, 2)],
                    ["可用資金", fmt_num(fubon_account.available, 2)],
                    ["股票市值", fmt_num(fubon_account.stock_value, 2)],
                    ["未實現損益", fmt_num(fubon_account.unrealized_pnl, 2)],
                ],
            ))
            lines.append("")
    else:
        lines.append("- Fubon Neo 未載入或未可用，本段落無數據。")
        lines.append("")

    lines.append("## 9. 隔日漲跌推估")
    lines.append("")
    if next_day_estimate:
        lines.append(f"- 推估方向：`{next_day_estimate.bias}`")
        lines.append(f"- 推估區間：`{next_day_estimate.change_range}`")
        lines.append(f"- 機械分數：`{next_day_estimate.score:+.2f}`")
        lines.append("- 依據：")
        for note in next_day_estimate.notes:
            lines.append(f"  - {note}")
    else:
        lines.append("- 資料不足，無法產生隔日漲跌推估。")
    lines.append("")

    lines.append("## 10. 資料缺口")
    lines.append("")
    gaps = []
    if not fubon_quotes:
        gaps.append("Fubon Neo 未載入或不可用，僅使用 TWSE 公開資料。")
    if not taifex_futures_current:
        gaps.append("TAIFEX 台指期資料缺口。")
    if txo_summary is None:
        gaps.append("TXO 台指選擇權資料缺口。")
    if cdo_summary is None:
        gaps.append("2330 台積電選擇權資料缺口。")
    if not index_close or index_close == "NA":
        gaps.append("TWII index row not found in TWSE daily tables.")
    for symbol in symbols:
        if symbol != "TWII" and symbol not in current_rows:
            gaps.append(f"{symbol} 當日 TWSE daily row 缺失。")
    if not gaps:
        gaps.append("無。")
    for gap in gaps:
        lines.append(f"- {gap}")
    lines.append("")

    lines.append("## 11. 備註")
    lines.append("")
    lines.append("- 若 Fubon Neo 可用，會作為即時備援；若不可用，不影響 TWSE 日終報表輸出。")
    lines.append("- 本報表以收盤後資料為準，適合 17:05 後自動排程。")
    lines.append("- 若遇休市或假日，腳本會回退至最近一個有交易資料的日期。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate TW market daily report.")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD, default: today in Asia/Taipei.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to track.")
    parser.add_argument("--output-dir", default=str(DOC_DIR), help="Output directory.")
    parser.add_argument("--json", action="store_true", help="Print metadata as JSON.")
    args = parser.parse_args()

    target_date = parse_date(args.date) if args.date else taipei_today()
    current_date, current_data, current_rows = find_latest_trading_day(target_date)
    prev_date, prev_data, prev_rows = find_latest_trading_day(current_date - dt.timedelta(days=1))
    t86 = fetch_twse_t86(current_date)
    fubon_quotes = fetch_fubon_quotes(args.symbols)
    taifex_futures_current = fetch_taifex_futures(current_date)
    taifex_futures_prev = fetch_taifex_futures(prev_date)
    twii_close_value = None
    if current_rows.get("TWII") and current_rows["TWII"].close is not None:
        twii_close_value = current_rows["TWII"].close
    elif current_data.get("tables"):
        try:
            for row in current_data["tables"][0].get("data") or []:
                if row and strip_html(row[0]) == "發行量加權股價指數":
                    twii_close_value = parse_taifex_number(row[1])
                    break
        except Exception:
            twii_close_value = None

    txo_summary = fetch_taifex_option_summary(current_date, "TXO", "", "TXO", twii_close_value)
    txo_prev_summary = fetch_taifex_option_summary(prev_date, "TXO", "", "TXO", twii_close_value)
    cdo_summary = fetch_taifex_option_summary(current_date, "specialid", "CDO", "2330選擇權(CDO)", current_rows.get("2330").close if current_rows.get("2330") else None)
    cdo_prev_summary = fetch_taifex_option_summary(prev_date, "specialid", "CDO", "2330選擇權(CDO)", current_rows.get("2330").close if current_rows.get("2330") else None)

    twii_close_num = to_float(str(twii_close_value)) if twii_close_value is not None else None
    current_twii_change_pct = None
    twii_volume_ratio = None
    if current_data.get("tables") and prev_data.get("tables"):
        try:
            cur_market_stats = market_stat_lookup(current_data["tables"][6].get("data") or [], "總計(1~15)")
            prev_market_stats = market_stat_lookup(prev_data["tables"][6].get("data") or [], "總計(1~15)")
            cur_vol = to_float(cur_market_stats.get("volume")) if cur_market_stats else None
            prev_vol = to_float(prev_market_stats.get("volume")) if prev_market_stats else None
            twii_volume_ratio = volume_ratio(cur_vol, prev_vol)
        except Exception:
            twii_volume_ratio = None

    close_2330 = current_rows.get("2330").close if current_rows.get("2330") else None
    close_2330_change_pct = None
    if current_rows.get("2330") and prev_rows.get("2330") and current_rows["2330"].close is not None and prev_rows["2330"].close not in (None, 0):
        close_2330_change_pct = (current_rows["2330"].close - prev_rows["2330"].close) / prev_rows["2330"].close * 100.0

    # TWII change % from the daily index table.
    try:
        for row in current_data["tables"][0].get("data") or []:
            if row and strip_html(row[0]) == "發行量加權股價指數":
                current_twii_change_pct = parse_taifex_number(row[4])
                break
    except Exception:
        current_twii_change_pct = None

    next_day_estimate = estimate_next_day_bias(
        twii_close_num,
        current_twii_change_pct,
        taifex_futures_current[0] if taifex_futures_current else None,
        taifex_futures_prev[0] if taifex_futures_prev else None,
        txo_summary,
        cdo_summary,
        twii_volume_ratio,
        close_2330,
        close_2330_change_pct,
    )

    # Fetch extended Fubon data (K-lines, technical indicators, account info)
    fubon_data = fetch_fubon_data(
        symbols=args.symbols,
        futopt_symbols=["TXFB5", "TXF", "TX"],  # Taiwan stock index futures symbols
    )

    # P3: Fetch big order summary
    bigorder_summary = fetch_bigorder_summary(current_date)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"cc_tw_market_fubon_daily_{current_date:%Y-%m-%d}.md"
    report = build_report(
        report_date=target_date,
        current_date=current_date,
        current_data=current_data,
        current_rows=current_rows,
        prev_date=prev_date,
        prev_data=prev_data,
        prev_rows=prev_rows,
        index_data=current_data,
        current_index_date=current_date,
        t86=t86,
        fubon_quotes=fubon_quotes,
        taifex_futures_current=taifex_futures_current,
        taifex_futures_prev=taifex_futures_prev,
        txo_summary=txo_summary,
        txo_prev_summary=txo_prev_summary,
        cdo_summary=cdo_summary,
        cdo_prev_summary=cdo_prev_summary,
        next_day_estimate=next_day_estimate,
        symbols=args.symbols,
        fubon_data=fubon_data,
        bigorder_summary=bigorder_summary,
    )
    report_path.write_text(report, encoding="utf-8")

    if args.json:
        print(
            json.dumps(
                {
                    "report_path": str(report_path),
                    "current_date": current_date.isoformat(),
                    "previous_date": prev_date.isoformat(),
                    "symbols": args.symbols,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"REPORT_PATH={report_path}")
        print(f"CURRENT_DATE={current_date:%Y-%m-%d}")
        print(f"PREVIOUS_DATE={prev_date:%Y-%m-%d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
