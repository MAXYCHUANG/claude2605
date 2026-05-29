#!/usr/bin/env python3
"""
Phase 6：訓練視窗長度 × sig_dir 確認機制 OOS 對比
  A. 對比 train_window = 60 / 120 / 180 天
  B. sig_dir 確認機制：連續 confirm_n 次重估方向一致才切換（1=立即切換）
  → 9 組組合（3×3）的 OOS 績效對比表

用法：
  /usr/bin/python3 scripts/cc_analyze_tw_futures_phase6.py --ym-range 202401 202512

選用參數：
  --train-windows  int [int ...]  訓練視窗清單（預設 60 120 180）
  --confirm-ns     int [int ...]  確認次數清單（預設 1 2 3）
  --refit-freq     int            重估頻率（天，預設 5）
  --entry-thresh   float          進場門檻（預設 1.0）
  --exit-thresh    float          出場門檻（預設 0.5）
  --max-hold       int            最長持有天數（預設 5）
  --cost           float          單邊成本（預設 0.001）
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


# ── 資料載入 ──────────────────────────────────────────────────────────────────

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
        taiex  = parse_float(row["taiex"])
        t_chg  = parse_float(row["change"])
        amount = parse_float(row["amount_twd"])
        t_cl   = parse_float(tx["close"])
        t_vol  = parse_float(tx["vol_total"])
        t_ngt  = parse_float(tx["vol_night"])
        t_chgf = parse_float(tx["change"])

        def _nn(*v): return all(x is not None for x in v)

        t_pct = (t_chg / (taiex - t_chg) * 100) if (_nn(t_chg, taiex) and (taiex - t_chg) != 0) else None
        f_pct = (t_chgf / (t_cl - t_chgf) * 100) if (_nn(t_chgf, t_cl) and (t_cl - t_chgf) != 0) else None
        n_rat = (t_ngt / t_vol * 100) if (_nn(t_ngt, t_vol) and t_vol > 0) else None
        result.append({
            "date":       d,
            "taiex":      taiex,
            "taiex_pct":  t_pct,
            "tx_close":   t_cl,
            "tx_pct":     f_pct,
            "tx_vol":     t_vol,
            "night_ratio":n_rat,
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
        k_ar = max(1, min(2, (n - 4) // 4))
        res  = VECMModel(np.column_stack([taiex_w, tx_w]),
                         k_ar_diff=k_ar, coint_rank=1,
                         deterministic="co").fit()
    except Exception as e:
        return {"ok": False, "reason": f"VECM例外: {e}"}

    beta = res.beta[:, 0]
    alph = res.alpha
    pv   = res.pvalues_alpha
    b0 = float(beta[0]); b1 = float(beta[1])
    bc = float(beta[2]) if len(beta) > 2 else 0.0
    a_t = float(alph[0, 0]); p_t = float(pv[0, 0])
    a_x = float(alph[1, 0]); p_x = float(pv[1, 0])

    if p_x < 0.10:
        sig_dir = int(np.sign(a_x)) if a_x != 0 else -1
    elif p_t < 0.10:
        sig_dir = int(np.sign(a_t)) if a_t != 0 else -1
    else:
        sig_dir = -1

    ect_w = b0 * taiex_w + b1 * tx_w + bc
    return {
        "ok": True,
        "b0": b0, "b1": b1, "bc": bc,
        "sig_dir": sig_dir,
        "mu_w": float(np.mean(ect_w)),
        "sd_w": float(np.std(ect_w, ddof=1)),
        "eg_pval": eg_pval,
    }


# ── 滾動 OOS 信號生成（含確認機制）────────────────────────────────────────────

def generate_oos(ds: list[dict],
                 train_window: int,
                 refit_freq: int,
                 confirm_n: int) -> dict:
    """
    confirm_n: 連續 confirm_n 次重估結果與 cur_sig_dir 不同才切換。
               confirm_n=1 → 立即切換（等同 Phase 5）。
    """
    n = len(ds)
    taiex_a = np.array([r["taiex"]    or np.nan for r in ds], dtype=np.float64)
    tx_a    = np.array([r["tx_close"] or np.nan for r in ds], dtype=np.float64)

    z_arr       = np.full(n, np.nan)
    sig_dir_arr = np.zeros(n, dtype=int)

    # VECM 當前確認狀態
    confirmed = {"ok": False, "b0": 0., "b1": 0., "bc": 0.,
                 "mu": 0., "sd": 1., "sig_dir": -1}
    # 確認機制緩衝
    pending_dir   = None   # 待確認的新方向
    pending_count = 0      # 連續次數

    n_success = n_fail = 0
    switches  = []
    prev_confirmed_dir = -1

    for t in range(train_window, n):
        oos_idx = t - train_window
        if oos_idx % refit_freq == 0:
            tw = taiex_a[t - train_window: t]
            txw = tx_a[t - train_window: t]
            valid = ~(np.isnan(tw) | np.isnan(txw))
            if valid.sum() >= 20:
                res = fit_vecm_window(tw[valid], txw[valid])
                if res["ok"]:
                    n_success += 1
                    new_dir = res["sig_dir"]
                    # 更新 VECM 參數（beta / mu / sd 總是取最新）
                    confirmed.update({
                        "ok": True,
                        "b0": res["b0"], "b1": res["b1"], "bc": res["bc"],
                        "mu": res["mu_w"], "sd": res["sd_w"],
                    })
                    # 確認機制：只對 sig_dir 切換部分控制
                    if new_dir == confirmed["sig_dir"]:
                        # 與目前一致，重置 pending
                        pending_dir   = None
                        pending_count = 0
                    elif new_dir == pending_dir:
                        # 連續第 N 次提議新方向
                        pending_count += 1
                        if pending_count >= confirm_n:
                            prev = confirmed["sig_dir"]
                            confirmed["sig_dir"] = new_dir
                            switches.append({
                                "date": ds[t]["date"],
                                "from": prev, "to": new_dir,
                                "pending_count": pending_count,
                            })
                            pending_dir   = None
                            pending_count = 0
                    else:
                        # 全新提議方向
                        pending_dir   = new_dir
                        pending_count = 1
                        if confirm_n == 1:
                            # 立即切換
                            prev = confirmed["sig_dir"]
                            if new_dir != prev:
                                confirmed["sig_dir"] = new_dir
                                switches.append({
                                    "date": ds[t]["date"],
                                    "from": prev, "to": new_dir,
                                    "pending_count": 1,
                                })
                            pending_dir   = None
                            pending_count = 0
                else:
                    n_fail += 1
            else:
                n_fail += 1

        if not confirmed["ok"]:
            continue

        ta = taiex_a[t - 1]; tx = tx_a[t - 1]
        if np.isnan(ta) or np.isnan(tx):
            continue
        ect = confirmed["b0"] * ta + confirmed["b1"] * tx + confirmed["bc"]
        z   = (ect - confirmed["mu"]) / confirmed["sd"] if confirmed["sd"] > 1e-10 else 0.
        z_arr[t]       = z
        sig_dir_arr[t] = confirmed["sig_dir"]

    return {
        "oos_start":    train_window,
        "z_arr":        z_arr,
        "sig_dir_arr":  sig_dir_arr,
        "n_success":    n_success,
        "n_fail":       n_fail,
        "n_switches":   len(switches),
        "switches":     switches,
    }


# ── 回測 ──────────────────────────────────────────────────────────────────────

def backtest(ds, z_arr, sig_dir_arr, oos_start,
             entry_thresh, exit_thresh, max_hold, cost,
             stop_loss: float = 0.0) -> dict:
    """
    stop_loss: 單筆最大允許虧損（%，正數）。
               0.0 = 停用（預設）。
               以進場後累計損益（含入場成本）跌破 -stop_loss 時出場。
    """
    n = len(z_arr)
    state = FLAT; hold = 0; ei = None; ez = 0.; esd = -1
    pnl = np.zeros(n); pos = np.zeros(n, dtype=int); trades = []

    def ret(i):
        v = ds[i].get("tx_pct"); return v if v is not None else 0.

    for t in range(oos_start, n):
        if np.isnan(z_arr[t]):
            pos[t] = state; continue
        z  = float(z_arr[t])
        sd = int(sig_dir_arr[t]) if sig_dir_arr[t] != 0 else -1
        sz = sd * z

        if state == FLAT:
            if sz > entry_thresh:
                state = LONG;  hold = 0; ei = t; ez = z; esd = sd; pnl[t] -= cost
            elif sz < -entry_thresh:
                state = SHORT; hold = 0; ei = t; ez = z; esd = sd; pnl[t] -= cost
        else:
            hold += 1; pnl[t] += state * ret(t)
            trade_pnl = float(np.sum(pnl[ei:t + 1]))
            sl_hit    = stop_loss > 0 and trade_pnl < -stop_loss
            if abs(z) < exit_thresh or hold >= max_hold or sl_hit:
                pnl[t] -= cost
                note = "停損" if sl_hit else ("強制平倉" if hold >= max_hold else "")
                trades.append({
                    "entry_date": ds[ei]["date"], "exit_date": ds[t]["date"],
                    "direction":  "LONG" if state == LONG else "SHORT",
                    "entry_z": round(ez, 3), "exit_z": round(z, 3),
                    "hold_days": hold,
                    "pnl_pct":  round(float(np.sum(pnl[ei:t + 1])), 4),
                    "sig_dir": esd,
                    "note": note,
                })
                state = FLAT; hold = 0
        pos[t] = state

    if state != FLAT and ei is not None:
        t = n - 1; pnl[t] -= cost
        trades.append({
            "entry_date": ds[ei]["date"], "exit_date": ds[t]["date"],
            "direction":  "LONG" if state == LONG else "SHORT",
            "entry_z": round(ez, 3),
            "exit_z": round(float(z_arr[t]), 3) if not np.isnan(z_arr[t]) else 0.,
            "hold_days": hold,
            "pnl_pct":  round(float(np.sum(pnl[ei:])), 4),
            "sig_dir": esd, "note": "強制平倉",
        })

    cum = np.cumsum(pnl)
    bh  = np.cumsum(np.array([r.get("tx_pct") or 0. for r in ds], dtype=np.float64))
    return {"trades": trades, "daily_pnl": pnl, "cum_pnl": cum, "cum_bh": bh, "position": pos}


def stats(bt, oos_start):
    pnl = bt["daily_pnl"][oos_start:]
    tr  = bt["trades"]
    cum = bt["cum_pnl"]

    total = float(cum[-1])
    n_tr  = len(tr)
    wins  = sum(1 for t in tr if t["pnl_pct"] > 0)
    hr    = wins / n_tr * 100 if n_tr > 0 else 0.

    act  = pnl[pnl != 0]
    shrp = 0.
    if len(act) > 1:
        mu = float(np.mean(act)); sd = float(np.std(act, ddof=1))
        shrp = mu / sd * math.sqrt(252) if sd > 0 else 0.

    peak  = np.maximum.accumulate(cum)
    mdd   = float(np.min(cum - peak))
    adays = int(np.sum(pnl != 0))
    ann   = total * 252 / max(1, adays)
    cal   = ann / abs(mdd) if mdd < -1e-6 else float("inf")

    return {"total": total, "n_tr": n_tr, "hr": hr,
            "sharpe": shrp, "mdd": mdd, "calmar": cal}


# ── 圖表 ──────────────────────────────────────────────────────────────────────

def chart_sigdir(dates_oos, sd_oos, switches, label, out):
    n = len(dates_oos)
    x = np.arange(n)
    colors = [STYLE["pos1"] if v > 0 else STYLE["neg1"] if v < 0 else STYLE["na"]
              for v in sd_oos]
    fig, ax = plt.subplots(figsize=(13, 3.5))
    ax.bar(x, sd_oos, color=colors, width=1.0, alpha=0.7)
    ax.axhline(0, color=STYLE["zero"], lw=0.8)
    date_idx = {d: i for i, d in enumerate(dates_oos)}
    for sw in switches:
        i = date_idx.get(sw["date"])
        if i is not None:
            ax.axvline(i, color="black", lw=1.0, ls="--", alpha=0.6)
            ax.text(i, 0.8, sw["date"], fontsize=5.5, rotation=90,
                    ha="right", va="top", color="black")
    step = max(1, n // 14)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(dates_oos[::step], rotation=35, ha="right", fontsize=7)
    ax.set_yticks([-1, 0, 1])
    ax.set_yticklabels(["-1 (均值回歸)", "0", "+1 (追趕)"], fontsize=8)
    ax.set_title(f"sig_dir 時序  {label}  切換次數={len(switches)}", fontsize=9)
    ax.grid(color=STYLE["grid"], lw=0.4, axis="x")
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI); plt.close()


def chart_equity(dates_all, cum_pnl, cum_bh, oos_start, trades, label, out):
    n = len(dates_all); x = np.arange(n)
    bs = cum_pnl[oos_start]; bb = cum_bh[oos_start]
    fig, ax = plt.subplots(figsize=(13, 4.5))
    ax.plot(x[oos_start:], (cum_pnl - bs)[oos_start:],
            color=STYLE["long"], lw=1.8, label="OOS 策略")
    ax.plot(x[oos_start:], (cum_bh - bb)[oos_start:],
            color=STYLE["bh"], lw=1.5, ls="--", label="Buy-Hold TX", alpha=0.8)
    ax.axhline(0, color=STYLE["zero"], lw=0.7, ls=":")
    di = {d: i for i, d in enumerate(dates_all)}
    fl = fs = True
    for tr in trades:
        ei = di.get(tr["entry_date"])
        if ei is None: continue
        c   = STYLE["long"] if tr["direction"] == "LONG" else STYLE["short"]
        lbl = (f"{tr['direction']}" if (tr["direction"] == "LONG" and fl) or
               (tr["direction"] == "SHORT" and fs) else None)
        if tr["direction"] == "LONG":  fl = False
        if tr["direction"] == "SHORT": fs = False
        ax.axvline(ei, color=c, lw=0.5, alpha=0.25, label=lbl)
    step = max(1, n // 14)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(dates_all[::step], rotation=35, ha="right", fontsize=7)
    ax.set_ylabel("累積報酬 (%, OOS 歸零)")
    ax.set_title(f"OOS 累積報酬  {label}", fontsize=9)
    ax.legend(fontsize=7, loc="best")
    ax.grid(color=STYLE["grid"], lw=0.4)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI); plt.close()


def chart_comparison(rows, out):
    """對比圖：9 組組合的 OOS Sharpe 與 Max DD。"""
    labels  = [r["label"]  for r in rows]
    sharpes = [r["sharpe"] for r in rows]
    mdds    = [r["mdd"]    for r in rows]

    x   = np.arange(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax1 = axes[0]
    colors = [STYLE["long"] if s > 0 else STYLE["short"] for s in sharpes]
    ax1.bar(x, sharpes, color=colors, width=0.6)
    ax1.axhline(0, color="grey", lw=0.8)
    # Phase 5 基準線（train=60, confirm=1）
    ax1.axhline(0.23, color="orange", lw=1.2, ls="--", label="Phase 5 基準 +0.23")
    ax1.set_xticks(x); ax1.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax1.set_ylabel("年化 Sharpe"); ax1.set_title("OOS Sharpe 比較", fontsize=9)
    ax1.legend(fontsize=7); ax1.grid(color=STYLE["grid"], lw=0.4, axis="y")
    for i, v in enumerate(sharpes):
        ax1.text(i, v + (0.02 if v >= 0 else -0.06), f"{v:+.2f}",
                 ha="center", fontsize=7)

    ax2 = axes[1]
    ax2.bar(x, mdds, color=STYLE["short"], width=0.6, alpha=0.7)
    ax2.axhline(-27.46, color="orange", lw=1.2, ls="--", label="Phase 5 基準 -27.46%")
    ax2.set_xticks(x); ax2.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax2.set_ylabel("最大回撤 (%)"); ax2.set_title("OOS 最大回撤比較", fontsize=9)
    ax2.legend(fontsize=7); ax2.grid(color=STYLE["grid"], lw=0.4, axis="y")
    for i, v in enumerate(mdds):
        ax2.text(i, v - 1.5, f"{v:.1f}%", ha="center", fontsize=7)

    fig.suptitle("Phase 6 | 訓練視窗 × sig_dir 確認機制 OOS 對比", fontsize=11)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI); plt.close()


# ── 報告 ──────────────────────────────────────────────────────────────────────

def build_report(label, results, best_key, best_oos, best_bt, best_ps,
                 entry_thresh, exit_thresh, max_hold, cost,
                 train_windows, confirm_ns, stop_loss=0.0) -> str:
    lines = [
        f"# Phase 6 OOS 對比報告 ({label})",
        "",
        f"> 訓練視窗：{train_windows}天  確認次數：{confirm_ns}",
        f"> 進場±{entry_thresh}σ / 出場±{exit_thresh}σ / 最長持有{max_hold}天 / 單邊成本{cost*100:.1f}%",
        f"> 單筆停損：{'停用' if stop_loss == 0 else f'-{stop_loss:.1f}%'}",
        "",

        "## 1. 全組合 OOS 績效對比表",
        "",
        "| 訓練視窗 | 確認N | 交易次數 | 勝率 | 合計報酬 | Buy-Hold | Sharpe | Max DD | sig_dir切換 | VECM成功率 |",
        "|----------|-------|----------|------|----------|----------|--------|--------|------------|-----------|",
    ]
    bh_ref = None
    for r in results:
        if bh_ref is None:
            bh_ref = r["bh_oos"]
        marker = " ◀ 最佳" if r["key"] == best_key else ""
        lines.append(
            f"| {r['train_window']}天 | {r['confirm_n']} "
            f"| {r['n_tr']} | {r['hr']:.0f}% "
            f"| {r['total']:+.2f}% | {r['bh_oos']:+.2f}% "
            f"| {r['sharpe']:+.2f} | {r['mdd']:.2f}% "
            f"| {r['n_switches']} | {r['success_rate']:.0f}%{marker} |"
        )
    lines += [
        "",
        "> Phase 5 基準（train=60, confirm=1）：Sharpe +0.23 / Max DD −27.46% / 切換 10 次",
        "",

        f"## 2. 最佳組合詳細結果（{best_key}）",
        "",
        f"| 指標 | OOS 策略 | Buy-Hold TX |",
        f"|------|----------|-------------|",
        f"| 合計報酬 | {best_ps['total']:+.2f}% | {best_oos['bh_oos']:+.2f}% |",
        f"| 交易次數 | {best_ps['n_tr']} | — |",
        f"| 命中率 | {best_ps['hr']:.0f}% | — |",
        f"| 年化 Sharpe | {best_ps['sharpe']:+.2f} | — |",
        f"| 最大回撤 | {best_ps['mdd']:.2f}% | — |",
        f"| Calmar 比率 | {best_ps['calmar']:.2f} | — |",
        f"| sig_dir 切換次數 | {best_oos['n_switches']} | — |",
        "",
    ]

    # 年度分解
    daily = best_bt["daily_pnl"]
    txp   = np.array([r.get("tx_pct") or 0. for r in best_oos["ds"]], dtype=np.float64)
    dates = [r["date"] for r in best_oos["ds"]]
    oos_s = best_oos["oos_start"]
    years = sorted(set(d[:4] for d in dates[oos_s:]))

    lines += [
        "### 年度分解",
        "",
        "| 年度 | OOS 策略 | Buy-Hold TX | 交易次數 | 勝率 |",
        "|------|----------|-------------|----------|------|",
    ]
    for yr in years:
        idx = [i for i in range(oos_s, len(dates)) if dates[i][:4] == yr]
        if not idx: continue
        st  = float(np.sum(daily[idx]))
        bh2 = float(np.sum(txp[idx]))
        ytr = [t for t in best_bt["trades"] if t["entry_date"][:4] == yr]
        ntr = len(ytr)
        w   = sum(1 for t in ytr if t["pnl_pct"] > 0)
        hr  = f"{w/ntr*100:.0f}%" if ntr > 0 else "—"
        lines.append(f"| {yr} | {st:+.2f}% | {bh2:+.2f}% | {ntr} | {hr} |")

    lines += [
        "",
        "## 3. 圖表說明",
        "",
        "- **chart_p6_comparison.png**：全 9 組 Sharpe / Max DD 橫向對比（橙色虛線 = Phase 5 基準）",
        f"- **chart_p6_sigdir_{best_key}.png**：最佳組合 sig_dir 時序 + 切換點",
        f"- **chart_p6_equity_{best_key}.png**：最佳組合 OOS 累積報酬 vs Buy-Hold TX",
        "",
        "## 4. 結論",
        "",
    ]

    # 找出改善幅度
    base_sharpe = 0.23; base_mdd = -27.46
    delta_s = best_ps["sharpe"] - base_sharpe
    delta_m = best_ps["mdd"] - base_mdd

    improved_s = delta_s > 0.05
    improved_m = delta_m > 2.0

    lines += [
        f"- **最佳組合**：{best_key}（Sharpe {best_ps['sharpe']:+.2f} / Max DD {best_ps['mdd']:.2f}%）",
        f"- Phase 5 基準對比：Sharpe {'改善' if improved_s else '未改善'} {delta_s:+.2f}"
        f"，Max DD {'改善' if improved_m else '未改善'} {delta_m:+.2f}%",
    ]
    if best_oos["n_switches"] < 10:
        lines.append(f"- sig_dir 切換從 Phase 5 的 10 次降至 {best_oos['n_switches']} 次——確認機制有效抑制假切換。")
    else:
        lines.append(f"- sig_dir 切換 {best_oos['n_switches']} 次，與 Phase 5 相近。")

    lines += [
        "",
        "---",
        "*Phase 6 完成。*",
    ]
    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ym",           help="單月 YYYYMM")
    parser.add_argument("--ym-range",     nargs=2, metavar=("START", "END"))
    parser.add_argument("--data-dir",     default="data/tw_futures")
    parser.add_argument("--output-dir",   default="reports/tw_futures_analysis")
    parser.add_argument("--train-windows",nargs="+", type=int, default=[60, 120, 180])
    parser.add_argument("--confirm-ns",   nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--refit-freq",   type=int,   default=5)
    parser.add_argument("--entry-thresh", type=float, default=1.0)
    parser.add_argument("--exit-thresh",  type=float, default=0.5)
    parser.add_argument("--max-hold",     type=int,   default=5)
    parser.add_argument("--cost",         type=float, default=0.001)
    parser.add_argument("--stop-loss",    type=float, default=0.0,
                        help="單筆停損門檻（%%，正數，0=停用，預設 0）")
    args = parser.parse_args()

    if args.ym_range:
        months = _ym_range(args.ym_range[0], args.ym_range[1])
        label  = f"{args.ym_range[0]}-{args.ym_range[1]}"
    elif args.ym:
        if not re.fullmatch(r"\d{6}", args.ym):
            sys.exit("--ym 格式錯誤")
        months = [args.ym]; label = args.ym
    else:
        sys.exit("請指定 --ym YYYYMM 或 --ym-range START END")

    data_dir  = Path(args.data_dir)
    out_dir   = Path(args.output_dir)
    chart_dir = out_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    # ── 載入資料 ──────────────────────────────────────────────────────────────
    print(f"[Phase 6] 載入資料：{months[0]} … {months[-1]}（{len(months)} 個月）")
    twse_rows, tx_rows = [], []
    for m in months:
        tp = data_dir / f"twse_taiex_{m}.csv"
        fp = data_dir / f"taifex_tx_{m}.csv"
        if not tp.exists() or not fp.exists():
            print(f"  ⚠ 跳過缺失月份：{m}")
            continue
        twse_rows.extend(load_csv(tp))
        tx_rows.extend(load_csv(fp))

    ds_raw = build_dataset(twse_rows, tx_rows)
    ds     = [r for r in ds_raw if r["taiex"] is not None and r["tx_close"] is not None]
    print(f"[Phase 6] 有效交易日：{len(ds)} 筆")

    # ── 多組合執行 ─────────────────────────────────────────────────────────────
    results   = []
    best_key  = None
    best_sharpe = -999

    total_combos = len(args.train_windows) * len(args.confirm_ns)
    combo_idx    = 0

    for tw in args.train_windows:
        for cn in args.confirm_ns:
            combo_idx += 1
            key = f"W{tw}_C{cn}"
            print(f"\n[Phase 6] [{combo_idx}/{total_combos}] train={tw}天 confirm={cn} …")

            if len(ds) <= tw:
                print(f"  ⚠ 資料不足（{len(ds)} ≤ {tw}），跳過")
                continue

            oos = generate_oos(ds, tw, args.refit_freq, cn)
            oos["ds"] = ds  # 傳給報告用

            bt  = backtest(ds, oos["z_arr"], oos["sig_dir_arr"], oos["oos_start"],
                           args.entry_thresh, args.exit_thresh, args.max_hold, args.cost,
                           args.stop_loss)
            ps  = stats(bt, oos["oos_start"])

            bh_oos = (float(bt["cum_bh"][-1])
                      - float(bt["cum_bh"][oos["oos_start"]]))
            sr = oos["n_success"] / max(1, oos["n_success"] + oos["n_fail"]) * 100

            print(f"  → 交易{ps['n_tr']}筆 / 勝率{ps['hr']:.0f}% / 報酬{ps['total']:+.2f}%"
                  f" / Sharpe{ps['sharpe']:+.2f} / MaxDD{ps['mdd']:.2f}%"
                  f" / 切換{oos['n_switches']}次")

            rec = {
                "key": key, "train_window": tw, "confirm_n": cn,
                "oos_start": oos["oos_start"],
                "n_tr": ps["n_tr"], "hr": ps["hr"],
                "total": ps["total"], "sharpe": ps["sharpe"],
                "mdd": ps["mdd"], "calmar": ps["calmar"],
                "bh_oos": bh_oos,
                "n_switches": oos["n_switches"],
                "success_rate": sr,
                "label": key,
                # 保存供圖表
                "_oos": oos, "_bt": bt, "_ps": ps,
            }
            results.append(rec)

            if ps["sharpe"] > best_sharpe:
                best_sharpe = ps["sharpe"]
                best_key    = key

    if not results:
        sys.exit("[Phase 6] 所有組合均無結果。")

    best_rec = next(r for r in results if r["key"] == best_key)

    # ── 圖表 ─────────────────────────────────────────────────────────────────
    print(f"\n[Phase 6] 生成圖表…")

    chart_comparison(results, chart_dir / "chart_p6_comparison.png")
    print("  ✓ chart_p6_comparison.png")

    dates_all = [r["date"] for r in ds]
    boo = best_rec["_oos"]
    bbt = best_rec["_bt"]
    dates_oos = dates_all[boo["oos_start"]:]
    sd_oos    = boo["sig_dir_arr"][boo["oos_start"]:]

    chart_sigdir(dates_oos, sd_oos, boo["switches"], best_key,
                 chart_dir / f"chart_p6_sigdir_{best_key}.png")
    print(f"  ✓ chart_p6_sigdir_{best_key}.png")

    chart_equity(dates_all, bbt["cum_pnl"], bbt["cum_bh"],
                 boo["oos_start"], bbt["trades"], best_key,
                 chart_dir / f"chart_p6_equity_{best_key}.png")
    print(f"  ✓ chart_p6_equity_{best_key}.png")

    # ── 報告 ─────────────────────────────────────────────────────────────────
    print("[Phase 6] 生成報告…")
    report = build_report(
        label, results, best_key,
        {**best_rec, "oos_start": boo["oos_start"], "n_switches": boo["n_switches"],
         "ds": ds},
        bbt, best_rec["_ps"],
        args.entry_thresh, args.exit_thresh,
        args.max_hold, args.cost,
        args.train_windows, args.confirm_ns,
        stop_loss=args.stop_loss,
    )
    rpt_path = out_dir / f"phase6_report_{label}.md"
    rpt_path.write_text(report, encoding="utf-8")
    print(f"  ✓ {rpt_path}")

    # ── CSV（最佳組合）──────────────────────────────────────────────────────
    csv_path = out_dir / f"phase6_oos_{label}_{best_key}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv_mod.writer(f)
        w.writerow(["date", "taiex", "tx_close", "z_oos", "sig_dir", "position"])
        for i in range(boo["oos_start"], len(ds)):
            z_v = f"{boo['z_arr'][i]:.4f}" if not np.isnan(boo["z_arr"][i]) else ""
            w.writerow([ds[i]["date"], ds[i]["taiex"], ds[i]["tx_close"],
                        z_v, int(boo["sig_dir_arr"][i]), int(bbt["position"][i])])
    print(f"  ✓ {csv_path}")

    # ── 最終摘要 ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"[Phase 6 完成]  最佳組合：{best_key}")
    print(f"  Sharpe {best_rec['_ps']['sharpe']:+.2f}  Max DD {best_rec['_ps']['mdd']:.2f}%"
          f"  切換 {boo['n_switches']} 次（Phase 5 基準：+0.23 / -27.46% / 10次）")
    print(f"{'='*60}")
    print(f"\n全組合 Sharpe 排名：")
    for r in sorted(results, key=lambda x: -x["sharpe"]):
        marker = " ◀" if r["key"] == best_key else ""
        print(f"  {r['key']:10s}  Sharpe {r['sharpe']:+.2f}  MDD {r['mdd']:.1f}%"
              f"  切換{r['n_switches']}次{marker}")


if __name__ == "__main__":
    main()
