#!/usr/bin/env python3
"""
Phase 5：滾動視窗樣本外驗證
  - 每隔 refit_freq 天以前 train_window 天重估 VECM（含 EG 協整預檢）
  - 每次重估自動偵測 sig_dir，z-score 完全使用訓練視窗 mu/sigma（無未來資訊）
  - 追蹤 sig_dir 切換時序，分析偵測延遲
  - 圖表 Chart 18（sig_dir 時序）、Chart 19（OOS 累積報酬）、Chart 20（逐筆損益）
  - 報告：phase5_report_LABEL.md

用法：
  /usr/bin/python3 scripts/cc_analyze_tw_futures_phase5.py --ym-range 202401 202512

選用參數：
  --train-window  int    訓練視窗天數（預設 60）
  --refit-freq    int    VECM 重估頻率（天，預設 5；1=每天重估）
  --entry-thresh  float  進場門檻 z-score 倍數（預設 1.0）
  --exit-thresh   float  出場門檻 z-score 倍數（預設 0.5）
  --max-hold      int    最長持有天數（預設 5）
  --cost          float  單邊交易成本（預設 0.001 = 0.1%）
"""

import argparse
import csv as csv_mod
import math
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from statsmodels.tsa.stattools import coint
from statsmodels.tsa.vector_ar.vecm import VECM as VECMModel

FIG_DPI = 150
STYLE = {
    "long":  "#1f77b4",
    "short": "#d62728",
    "bh":    "#2ca02c",
    "pos1":  "#1f77b4",
    "neg1":  "#d62728",
    "na":    "#aaaaaa",
    "grid":  "#e0e0e0",
    "zero":  "#555555",
}

FLAT  =  0
LONG  =  1
SHORT = -1


# ── 資料載入（與 Phase 3/4 相同） ────────────────────────────────────────────

def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv_mod.DictReader(f))


def parse_float(v: str):
    v = v.strip().replace(",", "")
    while v.startswith("--"):
        v = v[1:]
    if v.startswith("+-"):
        v = v[1:]
    if not v or v in ("-", "+"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def build_dataset(twse_rows, tx_rows) -> list[dict]:
    tx_by_date = {r["date"]: r for r in tx_rows}
    result = []
    for row in twse_rows:
        d  = row["date"]
        tx = tx_by_date.get(d)
        if not tx:
            continue
        taiex   = parse_float(row["taiex"])
        t_chg   = parse_float(row["change"])
        amount  = parse_float(row["amount_twd"])
        t_close = parse_float(tx["close"])
        t_vol   = parse_float(tx["vol_total"])
        t_night = parse_float(tx["vol_night"])
        t_chgf  = parse_float(tx["change"])

        def _nn(*vals):
            return all(v is not None for v in vals)

        t_pct  = (t_chg / (taiex - t_chg) * 100) if (_nn(t_chg, taiex) and (taiex - t_chg) != 0) else None
        f_pct  = (t_chgf / (t_close - t_chgf) * 100) if (_nn(t_chgf, t_close) and (t_close - t_chgf) != 0) else None
        n_rat  = (t_night / t_vol * 100) if (_nn(t_night, t_vol) and t_vol > 0) else None
        result.append({
            "date":       d,
            "taiex":      taiex,
            "taiex_pct":  t_pct,
            "amount_bn":  amount / 1e9 if amount else None,
            "tx_close":   t_close,
            "tx_pct":     f_pct,
            "tx_vol":     t_vol,
            "night_ratio":n_rat,
            "basis":      (t_close - taiex) if _nn(t_close, taiex) else None,
        })
    return result


def _ym_range(start: str, end: str) -> list[str]:
    sy, sm = int(start[:4]), int(start[4:])
    ey, em = int(end[:4]), int(end[4:])
    months, y, m = [], sy, sm
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


# ── 視窗 VECM 估計 ─────────────────────────────────────────────────────────────

def fit_vecm_window(taiex_w: np.ndarray, tx_w: np.ndarray) -> dict:
    n = len(taiex_w)
    if n < 20:
        return {"ok": False, "reason": "視窗太短"}

    try:
        _, eg_pval, _ = coint(taiex_w, tx_w)
    except Exception as e:
        return {"ok": False, "reason": f"EG例外: {e}"}

    if eg_pval >= 0.15:
        return {"ok": False, "reason": f"EG p={eg_pval:.4f}"}

    try:
        k_ar_diff = max(1, min(2, (n - 4) // 4))
        mdl = VECMModel(np.column_stack([taiex_w, tx_w]),
                        k_ar_diff=k_ar_diff, coint_rank=1, deterministic="co")
        res = mdl.fit()
    except Exception as e:
        return {"ok": False, "reason": f"VECM例外: {e}"}

    beta = res.beta[:, 0]
    alph = res.alpha
    pv_a = res.pvalues_alpha

    b0 = float(beta[0])
    b1 = float(beta[1])
    bc = float(beta[2]) if len(beta) > 2 else 0.0
    beta_tx = float(-b1 / b0) if abs(b0) > 1e-10 else float(-b1)

    a_t = float(alph[0, 0]); p_t = float(pv_a[0, 0])
    a_x = float(alph[1, 0]); p_x = float(pv_a[1, 0])

    if p_x < 0.10:
        sig_dir = int(np.sign(a_x)) if a_x != 0 else -1
        sig_src = f"α_TX={a_x:+.4f}(p={p_x:.4f})"
    elif p_t < 0.10:
        sig_dir = int(np.sign(a_t)) if a_t != 0 else -1
        sig_src = f"α_TAIEX={a_t:+.4f}(p={p_t:.4f})"
    else:
        sig_dir = -1
        sig_src = "均不顯著→預設-1"

    ect_w = b0 * taiex_w + b1 * tx_w + bc
    mu_w  = float(np.mean(ect_w))
    sd_w  = float(np.std(ect_w, ddof=1))

    return {
        "ok": True,
        "b0": b0, "b1": b1, "bc": bc, "beta_tx": beta_tx,
        "a_t": a_t, "p_t": p_t,
        "a_x": a_x, "p_x": p_x,
        "sig_dir": sig_dir,
        "sig_src": sig_src,
        "mu_w": mu_w,
        "sd_w": sd_w,
        "eg_pval": eg_pval,
    }


# ── 滾動樣本外信號生成 ────────────────────────────────────────────────────────

def generate_oos_signals(ds_aligned: list[dict],
                         train_window: int,
                         refit_freq: int) -> dict:
    """
    對每個樣本外日 t (t >= train_window) 生成 OOS z-score 和 sig_dir。

    z_arr[t] = ECT z-score of day t-1 using rolling VECM fitted on
               [t-train_window, t-1] (inclusive, 60 days ending yesterday).
    Signal for day t is based on z_arr[t].
    """
    n = len(ds_aligned)
    taiex_full = np.array([r["taiex"]    or np.nan for r in ds_aligned], dtype=np.float64)
    tx_full    = np.array([r["tx_close"] or np.nan for r in ds_aligned], dtype=np.float64)

    z_arr       = np.full(n, np.nan)
    sig_dir_arr = np.zeros(n, dtype=int)
    fit_log     = []
    fail_log    = []

    cur = {"ok": False, "b0": 0.0, "b1": 0.0, "bc": 0.0,
           "mu": 0.0, "sd": 1.0, "sig_dir": -1}

    print(f"[Phase 5] 開始滾動重估（{n - train_window} 個 OOS 點，"
          f"每 {refit_freq} 天重估一次）…")

    for t in range(train_window, n):
        oos_idx = t - train_window

        if oos_idx % refit_freq == 0:
            # 訓練視窗：[t - train_window, t)，共 train_window 天
            # 包含第 t-1 天（昨天），ECT z-score 取 t-1
            w_start = t - train_window
            tw = taiex_full[w_start:t]
            txw = tx_full[w_start:t]
            valid = ~(np.isnan(tw) | np.isnan(txw))
            if valid.sum() >= 20:
                res = fit_vecm_window(tw[valid], txw[valid])
                if res["ok"]:
                    cur = {
                        "ok": True,
                        "b0": res["b0"], "b1": res["b1"], "bc": res["bc"],
                        "mu": res["mu_w"], "sd": res["sd_w"],
                        "sig_dir": res["sig_dir"],
                    }
                    fit_log.append({
                        "t": t,
                        "date": ds_aligned[t]["date"],
                        "train_start": ds_aligned[w_start]["date"],
                        "train_end":   ds_aligned[t - 1]["date"],
                        "sig_dir":  res["sig_dir"],
                        "sig_src":  res["sig_src"],
                        "beta_tx":  res["beta_tx"],
                        "eg_pval":  res["eg_pval"],
                        "a_t": res["a_t"], "p_t": res["p_t"],
                        "a_x": res["a_x"], "p_x": res["p_x"],
                    })
                else:
                    fail_log.append({
                        "t": t, "date": ds_aligned[t]["date"],
                        "reason": res["reason"],
                    })
            else:
                fail_log.append({
                    "t": t, "date": ds_aligned[t]["date"],
                    "reason": f"有效點數{valid.sum()}<20",
                })

        if not cur["ok"]:
            continue

        # z-score of day t-1 using rolling VECM
        ta = taiex_full[t - 1]
        tx = tx_full[t - 1]
        if np.isnan(ta) or np.isnan(tx):
            continue
        ect_tm1 = cur["b0"] * ta + cur["b1"] * tx + cur["bc"]
        z_tm1 = (ect_tm1 - cur["mu"]) / cur["sd"] if cur["sd"] > 1e-10 else 0.0
        z_arr[t]       = z_tm1
        sig_dir_arr[t] = cur["sig_dir"]

        if oos_idx % 100 == 0:
            print(f"  … OOS {oos_idx}/{n - train_window}  date={ds_aligned[t]['date']}"
                  f"  sig_dir={cur['sig_dir']:+d}  z={z_tm1:+.2f}")

    success = len(fit_log)
    total   = success + len(fail_log)
    print(f"[Phase 5] 重估完成：成功 {success}/{total}，失敗 {len(fail_log)}")
    return {
        "oos_start":    train_window,
        "z_arr":        z_arr,
        "sig_dir_arr":  sig_dir_arr,
        "fit_log":      fit_log,
        "fail_log":     fail_log,
    }


# ── sig_dir 切換分析 ──────────────────────────────────────────────────────────

def analyze_sigdir_switches(fit_log: list[dict]) -> list[dict]:
    if not fit_log:
        return []
    switches = []
    prev_sd = fit_log[0]["sig_dir"]
    prev_dt = fit_log[0]["date"]
    for rec in fit_log[1:]:
        if rec["sig_dir"] != prev_sd:
            switches.append({
                "switch_date": rec["date"],
                "from": prev_sd,
                "to":   rec["sig_dir"],
                "prev_date": prev_dt,
            })
            prev_sd = rec["sig_dir"]
            prev_dt = rec["date"]
    return switches


def sigdir_year_summary(fit_log: list[dict]) -> dict:
    by_year: dict[str, dict] = {}
    for rec in fit_log:
        yr = rec["date"][:4]
        if yr not in by_year:
            by_year[yr] = {"+1": 0, "-1": 0}
        key = "+1" if rec["sig_dir"] > 0 else "-1"
        by_year[yr][key] += 1
    return by_year


# ── 回測（OOS，sig_dir 逐日可變） ─────────────────────────────────────────────

def backtest_oos(ds_aligned: list[dict],
                 z_arr: np.ndarray,
                 sig_dir_arr: np.ndarray,
                 oos_start: int,
                 entry_thresh: float,
                 exit_thresh: float,
                 max_hold: int,
                 cost: float) -> dict:
    n = len(z_arr)
    state = FLAT; hold = 0; entry_i = None; entry_z = 0.0; entry_sd = -1
    daily_pnl = np.zeros(n)
    position  = np.zeros(n, dtype=int)
    trades    = []

    def tx_pct(i):
        v = ds_aligned[i].get("tx_pct")
        return v if v is not None else 0.0

    for t in range(oos_start, n):
        if np.isnan(z_arr[t]):
            position[t] = state
            continue
        z_t  = float(z_arr[t])
        sd_t = int(sig_dir_arr[t]) if sig_dir_arr[t] != 0 else -1
        sz   = sd_t * z_t   # sz > entry_thresh → LONG; sz < -entry_thresh → SHORT

        if state == FLAT:
            if sz > entry_thresh:
                state = LONG;  hold = 0; entry_i = t; entry_z = z_t; entry_sd = sd_t
                daily_pnl[t] -= cost
            elif sz < -entry_thresh:
                state = SHORT; hold = 0; entry_i = t; entry_z = z_t; entry_sd = sd_t
                daily_pnl[t] -= cost
        else:
            hold += 1
            daily_pnl[t] += state * tx_pct(t)
            if (abs(z_t) < exit_thresh) or (hold >= max_hold):
                daily_pnl[t] -= cost
                trades.append({
                    "entry_date": ds_aligned[entry_i]["date"],
                    "exit_date":  ds_aligned[t]["date"],
                    "direction":  "LONG" if state == LONG else "SHORT",
                    "entry_z":    round(entry_z, 3),
                    "exit_z":     round(z_t, 3),
                    "hold_days":  hold,
                    "pnl_pct":    round(float(np.sum(daily_pnl[entry_i:t + 1])), 4),
                    "sig_dir":    entry_sd,
                })
                state = FLAT; hold = 0
        position[t] = state

    if state != FLAT and entry_i is not None:
        t = n - 1
        daily_pnl[t] -= cost
        z_last = float(z_arr[t]) if not np.isnan(z_arr[t]) else 0.0
        trades.append({
            "entry_date": ds_aligned[entry_i]["date"],
            "exit_date":  ds_aligned[t]["date"],
            "direction":  "LONG" if state == LONG else "SHORT",
            "entry_z":    round(entry_z, 3),
            "exit_z":     round(z_last, 3),
            "hold_days":  hold,
            "pnl_pct":    round(float(np.sum(daily_pnl[entry_i:])), 4),
            "sig_dir":    entry_sd,
            "note":       "強制平倉",
        })

    cum_pnl = np.cumsum(daily_pnl)
    tx_pcts = np.array([r.get("tx_pct") or 0.0 for r in ds_aligned], dtype=np.float64)
    cum_bh  = np.cumsum(tx_pcts)
    return {"trades": trades, "daily_pnl": daily_pnl,
            "cum_pnl": cum_pnl, "cum_bh": cum_bh, "position": position}


def perf_stats(bt: dict, oos_start: int = 0) -> dict:
    daily_pnl = bt["daily_pnl"][oos_start:]
    trades    = bt["trades"]
    cum_pnl   = bt["cum_pnl"]

    total_ret = float(cum_pnl[-1])
    n_trades  = len(trades)
    wins      = sum(1 for t in trades if t["pnl_pct"] > 0)
    hit_rate  = (wins / n_trades * 100) if n_trades > 0 else 0.0
    avg_win   = float(np.mean([t["pnl_pct"] for t in trades if t["pnl_pct"] > 0])) if wins > 0 else 0.0
    avg_loss  = float(np.mean([t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0])) if (n_trades - wins) > 0 else 0.0

    active = daily_pnl[daily_pnl != 0]
    sharpe = 0.0
    if len(active) > 1:
        mu_d = float(np.mean(active))
        sd_d = float(np.std(active, ddof=1))
        sharpe = (mu_d / sd_d * math.sqrt(252)) if sd_d > 0 else 0.0

    peak   = np.maximum.accumulate(cum_pnl)
    dd     = cum_pnl - peak
    max_dd = float(np.min(dd))

    active_days = int(np.sum(daily_pnl != 0))
    ann_ret = total_ret * 252 / max(1, active_days)
    calmar  = (ann_ret / abs(max_dd)) if max_dd < -1e-6 else float("inf")

    return {
        "total_ret": total_ret, "n_trades": n_trades,
        "hit_rate": hit_rate,   "avg_win": avg_win,
        "avg_loss": avg_loss,   "sharpe": sharpe,
        "max_dd": max_dd,       "calmar": calmar,
        "ann_ret": ann_ret,
    }


def multi_thresh_table_oos(ds_aligned, z_arr, sig_dir_arr, oos_start,
                            thresholds, exit_thresh, max_hold, cost) -> str:
    rows = [
        "| 進場門檻 | 交易次數 | 勝率 | 合計報酬 | Buy-Hold | Sharpe | 最大回撤 |",
        "|----------|----------|------|----------|----------|--------|----------|",
    ]
    for et in thresholds:
        bt = backtest_oos(ds_aligned, z_arr, sig_dir_arr, oos_start,
                          et, exit_thresh, max_hold, cost)
        ps = perf_stats(bt, oos_start)
        bh = float(bt["cum_bh"][-1]) - float(bt["cum_bh"][oos_start])
        rows.append(
            f"| ±{et:.1f}σ | {ps['n_trades']} | {ps['hit_rate']:.0f}% "
            f"| {ps['total_ret']:+.2f}% | {bh:+.2f}% "
            f"| {ps['sharpe']:+.2f} | {ps['max_dd']:.2f}% |"
        )
    return "\n".join(rows)


def annual_breakdown_oos(ds_aligned, bt, oos_start) -> str:
    daily_pnl = bt["daily_pnl"]
    tx_pcts   = np.array([r.get("tx_pct") or 0.0 for r in ds_aligned], dtype=np.float64)
    dates     = [r["date"] for r in ds_aligned]

    years = sorted(set(d[:4] for d in dates[oos_start:]))
    rows  = [
        "| 年度 | OOS 策略報酬 | Buy-Hold TX | 交易次數 | 勝率 |",
        "|------|-------------|-------------|----------|------|",
    ]
    for yr in years:
        idx = [i for i in range(oos_start, len(dates)) if dates[i][:4] == yr]
        if not idx:
            continue
        strat = float(np.sum(daily_pnl[idx]))
        bh    = float(np.sum(tx_pcts[idx]))
        yr_tr = [t for t in bt["trades"] if t["entry_date"][:4] == yr]
        n_tr  = len(yr_tr)
        wins  = sum(1 for t in yr_tr if t["pnl_pct"] > 0)
        hr    = f"{wins/n_tr*100:.0f}%" if n_tr > 0 else "—"
        rows.append(f"| {yr} | {strat:+.2f}% | {bh:+.2f}% | {n_tr} | {hr} |")
    return "\n".join(rows)


# ── 圖表 ──────────────────────────────────────────────────────────────────────

def chart_sigdir(dates_oos: list[str], sig_dir_arr_oos: np.ndarray,
                 fit_log: list[dict], switches: list[dict],
                 label: str, out: Path):
    """Chart 18: sig_dir 時序（+1 藍 / -1 紅 / 0 灰）。"""
    n = len(dates_oos)
    x = np.arange(n)
    colors = [STYLE["pos1"] if v > 0 else STYLE["neg1"] if v < 0 else STYLE["na"]
              for v in sig_dir_arr_oos]
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.bar(x, sig_dir_arr_oos, color=colors, width=1.0, alpha=0.7)
    ax.axhline(0, color=STYLE["zero"], lw=0.8)

    # 切換點垂直線
    date_idx = {d: i for i, d in enumerate(dates_oos)}
    for sw in switches:
        i = date_idx.get(sw["switch_date"])
        if i is not None:
            ax.axvline(i, color="black", lw=1.2, ls="--", alpha=0.7)
            ax.text(i, 0.9, sw["switch_date"], fontsize=6,
                    rotation=90, ha="right", va="top", color="black")

    step = max(1, n // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(dates_oos[::step], rotation=35, ha="right", fontsize=7)
    ax.set_yticks([-1, 0, 1])
    ax.set_yticklabels(["-1 (均值回歸)", "0 / NA", "+1 (追趕)"], fontsize=8)
    ax.set_ylabel("sig_dir")
    ax.set_title(f"Chart 18 | 滾動 sig_dir 時序  {label}\n"
                 "藍 = +1（TX 追 TAIEX）  紅 = -1（均值回歸）  ▏= 切換點", fontsize=9)
    ax.grid(color=STYLE["grid"], lw=0.4, axis="x")
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_equity_oos(dates_all: list[str], cum_pnl: np.ndarray,
                     cum_bh: np.ndarray, oos_start: int,
                     trades: list[dict], label: str, out: Path):
    """Chart 19: OOS 累積報酬（策略 vs Buy-Hold TX，從 OOS 起始點歸零）。"""
    n   = len(dates_all)
    x   = np.arange(n)

    # 從 oos_start 歸零
    base_s = cum_pnl[oos_start]
    base_b = cum_bh[oos_start]
    strat  = cum_pnl - base_s
    bh     = cum_bh  - base_b

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(x[oos_start:], strat[oos_start:], color=STYLE["long"],
            lw=1.8, label="OOS ECT 信號策略")
    ax.plot(x[oos_start:], bh[oos_start:],  color=STYLE["bh"],
            lw=1.5, ls="--", label="Buy-Hold TX", alpha=0.8)
    ax.axhline(0, color=STYLE["zero"], lw=0.7, ls=":")

    date_idx = {d: i for i, d in enumerate(dates_all)}
    first_l = first_s = True
    for tr in trades:
        ei = date_idx.get(tr["entry_date"])
        if ei is not None:
            c   = STYLE["long"] if tr["direction"] == "LONG" else STYLE["short"]
            lbl = (f"LONG" if (tr["direction"] == "LONG" and first_l) else
                   f"SHORT" if (tr["direction"] == "SHORT" and first_s) else None)
            if tr["direction"] == "LONG":  first_l = False
            if tr["direction"] == "SHORT": first_s = False
            ax.axvline(ei, color=c, lw=0.6, alpha=0.3, label=lbl)

    step = max(1, n // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(dates_all[::step], rotation=35, ha="right", fontsize=7)
    ax.set_ylabel("累積報酬 (%, 從 OOS 起始點歸零)")
    ax.set_title(f"Chart 19 | OOS 累積報酬：策略 vs Buy-Hold TX  {label}", fontsize=9)
    ax.legend(fontsize=7, loc="best")
    ax.grid(color=STYLE["grid"], lw=0.4)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_trade_pnl_oos(trades: list[dict], label: str, out: Path):
    """Chart 20: 逐筆損益棒圖 + 分佈（按 sig_dir 著色）。"""
    if not trades:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "無交易紀錄", ha="center", va="center", transform=ax.transAxes)
        plt.savefig(out, dpi=FIG_DPI)
        plt.close()
        return

    pnls  = [t["pnl_pct"] for t in trades]
    dirs  = [t["direction"] for t in trades]
    dates = [t["entry_date"] for t in trades]
    sds   = [t.get("sig_dir", -1) for t in trades]
    x     = np.arange(len(pnls))

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    ax1 = axes[0]
    colors = [STYLE["long"] if p > 0 else STYLE["short"] for p in pnls]
    ax1.bar(x, pnls, color=colors, width=0.6)
    ax1.axhline(0, color="grey", lw=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels(
        [f"{d}\n{dr[0]}|sd{s:+d}" for d, dr, s in zip(dates, dirs, sds)],
        fontsize=6, rotation=45, ha="right"
    )
    ax1.set_ylabel("損益 (%)")
    ax1.set_title(f"逐筆損益  {label}", fontsize=9)
    ax1.grid(color=STYLE["grid"], lw=0.4, axis="y")
    wins = sum(1 for p in pnls if p > 0)
    ax1.text(0.02, 0.97,
             f"共 {len(pnls)} 筆 | 勝率 {wins/len(pnls)*100:.0f}% | 合計 {sum(pnls):+.2f}%",
             transform=ax1.transAxes, fontsize=8, va="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    ax2 = axes[1]
    bins = max(5, len(pnls) // 2)
    ax2.hist(pnls, bins=bins,
             color=STYLE["long"] if np.mean(pnls) > 0 else STYLE["short"],
             edgecolor="white", alpha=0.8)
    ax2.axvline(0, color="grey", lw=1, ls="--")
    ax2.axvline(float(np.mean(pnls)), color="#ff7f0e", lw=1.5,
                label=f"均值 {np.mean(pnls):+.2f}%")
    ax2.set_xlabel("損益 (%)")
    ax2.set_ylabel("頻次")
    ax2.set_title("損益分佈", fontsize=9)
    ax2.legend(fontsize=7)
    ax2.grid(color=STYLE["grid"], lw=0.4)

    fig.suptitle(f"Chart 20 | OOS 逐筆損益  {label}", fontsize=10)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


# ── Markdown 報告 ─────────────────────────────────────────────────────────────

def fmt_p(p):
    if p < 0.001: return "< 0.001***"
    if p < 0.01:  return f"{p:.4f}**"
    if p < 0.05:  return f"{p:.4f}*"
    if p < 0.10:  return f"{p:.4f}†"
    return f"{p:.4f}"


def build_report(label: str, n_total: int, oos_start: int,
                 oos_result: dict, bt: dict, ps: dict,
                 entry_thresh: float, exit_thresh: float,
                 max_hold: int, cost: float,
                 multi_table: str, annual_table: str,
                 train_window: int, refit_freq: int) -> str:

    fit_log  = oos_result["fit_log"]
    fail_log = oos_result["fail_log"]
    switches = analyze_sigdir_switches(fit_log)
    yr_sum   = sigdir_year_summary(fit_log)
    n_oos    = n_total - oos_start
    bh_oos   = float(bt["cum_bh"][-1]) - float(bt["cum_bh"][oos_start])

    lines = [
        f"# Phase 5 樣本外驗證報告 ({label})",
        "",
        f"> **資料範圍**：{n_total} 筆交易日。",
        f"> **訓練視窗**：{train_window} 天  **重估頻率**：每 {refit_freq} 天",
        f"> **OOS 期間**：{n_oos} 天（從第 {oos_start + 1} 日起）",
        f"> z-score 及 VECM β 完全使用訓練視窗估計——**無任何未來資訊**。",
        "",

        "## 1. 滾動 VECM 重估統計",
        "",
        f"| 項目 | 數值 |",
        f"|------|------|",
        f"| 重估嘗試次數 | {len(fit_log) + len(fail_log)} |",
        f"| 成功次數 | {len(fit_log)} |",
        f"| 失敗次數 | {len(fail_log)} |",
        f"| 成功率 | {len(fit_log) / max(1, len(fit_log) + len(fail_log)) * 100:.1f}% |",
        "",
    ]

    if fail_log:
        lines += [
            "### 失敗紀錄（前 10 筆）",
            "",
            "| 日期 | 原因 |",
            "|------|------|",
        ]
        for f in fail_log[:10]:
            lines.append(f"| {f['date']} | {f['reason']} |")
        lines.append("")

    lines += [
        "## 2. sig_dir 時序分析",
        "",
        "### 年度分佈",
        "",
        "| 年度 | sig_dir=+1（次）| sig_dir=-1（次）|",
        "|------|----------------|----------------|",
    ]
    for yr in sorted(yr_sum):
        p1 = yr_sum[yr].get("+1", 0)
        n1 = yr_sum[yr].get("-1", 0)
        dom = "**+1**" if p1 >= n1 else "**-1**"
        lines.append(f"| {yr} | {p1}（{dom if p1 >= n1 else p1}）| {n1}（{dom if n1 > p1 else n1}）|")
    lines.append("")

    lines += [
        "### sig_dir 切換事件",
        "",
    ]
    if switches:
        lines += [
            "| 切換日期 | 方向 | 前次重估日 |",
            "|----------|------|-----------|",
        ]
        for sw in switches:
            lines.append(f"| {sw['switch_date']} | {sw['from']:+d} → {sw['to']:+d} | {sw['prev_date']} |")
    else:
        lines.append("> 無切換事件（sig_dir 全程一致）。")
    lines.append("")

    lines += [
        "## 3. OOS 回測績效",
        "",
        "| 指標 | OOS 策略 | Buy-Hold TX（OOS 期）|",
        "|------|----------|---------------------|",
        f"| 合計報酬 | {ps['total_ret']:+.2f}% | {bh_oos:+.2f}% |",
        f"| 交易次數 | {ps['n_trades']} | — |",
        f"| 命中率 | {ps['hit_rate']:.0f}% | — |",
        f"| 平均獲利（勝）| {ps['avg_win']:+.3f}% | — |",
        f"| 平均虧損（敗）| {ps['avg_loss']:+.3f}% | — |",
        f"| 年化 Sharpe | {ps['sharpe']:+.2f} | — |",
        f"| 最大回撤 | {ps['max_dd']:.2f}% | — |",
        f"| Calmar 比率 | {ps['calmar']:.2f} | — |",
        "",

        "## 4. 多門檻比較（OOS）",
        "",
        multi_table,
        "",

        "## 5. 年度 OOS 績效分解",
        "",
        annual_table,
        "",

        "## 6. 逐筆交易明細",
        "",
        "| # | 進場日 | 方向 | sig_dir | 進場z | 出場日 | 出場z | 持有(天) | 損益% |",
        "|---|--------|------|---------|-------|--------|-------|----------|-------|",
    ]
    for i, t in enumerate(bt["trades"], 1):
        note = t.get("note", "")
        lines.append(
            f"| {i} | {t['entry_date']} | {t['direction']} "
            f"| {t.get('sig_dir', '?'):+d} | {t['entry_z']:+.2f} "
            f"| {t['exit_date']} | {t['exit_z']:+.2f} "
            f"| {t['hold_days']} | {t['pnl_pct']:+.4f}% {note} |"
        )

    lines += [
        "",
        "## 7. 圖表說明",
        "",
        "- **Chart 18**：滾動 sig_dir 時序。藍=+1（TX 追 TAIEX）紅=-1（均值回歸），垂直虛線=切換點。",
        "- **Chart 19**：OOS 累積報酬（策略 vs Buy-Hold TX），從 OOS 起始歸零。",
        "- **Chart 20**：OOS 逐筆損益棒圖（左）+ 分佈直方圖（右），底部標示 sig_dir。",
        "",

        "## 8. 結論",
        "",
        f"- **樣本外共 {n_oos} 天**，{len(fit_log)} 次 VECM 重估，成功率 {len(fit_log)/max(1,len(fit_log)+len(fail_log))*100:.1f}%。",
        f"- OOS 合計報酬 {ps['total_ret']:+.2f}%，Buy-Hold {bh_oos:+.2f}%，Sharpe {ps['sharpe']:+.2f}。",
    ]
    if switches:
        lines.append(f"- sig_dir 共發生 {len(switches)} 次切換，顯示 α 方向在樣本外期間並非穩定。")
    else:
        lines.append("- sig_dir 全程未切換，α 方向在樣本外期間穩定。")
    lines += [
        "- 與 Phase 4 in-sample 比較：",
        "  - in-sample（202401–202512）Sharpe = +2.43（全樣本 z，±1.0σ）",
        f"  - OOS Sharpe = {ps['sharpe']:+.2f}——{'退化明顯，模型有前視偏差' if ps['sharpe'] < 0.5 else '維持正向，OOS 有效' if ps['sharpe'] > 0 else 'OOS 接近零，信號稀疏'}",
        "",
        "---",
        "*Phase 5 完成。*",
    ]
    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ym",         help="單月 YYYYMM")
    parser.add_argument("--ym-range",   nargs=2, metavar=("START", "END"))
    parser.add_argument("--data-dir",   default="data/tw_futures")
    parser.add_argument("--output-dir", default="reports/tw_futures_analysis")
    parser.add_argument("--train-window", type=int,   default=60)
    parser.add_argument("--refit-freq",   type=int,   default=5)
    parser.add_argument("--entry-thresh", type=float, default=1.0)
    parser.add_argument("--exit-thresh",  type=float, default=0.5)
    parser.add_argument("--max-hold",     type=int,   default=5)
    parser.add_argument("--cost",         type=float, default=0.001)
    args = parser.parse_args()

    if args.ym_range:
        months = _ym_range(args.ym_range[0], args.ym_range[1])
        label  = f"{args.ym_range[0]}-{args.ym_range[1]}"
    elif args.ym:
        if not re.fullmatch(r"\d{6}", args.ym):
            sys.exit("--ym 格式錯誤")
        months = [args.ym]
        label  = args.ym
    else:
        sys.exit("請指定 --ym YYYYMM 或 --ym-range START END")

    data_dir  = Path(args.data_dir)
    out_dir   = Path(args.output_dir)
    chart_dir = out_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    # ── 載入資料 ──────────────────────────────────────────────────────────────
    print(f"[Phase 5] 載入資料：{months[0]} … {months[-1]}（{len(months)} 個月）")
    twse_rows, tx_rows = [], []
    for m in months:
        tp = data_dir / f"twse_taiex_{m}.csv"
        fp = data_dir / f"taifex_tx_{m}.csv"
        if not tp.exists() or not fp.exists():
            sys.exit(f"找不到資料檔：{m}，請先執行 Phase 1。")
        twse_rows.extend(load_csv(tp))
        tx_rows.extend(load_csv(fp))

    # 過濾有效列（taiex 與 tx_close 均非 None）
    ds_raw = build_dataset(twse_rows, tx_rows)
    ds     = [r for r in ds_raw if r["taiex"] is not None and r["tx_close"] is not None]
    print(f"[Phase 5] 有效交易日：{len(ds)} 筆")

    if len(ds) <= args.train_window:
        sys.exit(f"資料不足（{len(ds)} ≤ train_window={args.train_window}）")

    # ── 滾動 OOS 信號生成 ───────────────────────────────────────────────────
    oos_result = generate_oos_signals(ds, args.train_window, args.refit_freq)
    oos_start  = oos_result["oos_start"]
    z_arr      = oos_result["z_arr"]
    sig_dir_arr= oos_result["sig_dir_arr"]

    n_oos = len(ds) - oos_start
    n_valid = int(np.sum(~np.isnan(z_arr[oos_start:])))
    print(f"[Phase 5] OOS z-score 有效：{n_valid}/{n_oos}")

    # ── 回測 ─────────────────────────────────────────────────────────────────
    print(f"[Phase 5] OOS 回測（entry±{args.entry_thresh}σ / exit±{args.exit_thresh}σ / "
          f"max_hold={args.max_hold}d / cost={args.cost*100:.1f}%）…")
    bt = backtest_oos(ds, z_arr, sig_dir_arr, oos_start,
                      args.entry_thresh, args.exit_thresh,
                      args.max_hold, args.cost)
    ps = perf_stats(bt, oos_start)
    print(f"  交易次數：{ps['n_trades']}  合計報酬：{ps['total_ret']:+.2f}%"
          f"  命中率：{ps['hit_rate']:.0f}%  Sharpe：{ps['sharpe']:+.2f}")

    multi_table  = multi_thresh_table_oos(ds, z_arr, sig_dir_arr, oos_start,
                                          [0.5, 1.0, 1.5],
                                          args.exit_thresh, args.max_hold, args.cost)
    annual_table = annual_breakdown_oos(ds, bt, oos_start)

    # ── 圖表 ─────────────────────────────────────────────────────────────────
    print("[Phase 5] 生成圖表…")
    dates_all  = [r["date"] for r in ds]
    dates_oos  = dates_all[oos_start:]
    sd_oos     = sig_dir_arr[oos_start:]
    switches   = analyze_sigdir_switches(oos_result["fit_log"])

    chart_sigdir(dates_oos, sd_oos, oos_result["fit_log"], switches,
                 label, chart_dir / "chart_18_sigdir.png")
    print("  ✓ chart_18_sigdir.png")

    chart_equity_oos(dates_all, bt["cum_pnl"], bt["cum_bh"], oos_start,
                     bt["trades"], label, chart_dir / "chart_19_equity_oos.png")
    print("  ✓ chart_19_equity_oos.png")

    chart_trade_pnl_oos(bt["trades"], label, chart_dir / "chart_20_trade_pnl_oos.png")
    print("  ✓ chart_20_trade_pnl_oos.png")

    # ── 報告 ─────────────────────────────────────────────────────────────────
    print("[Phase 5] 生成報告…")
    report = build_report(
        label, len(ds), oos_start,
        oos_result, bt, ps,
        args.entry_thresh, args.exit_thresh,
        args.max_hold, args.cost,
        multi_table, annual_table,
        args.train_window, args.refit_freq,
    )
    rpt_path = out_dir / f"phase5_report_{label}.md"
    rpt_path.write_text(report, encoding="utf-8")
    print(f"  ✓ {rpt_path}")

    # ── OOS CSV ──────────────────────────────────────────────────────────────
    csv_path = out_dir / f"phase5_oos_{label}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv_mod.writer(f)
        w.writerow(["date", "taiex", "tx_close", "ect_zscore_oos", "sig_dir", "position"])
        pos_arr = bt["position"]
        for i in range(oos_start, len(ds)):
            row = ds[i]
            z_v = f"{z_arr[i]:.4f}" if not np.isnan(z_arr[i]) else ""
            w.writerow([row["date"], row["taiex"], row["tx_close"],
                        z_v, int(sig_dir_arr[i]), int(pos_arr[i])])
    print(f"  ✓ {csv_path}")

    print(f"\n[Phase 5 完成]")
    print(f"  OOS 期間：{dates_all[oos_start]} → {dates_all[-1]}  ({n_oos} 天)")
    print(f"  合計報酬：{ps['total_ret']:+.2f}%  Buy-Hold：{float(bt['cum_bh'][-1])-float(bt['cum_bh'][oos_start]):+.2f}%")
    print(f"  命中率：{ps['hit_rate']:.0f}%  Sharpe：{ps['sharpe']:+.2f}  Max DD：{ps['max_dd']:.2f}%")
    print(f"  sig_dir 切換：{len(switches)} 次")


if __name__ == "__main__":
    main()
