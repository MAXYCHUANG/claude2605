#!/usr/bin/env python3
"""
台指期 ECT 日線信號腳本（W180_C2 實盤版）

流程：
  1. 更新本月資料（Phase 1 抓取）
  2. 載入近 240 天歷史（取最新 180 天訓練）
  3. 每 5 交易日重估 VECM（快取至 vecm_params_cache.json）
  4. 計算今日 ECT z-score
  5. 讀持倉狀態（signal_state.json）
  6. 熔斷邏輯（月度 -4% / sig_dir 連續 2 次確認才切換）
  7. 決定明日信號，更新狀態
  8. 寄送 email 報告

用法：
  /usr/bin/python3 scripts/cc_tw_futures_signal_daily.py
  /usr/bin/python3 scripts/cc_tw_futures_signal_daily.py --dry-run   # 不更新狀態、不寄信
  /usr/bin/python3 scripts/cc_tw_futures_signal_daily.py --reset     # 重置狀態（換月 / 手動覆寫）
"""

import argparse
import json
import math
import subprocess
import sys
import warnings
from datetime import date, datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np

from statsmodels.tsa.stattools import coint
from statsmodels.tsa.vector_ar.vecm import VECM as VECMModel

# ── 常數 ──────────────────────────────────────────────────────────────────────

TRAIN_WINDOW    = 180   # 訓練視窗（天）
REFIT_FREQ      = 5     # VECM 重估頻率（交易日）
CONFIRM_N       = 2     # sig_dir 切換需連續 N 次確認
ENTRY_THRESH    = 1.0   # 進場 z-score 門檻
EXIT_THRESH     = 0.5   # 出場 z-score 門檻
MAX_HOLD        = 5     # 最長持有天數
COST            = 0.001 # 單邊成本（0.1%）
MONTHLY_CIRCUIT = -4.0  # 月度熔斷門檻（%）

BASE_DIR   = Path(__file__).parent.parent
DATA_DIR   = BASE_DIR / "data" / "tw_futures"
STATE_FILE = DATA_DIR / "signal_state.json"
CACHE_FILE = DATA_DIR / "vecm_params_cache.json"
REPORT_DIR = BASE_DIR / "reports" / "tw_futures_analysis"

EMAIL_SCRIPT = BASE_DIR.parent / "codex2605" / "scripts" / "send_report_email.py"
ENV_FILE     = BASE_DIR.parent / "codex2605" / ".env.weather_email"


# ── 資料載入（與 Phase 6 相同）────────────────────────────────────────────────

import csv as csv_mod

def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv_mod.DictReader(f))

def parse_float(v: str):
    v = v.strip().replace(",", "")
    while v.startswith("--"): v = v[1:]
    if v.startswith("+-"): v = v[1:]
    if not v or v in ("-", "+"): return None
    try: return float(v)
    except ValueError: return None

def build_dataset(twse_rows, tx_rows) -> list[dict]:
    tx_by_date = {r["date"]: r for r in tx_rows}
    result = []
    for row in twse_rows:
        d = row["date"]
        tx = tx_by_date.get(d)
        if not tx: continue
        taiex  = parse_float(row["taiex"])
        t_chg  = parse_float(row["change"])
        t_cl   = parse_float(tx["close"])
        t_chgf = parse_float(tx["change"])
        if not all(x is not None for x in [taiex, t_cl]): continue
        t_pct = (t_chg / (taiex - t_chg) * 100) if (t_chg is not None and (taiex - t_chg) != 0) else None
        f_pct = (t_chgf / (t_cl - t_chgf) * 100) if (t_chgf is not None and (t_cl - t_chgf) != 0) else None
        result.append({
            "date": d, "taiex": taiex, "tx_close": t_cl,
            "taiex_pct": t_pct, "tx_pct": f_pct,
        })
    return result

def _ym_range(start: str, end: str) -> list[str]:
    sy, sm = int(start[:4]), int(start[4:])
    ey, em = int(end[:4]), int(end[4:])
    months, y, m = [], sy, sm
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12: m, y = 1, y + 1
    return months


# ── VECM 估計 ─────────────────────────────────────────────────────────────────

def fit_vecm(taiex_w: np.ndarray, tx_w: np.ndarray) -> dict:
    n = len(taiex_w)
    if n < 20:
        return {"ok": False, "reason": "視窗太短"}
    try:
        _, eg_pval, _ = coint(taiex_w, tx_w)
    except Exception as e:
        return {"ok": False, "reason": f"EG: {e}"}
    if eg_pval >= 0.15:
        return {"ok": False, "reason": f"EG p={eg_pval:.4f}"}
    try:
        k_ar = max(1, min(2, (n - 4) // 4))
        res  = VECMModel(np.column_stack([taiex_w, tx_w]),
                         k_ar_diff=k_ar, coint_rank=1, deterministic="co").fit()
    except Exception as e:
        return {"ok": False, "reason": f"VECM: {e}"}

    beta = res.beta[:, 0]
    alph = res.alpha
    pv   = res.pvalues_alpha
    b0 = float(beta[0]); b1 = float(beta[1])
    bc = float(beta[2]) if len(beta) > 2 else 0.0
    a_t = float(alph[0, 0]); p_t = float(pv[0, 0])
    a_x = float(alph[1, 0]); p_x = float(pv[1, 0])

    if p_x < 0.10:
        raw_sig_dir = int(np.sign(a_x)) if a_x != 0 else -1
        sig_src = f"α_TX={a_x:+.4f}(p={p_x:.4f})"
    elif p_t < 0.10:
        raw_sig_dir = int(np.sign(a_t)) if a_t != 0 else -1
        sig_src = f"α_TAIEX={a_t:+.4f}(p={p_t:.4f})"
    else:
        raw_sig_dir = -1
        sig_src = "均不顯著→預設-1"

    ect_w = b0 * taiex_w + b1 * tx_w + bc
    return {
        "ok": True,
        "b0": b0, "b1": b1, "bc": bc,
        "mu_ect": float(np.mean(ect_w)),
        "sd_ect": float(np.std(ect_w, ddof=1)),
        "raw_sig_dir": raw_sig_dir,
        "sig_src": sig_src,
        "eg_pval": eg_pval,
        "a_t": a_t, "p_t": p_t,
        "a_x": a_x, "p_x": p_x,
    }


# ── 狀態 JSON ─────────────────────────────────────────────────────────────────

DEFAULT_STATE = {
    "position":           "FLAT",    # FLAT / LONG / SHORT
    "entry_date":         None,
    "entry_z":            None,
    "entry_sig_dir":      None,
    "hold_days":          0,
    "trade_pnl":          0.0,       # 本次持倉累計損益（%）
    "month":              None,       # 目前月份（YYYY/MM）
    "monthly_pnl":        0.0,       # 本月已實現 + 浮動損益（%）
    "monthly_paused":     False,      # 月度熔斷是否啟動
    "pause_until_month":  None,       # 熔斷暫停至（YYYY/MM）
    "confirmed_sig_dir":  -1,         # 當前確認的 sig_dir
    "pending_sig_dir":    None,       # 待確認切換方向
    "pending_count":      0,          # 連續提議次數
    "last_run_date":      None,
    "last_z":             None,
}

DEFAULT_CACHE = {
    "last_refit_date":   None,
    "refit_day_count":   0,    # 距上次重估的交易日數
    "b0": None, "b1": None, "bc": None,
    "mu_ect": None, "sd_ect": None,
    "raw_sig_dir":  -1,
    "eg_pval":      None,
    "sig_src":      "",
    "train_start":  None,
    "train_end":    None,
    "a_t": None, "p_t": None,
    "a_x": None, "p_x": None,
}

def load_json(path: Path, default: dict) -> dict:
    if path.exists():
        try:
            d = json.loads(path.read_text())
            # 補齊缺失 key（版本升級相容）
            for k, v in default.items():
                d.setdefault(k, v)
            return d
        except Exception:
            pass
    return dict(default)

def save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ── 月份工具 ──────────────────────────────────────────────────────────────────

def today_ym() -> str:
    return date.today().strftime("%Y/%m")

def today_str() -> str:
    return date.today().strftime("%Y/%m/%d")

def prev_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:])
    m -= 1
    if m == 0: m, y = 12, y - 1
    return f"{y:04d}/{m:02d}"


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="計算信號但不更新狀態、不寄信")
    parser.add_argument("--reset",   action="store_true",
                        help="重置持倉狀態為 FLAT（換月 / 手動覆寫）")
    parser.add_argument("--no-fetch",action="store_true",
                        help="跳過 Phase 1 資料更新（離線模式）")
    args = parser.parse_args()

    today = today_str()
    ym_today = today_ym()
    ym_code  = ym_today.replace("/", "")  # e.g. "202606"

    print(f"[signal] {today}  dry_run={args.dry_run}  reset={args.reset}")

    # ── 0. 重置狀態 ────────────────────────────────────────────────────────────
    if args.reset:
        save_json(STATE_FILE, dict(DEFAULT_STATE))
        print("[signal] 狀態已重置。")

    # ── 1. 更新本月資料 ────────────────────────────────────────────────────────
    if not args.no_fetch:
        print(f"[signal] 抓取 {ym_code} 資料…")
        ret = subprocess.run(
            ["python3", "scripts/cc_fetch_tw_futures_phase1.py", "--ym", ym_code],
            capture_output=True, text=True
        )
        if ret.returncode != 0:
            print(f"  ⚠ Phase 1 失敗：{ret.stderr[-200:]}")
        else:
            print("  ✓ 資料更新完成")

    # ── 2. 載入近 240 天資料 ───────────────────────────────────────────────────
    print("[signal] 載入歷史資料…")
    y_now, m_now = int(ym_today[:4]), int(ym_today[5:])
    months_needed = []
    y, m = y_now, m_now
    for _ in range(10):  # 最多往前 10 個月（確保 ≥ 240 天）
        months_needed.insert(0, f"{y:04d}{m:02d}")
        m -= 1
        if m == 0: m, y = 12, y - 1

    twse_rows, tx_rows = [], []
    for mo in months_needed:
        tp = DATA_DIR / f"twse_taiex_{mo}.csv"
        fp = DATA_DIR / f"taifex_tx_{mo}.csv"
        if tp.exists() and fp.exists():
            twse_rows.extend(load_csv(tp))
            tx_rows.extend(load_csv(fp))

    ds = build_dataset(twse_rows, tx_rows)
    if len(ds) < TRAIN_WINDOW + 5:
        sys.exit(f"[signal] 歷史資料不足（{len(ds)} 筆），需要至少 {TRAIN_WINDOW + 5} 筆")

    print(f"  載入 {len(ds)} 筆，日期 {ds[0]['date']} → {ds[-1]['date']}")
    today_row = ds[-1]
    prev_row  = ds[-2] if len(ds) >= 2 else None

    # ── 3. VECM 重估（每 5 交易日）─────────────────────────────────────────────
    cache = load_json(CACHE_FILE, DEFAULT_CACHE)
    state = load_json(STATE_FILE, DEFAULT_STATE)

    cache["refit_day_count"] = cache.get("refit_day_count", 0) + 1
    need_refit = (cache["last_refit_date"] is None or
                  cache["refit_day_count"] >= REFIT_FREQ)

    if need_refit:
        print(f"[signal] 重估 VECM（訓練視窗 {TRAIN_WINDOW} 天）…")
        train = ds[-(TRAIN_WINDOW + 1):-1]   # 不含今天，用昨日結尾
        taiex_w = np.array([r["taiex"]    for r in train], dtype=np.float64)
        tx_w    = np.array([r["tx_close"] for r in train], dtype=np.float64)
        valid   = ~(np.isnan(taiex_w) | np.isnan(tx_w))
        res = fit_vecm(taiex_w[valid], tx_w[valid])
        if res["ok"]:
            cache.update({
                "last_refit_date": today,
                "refit_day_count": 0,
                "b0": res["b0"], "b1": res["b1"], "bc": res["bc"],
                "mu_ect": res["mu_ect"], "sd_ect": res["sd_ect"],
                "raw_sig_dir": res["raw_sig_dir"],
                "sig_src": res["sig_src"],
                "eg_pval": res["eg_pval"],
                "train_start": train[0]["date"],
                "train_end":   train[-1]["date"],
                "a_t": res["a_t"], "p_t": res["p_t"],
                "a_x": res["a_x"], "p_x": res["p_x"],
            })
            print(f"  ✓ VECM 成功  sig_dir_raw={res['raw_sig_dir']:+d}  {res['sig_src']}")
            print(f"    EG p={res['eg_pval']:.4f}  訓練 {train[0]['date']}→{train[-1]['date']}")
        else:
            print(f"  ⚠ VECM 失敗：{res['reason']}  沿用上次參數")
    else:
        days_ago = cache["refit_day_count"]
        print(f"[signal] 沿用 VECM 快取（{days_ago} 天前重估，下次重估再 {REFIT_FREQ - days_ago} 天）")

    # ── 4. sig_dir 確認機制（confirm_n=2）──────────────────────────────────────
    raw_dir = cache.get("raw_sig_dir", -1)
    confirmed_dir = state["confirmed_sig_dir"]
    pending_dir   = state["pending_sig_dir"]
    pending_count = state["pending_count"]
    sig_dir_switched = False

    if need_refit and cache["last_refit_date"] == today:
        if raw_dir == confirmed_dir:
            pending_dir = None; pending_count = 0
        elif raw_dir == pending_dir:
            pending_count += 1
            if pending_count >= CONFIRM_N:
                old_dir = confirmed_dir
                confirmed_dir = raw_dir
                pending_dir = None; pending_count = 0
                sig_dir_switched = True
                print(f"  ★ sig_dir 切換確認：{old_dir:+d} → {confirmed_dir:+d}")
        else:
            pending_dir = raw_dir; pending_count = 1
            print(f"  ⚠ sig_dir 候選方向：{raw_dir:+d}（第 1/{CONFIRM_N} 次，待確認）")

    # ── 5. 計算今日 z-score（用昨收 ECT）─────────────────────────────────────
    b0 = cache["b0"]; b1 = cache["b1"]; bc = cache["bc"]
    mu = cache["mu_ect"]; sd = cache["sd_ect"]

    if None in (b0, b1, bc, mu, sd):
        sys.exit("[signal] VECM 參數未初始化，請確認快取檔或執行完整重估")

    prev = prev_row or today_row
    ect_prev = b0 * prev["taiex"] + b1 * prev["tx_close"] + bc
    z_today  = (ect_prev - mu) / sd if sd > 1e-10 else 0.0
    sz       = confirmed_dir * z_today  # 統一化信號

    print(f"[signal] 昨收 ECT={ect_prev:.2f}  z={z_today:+.3f}  "
          f"sz={sz:+.3f}  sig_dir={confirmed_dir:+d}")

    # ── 6. 月份切換 ────────────────────────────────────────────────────────────
    if state["month"] != ym_today:
        if state["month"] is not None:
            print(f"[signal] 月份切換：{state['month']} → {ym_today}")
        state["month"]         = ym_today
        state["monthly_pnl"]   = 0.0
        # 月度熔斷：若上月暫停且本月是 pause_until_month，解除
        if state.get("pause_until_month") == ym_today:
            state["monthly_paused"]    = False
            state["pause_until_month"] = None
            print("  ✓ 月度熔斷解除")

    # ── 7. 更新持倉浮動損益（今日）────────────────────────────────────────────
    tx_ret_today = today_row.get("tx_pct") or 0.0
    if state["position"] == "LONG":
        daily_contrib = tx_ret_today
    elif state["position"] == "SHORT":
        daily_contrib = -tx_ret_today
    else:
        daily_contrib = 0.0

    state["trade_pnl"]   = round(state.get("trade_pnl", 0.0) + daily_contrib, 4)
    state["monthly_pnl"] = round(state.get("monthly_pnl", 0.0) + daily_contrib, 4)

    # ── 8. 熔斷判斷 ───────────────────────────────────────────────────────────
    circuit_note = ""
    if state["monthly_paused"]:
        circuit_note = f"⛔ 月度熔斷中（暫停至 {state.get('pause_until_month','?')}）"
    elif state["monthly_pnl"] <= MONTHLY_CIRCUIT:
        state["monthly_paused"]    = True
        pause_ym = ym_today        # 暫停至下月
        y2, m2 = int(pause_ym[:4]), int(pause_ym[5:])
        m2 += 1
        if m2 > 12: m2, y2 = 1, y2 + 1
        state["pause_until_month"] = f"{y2:04d}/{m2:02d}"
        circuit_note = f"🔴 月度熔斷觸發！月損 {state['monthly_pnl']:.2f}%（暫停至 {state['pause_until_month']}）"
        print(f"  {circuit_note}")

    paused = state["monthly_paused"]

    # ── 9. 進出場信號 ─────────────────────────────────────────────────────────
    pos      = state["position"]
    hold     = state.get("hold_days", 0)
    action   = "HOLD"
    action_detail = ""
    exit_reason   = ""

    if pos != "FLAT":
        hold += 1
        # 出場檢查
        z_exit = abs(z_today) < EXIT_THRESH
        t_exit = hold >= MAX_HOLD
        if z_exit or t_exit:
            action      = "EXIT"
            exit_reason = "z 回歸均衡" if z_exit else f"持滿 {MAX_HOLD} 天"
            action_detail = f"平倉（{exit_reason}）"
    else:
        hold = 0

    # 進場（FLAT 且未熔斷）
    new_pos = None
    if action == "HOLD" and pos == "FLAT" and not paused:
        if sz > ENTRY_THRESH:
            new_pos = "LONG";  action = "ENTER_LONG"
            action_detail = f"明日買進 TX（z={z_today:+.2f} → sz={sz:+.2f} > +{ENTRY_THRESH}）"
        elif sz < -ENTRY_THRESH:
            new_pos = "SHORT"; action = "ENTER_SHORT"
            action_detail = f"明日放空 TX（z={z_today:+.2f} → sz={sz:+.2f} < -{ENTRY_THRESH}）"

    if action == "HOLD" and pos != "FLAT":
        action_detail = f"繼續持有 {pos}（第 {hold} 天，z={z_today:+.2f}）"
    elif action == "HOLD" and pos == "FLAT":
        action_detail = f"觀望（sz={sz:+.2f}，未達 ±{ENTRY_THRESH}）"
    if paused and pos == "FLAT" and action in ("HOLD",):
        action_detail = f"熔斷中暫不開倉"

    # ── 10. 更新狀態 ─────────────────────────────────────────────────────────
    if not args.dry_run:
        state["confirmed_sig_dir"] = confirmed_dir
        state["pending_sig_dir"]   = pending_dir
        state["pending_count"]     = pending_count
        state["last_run_date"]     = today
        state["last_z"]            = round(z_today, 4)

        if action == "EXIT":
            # 加出場成本
            state["trade_pnl"]   = round(state["trade_pnl"] - COST * 100, 4)
            state["monthly_pnl"] = round(state["monthly_pnl"] - COST * 100, 4)
            state["position"]    = "FLAT"
            state["entry_date"]  = None
            state["entry_z"]     = None
            state["entry_sig_dir"] = None
            state["hold_days"]   = 0
            state["trade_pnl"]   = 0.0
        elif action in ("ENTER_LONG", "ENTER_SHORT"):
            state["position"]    = new_pos
            state["entry_date"]  = today
            state["entry_z"]     = round(z_today, 4)
            state["entry_sig_dir"] = confirmed_dir
            state["hold_days"]   = 0
            state["trade_pnl"]   = round(-COST * 100, 4)  # 入場成本
            state["monthly_pnl"] = round(state["monthly_pnl"] - COST * 100, 4)
        elif pos != "FLAT":
            state["hold_days"] = hold

        save_json(STATE_FILE,  state)
        save_json(CACHE_FILE,  cache)
        print(f"[signal] 狀態已更新 → position={state['position']}  monthly_pnl={state['monthly_pnl']:.2f}%")

    # ── 11. 生成報告 ─────────────────────────────────────────────────────────
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rpt_path = REPORT_DIR / f"tw_futures_signal_{today.replace('/', '-')}.md"

    action_emoji = {
        "ENTER_LONG":  "🟢 買進 TX（LONG）",
        "ENTER_SHORT": "🔴 放空 TX（SHORT）",
        "EXIT":        "⬜ 平倉",
        "HOLD":        "🔵 持倉維持" if pos != "FLAT" else "⚪ 觀望",
    }.get(action, action)

    sig_dir_label = "+1（TX 追 TAIEX，追趕模式）" if confirmed_dir > 0 else "-1（TAIEX 追 TX，均值回歸）"
    circuit_status = circuit_note if circuit_note else "✅ 正常"
    pending_note = ""
    if pending_dir is not None:
        pending_note = f"\n> ⚠️ sig_dir 候選切換 {confirmed_dir:+d}→{pending_dir:+d}（已連續 {pending_count}/{CONFIRM_N} 次）——尚未確認，本輪維持原方向"

    report_lines = [
        f"# 台指期 ECT 信號報告 {today}",
        "",
        f"## 今日信號",
        "",
        f"| 項目 | 內容 |",
        f"|------|------|",
        f"| **動作** | **{action_emoji}** |",
        f"| 說明 | {action_detail} |",
        f"| sig_dir | {sig_dir_label} |",
        f"| z-score（昨收）| {z_today:+.3f}（均值化信號 sz = {sz:+.3f}）|",
        f"| 熔斷狀態 | {circuit_status} |",
        "",
    ]

    if pending_note:
        report_lines += [pending_note, ""]

    report_lines += [
        f"## 持倉狀態",
        "",
        f"| 項目 | 內容 |",
        f"|------|------|",
        f"| 目前倉位 | {state['position']} |",
    ]
    if state["position"] != "FLAT":
        report_lines += [
            f"| 進場日 | {state['entry_date']} |",
            f"| 進場 z | {state['entry_z']:+.3f} |",
            f"| 持有天數 | {hold} 天 |",
            f"| 本筆浮動損益 | {state['trade_pnl']:+.2f}% |",
        ]
    report_lines += [
        f"| 本月累計損益 | {state['monthly_pnl']:+.2f}%（熔斷閾值 {MONTHLY_CIRCUIT:.0f}%）|",
        "",
        f"## VECM 快取參數",
        "",
        f"| 參數 | 值 |",
        f"|------|-----|",
        f"| 訓練視窗 | {TRAIN_WINDOW} 天（{cache.get('train_start','?')} → {cache.get('train_end','?')}）|",
        f"| 上次重估 | {cache.get('last_refit_date','?')}（距今 {cache.get('refit_day_count',0)} 交易日）|",
        f"| 下次重估 | 再 {max(0, REFIT_FREQ - cache.get('refit_day_count',0))} 交易日 |",
        f"| EG p-value | {cache.get('eg_pval', '?')} |",
        f"| α 方向依據 | {cache.get('sig_src','?')} |",
        f"| β(TX) | {-cache['b1']/cache['b0']:.4f}（若 b0 非零）|" if cache.get("b0") else "| β(TX) | — |",
        "",
        f"## 操作指引",
        "",
        f"| 規則 | 值 |",
        f"|------|-----|",
        f"| 進場門檻 | \\|sz\\| > {ENTRY_THRESH} |",
        f"| 出場門檻 | \\|z\\| < {EXIT_THRESH} 或持有 ≥ {MAX_HOLD} 天 |",
        f"| sig_dir 確認 | 連續 {CONFIRM_N} 次重估一致才切換 |",
        f"| 月度熔斷 | 月損 ≤ {MONTHLY_CIRCUIT:.0f}% → 暫停至次月 |",
        "",
        f"---",
        f"*生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ]

    rpt_content = "\n".join(report_lines)
    rpt_path.write_text(rpt_content, encoding="utf-8")
    print(f"[signal] 報告寫入：{rpt_path}")

    # ── 12. 寄送 email ────────────────────────────────────────────────────────
    if args.dry_run:
        print("[signal] dry-run：不寄信")
        print("\n" + "="*60)
        print(rpt_content)
        return

    action_short = {
        "ENTER_LONG":  "買進 TX",
        "ENTER_SHORT": "放空 TX",
        "EXIT":        "平倉",
        "HOLD":        f"持倉 {pos}" if pos != "FLAT" else "觀望",
    }.get(action, action)

    subject = f"[台指期信號] {today} │ {action_short} │ z={z_today:+.2f} │ 月損益{state['monthly_pnl']:+.2f}%"

    email_cmd = (
        f"set -a && source {ENV_FILE} && set +a && "
        f"python3 {EMAIL_SCRIPT} "
        f"--to yc5780 "
        f"--subject \"{subject}\" "
        f"--body \"台指期 ECT 日線信號，詳見附件。\" "
        f"--html-body "
        f"--attachment {rpt_path}"
    )
    ret = subprocess.run(["bash", "-c", email_cmd], capture_output=True, text=True,
                         cwd=str(BASE_DIR.parent / "codex2605"))
    if ret.returncode == 0:
        print(f"[signal] Email 寄出：{subject}")
    else:
        print(f"[signal] Email 失敗：{ret.stderr[-300:]}")

    print(f"\n[signal 完成] action={action}  z={z_today:+.3f}  sig_dir={confirmed_dir:+d}  monthly={state['monthly_pnl']:+.2f}%")


if __name__ == "__main__":
    main()
