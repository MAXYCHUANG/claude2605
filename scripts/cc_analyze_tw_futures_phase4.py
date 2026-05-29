#!/usr/bin/env python3
"""
Phase 4：ECT 均值回歸信號萃取與回測
  - 重新估計 VECM（與 Phase 3 相同參數）
  - 計算 ECT z-score 時序
  - 均值回歸信號：|z_{t-1}| > entry_thresh → 進場（SHORT TX / LONG TX）
  - 出場：|z_t| < exit_thresh 或持有 >= max_hold_days
  - 績效統計：命中率、Sharpe、最大回撤、Calmar
  - 多門檻比較（0.5σ / 1.0σ / 1.5σ）
  - 圖表 Chart 15~17，報告 phase4_report_LABEL.md

用法（多月範圍，與 Phase 3 相同）：
  /usr/bin/python3 scripts/cc_analyze_tw_futures_phase4.py --ym-range 202603 202605

選用參數：
  --entry-thresh  float   進場門檻（z-score 倍數，預設 1.0）
  --exit-thresh   float   出場門檻（z-score 倍數，預設 0.5）
  --max-hold      int     最長持有天數（預設 5）
  --cost          float   單邊交易成本（佔成交金額，預設 0.001 = 0.1%）
"""

import argparse
import csv
import math
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from statsmodels.tsa.stattools import coint
from statsmodels.tsa.vector_ar.vecm import VECM as VECMModel

FIG_DPI = 150
STYLE = {
    "long":  "#1f77b4",
    "short": "#d62728",
    "ect":   "#ff7f0e",
    "bh":    "#2ca02c",
    "cost":  "#9467bd",
    "ci":    "#aec7e8",
    "grid":  "#e0e0e0",
    "zero":  "#555555",
}


# ── 資料載入（與 Phase 3 相同）────────────────────────────────────────────────

def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


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
        t_oi    = parse_float(tx["oi"])
        t_chgf  = parse_float(tx["change"])

        def _nn(*vals):
            return all(v is not None for v in vals)

        basis   = (t_close - taiex) if _nn(t_close, taiex) else None
        t_pct   = (t_chg / (taiex - t_chg) * 100) if (_nn(t_chg, taiex) and (taiex - t_chg) != 0) else None
        f_pct   = (t_chgf / (t_close - t_chgf) * 100) if (_nn(t_chgf, t_close) and (t_close - t_chgf) != 0) else None
        night_r = (t_night / t_vol * 100) if (_nn(t_night, t_vol) and t_vol > 0) else None
        result.append({
            "date":        d,
            "taiex":       taiex,
            "taiex_chg":   t_chg,
            "taiex_pct":   t_pct,
            "amount_bn":   amount / 1e9 if amount else None,
            "tx_close":    t_close,
            "tx_chg":      t_chgf,
            "tx_pct":      f_pct,
            "tx_vol":      t_vol,
            "tx_night":    t_night,
            "night_ratio": night_r,
            "tx_oi":       t_oi,
            "basis":       basis,
        })
    return result


def vec_aligned(*keys, ds) -> tuple[np.ndarray, ...]:
    mask = [all(r[k] is not None for k in keys) for r in ds]
    rows = [r for r, m in zip(ds, mask) if m]
    return tuple(np.array([r[k] for r in rows], dtype=np.float64) for k in keys)


# ── VECM 估計與 ECT 計算 ──────────────────────────────────────────────────────

def fit_vecm_and_ect(ds: list[dict]) -> dict:
    """
    估計 VECM，回傳 beta / alpha / ECT 序列與 z-score。
    """
    taiex_lv, tx_lv = vec_aligned("taiex", "tx_close", ds=ds)
    n = len(taiex_lv)
    dates_lv = [r["date"] for r in ds
                if r["taiex"] is not None and r["tx_close"] is not None]

    # Engle-Granger 協整預檢
    eg_stat, eg_pval, _ = coint(taiex_lv, tx_lv)
    print(f"  EG 協整：stat={eg_stat:.4f}  p={eg_pval:.4f}")
    if eg_pval >= 0.10:
        return {"ok": False, "reason": f"EG 協整 p={eg_pval:.4f}，未達顯著，無法建立 ECT 信號。"}

    # VECM（與 Phase 3 相同參數）
    k_ar_diff = max(1, min(2, (n - 4) // 4))
    vecm_mdl  = VECMModel(np.column_stack([taiex_lv, tx_lv]),
                          k_ar_diff=k_ar_diff, coint_rank=1, deterministic="co")
    res = vecm_mdl.fit()

    beta  = res.beta[:, 0]   # [b0, b1, bc]
    alpha = res.alpha         # (2, 1)
    pv_a  = res.pvalues_alpha # (2, 1)
    b0    = float(beta[0])
    b1    = float(beta[1])
    bc    = float(beta[2]) if len(beta) > 2 else 0.0
    beta_tx = float(-b1 / b0) if abs(b0) > 1e-10 else float(-b1)

    print(f"  β(TX)={beta_tx:.4f}  α_TAIEX={alpha[0,0]:.4f}(p={pv_a[0,0]:.4f})"
          f"  α_TX={alpha[1,0]:.4f}(p={pv_a[1,0]:.4f})")

    ect_raw = np.array([b0 * t + b1 * x + bc
                        for t, x in zip(taiex_lv, tx_lv)])
    mu_ect  = float(np.mean(ect_raw))
    sd_ect  = float(np.std(ect_raw, ddof=1))
    z_full  = (ect_raw - mu_ect) / sd_ect if sd_ect > 0 else ect_raw * 0

    # 從 α 決定信號方向：哪一方是追隨者，TX 會怎麼動？
    # α_TX > 0, sig → ECT>0 時 TX 上漲追 TAIEX → LONG TX → sig_dir = +1
    # α_TX < 0, sig → ECT>0 時 TX 下跌收斂  → SHORT TX → sig_dir = -1
    # α_TAIEX sig (fallback) → TX 因高相關跟 TAIEX → sig_dir = sign(α_TAIEX)
    # 都不顯著 → 預設均值回歸 → sig_dir = -1
    a_t = float(alpha[0, 0]); p_t = float(pv_a[0, 0])
    a_x = float(alpha[1, 0]); p_x = float(pv_a[1, 0])
    if p_x < 0.10:
        sig_dir = int(np.sign(a_x))
        sig_source = f"α_TX={a_x:+.4f}(p={p_x:.4f})"
    elif p_t < 0.10:
        sig_dir = int(np.sign(a_t))
        sig_source = f"α_TAIEX={a_t:+.4f}(p={p_t:.4f})"
    else:
        sig_dir = -1
        sig_source = "α 均不顯著，預設均值回歸"
    print(f"  信號方向：{'FOLLOW ECT (+1)' if sig_dir > 0 else 'OPPOSE ECT (-1)'}  依據：{sig_source}")

    return {
        "ok":        True,
        "dates":     dates_lv,
        "taiex_lv":  taiex_lv,
        "tx_lv":     tx_lv,
        "beta":      (b0, b1, bc, beta_tx),
        "alpha":     (float(alpha[0, 0]), float(alpha[1, 0])),
        "pvalues":   (float(pv_a[0, 0]),  float(pv_a[1, 0])),
        "ect_raw":   ect_raw,
        "mu_ect":    mu_ect,
        "sd_ect":    sd_ect,
        "z_score":   z_full,
        "eg_pval":   eg_pval,
        "k_ar_diff": k_ar_diff,
        "n":         n,
        "sig_dir":   sig_dir,
        "sig_source":sig_source,
    }


def rolling_zscore(ect_raw: np.ndarray, window: int) -> np.ndarray:
    """
    以滾動視窗計算 z-score（trailing window，不含未來資料）。
    前 window 天使用擴張視窗（expanding）避免 NaN 過多。
    """
    n = len(ect_raw)
    z = np.zeros(n)
    for t in range(n):
        start = max(0, t - window + 1)
        seg   = ect_raw[start: t + 1]
        if len(seg) < 2:
            z[t] = 0.0
            continue
        mu = float(np.mean(seg))
        sd = float(np.std(seg, ddof=1))
        z[t] = (ect_raw[t] - mu) / sd if sd > 1e-10 else 0.0
    return z


# ── 交易信號生成與回測 ────────────────────────────────────────────────────────

FLAT  =  0
LONG  =  1   # Long TX
SHORT = -1   # Short TX


def backtest(ds_aligned: list[dict], z: np.ndarray,
             entry_thresh: float, exit_thresh: float,
             max_hold: int, cost: float, sig_dir: int = -1) -> dict:
    """
    state machine 回測。
    sig_dir: +1 = follow ECT（TX 追 TAIEX）；-1 = oppose ECT（均值回歸）。
    entry logic: sz = sig_dir * z_prev; sz > thresh → LONG; sz < -thresh → SHORT
    """
    n       = len(z)
    state   = FLAT
    hold    = 0
    entry_i = None
    entry_z = None
    entry_dir = FLAT

    daily_pnl  = np.zeros(n)    # 當日策略報酬（%）
    position   = np.zeros(n, dtype=int)  # 當日持倉方向
    trades     = []

    # tx_pct for return calculation
    def get_tx_pct(i):
        v = ds_aligned[i].get("tx_pct")
        return v if v is not None else 0.0

    for t in range(1, n):
        z_prev = float(z[t - 1])
        z_curr = float(z[t])

        sz = sig_dir * z_prev   # 統一化：sz > thresh → LONG，sz < -thresh → SHORT
        if state == FLAT:
            if sz > entry_thresh:
                state = LONG;  hold = 0; entry_i = t; entry_z = z_prev
                daily_pnl[t] += -cost
            elif sz < -entry_thresh:
                state = SHORT; hold = 0; entry_i = t; entry_z = z_prev
                daily_pnl[t] += -cost           # 入場成本
        else:
            hold += 1
            ret = get_tx_pct(t)
            daily_pnl[t] += state * ret         # LONG=+, SHORT=-

            # 出場條件：z 回歸 exit zone 或超過最大持有
            should_exit = (abs(z_curr) < exit_thresh) or (hold >= max_hold)
            if should_exit:
                daily_pnl[t] += -cost           # 出場成本
                trades.append({
                    "entry_date": ds_aligned[entry_i]["date"],
                    "exit_date":  ds_aligned[t]["date"],
                    "direction":  "LONG" if state == LONG else "SHORT",
                    "entry_z":    round(entry_z, 3),
                    "exit_z":     round(z_curr, 3),
                    "hold_days":  hold,
                    "pnl_pct":    round(float(np.sum(daily_pnl[entry_i:t + 1])), 4),
                })
                state = FLAT; hold = 0; entry_i = None

        position[t] = state

    # 若期末仍持倉，強制平倉
    if state != FLAT and entry_i is not None:
        t = n - 1
        daily_pnl[t] += -cost
        trades.append({
            "entry_date": ds_aligned[entry_i]["date"],
            "exit_date":  ds_aligned[t]["date"],
            "direction":  "LONG" if state == LONG else "SHORT",
            "entry_z":    round(entry_z, 3),
            "exit_z":     round(float(z[t]), 3),
            "hold_days":  hold,
            "pnl_pct":    round(float(np.sum(daily_pnl[entry_i:])), 4),
            "note":       "強制平倉",
        })

    # 累積報酬（簡單加總，未複利，單位：%）
    cum_pnl = np.cumsum(daily_pnl)

    # Buy-and-Hold TX
    tx_pcts = np.array([r.get("tx_pct") or 0.0 for r in ds_aligned], dtype=np.float64)
    cum_bh  = np.cumsum(tx_pcts)

    return {
        "trades":    trades,
        "daily_pnl": daily_pnl,
        "cum_pnl":   cum_pnl,
        "cum_bh":    cum_bh,
        "position":  position,
    }


def perf_stats(bt: dict, daily_pnl: np.ndarray = None) -> dict:
    if daily_pnl is None:
        daily_pnl = bt["daily_pnl"]
    trades   = bt["trades"]
    cum_pnl  = bt["cum_pnl"]

    total_ret = float(cum_pnl[-1])
    n_trades  = len(trades)
    wins      = sum(1 for t in trades if t["pnl_pct"] > 0)
    hit_rate  = (wins / n_trades * 100) if n_trades > 0 else 0.0
    avg_win   = float(np.mean([t["pnl_pct"] for t in trades if t["pnl_pct"] > 0])) if wins > 0 else 0.0
    avg_loss  = float(np.mean([t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0])) if (n_trades - wins) > 0 else 0.0

    # Sharpe（年化，假設 252 交易日）
    active   = daily_pnl[daily_pnl != 0]
    sharpe   = 0.0
    if len(active) > 1:
        mu_d = float(np.mean(active))
        sd_d = float(np.std(active, ddof=1))
        sharpe = (mu_d / sd_d * math.sqrt(252)) if sd_d > 0 else 0.0

    # 最大回撤
    peak   = np.maximum.accumulate(cum_pnl)
    dd     = cum_pnl - peak
    max_dd = float(np.min(dd))

    # Calmar（年化報酬 / 最大回撤絕對值）
    active_days = int(np.sum(daily_pnl != 0))
    ann_ret = total_ret * 252 / max(1, active_days)
    calmar  = (ann_ret / abs(max_dd)) if max_dd < -1e-6 else float("inf")

    return {
        "total_ret": total_ret,
        "n_trades":  n_trades,
        "hit_rate":  hit_rate,
        "avg_win":   avg_win,
        "avg_loss":  avg_loss,
        "sharpe":    sharpe,
        "max_dd":    max_dd,
        "calmar":    calmar,
        "ann_ret":   ann_ret,
    }


# ── 圖表 ──────────────────────────────────────────────────────────────────────

def chart_ect_signals(dates: list[str], z: np.ndarray, trades: list[dict],
                      entry_thresh: float, exit_thresh: float,
                      label: str, out: Path):
    """Chart 15: ECT z-score 時序 + 進出場標記。"""
    n = len(z)
    x = np.arange(n)
    fig, ax = plt.subplots(figsize=(13, 5))

    colors = [STYLE["short"] if v > 0 else STYLE["long"] for v in z]
    ax.bar(x, z, color=colors, width=0.7, alpha=0.75)

    ax.axhline(0,              color=STYLE["zero"], lw=0.8)
    ax.axhline( entry_thresh,  color=STYLE["short"], lw=1.2, ls="--",
                label=f"+{entry_thresh}σ 進場（SHORT TX）")
    ax.axhline(-entry_thresh,  color=STYLE["long"],  lw=1.2, ls="--",
                label=f"−{entry_thresh}σ 進場（LONG TX）")
    ax.axhline( exit_thresh,   color="grey", lw=0.8, ls=":")
    ax.axhline(-exit_thresh,   color="grey", lw=0.8, ls=":", label=f"±{exit_thresh}σ 出場")

    # 標記進出場
    date_idx = {d: i for i, d in enumerate(dates)}
    for tr in trades:
        ei = date_idx.get(tr["entry_date"])
        xi = date_idx.get(tr["exit_date"])
        if ei is not None:
            marker = "v" if tr["direction"] == "SHORT" else "^"
            color  = STYLE["short"] if tr["direction"] == "SHORT" else STYLE["long"]
            ax.scatter(ei, float(z[ei]) + (0.15 if tr["direction"] == "LONG" else -0.15),
                       marker=marker, color=color, s=80, zorder=5)
        if xi is not None:
            ax.scatter(xi, float(z[xi]),
                       marker="x", color="black", s=60, zorder=5)

    # 日期軸（每 5 天顯示一個標籤）
    step = max(1, n // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(dates[::step], rotation=35, ha="right", fontsize=7)
    ax.set_ylabel("ECT z-score")
    ax.set_title(f"Chart 15 | ECT z-score 與交易信號  {label}\n"
                 "▲ = LONG TX 進場  ▼ = SHORT TX 進場  × = 出場", fontsize=9)
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(color=STYLE["grid"], lw=0.4)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_equity(dates: list[str], cum_pnl: np.ndarray, cum_bh: np.ndarray,
                 trades: list[dict], label: str, out: Path):
    """Chart 16: 累積報酬（策略 vs Buy-Hold TX）。"""
    n = len(dates)
    x = np.arange(n)
    fig, ax = plt.subplots(figsize=(13, 5))

    ax.plot(x, cum_pnl, color=STYLE["long"],  lw=1.8, label="ECT 信號策略")
    ax.plot(x, cum_bh,  color=STYLE["bh"],    lw=1.5, ls="--", label="Buy-Hold TX", alpha=0.8)
    ax.axhline(0, color=STYLE["zero"], lw=0.7, ls=":")

    # 交易進出場垂直線
    date_idx = {d: i for i, d in enumerate(dates)}
    first_long = first_short = True
    for tr in trades:
        ei = date_idx.get(tr["entry_date"])
        if ei is not None:
            color = STYLE["long"] if tr["direction"] == "LONG" else STYLE["short"]
            lbl   = (f"LONG 進場" if (tr["direction"] == "LONG" and first_long) else
                     f"SHORT 進場" if (tr["direction"] == "SHORT" and first_short) else None)
            if tr["direction"] == "LONG": first_long = False
            if tr["direction"] == "SHORT": first_short = False
            ax.axvline(ei, color=color, lw=0.8, alpha=0.4, label=lbl)

    step = max(1, n // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(dates[::step], rotation=35, ha="right", fontsize=7)
    ax.set_ylabel("累積報酬 (%，簡單加總)")
    ax.set_title(f"Chart 16 | 累積報酬：ECT 信號策略 vs Buy-Hold TX  {label}", fontsize=9)
    ax.legend(fontsize=7, loc="best")
    ax.grid(color=STYLE["grid"], lw=0.4)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_trade_pnl(trades: list[dict], label: str, out: Path):
    """Chart 17: 逐筆損益棒圖 + 分佈直方圖。"""
    if not trades:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "無交易紀錄", ha="center", va="center", transform=ax.transAxes)
        plt.savefig(out, dpi=FIG_DPI)
        plt.close()
        return

    pnls  = [t["pnl_pct"] for t in trades]
    dirs  = [t["direction"] for t in trades]
    dates = [t["entry_date"] for t in trades]
    x     = np.arange(len(pnls))

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # 棒圖
    ax1 = axes[0]
    colors = [STYLE["long"] if p > 0 else STYLE["short"] for p in pnls]
    bars = ax1.bar(x, pnls, color=colors, width=0.6)
    ax1.axhline(0, color="grey", lw=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{d}\n{dr[0]}" for d, dr in zip(dates, dirs)],
                        fontsize=7, rotation=45, ha="right")
    ax1.set_ylabel("損益 (%)")
    ax1.set_title(f"逐筆損益  {label}", fontsize=9)
    ax1.grid(color=STYLE["grid"], lw=0.4, axis="y")

    total = sum(pnls)
    wins  = sum(1 for p in pnls if p > 0)
    ax1.text(0.02, 0.97,
             f"共 {len(pnls)} 筆 | 勝率 {wins/len(pnls)*100:.0f}% | 合計 {total:+.2f}%",
             transform=ax1.transAxes, fontsize=8, va="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    # 分佈直方圖
    ax2 = axes[1]
    bins = max(5, len(pnls) // 2)
    ax2.hist(pnls, bins=bins,
             color=[STYLE["long"] if np.mean(pnls) > 0 else STYLE["short"]],
             edgecolor="white", alpha=0.8)
    ax2.axvline(0, color="grey", lw=1, ls="--")
    ax2.axvline(float(np.mean(pnls)), color=STYLE["ect"], lw=1.5,
                label=f"均值 {np.mean(pnls):+.2f}%")
    ax2.set_xlabel("損益 (%)")
    ax2.set_ylabel("頻次")
    ax2.set_title("損益分佈", fontsize=9)
    ax2.legend(fontsize=7)
    ax2.grid(color=STYLE["grid"], lw=0.4)

    fig.suptitle(f"Chart 17 | 逐筆損益分析  {label}", fontsize=10)
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


def annual_breakdown(ds_aligned: list[dict], bt: dict) -> str:
    """按年度分解績效。"""
    daily_pnl = bt["daily_pnl"]
    tx_pcts   = np.array([r.get("tx_pct") or 0.0 for r in ds_aligned], dtype=np.float64)
    dates     = [r["date"] for r in ds_aligned]

    years = sorted(set(d[:4] for d in dates))
    rows  = ["| 年度 | 策略報酬 | Buy-Hold TX | 交易次數 | 勝率 |",
             "|------|----------|-------------|----------|------|"]

    for yr in years:
        idx = [i for i, d in enumerate(dates) if d[:4] == yr]
        if not idx:
            continue
        strat_ret = float(np.sum(daily_pnl[idx]))
        bh_ret    = float(np.sum(tx_pcts[idx]))
        yr_trades = [t for t in bt["trades"]
                     if t["entry_date"][:4] == yr]
        n_tr  = len(yr_trades)
        wins  = sum(1 for t in yr_trades if t["pnl_pct"] > 0)
        hr    = f"{wins/n_tr*100:.0f}%" if n_tr > 0 else "—"
        rows.append(f"| {yr} | {strat_ret:+.2f}% | {bh_ret:+.2f}% | {n_tr} | {hr} |")

    return "\n".join(rows)


def multi_thresh_table(ds_aligned, z, entry_thresholds, exit_thresh,
                       max_hold, cost, sig_dir=-1) -> str:
    rows = []
    rows.append("| 進場門檻 | 交易次數 | 勝率 | 合計報酬 | Buy-Hold | Sharpe | 最大回撤 |")
    rows.append("|----------|----------|------|----------|----------|--------|----------|")
    for et in entry_thresholds:
        bt = backtest(ds_aligned, z, et, exit_thresh, max_hold, cost, sig_dir=sig_dir)
        ps = perf_stats(bt)
        bh = float(bt["cum_bh"][-1])
        rows.append(
            f"| ±{et:.1f}σ "
            f"| {ps['n_trades']} "
            f"| {ps['hit_rate']:.0f}% "
            f"| {ps['total_ret']:+.2f}% "
            f"| {bh:+.2f}% "
            f"| {ps['sharpe']:+.2f} "
            f"| {ps['max_dd']:.2f}% |"
        )
    return "\n".join(rows)


def build_report(label: str, n: int, vecm: dict, bt: dict, ps: dict,
                 entry_thresh: float, exit_thresh: float,
                 max_hold: int, cost: float,
                 multi_table: str,
                 annual_table: str = "",
                 rolling_window: int = 0,
                 sig_dir: int = -1) -> str:
    b0, b1, bc, beta_tx = vecm["beta"]
    a_taiex, a_tx       = vecm["alpha"]
    p_taiex, p_tx       = vecm["pvalues"]
    z  = vecm["z_score"]
    bh = float(bt["cum_bh"][-1])
    trades = bt["trades"]

    zscore_note = (
        f"z-score 採 **滾動 {rolling_window} 天**視窗（trailing，無未來資料）；"
        "VECM β 仍為全樣本估計（look-ahead），純 ECT 標準化已消除。"
        if rolling_window > 0 else
        "z-score 與 VECM β 均為**全樣本**估計（in-sample baseline，含前視偏差）。"
    )
    lines = [
        f"# Phase 4 回測報告：ECT 均值回歸信號 ({label})",
        "",
        f"> **樣本**：{n} 筆交易日。{zscore_note}",
        "",

        "## 1. VECM 參數回顧（Phase 3 結果）",
        "",
        "| 參數 | 值 |",
        "|------|-----|",
        f"| β(TX) | {beta_tx:.4f} |",
        f"| α_TAIEX | {a_taiex:.4f}（p={fmt_p(p_taiex)}）|",
        f"| α_TX | {a_tx:.4f}（p={fmt_p(p_tx)}）|",
        f"| EG 協整 p | {vecm['eg_pval']:.4f} |",
        "",
        "> α_TAIEX < 0 且顯著：當 ECT > 0（TAIEX 相對偏高），次日 TAIEX 傾向下跌 → 提供均值回歸信號。",
        "",

        "## 2. ECT z-score 統計",
        "",
        "| 統計量 | 值 |",
        "|--------|-----|",
        f"| 樣本數 | {len(z)} |",
        f"| 均值（原始 ECT）| {vecm['mu_ect']:+.2f} pts |",
        f"| 標準差 | {vecm['sd_ect']:.2f} pts |",
        f"| z-score 最大值 | {float(np.max(z)):+.3f} |",
        f"| z-score 最小值 | {float(np.min(z)):+.3f} |",
        f"| |z| > 1.0σ 次數 | {int(np.sum(np.abs(z) > 1.0))} |",
        f"| |z| > 1.5σ 次數 | {int(np.sum(np.abs(z) > 1.5))} |",
        "",

        "## 3. 交易信號設計",
        "",
    ]
    a_taiex, a_tx = vecm["alpha"]
    p_taiex, p_tx = vecm["pvalues"]
    follower = ("TX 是追隨者（α_TX 顯著）：TX 向 TAIEX 方向靠攏"
                if p_tx < 0.10 else
                "TAIEX 是追隨者（α_TAIEX 顯著）：TAIEX 向 TX 方向靠攏"
                if p_taiex < 0.10 else
                "α 均不顯著，採預設均值回歸方向")
    if sig_dir > 0:
        long_cond  = f"z_{{t-1}} > +{entry_thresh}σ"
        short_cond = f"z_{{t-1}} < −{entry_thresh}σ"
        long_why   = "TAIEX 偏高，TX 向上追趕"
        short_why  = "TAIEX 偏低，TX 向下追趕"
    else:
        long_cond  = f"z_{{t-1}} < −{entry_thresh}σ"
        short_cond = f"z_{{t-1}} > +{entry_thresh}σ"
        long_why   = "TAIEX 偏低，均值回升，TX 跟漲"
        short_why  = "TAIEX 偏高，均值回落，TX 跟跌"
    lines += [
        f"> **偵測結論**：{follower}  →  `sig_dir = {sig_dir:+d}`",
        "",
        "| 條件 | 動作 | 理由 |",
        "|------|------|------|",
        f"| {long_cond} | **LONG TX** | {long_why} |",
        f"| {short_cond} | **SHORT TX** | {short_why} |",
        f"| |z_t| < {exit_thresh}σ 或持有 ≥ {max_hold} 天 | **平倉** | ECT 回歸均衡 |",
        "",

        "## 4. 回測設定",
        "",
        f"- 進場門檻：±{entry_thresh}σ",
        f"- 出場門檻：|z| < {exit_thresh}σ 或持有 ≥ {max_hold} 天",
        f"- 單邊交易成本：{cost * 100:.2f}%（往返 {cost * 200:.2f}%）",
        f"- 計算方式：簡單加總日報酬（%），未複利",
        "",

        "## 5. 績效總結",
        "",
        "| 指標 | 策略 | Buy-Hold TX |",
        "|------|------|-------------|",
        f"| 合計報酬 | {ps['total_ret']:+.2f}% | {bh:+.2f}% |",
        f"| 交易次數 | {ps['n_trades']} | — |",
        f"| 命中率 | {ps['hit_rate']:.0f}% | — |",
        f"| 平均獲利（勝） | {ps['avg_win']:+.3f}% | — |",
        f"| 平均虧損（敗） | {ps['avg_loss']:+.3f}% | — |",
        f"| 年化 Sharpe | {ps['sharpe']:+.2f} | — |",
        f"| 最大回撤 | {ps['max_dd']:.2f}% | — |",
        f"| Calmar 比率 | {ps['calmar']:.2f} | — |",
        "",

        "## 6. 多門檻比較",
        "",
        multi_table,
        "",

        "## 7. 逐筆交易明細",
        "",
        "| # | 進場日 | 方向 | 進場z | 出場日 | 出場z | 持有(天) | 損益% |",
        "|---|--------|------|-------|--------|-------|----------|-------|",
    ]

    for i, t in enumerate(trades, 1):
        note = t.get("note", "")
        lines.append(
            f"| {i} | {t['entry_date']} | {t['direction']} "
            f"| {t['entry_z']:+.2f} | {t['exit_date']} "
            f"| {t['exit_z']:+.2f} | {t['hold_days']} "
            f"| {t['pnl_pct']:+.4f}% {note} |"
        )

    lines += [
        "",
        "## 8. 圖表說明",
        "",
        "- **Chart 15**：ECT z-score 時序圖（橘＝正偏離，藍＝負偏離）+ 進出場標記。",
        "  ▲ = LONG TX 進場，▼ = SHORT TX 進場，× = 出場。",
        "- **Chart 16**：累積報酬（策略 vs Buy-Hold TX）。垂直線為進場時點。",
        "- **Chart 17**：逐筆損益棒圖（左）+ 損益分佈直方圖（右）。",
        "",
    ]
    if annual_table:
        lines += [
            "## 9. 年度績效分解",
            "",
            annual_table,
            "",
        ]
    lines += [
        "## 10. 結論與局限",
        "",
        f"- 共 {ps['n_trades']} 筆交易，合計報酬 {ps['total_ret']:+.2f}%，",
        f"  Buy-Hold TX {bh:+.2f}%，命中率 {ps['hit_rate']:.0f}%。",
        f"- {zscore_note}",
        "- VECM 只能捕捉**均值回歸**機會；強趨勢行情中 ECT 持續偏離，信號多次失效。",
        f"- 樣本共 {n} 筆交易日，統計功效{'較充足' if n >= 200 else '有限，建議累積更多資料'}。",
        "",
        "### Phase 5 建議",
        "1. **滾動視窗回測**：以前 3 個月估計 VECM，第 4 個月做樣本外信號，消除前視偏差。",
        "2. **日內分鐘資料**：ECT 在分鐘級偏離更明顯，信號頻率更高，可提升統計功效。",
        "3. **風控層**：加入停損（單筆虧損 > 0.5%）、日內 VaR 上限、部位規模管理。",
        "4. **配對交易版本**：Long TX / Short 0050 ETF 以消除市場方向風險，聚焦純基差回歸。",
        "",
        "---",
        "*Phase 4 完成。下一步：Phase 5 — 滾動視窗樣本外驗證*",
    ]
    return "\n".join(lines)


# ── 月份工具 ──────────────────────────────────────────────────────────────────

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


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ym",        help="單月 YYYYMM")
    parser.add_argument("--ym-range",  nargs=2, metavar=("START", "END"))
    parser.add_argument("--data-dir",  default="data/tw_futures")
    parser.add_argument("--output-dir",default="reports/tw_futures_analysis")
    parser.add_argument("--entry-thresh", type=float, default=1.0,
                        help="進場門檻 z-score（預設 1.0）")
    parser.add_argument("--exit-thresh",  type=float, default=0.5,
                        help="出場門檻 z-score（預設 0.5）")
    parser.add_argument("--max-hold",     type=int,   default=5,
                        help="最長持有天數（預設 5）")
    parser.add_argument("--cost",         type=float, default=0.001,
                        help="單邊交易成本 (預設 0.001 = 0.1%%)")
    parser.add_argument("--rolling-window", type=int, default=0,
                        help="z-score 滾動視窗天數（0=全樣本，預設 0；建議 60）")
    parser.add_argument("--sig-dir", type=int, default=0, choices=[-1, 0, 1],
                        help="信號方向覆寫：-1=均值回歸 / +1=追趕 / 0=自動偵測（預設）")
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
    print(f"[Phase 4] 載入資料：{months}…")
    twse_rows, tx_rows = [], []
    for m in months:
        tp = data_dir / f"twse_taiex_{m}.csv"
        fp = data_dir / f"taifex_tx_{m}.csv"
        if not tp.exists() or not fp.exists():
            sys.exit(f"找不到資料檔：{m}，請先執行 Phase 1。")
        twse_rows.extend(load_csv(tp))
        tx_rows.extend(load_csv(fp))
    ds = build_dataset(twse_rows, tx_rows)
    print(f"[Phase 4] {len(ds)} 筆交易日（{len(months)} 個月）")

    # ── VECM 估計 + ECT ───────────────────────────────────────────────────────
    print("[Phase 4] 估計 VECM 並計算 ECT…")
    vecm = fit_vecm_and_ect(ds)
    if not vecm["ok"]:
        sys.exit(f"[Phase 4] VECM 失敗：{vecm['reason']}")

    # 對齊到有 taiex / tx_close 的列（ECT 所在列）
    ds_aligned = [r for r in ds if r["taiex"] is not None and r["tx_close"] is not None]
    dates      = vecm["dates"]
    n_ecm      = len(vecm["z_score"])

    # z-score：全樣本 or 滾動視窗
    if args.rolling_window > 0:
        z = rolling_zscore(vecm["ect_raw"], args.rolling_window)
        print(f"  使用滾動 {args.rolling_window} 天 z-score")
    else:
        z = vecm["z_score"]
    print(f"  ECT 序列長度：{n_ecm}  |z|>1σ：{int(np.sum(np.abs(z) > 1.0))} 次")

    # 信號方向：自動偵測或手動覆寫
    sig_dir = args.sig_dir if args.sig_dir != 0 else vecm["sig_dir"]
    sig_label = "auto-detected" if args.sig_dir == 0 else "manual override"
    print(f"  sig_dir = {sig_dir:+d}（{sig_label}）")

    # ── 主回測 ─────────────────────────────────────────────────────────────────
    print(f"[Phase 4] 回測（entry±{args.entry_thresh}σ / exit±{args.exit_thresh}σ / "
          f"max_hold={args.max_hold}d / cost={args.cost*100:.1f}%）…")
    bt = backtest(ds_aligned, z,
                  entry_thresh=args.entry_thresh,
                  exit_thresh=args.exit_thresh,
                  max_hold=args.max_hold,
                  cost=args.cost,
                  sig_dir=sig_dir)
    ps = perf_stats(bt)
    print(f"  交易次數：{ps['n_trades']}  合計報酬：{ps['total_ret']:+.2f}%"
          f"  命中率：{ps['hit_rate']:.0f}%  Sharpe：{ps['sharpe']:+.2f}")

    # 多門檻比較
    multi_table  = multi_thresh_table(ds_aligned, z,
                                      [0.5, 1.0, 1.5],
                                      args.exit_thresh,
                                      args.max_hold,
                                      args.cost,
                                      sig_dir=sig_dir)
    annual_table = annual_breakdown(ds_aligned, bt)

    # ── 圖表 ─────────────────────────────────────────────────────────────────
    print("[Phase 4] 生成圖表…")
    chart_ect_signals(dates, z, bt["trades"],
                      args.entry_thresh, args.exit_thresh,
                      label, chart_dir / "chart_15_ect_signals.png")
    print("  ✓ chart_15_ect_signals.png")

    chart_equity(dates, bt["cum_pnl"], bt["cum_bh"],
                 bt["trades"], label, chart_dir / "chart_16_equity.png")
    print("  ✓ chart_16_equity.png")

    chart_trade_pnl(bt["trades"], label, chart_dir / "chart_17_trade_pnl.png")
    print("  ✓ chart_17_trade_pnl.png")

    # ── 報告 ─────────────────────────────────────────────────────────────────
    print("[Phase 4] 生成報告…")
    report = build_report(label, n_ecm, vecm, bt, ps,
                          args.entry_thresh, args.exit_thresh,
                          args.max_hold, args.cost, multi_table,
                          annual_table=annual_table,
                          rolling_window=args.rolling_window,
                          sig_dir=sig_dir)
    rpt_path = out_dir / f"phase4_report_{label}.md"
    rpt_path.write_text(report, encoding="utf-8")
    print(f"  ✓ {rpt_path}")

    # ── ECT CSV（供後續分析）────────────────────────────────────────────────
    csv_path = out_dir / f"phase4_ect_{label}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        import csv as csv_mod
        w = csv_mod.writer(f)
        w.writerow(["date", "taiex", "tx_close", "ect_raw", "ect_zscore", "signal"])
        sig_arr = bt["position"]
        for i, (row, ect_r, z_v, sig) in enumerate(zip(ds_aligned,
                                                         vecm["ect_raw"],
                                                         z, sig_arr)):
            w.writerow([row["date"], row["taiex"], row["tx_close"],
                        f"{ect_r:.4f}", f"{z_v:.4f}", int(sig)])
    print(f"  ✓ {csv_path}")

    print(f"\n[Phase 4 完成]")
    print(f"  合計報酬：{ps['total_ret']:+.2f}%  Buy-Hold TX：{float(bt['cum_bh'][-1]):+.2f}%")
    print(f"  命中率：{ps['hit_rate']:.0f}%  Sharpe：{ps['sharpe']:+.2f}  Max DD：{ps['max_dd']:.2f}%")


if __name__ == "__main__":
    main()
