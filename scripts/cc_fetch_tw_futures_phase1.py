#!/usr/bin/env python3
"""
Phase 1 資料建置：抓取指定月份的 TWSE 加權指數 + TAIFEX 台指期(TX) 日資料
輸出：data/tw_futures/twse_taiex_YYYYMM.csv
      data/tw_futures/taifex_tx_YYYYMM.csv

用法：
  python3 scripts/cc_fetch_tw_futures_phase1.py --ym 202603
  python3 scripts/cc_fetch_tw_futures_phase1.py --ym 202603 --output-dir data/tw_futures
"""

import argparse
import csv
import datetime as dt
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
SLEEP_SEC = 1.2  # TAIFEX 每次請求間隔


# ── TWSE ──────────────────────────────────────────────────────────────────────

def fetch_twse_month(year_month: str) -> list[dict]:
    """
    呼叫 TWSE FMTQIK API，取得整個月的加權指數價量資料。
    year_month: 'YYYYMM'
    回傳 list of dict，每筆一個交易日。
    """
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
    params = {"date": f"{year_month}01", "response": "json"}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("stat") != "OK":
        print(f"[TWSE] stat={data.get('stat')}, 本月可能無資料", file=sys.stderr)
        return []

    fields = data.get("fields", [])
    rows = []
    for raw in data.get("data", []):
        row = dict(zip(fields, raw))
        # 將民國日期轉成西元
        roc_date = row.get("日期", "")  # 例 "115/03/03"
        try:
            parts = roc_date.split("/")
            ce_year = int(parts[0]) + 1911
            date_str = f"{ce_year}/{parts[1]}/{parts[2]}"
        except Exception:
            date_str = roc_date

        def clean(v: str) -> str:
            return v.replace(",", "").strip()

        rows.append({
            "date":         date_str,
            "taiex":        clean(row.get("發行量加權股價指數", "")),
            "change":       clean(row.get("漲跌點數", "")),
            "volume_shares": clean(row.get("成交股數", "")),
            "amount_twd":   clean(row.get("成交金額", "")),
            "transactions": clean(row.get("成交筆數", "")),
        })
    return rows


# ── TAIFEX ────────────────────────────────────────────────────────────────────

def _parse_taifex_table(html: str) -> list[dict]:
    """從 TAIFEX 日行情 HTML 解析 TX 所有契約月份的一列資料。"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="table_f")
    if not table:
        return []

    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    headers_raw = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]

    results = []
    for row in rows[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all(["th", "td"])]
        if not cells or cells[0] != "TX":
            continue
        rec = dict(zip(headers_raw, cells))

        def clean(v: str) -> str:
            return v.replace(",", "").replace("▲", "+").replace("▼", "-").strip()

        # 成交量：合計 = 盤後 + 一般
        total_vol = clean(rec.get("*合計成交量", "0"))
        night_vol = clean(rec.get("*盤後交易時段成交量", "0"))
        day_vol   = clean(rec.get("*一般交易時段成交量", "0"))
        oi        = clean(rec.get("*未沖銷契約量", "0"))

        results.append({
            "contract":     rec.get("到期月份(週別)", ""),
            "open":         clean(rec.get("開盤價", "")),
            "high":         clean(rec.get("最高價", "")),
            "low":          clean(rec.get("最低價", "")),
            "close":        clean(rec.get("最後成交價", "")),
            "change":       clean(rec.get("漲跌價", "")),
            "settlement":   clean(rec.get("結算價", "")),
            "vol_total":    total_vol,
            "vol_day":      day_vol,
            "vol_night":    night_vol,
            "oi":           oi,
        })
    return results


def fetch_taifex_day(date: dt.date) -> list[dict]:
    """取得單日 TAIFEX TX 所有月份契約資料。"""
    url = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
    params = {
        "queryType":    "2",
        "marketCode":   "0",
        "commodity_id": "TX",
        "queryDate":    date.strftime("%Y/%m/%d"),
        "commodity_id2": "",
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return _parse_taifex_table(resp.text)


def front_month_row(rows: list[dict], date: dt.date) -> dict | None:
    """
    從當日所有契約中選出主力近月契約（成交量最大者）。
    若無資料回傳 None。
    """
    if not rows:
        return None

    def vol(r: dict) -> int:
        try:
            return int(r.get("vol_total", "0") or "0")
        except ValueError:
            return 0

    return max(rows, key=vol)


# ── 交易日推算 ─────────────────────────────────────────────────────────────────

def trading_days_in_month(year: int, month: int) -> list[dt.date]:
    """回傳該月所有非週末日期（作為候選交易日；實際休市日由 API 空回應過濾）。"""
    days = []
    d = dt.date(year, month, 1)
    while d.month == month:
        if d.weekday() < 5:  # Mon–Fri
            days.append(d)
        d += dt.timedelta(days=1)
    return days


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 1 台指期×加權指數日資料抓取")
    parser.add_argument("--ym", required=True, help="年月，格式 YYYYMM，例 202603")
    parser.add_argument("--output-dir", default="data/tw_futures",
                        help="輸出目錄（預設 data/tw_futures）")
    args = parser.parse_args()

    ym = args.ym
    if not re.fullmatch(r"\d{6}", ym):
        sys.exit("--ym 格式錯誤，請用 YYYYMM")

    year  = int(ym[:4])
    month = int(ym[4:])
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. TWSE 加權指數（一次拿整月）────────────────────────────────────────
    print(f"[TWSE] 抓取 {ym} 加權指數…")
    twse_rows = fetch_twse_month(ym)
    twse_path = out_dir / f"twse_taiex_{ym}.csv"
    twse_fields = ["date", "taiex", "change", "volume_shares", "amount_twd", "transactions"]
    with twse_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=twse_fields)
        w.writeheader()
        w.writerows(twse_rows)
    print(f"[TWSE] 完成，{len(twse_rows)} 筆 → {twse_path}")

    # ── 2. TAIFEX TX（逐日抓取）──────────────────────────────────────────────
    candidate_days = trading_days_in_month(year, month)
    print(f"[TAIFEX] 候選交易日 {len(candidate_days)} 天，逐日抓取台指期…")

    tx_rows = []
    tx_fields = ["date", "contract", "open", "high", "low", "close", "change",
                 "settlement", "vol_total", "vol_day", "vol_night", "oi"]

    for d in candidate_days:
        # 跳過未來日期
        if d > dt.date.today():
            print(f"  {d} 未來日期，略過")
            continue

        contracts = fetch_taifex_day(d)
        if not contracts:
            print(f"  {d} 無資料（休市或假日）")
        else:
            front = front_month_row(contracts, d)
            if front:
                front["date"] = d.strftime("%Y/%m/%d")
                tx_rows.append({k: front.get(k, "") for k in tx_fields})
                print(f"  {d}  契約={front['contract']}  成交量={front['vol_total']}  OI={front['oi']}")
        time.sleep(SLEEP_SEC)

    tx_path = out_dir / f"taifex_tx_{ym}.csv"
    with tx_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=tx_fields)
        w.writeheader()
        w.writerows(tx_rows)
    print(f"[TAIFEX] 完成，{len(tx_rows)} 筆 → {tx_path}")

    print("\n✓ Phase 1 資料建置完成")
    print(f"  TWSE  → {twse_path}  ({len(twse_rows)} rows)")
    print(f"  TAIFEX→ {tx_path}  ({len(tx_rows)} rows)")


if __name__ == "__main__":
    main()
