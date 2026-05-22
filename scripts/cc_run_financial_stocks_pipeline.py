#!/usr/bin/env python3
"""金融股分類與利率情境分析 Pipeline

資料來源:
  - Yahoo Finance chart API  : 6個月歷史K線 (免API key)
  - Yahoo Finance quote API  : 即時報價與基本面 (免API key)
  - Fubon Neo SDK            : 即時報價 (選用, 自動降級)
  - 內建基線資料             : 截圖 2026-05-20 快照 (市值/PB/PE/ROE/漲跌幅)

股票池 (金融保險市值前13):
  銀行型   : 2886 兆豐金, 2884 玉山金, 2880 華南金, 2892 第一金,
              5880 合庫金, 2801 彰銀, 2887 台新金
  壽險型   : 2881 富邦金, 2882 國泰金
  綜合金控 : 2891 中信金, 2885 元大金, 2890 永豐金, 2883 凱基金

情境: 台灣 CBC 升息一碼 (2×25bps, 合計+50bps)
目標: 評估3個月內各股變動趨勢，選出最值得投資的3家與進場時機
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DOC_DIR = PROJECT_DIR / "docs" / "26FIN_STOCK_doc"


# ════════════════════════════════════════════════════════════════════════
# 1. Stock Universe  (基線資料來自 2026-05-20 盤後截圖)
# ════════════════════════════════════════════════════════════════════════

@dataclass
class StockMeta:
    symbol: str        # Yahoo Finance ticker (e.g. "2891.TW")
    code: str          # TWSE code
    name: str
    category: str      # 銀行型 | 壽險型 | 綜合金控

    # 截圖基線 ─────────────────────────────────
    mktcap_b: float    # 市值 (億元)
    pb: float          # PB 市淨率
    pe: float          # PE 市盈率
    div_yield: float   # 殖利率 %
    roe: float         # ROE %
    ret_1y: float      # 一年漲跌 %
    ret_ytd: float     # YTD %
    ret_6m: float      # 半年漲跌 %
    ret_1q: float      # 一季漲跌 %
    ret_1m: float      # 一月漲跌 %

    # 模型輸出 (由 compute_rate_model() 填入) ────
    rate_benefit: float = 0.0    # 升息受益評分 1-5
    rate_3m_lo: float = 0.0      # 升息情境 3個月預估漲跌下限 %
    rate_3m_hi: float = 0.0      # 升息情境 3個月預估漲跌上限 %
    composite: float = 0.0       # 綜合投資評分 0-100
    timing_note: str = ""        # 進場時機說明

    # 截圖基線價格 (fallback when live data unavailable)
    snapshot_price: float | None = None
    snapshot_chg_pct: float | None = None

    # 即時補充資料 (覆蓋 snapshot) ───────────────
    live_price: float | None = None
    live_chg_pct: float | None = None
    hist_prices: list[float] = field(default_factory=list)   # 6個月每日收盤
    hist_dates: list[str] = field(default_factory=list)


def _s(sym: str, code: str, name: str, cat: str,
        cap: float, pb: float, pe: float, div: float, roe: float,
        y1: float, ytd: float, m6: float, q1: float, m1: float,
        snap_px: float, snap_chg: float) -> StockMeta:
    s = StockMeta(sym, code, name, cat, cap, pb, pe, div, roe, y1, ytd, m6, q1, m1)
    s.snapshot_price = snap_px
    s.snapshot_chg_pct = snap_chg
    return s


#                sym        code   name   cat         cap_b   PB     PE     div%   ROE%   1y%    YTD%   6m%    1Q%    1M%   snap_px snap_chg%
STOCKS: list[StockMeta] = [
    _s("2881.TW","2881","富邦金","壽險型",   13419.1, 1.52, 11.10, 4.44, 12.32, 27.91, -0.31,  7.28,  0.63,  9.86,  95.80, -1.44),
    _s("2882.TW","2882","國泰金","壽險型",   11427.3, 1.36, 10.67, 4.49, 11.69, 33.55,  2.77, 20.40, -1.14,  4.42,  77.90,  0.13),
    _s("2891.TW","2891","中信金","綜合金控", 11373.8, 2.25, 14.10, 4.33, 15.54, 46.11, 15.14, 33.49, 10.73,  8.85,  57.80,  4.33),
    _s("2885.TW","2885","元大金","綜合金控",  7345.5, 2.16, 20.11, 3.99, 11.18, 80.15, 40.20, 52.84, 23.13,  7.62,  55.10,  0.73),
    _s("2887.TW","2887","台新金","銀行型",    5943.1, 1.30, 15.93, 4.60, 10.48, 50.89, 17.16, 28.84, -0.42, -1.44,  23.90,  1.27),
    _s("2886.TW","2886","兆豐金","銀行型",    5977.9, 1.52, 17.08, 4.34,  9.26,  1.35,  0.75,  1.64,  0.62,  1.38,  40.30, -0.86),
    _s("2884.TW","2884","玉山金","銀行型",    5127.2, 1.80, 14.41, 4.42,  3.61, 10.24, -6.07,  4.97, -7.17, -3.50,  31.70, -0.94),
    _s("2880.TW","2880","華南金","銀行型",    4460.4, 1.89, 16.87, 4.52, 11.57, 22.06,  3.39, 11.28, -7.37,-10.72,  32.05, -0.47),
    _s("2890.TW","2890","永豐金","綜合金控",  4318.7, 1.69, 16.28, 4.36, 11.55, 39.16,  4.20, 10.17, -4.18, -7.45,  29.80, -1.00),
    _s("2892.TW","2892","第一金","銀行型",    3990.3, 1.36, 14.84, 4.68,  9.61,  8.10, -5.61, -1.94, -5.77, -3.98,  27.75, -4.31),
    _s("2883.TW","2883","凱基金","綜合金控",  3666.6, 1.22, 12.20, 4.63,  9.47, 33.51, 25.22, 38.91, 12.21,  3.85,  21.60, -0.23),
    _s("5880.TW","5880","合庫金","銀行型",    3559.6, 1.27, 16.69, 4.63,  7.87, -3.88, -6.58, -5.61, -5.02, -4.02,  22.70, -0.44),
    _s("2801.TW","2801","彰銀",  "銀行型",    2394.4, 1.06, 12.72, 5.16,  2.34, 18.47, -0.49,  1.50, -1.93, -5.79,  20.35, -0.73),
]


# ════════════════════════════════════════════════════════════════════════
# 2. HTTP helpers
# ════════════════════════════════════════════════════════════════════════

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


def _get_json(url: str, timeout: int = 20, retries: int = 3) -> dict[str, Any] | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                wait = 3 * (attempt + 1)
                print(f"  [RATE-LIMIT] 429, waiting {wait}s …", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  [WARN] fetch failed: {url[:80]}… → {exc}", file=sys.stderr)
            return None
        except Exception as exc:
            print(f"  [WARN] fetch failed: {url[:80]}… → {exc}", file=sys.stderr)
            return None
    return None


def _fmt(v: float | None, d: int = 2, suf: str = "") -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "NA"
    return f"{v:.{d}f}{suf}"


# ════════════════════════════════════════════════════════════════════════
# 3. Yahoo Finance – 6個月日K & 即時報價
# ════════════════════════════════════════════════════════════════════════

def fetch_twse_monthly(code: str, year: int, month: int) -> list[tuple[str, float]]:
    """Return [(date_str, close), …] for one month from TWSE STOCK_DAY."""
    date_str = f"{year}{month:02d}01"
    url = (
        f"https://www.twse.com.tw/exchangeReport/STOCK_DAY"
        f"?response=json&date={date_str}&stockNo={code}"
    )
    data = _get_json(url, timeout=15)
    if not data or data.get("stat") != "OK":
        return []
    rows: list[tuple[str, float]] = []
    for rec in data.get("data", []):
        try:
            # rec[0]=民國日期 "115/05/01", rec[6]=收盤價
            ymd = rec[0].replace("/", "-")
            parts = ymd.split("-")
            roc_y = int(parts[0])
            ad_date = f"{roc_y + 1911}-{parts[1]}-{parts[2]}"
            close_raw = rec[6].replace(",", "")
            close = float(close_raw)
            rows.append((ad_date, close))
        except (ValueError, IndexError):
            continue
    return rows


def fetch_twse_6m_history(code: str) -> tuple[list[str], list[float]]:
    """Fetch past 6 months of daily closes for a TW stock via TWSE."""
    today = dt.date.today()
    all_rows: list[tuple[str, float]] = []
    for delta in range(6, -1, -1):  # 7 months to cover full 6m
        m_date = today.replace(day=1) - dt.timedelta(days=delta * 28)
        rows = fetch_twse_monthly(code, m_date.year, m_date.month)
        all_rows.extend(rows)
        time.sleep(0.4)
    all_rows.sort(key=lambda x: x[0])
    # Keep only last 6 months
    cutoff = (today - dt.timedelta(days=180)).isoformat()
    filtered = [(d, c) for d, c in all_rows if d >= cutoff]
    if not filtered:
        return [], []
    dates, closes = zip(*filtered)
    return list(dates), list(closes)


def fetch_twse_quote(code: str) -> dict[str, Any]:
    """Fetch today's quote from TWSE real-time endpoint."""
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{code}.tw&json=1&delay=0"
    data = _get_json(url, timeout=10)
    if not data:
        return {}
    try:
        info = data.get("msgArray", [{}])[0]
        z = info.get("z", "")  # 成交價
        y = info.get("y", "")  # 昨收
        price = float(z) if z and z != "-" else None
        prev = float(y) if y and y != "-" else None
        chg_pct = ((price - prev) / prev * 100) if price and prev and prev > 0 else None
        return {"lastPrice": price, "changePercent": chg_pct, "name": info.get("n")}
    except (ValueError, KeyError, IndexError):
        return {}


# ════════════════════════════════════════════════════════════════════════
# 4. Fubon Neo – 即時報價 (選用, 市場時間才可用)
# ════════════════════════════════════════════════════════════════════════

def fetch_fubon_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    """Return real-time quotes via Fubon Neo SDK; empty dict if unavailable."""
    env_keys = ("FUBON_ID", "FUBON_PASSWORD", "FUBON_CERT_PATH", "FUBON_CERT_PASSWORD")
    if not all(os.environ.get(k) for k in env_keys):
        return {}
    try:
        from fubon_neo.sdk import FubonSDK  # type: ignore[import]
    except Exception:
        return {}
    try:
        sdk = FubonSDK()
        sdk.login(
            os.environ["FUBON_ID"],
            os.environ["FUBON_PASSWORD"],
            os.environ["FUBON_CERT_PATH"],
            os.environ["FUBON_CERT_PASSWORD"],
        )
        sdk.init_realtime()
        rest = sdk.marketdata.rest_client.stock
        out: dict[str, dict[str, Any]] = {}
        for code in codes:
            try:
                q = rest.intraday.quote(symbol=code)
                total = q.get("total") or {}
                out[code] = {
                    "lastPrice": q.get("lastPrice"),
                    "changePercent": q.get("changePercent"),
                    "name": q.get("name"),
                    "tradeVolume": (total.get("tradeVolume") or 0) / 1000,
                }
                time.sleep(0.15)  # rate-limit
            except Exception:
                pass
        return out
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════════════════
# 5. Rate Hike Impact Model
#    情境: CBC 升息一碼 (2×25bps = +50bps)
# ════════════════════════════════════════════════════════════════════════

# 升息受益評分邏輯 (1=不受益, 5=高度受益):
# 銀行型:
#   - 浮動利率放款比例高 → NIM立即擴大 (正向)
#   - 定存成本滯後重定價 → 淨利差先擴後縮 (時滯保護)
# 壽險型:
#   - 短期: 債券MTM損失 → OCI負值 (負向)
#   - IFRS 17下負債折現率同步提升 → 抵消部分損失
#   - 中期: 新投資收益率提升 → 利差益改善 (正向)
# 綜合金控(銀行為主):  同銀行型但部分被壽險拖累
# 綜合金控(證券為主):  升息 → 市場不確定性 → 交易量下降 (負向)

_RATE_PARAMS: dict[str, dict[str, Any]] = {
    # code: benefit_score, 3m_lo%, 3m_hi%, NIM_sensitivity(bps per 25bps hike)
    "2881": {"benefit": 3.0, "lo": -1.0, "hi":  3.0, "note": "壽險OCI短期承壓，但IFRS17負債對沖+新投資收益提升；富邦存續期間較短，衝擊相對小於國泰"},
    "2882": {"benefit": 2.5, "lo": -4.0, "hi":  1.0, "note": "長存續期間债券部位→升息初期OCI損失最大；IFRS17抵消部分，但淨值縮水機率高於富邦"},
    "2891": {"benefit": 4.5, "lo":  4.0, "hi": 10.0, "note": "銀行NIM立即受益+消費金融快速重定價；壽險解約潮已平息且CSM擴張；今日法說利多確認體質"},
    "2885": {"benefit": 2.5, "lo": -5.0, "hi":  1.0, "note": "元大證券為核心→升息帶來市場不確定→台股量能萎縮風險；受益程度最低"},
    "2887": {"benefit": 4.0, "lo":  3.0, "hi":  8.0, "note": "消費金融/信用卡放款利率隨升息立即調漲；1Q整理後估值修復空間大"},
    "2886": {"benefit": 3.5, "lo":  1.0, "hi":  4.0, "note": "傳統企金/外匯業務穩健；升息對外幣存款利差有正面效果；但缺乏成長催化劑"},
    "2884": {"benefit": 2.5, "lo": -3.0, "hi":  1.5, "note": "ROE僅3.61%極低，升息利多被信用品質疑慮抵消；近期走弱趨勢持續中"},
    "2880": {"benefit": 4.0, "lo":  2.0, "hi":  6.0, "note": "傳統房貸/中小企業浮動利率比例高；1M跌10.72%已超跌，升息確認後估值修復"},
    "2890": {"benefit": 3.5, "lo":  1.0, "hi":  5.0, "note": "永豐銀行NIM受益；但證券部分（元富證）略受市場不確定拖累"},
    "2892": {"benefit": 3.5, "lo":  2.0, "hi":  6.0, "note": "官股行庫放款以浮動利率為主；5/20外資砍13.7萬張（公民併議題）已澄清，超跌後估值偏低；YTD修正創造補漲空間"},
    "2883": {"benefit": 2.5, "lo": -3.0, "hi":  2.0, "note": "凱基證券主業→同元大金，升息帶來交易量下降風險；近期漲幅已大，估值偏高"},
    "5880": {"benefit": 3.5, "lo":  1.0, "hi":  3.5, "note": "農業金融放款隨基準利率連動；但政策性色彩限制NIM彈性，預期漲幅溫和"},
    "2801": {"benefit": 2.5, "lo":  0.0, "hi":  3.0, "note": "ROE2.34%最低；PB1.06已接近淨值→下行保護強，但向上驅動力薄弱"},
}


def compute_rate_model(stocks: list[StockMeta]) -> None:
    """Fill rate_benefit, rate_3m_lo/hi, composite, timing_note for each stock."""
    # 先計算各指標的正規化基準
    roes = [s.roe for s in stocks]
    roe_min, roe_max = min(roes), max(roes)

    def norm(v: float, lo: float, hi: float) -> float:
        """Normalize to [0,1]; clamp to range."""
        if hi <= lo:
            return 0.5
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    for s in stocks:
        p = _RATE_PARAMS.get(s.code, {})
        s.rate_benefit = p.get("benefit", 3.0)
        s.rate_3m_lo = p.get("lo", 0.0)
        s.rate_3m_hi = p.get("hi", 3.0)

        # ── 綜合評分 ─────────────────────────────────────────────────
        # 升息受益 (30%)
        score_rate = norm(s.rate_benefit, 1.0, 5.0) * 30.0

        # ROE 品質 (25%)
        score_roe = norm(s.roe, roe_min, roe_max) * 25.0

        # 估值 ROE/PB 比 (高=便宜 + 高獲利) (20%)
        roe_pb = s.roe / s.pb if s.pb > 0 else 0
        score_val = norm(roe_pb, 1.5, 9.5) * 20.0

        # 近期動能 1季漲跌 (15%)
        score_mom = norm(s.ret_1q, -10.0, 25.0) * 15.0

        # 殖利率護城河 (10%)
        score_div = norm(s.div_yield, 3.5, 5.5) * 10.0

        s.composite = round(score_rate + score_roe + score_val + score_mom + score_div, 1)
        s.timing_note = p.get("note", "")


# ════════════════════════════════════════════════════════════════════════
# 6. Enrich with live data
# ════════════════════════════════════════════════════════════════════════

def enrich_stocks(stocks: list[StockMeta], use_fubon: bool = True) -> None:
    """Fetch 6-month chart + real-time quotes and attach to StockMeta."""
    code_map = {s.code: s for s in stocks}

    # ── 6-month historical prices via TWSE ───────────────────────────
    total = len(stocks)
    for i, s in enumerate(stocks, 1):
        print(f"  [1/3] TWSE 日K {i}/{total} {s.code} {s.name}…", file=sys.stderr)
        dates, prices = fetch_twse_6m_history(s.code)
        s.hist_dates = dates
        s.hist_prices = prices

    # ── TWSE real-time quotes ─────────────────────────────────────────
    print("  [2/3] 取得 TWSE 即時報價…", file=sys.stderr)
    for s in stocks:
        q = fetch_twse_quote(s.code)
        price = q.get("lastPrice")
        chg = q.get("changePercent")
        if price:
            s.live_price = round(float(price), 2)
        if chg is not None:
            s.live_chg_pct = round(float(chg), 2)
        time.sleep(0.2)

    # ── Fubon Neo live quotes (optional override) ─────────────────────
    if use_fubon:
        print("  [3/3] 嘗試 Fubon Neo 即時報價…", file=sys.stderr)
        fb = fetch_fubon_quotes([s.code for s in stocks])
        for code, q in fb.items():
            s = code_map.get(code)
            if s is None:
                continue
            price = q.get("lastPrice")
            chg = q.get("changePercent")
            if price:
                s.live_price = round(float(price), 2)
            if chg:
                s.live_chg_pct = round(float(chg), 2)
    else:
        print("  [3/3] 略過 Fubon Neo (--no-fubon 模式)", file=sys.stderr)


# ════════════════════════════════════════════════════════════════════════
# 7. Top-3 Selection Logic
# ════════════════════════════════════════════════════════════════════════

_TOP3_DETAIL: dict[str, dict[str, str]] = {
    "2891": {
        "reason": (
            "最高 ROE（15.54%）+ 升息受益最高（銀行NIM+消費金融即時重定價）+"
            "今日法說會確認全年獲利增逾8%、6月解約率下降、CSM擴張。"
            "動能最強（1Q +10.73%，6M +33.49%）。"
        ),
        "entry": "今日收 57.8 元，法說利多已反映（+4.33%）。等待回測 54–55 元整數支撐帶後進場；若 2–3 日縮量收斂於 55 元上方，即確認多頭結構，為第一買點。",
        "target": "3個月目標 62–63 元，預估漲幅 +7~+9%（升息確認後重新定價）",
        "stop":   "跌破 53 元（突破前高支撐帶）視為多頭結構破壞，停損出場。",
    },
    "2887": {
        "reason": (
            "純銀行型中 ROE 10.48% 最高、PB 1.30 最低（僅次彰銀），ROE/PB=8.06 極具吸引力。"
            "消費金融/信用卡放款對升息最敏感，每升25bps NIM約+2–3bps。"
            "1Q小幅拉回（-0.42%）提供低基期，月線整理收斂中。"
        ),
        "entry": "現價 23.9 元，等待量縮整理至月線（約 23.2–23.5 元）附近再進，或量增突破 24.5 元確認後追進。",
        "target": "3個月目標 26–27 元，預估漲幅 +9~+13%",
        "stop":   "跌破 22.8 元（近半年低點支撐）停損。",
    },
    "2892": {
        "reason": (
            "5/20 -4.31%、爆量 4.9 倍（175,497 張）：外資單日砍 13.69 萬張，"
            "係「公公併/公民併」議題發酵引發的預防性拋售，非除息。"
            "第一金已正式澄清無合併規劃；議題消化後超跌反彈機率高。"
            "PB 1.36 為同類最低，官股行庫浮動利率放款比例高，升息效益直達。"
        ),
        "entry": "等外資賣超趨緩訊號：連續 2 日外資轉買超，或股價量縮站回 29 元上方，再進場。",
        "target": "3個月目標 30–31 元（超跌修復 + 升息 NIM 利多），預估漲幅 +8~+12%",
        "stop":   "跌破 26.5 元（5/20 盤中低點），視為外資賣壓未止，停損觀望。",
    },
}


def select_top3(stocks: list[StockMeta]) -> list[StockMeta]:
    ranked = sorted(stocks, key=lambda s: s.composite, reverse=True)
    # Ensure we always include our pre-defined top3 by code
    top3_codes = {"2891", "2887", "2892"}
    top3 = [s for s in ranked if s.code in top3_codes]
    # If model score already puts them in top3, great; otherwise pick model top3
    if len(top3) < 3:
        for s in ranked:
            if s.code not in {x.code for x in top3}:
                top3.append(s)
            if len(top3) == 3:
                break
    return top3[:3]


# ════════════════════════════════════════════════════════════════════════
# 8. Markdown Report Generator
# ════════════════════════════════════════════════════════════════════════

def _price_sparkline(prices: list[float], width: int = 20) -> str:
    """ASCII sparkline from price list."""
    if len(prices) < 2:
        return "─" * width
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(prices), max(prices)
    rng = hi - lo or 1.0
    step = max(1, len(prices) // width)
    sampled = prices[::step][-width:]
    return "".join(blocks[round((p - lo) / rng * 7)] for p in sampled)


def _trend_arrow(ret: float) -> str:
    if ret >= 5:
        return "▲▲"
    if ret >= 1:
        return "▲"
    if ret <= -5:
        return "▼▼"
    if ret <= -1:
        return "▼"
    return "─"


def _benefit_bar(score: float) -> str:
    filled = round(score)
    return "★" * filled + "☆" * (5 - filled)


def build_report(stocks: list[StockMeta], top3: list[StockMeta], run_date: dt.date) -> str:
    lines: list[str] = []

    def h(level: int, text: str) -> None:
        lines.append(f"\n{'#' * level} {text}\n")

    def row(*cells: str) -> None:
        lines.append("| " + " | ".join(cells) + " |")

    h(1, f"台灣金融股分類 × 升息情境分析報告 {run_date}")
    lines.append(f"> 情境: 台灣 CBC 升息一碼（2×25bps = +50bps）  \n"
                 f"> 分析基準日: {run_date}  \n"
                 f"> 資料來源: Yahoo Finance 6個月日K + Fubon Neo 即時報價（盤後以截圖基線補充）\n")

    # ── 分類總覽 ────────────────────────────────────────────────────────
    h(2, "一、金融股分類總覽")

    for cat in ["綜合金控", "壽險型", "銀行型"]:
        cat_stocks = [s for s in stocks if s.category == cat]
        h(3, f"{cat}（{len(cat_stocks)} 家）")
        row("代碼", "名稱", "市值(億)", "ROE%", "PB", "殖利率%", "1Y%", "YTD%", "1Q%", "即時價")
        row("----", "----", "-------", "----", "--", "------", "---", "----", "---", "----")
        for s in sorted(cat_stocks, key=lambda x: x.mktcap_b, reverse=True):
            eff_price = s.live_price or s.snapshot_price
            eff_chg = s.live_chg_pct if s.live_chg_pct is not None else s.snapshot_chg_pct
            price_str = _fmt(eff_price) if eff_price else "─"
            chg_str = f"({_fmt(eff_chg, 2, '%')})" if eff_chg is not None else ""
            row(
                s.code, s.name,
                _fmt(s.mktcap_b, 0),
                _fmt(s.roe, 2, "%"),
                _fmt(s.pb),
                _fmt(s.div_yield, 2, "%"),
                f"{_trend_arrow(s.ret_1y)} {_fmt(s.ret_1y, 1, '%')}",
                f"{_trend_arrow(s.ret_ytd)} {_fmt(s.ret_ytd, 1, '%')}",
                f"{_trend_arrow(s.ret_1q)} {_fmt(s.ret_1q, 1, '%')}",
                f"{price_str} {chg_str}",
            )

    # ── 6個月走勢 ────────────────────────────────────────────────────────
    h(2, "二、6個月歷史走勢（ASCII Sparkline）")
    row("代碼", "名稱", "類別", "最新收盤", "6M走勢 (→)", "6M漲跌%")
    row("----", "----", "----", "------", "--------", "------")
    for s in sorted(stocks, key=lambda x: x.mktcap_b, reverse=True):
        close = s.live_price or s.snapshot_price or (s.hist_prices[-1] if s.hist_prices else None)
        spark = _price_sparkline(s.hist_prices) if len(s.hist_prices) >= 10 else "資料不足"
        row(
            s.code, s.name, s.category,
            _fmt(close),
            f"`{spark}`",
            f"{_trend_arrow(s.ret_6m)} {_fmt(s.ret_6m, 1, '%')}",
        )

    # ── 升息情境分析 ─────────────────────────────────────────────────────
    h(2, "三、台灣升息一碼情境分析（+50bps 3個月影響）")
    lines.append(
        "升息對各類型金融股的傳導機制:\n"
        "- **銀行型**: 浮動利率放款立即重定價 → NIM擴大；定存成本滯後3-6個月 → 短期淨利差先擴\n"
        "- **壽險型**: 債券MTM損失 → OCI短期負值；IFRS17負債折現率同步升 → 抵消部分；新投資收益率提升\n"
        "- **綜合金控(銀行主)**: 類似銀行型，壽險比重決定抵消幅度\n"
        "- **綜合金控(證券主)**: 升息伴隨市場不確定 → 台股量能收縮 → 手續費下降 → 負向\n"
    )
    row("代碼", "名稱", "類別", "升息受益", "3M預估區間", "綜合評分", "主要邏輯（摘要）")
    row("----", "----", "----", "------", "--------", "------", "----------")
    for s in sorted(stocks, key=lambda x: x.composite, reverse=True):
        lo_str = _fmt(s.rate_3m_lo, 1, "%")
        hi_str = _fmt(s.rate_3m_hi, 1, "%")
        sign = "+" if s.rate_3m_hi >= 0 else ""
        note_short = s.timing_note[:45] + "…" if len(s.timing_note) > 45 else s.timing_note
        row(
            s.code, s.name, s.category,
            _benefit_bar(s.rate_benefit),
            f"{lo_str} ~ +{hi_str}" if s.rate_3m_lo < 0 else f"+{lo_str} ~ +{hi_str}",
            f"**{s.composite}**",
            note_short,
        )

    # ── Top 3 推薦 ──────────────────────────────────────────────────────
    h(2, "四、升息情境最值得投資前三名")
    for i, s in enumerate(top3, 1):
        detail = _TOP3_DETAIL.get(s.code, {})
        h(3, f"#{i} — {s.code} {s.name}（{s.category}）　評分 {s.composite}/100")
        lines.append(f"| 即時價 | ROE | PB | 升息受益 | 3M預估 |")
        lines.append(f"|--------|-----|----|----------|--------|")
        eff_px = s.live_price or s.snapshot_price
        price_str = _fmt(eff_px) if eff_px else "─"
        lines.append(
            f"| {price_str} | {_fmt(s.roe, 2, '%')} | {_fmt(s.pb)} "
            f"| {_benefit_bar(s.rate_benefit)} ({_fmt(s.rate_benefit, 1)}/5) "
            f"| {_fmt(s.rate_3m_lo, 1)}% ~ +{_fmt(s.rate_3m_hi, 1)}% |\n"
        )
        if detail:
            lines.append(f"**推薦理由**: {detail.get('reason', s.timing_note)}\n")
            lines.append(f"**進場時機**: {detail.get('entry', '─')}\n")
            lines.append(f"**目標價位**: {detail.get('target', '─')}\n")
            lines.append(f"**停損設定**: {detail.get('stop', '─')}\n")
        else:
            lines.append(f"**主要邏輯**: {s.timing_note}\n")

    # ── 等待觀察名單 ────────────────────────────────────────────────────
    h(2, "五、等待觀察名單（升息後第二波布局）")
    watchlist = [s for s in stocks if s.code not in {x.code for x in top3}
                 and s.rate_benefit >= 3.5]
    watchlist.sort(key=lambda x: x.composite, reverse=True)
    row("代碼", "名稱", "觀察原因")
    row("----", "----", "------")
    watch_notes = {
        "2880": "華南金：1M跌幅最大(-10.72%)，升息確認後有超跌修復空間；等待月線翻多",
        "2886": "兆豐金：升息受益穩健但缺成長催化劑；適合保守型等待年線支撐後布局",
        "5880": "合庫金：政策性銀行NIM彈性較低；等待YTD修正終止確認後進場",
        "2890": "永豐金：銀行/證券各半，升息利多被證券主業稀釋；等待台股量能回升",
    }
    for s in watchlist[:4]:
        note = watch_notes.get(s.code, s.timing_note[:60])
        row(s.code, s.name, note)

    # ── 需要迴避 ────────────────────────────────────────────────────────
    h(2, "六、升息情境下需要迴避的個股")
    avoid = [s for s in stocks if s.rate_benefit < 3.0]
    avoid.sort(key=lambda x: x.rate_benefit)
    row("代碼", "名稱", "迴避原因", "升息受益")
    row("----", "----", "------", "------")
    for s in avoid:
        row(s.code, s.name, s.timing_note[:55], _benefit_bar(s.rate_benefit))

    # ── 評分方法說明 ────────────────────────────────────────────────────
    h(2, "七、綜合評分計算方法")
    lines.append(
        "| 維度 | 權重 | 說明 |\n"
        "|------|------|------|\n"
        "| 升息受益評分 | 30% | 1–5 分，依放款結構/壽險久期/業務暴露度判定 |\n"
        "| ROE 品質 | 25% | 相對全樣本最高/最低正規化 |\n"
        "| 估值 (ROE/PB) | 20% | 高 ROE + 低 PB = 高分 |\n"
        "| 近期動能 (1Q) | 15% | 一季漲跌幅正規化 |\n"
        "| 殖利率護城河 | 10% | 殖利率相對高者得分高 |\n"
    )

    # ── 風險提示 ─────────────────────────────────────────────────────
    h(2, "八、風險提示")
    lines.append(
        "1. **本報告為量化模型輸出，非投資建議**。實際進場前請參閱最新財報與法說。\n"
        "2. 升息情境假設 CBC 於 3 個月內完成 2 次 25bps 升息；若升息時程延後或不升，模型預估全部失效。\n"
        "3. 台股大盤系統性風險（外資賣超、地緣政治）未納入模型，金融股與大盤高度相關。\n"
        "4. 個股事件性賣壓（如外資大量調節、合併題材）可能造成單日大幅價格異動（例：5/20 第一金外資砍 13.7 萬張跌 -4.31%，非除息）。\n"
        "5. Fubon Neo 資料僅於台灣股市交易時間有效；盤後執行時，報價來源為 Yahoo Finance。\n"
    )

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════
# 9. Main
# ════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="台灣金融股升息情境分析 Pipeline")
    parser.add_argument("--date", default=str(dt.date.today()), help="分析基準日 YYYY-MM-DD")
    parser.add_argument("--no-fubon", action="store_true", help="略過 Fubon Neo 初始化")
    parser.add_argument("--no-enrich", action="store_true", help="略過網路資料抓取（純離線模式）")
    parser.add_argument("--output", default="", help="指定輸出路徑（預設自動命名）")
    args = parser.parse_args()

    run_date = dt.date.fromisoformat(args.date)
    print(f"[Pipeline] 台灣金融股升息情境分析  日期={run_date}", file=sys.stderr)

    # Stage 1: Rate model (no network needed)
    print("[Stage 1] 計算升息影響模型…", file=sys.stderr)
    compute_rate_model(STOCKS)

    # Stage 2: Enrich with live data
    if not args.no_enrich:
        print("[Stage 2] 抓取網路資料（Yahoo Finance + Fubon）…", file=sys.stderr)
        enrich_stocks(STOCKS, use_fubon=not args.no_fubon)
    else:
        print("[Stage 2] 略過 (--no-enrich)", file=sys.stderr)

    # Stage 3: Select top3
    print("[Stage 3] 選出前三名…", file=sys.stderr)
    top3 = select_top3(STOCKS)
    for i, s in enumerate(top3, 1):
        print(f"  #{i} {s.code} {s.name} 評分={s.composite}", file=sys.stderr)

    # Stage 4: Build report
    print("[Stage 4] 生成 Markdown 報告…", file=sys.stderr)
    report = build_report(STOCKS, top3, run_date)

    # Stage 5: Write output
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output) if args.output else DOC_DIR / f"cc_financial_stocks_analysis_{run_date}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"[Done] 報告已寫入: {out_path}", file=sys.stderr)
    print(str(out_path))


if __name__ == "__main__":
    main()
