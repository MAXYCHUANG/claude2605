#!/usr/bin/env python3
"""
Phase 3：台指期 × 加權指數 計量模型
  - ADF 單根檢定
  - Engle-Granger 協整檢定
  - VECM（向量誤差修正模型）：長期均衡向量 + 調整速度 α
  - Granger 因果：僅保留有統計意義的方向（Night%→TAIEX）
  - VAR on differenced series：IRF + FEVD

輸入：data/tw_futures/twse_taiex_YYYYMM.csv
      data/tw_futures/taifex_tx_YYYYMM.csv
輸出：reports/tw_futures_analysis/
        charts/ chart_09～14
        phase3_report_LABEL.md

用法（單月）：
  /usr/bin/python3 scripts/cc_analyze_tw_futures_phase3.py --ym 202603
用法（多月範圍）：
  /usr/bin/python3 scripts/cc_analyze_tw_futures_phase3.py --ym-range 202603 202605
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

from statsmodels.tsa.stattools import adfuller, grangercausalitytests, coint
from statsmodels.tsa.vector_ar.var_model import VAR
from statsmodels.tsa.vector_ar.vecm import VECM as VECMModel

FIG_DPI = 150
STYLE = {
    "taiex":   "#1f77b4",
    "tx":      "#d62728",
    "basis":   "#ff7f0e",
    "vol":     "#2ca02c",
    "irf_pos": "#1f77b4",
    "irf_neg": "#d62728",
    "ci":      "#aec7e8",
    "grid":    "#e0e0e0",
}


# ── 資料載入（與 Phase 2 共用邏輯）──────────────────────────────────────────────

def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_float(v: str):
    v = v.strip().replace(",", "")
    # Phase 1 clean() turns ▼-379 → --379; normalize double-sign
    while v.startswith("--"):
        v = v[1:]   # --379 → -379
    if v.startswith("+-"):
        v = v[1:]   # +-x → -x (edge case)
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
            "date":       d,
            "taiex":      taiex,
            "taiex_chg":  t_chg,
            "taiex_pct":  t_pct,
            "amount_bn":  amount / 1e9 if amount else None,
            "tx_close":   t_close,
            "tx_chg":     t_chgf,
            "tx_pct":     f_pct,
            "tx_vol":     t_vol,
            "tx_night":   t_night,
            "night_ratio":night_r,
            "tx_oi":      t_oi,
            "basis":      basis,
        })
    return result


def vec(ds, key) -> np.ndarray:
    """提取 series，過濾 None，回傳 float64 array。"""
    return np.array([r[key] for r in ds if r[key] is not None], dtype=np.float64)


def vec_aligned(*keys, ds) -> tuple[np.ndarray, ...]:
    """回傳多欄位對齊（每筆均非 None）的 arrays。"""
    mask = [all(r[k] is not None for k in keys) for r in ds]
    rows = [r for r, m in zip(ds, mask) if m]
    return tuple(np.array([r[k] for r in rows], dtype=np.float64) for k in keys)


# ── ADF 單根檢定 ──────────────────────────────────────────────────────────────

def run_adf(series: np.ndarray, name: str, maxlag: int = 3) -> dict:
    # "ct" uses 2 deterministic regressors; statsmodels requires maxlag < nobs/2 - 3
    safe_maxlag = max(1, min(maxlag, int(len(series) / 2) - 4))
    res = adfuller(series, maxlag=safe_maxlag, autolag="AIC", regression="ct")
    stat, pval, lags, nobs, crit = res[0], res[1], res[2], res[3], res[4]
    reject_1 = stat < crit["1%"]
    reject_5 = stat < crit["5%"]
    return {
        "name":     name,
        "stat":     stat,
        "pval":     pval,
        "lags":     lags,
        "nobs":     nobs,
        "crit_1":   crit["1%"],
        "crit_5":   crit["5%"],
        "crit_10":  crit["10%"],
        "reject_1": reject_1,
        "reject_5": reject_5,
        "stationary_5": reject_5,
    }


def chart_adf(results: list[dict], out: Path):
    """Chart 9: ADF t-statistics vs critical values."""
    names = [r["name"] for r in results]
    stats = [r["stat"] for r in results]
    crit5 = [r["crit_5"] for r in results]
    x = np.arange(len(names))

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = [STYLE["taiex"] if s < c else STYLE["tx"]
              for s, c in zip(stats, crit5)]
    bars = ax.bar(x, stats, color=colors, width=0.5, zorder=3)
    ax.step(x, crit5, where="mid", color="black", lw=1.5, ls="--",
            label="5% critical value")
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("ADF t-statistic")
    ax.set_title("Chart 9 | ADF Unit Root Test  (blue=stationary @ 5%, red=unit root)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", color=STYLE["grid"], lw=0.5)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


# ── Granger 因果檢定 ──────────────────────────────────────────────────────────

def run_granger(x: np.ndarray, y: np.ndarray, maxlag: int = 2) -> dict:
    """
    檢定 x → y 的 Granger 因果（x 的落後值對 y 有預測力）。
    回傳每個落差階的 F-stat 與 p-value。
    """
    data = np.column_stack([y, x])
    results = grangercausalitytests(data, maxlag=maxlag, verbose=False)
    out = {}
    for lag, res in results.items():
        ftest = res[0]["ssr_ftest"]
        out[lag] = {"F": ftest[0], "pval": ftest[1]}
    return out


# ── VAR 模型 ─────────────────────────────────────────────────────────────────

def fit_var(data: np.ndarray, names: list[str], maxlags: int = 3):
    """
    以 AIC 選最優落差，擬合 VAR。
    data: (T, k) array，每欄一個變數。
    """
    model = VAR(data)
    lag_order = model.select_order(maxlags=maxlags)
    best_lag = lag_order.aic
    if best_lag == 0:
        best_lag = 1
    result = model.fit(best_lag)
    return result, best_lag


def chart_irf(var_result, names: list[str], periods: int, out: Path):
    """Chart 11: IRF grid（標準化衝擊）。"""
    irf = var_result.irf(periods=periods)
    k = len(names)
    fig, axes = plt.subplots(k, k, figsize=(4 * k, 3 * k), squeeze=False)
    fig.suptitle(f"Chart 11 | Impulse Response Functions (periods={periods})", fontsize=11)

    for i in range(k):      # response variable (row)
        for j in range(k):  # impulse variable (col)
            ax = axes[i][j]
            irfs   = irf.irfs[:, i, j]
            lower  = irf.stderr(orth=False)[:, i, j] * -1.64 + irfs
            upper  = irf.stderr(orth=False)[:, i, j] *  1.64 + irfs
            xs = range(periods + 1)
            ax.fill_between(xs, lower, upper, color=STYLE["ci"], alpha=0.5)
            color = STYLE["taiex"] if irfs[-1] >= 0 else STYLE["tx"]
            ax.plot(xs, irfs, color=color, lw=1.5)
            ax.axhline(0, color="grey", lw=0.6)
            ax.set_title(f"{names[j]} → {names[i]}", fontsize=8)
            ax.grid(color=STYLE["grid"], lw=0.4)

    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_fevd(var_result, names: list[str], periods: int, out: Path):
    """Chart 12: Forecast Error Variance Decomposition。"""
    fevd = var_result.fevd(periods=periods)
    k = len(names)
    colors = [STYLE["taiex"], STYLE["tx"], STYLE["vol"], STYLE["basis"]][:k]

    fig, axes = plt.subplots(1, k, figsize=(5 * k, 4), squeeze=False)
    fig.suptitle("Chart 12 | Forecast Error Variance Decomposition", fontsize=11)
    xs = np.arange(1, periods + 1)

    for i in range(k):
        ax = axes[0][i]
        bottom = np.zeros(periods)
        for j in range(k):
            share = np.array(fevd.decomp[i])[:periods, j]
            ax.bar(xs, share * 100, bottom=bottom * 100,
                   color=colors[j], label=names[j], width=0.6)
            bottom += share
        ax.set_title(f"Variance of {names[i]}", fontsize=9)
        ax.set_ylabel("% explained")
        ax.set_ylim(0, 105)
        ax.legend(fontsize=7)
        ax.grid(axis="y", color=STYLE["grid"], lw=0.4)
        ax.set_xlabel("Horizon (days)")

    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_ect(dates: list[str], ect: np.ndarray, label: str, out: Path):
    """Chart 13: ECT（誤差修正項）時序圖。"""
    x = range(len(dates))
    fig, ax = plt.subplots(figsize=(12, 4))
    colors = [STYLE["tx"] if v < 0 else STYLE["taiex"] for v in ect]
    ax.bar(x, ect, color=colors, width=0.7, alpha=0.8)
    ax.axhline(0, color="black", lw=0.8)
    mean_ect = float(np.mean(ect))
    ax.axhline(mean_ect, color=STYLE["basis"], lw=1.2, ls="--",
               label=f"Mean ECT = {mean_ect:+.1f}")
    std_ect = float(np.std(ect))
    ax.axhline(mean_ect + std_ect, color="grey", lw=0.8, ls=":")
    ax.axhline(mean_ect - std_ect, color="grey", lw=0.8, ls=":", label="±1σ")
    ax.set_ylabel("ECT = TAIEX − β·TX − c  (pts)")
    ax.set_title(f"Chart 13 | Error Correction Term (ECT)  {label}\n"
                 f"  藍=TAIEX高於均衡(期貨應追漲)  紅=TAIEX低於均衡(期貨應追跌)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", color=STYLE["grid"], lw=0.5)
    n = len(dates)
    every = max(1, n // 12)
    idx = list(range(0, n, every))
    if (n - 1) not in idx:
        idx.append(n - 1)
    ax.set_xticks(idx)
    ax.set_xticklabels([dates[i][5:] for i in idx], rotation=45, ha="right", fontsize=8)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_alpha(alpha: np.ndarray, se_alpha: np.ndarray,
                pval_alpha: np.ndarray, names: list[str], out: Path):
    """Chart 14: VECM 調整速度 α（含 95% CI）。"""
    k = len(names)
    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.arange(k)
    colors = []
    for i in range(k):
        p = float(pval_alpha[i, 0])
        colors.append(STYLE["taiex"] if p < 0.05 else
                      (STYLE["basis"] if p < 0.10 else "#cccccc"))
    bars = ax.bar(x, alpha[:, 0], color=colors, width=0.5, zorder=3,
                  label="α (adjustment speed)")
    ci = 1.96 * se_alpha[:, 0]
    ax.errorbar(x, alpha[:, 0], yerr=ci, fmt="none", color="black",
                capsize=6, lw=1.5, zorder=4)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=10)
    ax.set_ylabel("α (adjustment speed per period)")
    ax.set_title("Chart 14 | VECM Adjustment Speeds α\n"
                 "  藍=5%顯著  橘=10%邊緣  灰=不顯著  誤差棒=±1.96 SE")
    ax.grid(axis="y", color=STYLE["grid"], lw=0.5)
    for i, (a, p) in enumerate(zip(alpha[:, 0], pval_alpha[:, 0])):
        star = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else ("†" if p < 0.1 else "")))
        ax.text(i, a + (0.005 if a >= 0 else -0.012), star,
                ha="center", fontsize=10, color="black")
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_var_residuals(var_result, names: list[str], out: Path):
    """Chart 10: VAR 殘差 QQ-plot + ACF。"""
    k = len(names)
    resid = var_result.resid  # (T, k)
    fig, axes = plt.subplots(2, k, figsize=(5 * k, 7), squeeze=False)
    fig.suptitle("Chart 10 | VAR Residuals Diagnostics", fontsize=11)

    for j in range(k):
        r = resid[:, j]
        # QQ plot
        ax_qq = axes[0][j]
        n = len(r)
        quantiles = np.sort(r)
        norm_q = np.array([
            (i - 0.5) / n for i in range(1, n + 1)
        ])
        # normal quantiles via scipy if available, else numpy approximation
        try:
            from scipy.special import erfinv as _erfinv
            norm_theoretical = np.array([math.sqrt(2) * _erfinv(2 * p - 1) for p in norm_q])
        except ImportError:
            norm_theoretical = np.array([float(np.percentile(np.random.randn(100000), p * 100))
                                         for p in norm_q])
        std_r = np.std(r)
        ax_qq.scatter(norm_theoretical, quantiles / std_r, s=15,
                      color=STYLE["taiex"], zorder=3)
        mn, mx = norm_theoretical[0], norm_theoretical[-1]
        ax_qq.plot([mn, mx], [mn, mx], color="grey", lw=1, ls="--")
        ax_qq.set_title(f"QQ: {names[j]}", fontsize=9)
        ax_qq.set_xlabel("Theoretical quantile")
        ax_qq.set_ylabel("Standardized residual")
        ax_qq.grid(color=STYLE["grid"], lw=0.4)

        # ACF (manual, lags 0..10)
        ax_acf = axes[1][j]
        max_lag = min(10, n // 3)
        acf_vals = []
        mean_r = np.mean(r)
        var_r  = np.sum((r - mean_r) ** 2)
        for lag in range(max_lag + 1):
            cov = np.sum((r[lag:] - mean_r) * (r[:n - lag] - mean_r))
            acf_vals.append(cov / var_r)
        lags_x = range(max_lag + 1)
        ax_acf.bar(lags_x, acf_vals, color=STYLE["vol"], width=0.5)
        ci = 1.96 / math.sqrt(n)
        ax_acf.axhline(ci,  color="red", lw=1, ls="--", label="±95% CI")
        ax_acf.axhline(-ci, color="red", lw=1, ls="--")
        ax_acf.axhline(0, color="grey", lw=0.5)
        ax_acf.set_title(f"ACF: {names[j]}", fontsize=9)
        ax_acf.set_xlabel("Lag")
        ax_acf.set_ylabel("ACF")
        ax_acf.legend(fontsize=7)
        ax_acf.grid(color=STYLE["grid"], lw=0.4)

    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


# ── Markdown 報告 ─────────────────────────────────────────────────────────────

def fmt_p(p):
    if p is None:
        return "N/A"
    if p < 0.001:
        return "< 0.001***"
    if p < 0.01:
        return f"{p:.4f}**"
    if p < 0.05:
        return f"{p:.4f}*"
    if p < 0.10:
        return f"{p:.4f}†"
    return f"{p:.4f}"


def sig_label(p):
    if p is None:
        return ""
    if p < 0.01:
        return "**顯著**"
    if p < 0.05:
        return "*顯著*"
    if p < 0.10:
        return "†邊緣"
    return "不顯著"


def build_report(ym, ds, adf_results, granger_pairs, var_result, var_names,
                 best_lag, coint_result, vecm_result=None) -> str:
    lines = []
    n = len(ds)
    # 格式化標題（標籤可能含 '-' 如 202603-202605）
    title_ym = ym if len(ym) <= 6 else ym.replace("-", " ～ ")
    caveat = ("本樣本已達 60+ 筆，統計功效尚可；如需更強結論請繼續累積資料。"
              if n >= 60 else
              f"本月僅 {n} 筆交易日，各統計檢定均為探索性質，建議累積 60+ 筆後重新估計。")
    lines += [
        f"# Phase 3 計量報告：台指期 × 加權指數 ({title_ym})",
        "",
        f"> **樣本說明**：{n} 筆交易日。{caveat}",
        "",
    ]

    # ── 1. ADF ────────────────────────────────────────────────────────────────
    lines += ["## 1. ADF 單根檢定", "",
              "| 變數 | t-stat | p-value | 落差 | 5% 臨界值 | 判斷 |",
              "|------|--------|---------|------|-----------|------|"]
    for r in adf_results:
        verdict = "✅ 定態 (I(0))" if r["stationary_5"] else "⚠️ 單根 (I(1))"
        lines.append(
            f"| {r['name']} | {r['stat']:.4f} | {fmt_p(r['pval'])} "
            f"| {r['lags']} | {r['crit_5']:.4f} | {verdict} |"
        )
    lines.append("")

    # ── 2. 協整 ────────────────────────────────────────────────────────────────
    lines += ["## 2. Engle-Granger 協整檢定（TAIEX vs TX 收盤價）", ""]
    eg_stat, eg_pval, _ = coint_result
    lines += [
        f"| 統計量 | p-value | 判斷 |",
        f"|--------|---------|------|",
        f"| {eg_stat:.4f} | {fmt_p(eg_pval)} | {'✅ 存在協整關係（長期均衡）' if eg_pval < 0.05 else '⚠️ 未發現顯著協整'} |",
        "",
    ]
    if eg_pval < 0.05:
        lines.append("→ 兩序列存在長期均衡，以下用 **VECM** 估計調整速度（α）。")
    else:
        lines.append("→ 未發現協整，以**一階差分（漲跌%）**進行 VAR 分析符合理論要求。")
    lines.append("")

    # ── 3. VECM ───────────────────────────────────────────────────────────────────
    lines += ["## 3. VECM 向量誤差修正模型", ""]
    if vecm_result is not None and eg_pval < 0.05:
        beta  = vecm_result.beta       # (k+1, r) or (k, r)
        alpha = vecm_result.alpha      # (k, r)
        se_a  = vecm_result.stderr_alpha   # (k, r)
        pv_a  = vecm_result.pvalues_alpha  # (k, r)

        # 正規化協整向量：TAIEX = β_tx · TX + c
        b = beta[:, 0]
        beta_tx = float(-b[1] / b[0]) if abs(b[0]) > 1e-10 else float(-b[1])
        beta_c  = float(-b[2] / b[0]) if len(b) > 2 and abs(b[0]) > 1e-10 else 0.0

        lines += [
            "### 長期協整向量（正規化：TAIEX = β·TX + c）",
            "",
            f"| 係數 | 估計值 |",
            f"|------|--------|",
            f"| β (TX) | {beta_tx:.4f} |",
            f"| c (常數) | {beta_c:.2f} |",
            "",
            "### 調整速度 α（偏離均衡後每日修正比例）",
            "",
            "| 方程 | α | SE | t-stat | p-value | 解讀 |",
            "|------|---|-----|--------|---------|------|",
        ]
        eq_names = ["ΔTAIEX（現貨）", "ΔTX（期貨）"]
        for i, eqn in enumerate(eq_names):
            a  = float(alpha[i, 0])
            se = float(se_a[i, 0])
            t  = a / se if se > 0 else float("nan")
            pv = float(pv_a[i, 0])
            if a < -0.01 and pv < 0.1:
                interp = "↓ 向下修正（追隨者）"
            elif a > 0.01 and pv < 0.1:
                interp = "↑ 向上修正（追隨者）"
            elif pv >= 0.1:
                interp = "— 不顯著（可能為領先者）"
            else:
                interp = "— 調整幅度極小"
            lines.append(
                f"| {eqn} | {a:.4f} | {se:.4f} | {t:.3f} | {fmt_p(pv)} | {interp} |"
            )

        lines += [
            "",
            "> α < 0 且顯著 → 該市場**追隨**均衡，偏離時向下修正",
            "> α ≈ 0 且不顯著 → 該市場**領先**均衡，不需修正（做價格發現）",
            "",
            "- **Chart 13**：ECT 時序圖（偏離均衡距離）→ `charts/chart_13_ect.png`",
            "- **Chart 14**：α 調整速度棒圖（含 95% CI）→ `charts/chart_14_alpha.png`",
            "",
        ]
    else:
        lines += [
            "> 協整未達顯著水準，略過 VECM 估計。",
            "",
        ]

    # ── 4. Granger（僅保留有統計意義方向）────────────────────────────────────────
    sig_pairs = [(n, g) for n, g in granger_pairs
                 if min(v["pval"] for v in g.values()) < 0.15]
    if sig_pairs:
        lines += ["## 4. Granger 因果檢定（僅顯著 / 邊緣方向）", "",
                  "| 因果方向 | 落差 1 F | p-value | 落差 2 F | p-value | 結論 |",
                  "|----------|----------|---------|----------|---------|------|"]
        for pair_name, gres in sig_pairs:
            l1 = gres.get(1, {})
            l2 = gres.get(2, {})
            f1, p1 = l1.get("F", ""), l1.get("pval", None)
            f2, p2 = l2.get("F", ""), l2.get("pval", None)
            best_p = min(p for p in [p1, p2] if p is not None)
            lines.append(
                f"| {pair_name} "
                f"| {f1:.3f} | {fmt_p(p1)} "
                f"| {f'{f2:.3f}' if isinstance(f2, float) else 'N/A'} | {fmt_p(p2)} "
                f"| {sig_label(best_p)} |"
            )
        lines.append("")
    else:
        lines += ["## 4. Granger 因果檢定", "",
                  "> 所有方向均不顯著（p > 0.15），日線 Granger 無因果。", ""]

    # ── 5. VAR ──────────────────────────────────────────────────────────────────
    lines += [
        "## 4. VAR 模型摘要",
        "",
        f"- 系統變數：{', '.join(var_names)}",
        f"- AIC 最優落差：p = {best_lag}",
        f"- 觀測數（扣除落差）：{var_result.nobs}",
        f"- AIC = {var_result.aic:.4f}",
        f"- BIC = {var_result.bic:.4f}",
        "",
        "### 係數表（第一個方程：TAIEX Chg%）",
        "",
        "| 解釋變數 | 係數 | p-value |",
        "|----------|------|---------|",
    ]
    reg_names = var_result.exog_names   # e.g. ['const', 'L1.y1', 'L1.y2', ...]
    params_col0 = var_result.params[:, 0]
    pvals_col0  = var_result.pvalues[:, 0]
    for pname, coef, pval in zip(reg_names, params_col0, pvals_col0):
        lines.append(f"| {pname} | {coef:.4f} | {fmt_p(pval)} |")
    lines.append("")

    # ── 5. IRF / FEVD 說明 ─────────────────────────────────────────────────────
    lines += [
        "## 5. 衝擊反應與變異分解",
        "",
        "- **Chart 11**（IRF）：各變數受到 1 單位標準差衝擊後的動態路徑。",
        "  藍色 = 最終為正影響，紅色 = 最終為負影響，灰帶 = 90% 信賴區間。",
        "- **Chart 12**（FEVD）：各變數預測誤差中，由各衝擊解釋的比例。",
        "  觀察自變數解釋比例的演化，可判斷資訊來源主要來自何方。",
        "",
    ]

    # ── 6. 結論 ───────────────────────────────────────────────────────────────────
    lines += ["## 6. 結論", ""]

    # VECM conclusions
    if vecm_result is not None and eg_pval < 0.05:
        alpha = vecm_result.alpha
        pv_a  = vecm_result.pvalues_alpha
        a0, p0 = float(alpha[0, 0]), float(pv_a[0, 0])
        a1, p1 = float(alpha[1, 0]), float(pv_a[1, 0])

        if p0 < 0.1 and p1 >= 0.1:
            lines.append(f"- **TAIEX 是追隨者**：α_現貨={a0:.4f}（{fmt_p(p0)}），α_期貨不顯著。"
                         "→ 現貨追期貨，期貨做**價格發現**。")
        elif p1 < 0.1 and p0 >= 0.1:
            lines.append(f"- **TX 是追隨者**：α_期貨={a1:.4f}（{fmt_p(p1)}），α_現貨不顯著。"
                         "→ 期貨追現貨，現貨做**價格發現**。")
        elif p0 < 0.1 and p1 < 0.1:
            lines.append(f"- **雙向調整**：α_現貨={a0:.4f}（{fmt_p(p0)}）、α_期貨={a1:.4f}（{fmt_p(p1)}）。"
                         "→ 兩市場共同分擔價格發現功能。")
        else:
            lines.append("- **α 均不顯著**：樣本尚不足以判斷哪一方主導調整，建議繼續累積資料。")
    else:
        lines.append("- 協整未達顯著，VECM 結論保留。")

    # Granger summary
    night_g = next((g for n, g in granger_pairs if "Night" in n), {})
    p_night = min((v["pval"] for v in night_g.values()), default=1)
    if p_night < 0.05:
        lines.append("- **夜盤成交量 Granger 顯著預測次日 TAIEX**：美盤資訊透過夜盤 TX 傳遞。")
    elif p_night < 0.1:
        lines.append(f"- **夜盤比例邊緣顯著**（p={p_night:.3f}）：美盤對台股的資訊傳遞值得深追。")
    else:
        lines.append("- 日線 Granger 因果全部不顯著；資訊傳遞可能在日內（分鐘）級發生。")

    lines += [
        "",
        "### 下一步建議",
        "1. **Phase 4**：以 ECT 偏離幅度設計交易信號（大幅折/溢價後的均值回歸機會）。",
        "2. 加入日內分鐘資料（TAIFEX tick），確認期貨「日內」領先現貨的分鐘數。",
        "3. 持續更新月份資料，半年後重跑 VECM 檢驗 α 穩定性。",
        "",
        "---",
        "*下一步：Phase 4 — 交易信號萃取與回測*",
    ]
    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────────────────────────────

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ym", help="單月 YYYYMM")
    parser.add_argument("--ym-range", nargs=2, metavar=("START", "END"),
                        help="月份範圍，例：202603 202605")
    parser.add_argument("--data-dir",   default="data/tw_futures")
    parser.add_argument("--output-dir", default="reports/tw_futures_analysis")
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

    ym = label   # 報告標籤
    data_dir  = Path(args.data_dir)
    out_dir   = Path(args.output_dir)
    chart_dir = out_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Phase 3] 載入資料：{months}…")
    twse_rows, tx_rows = [], []
    for m in months:
        tp = data_dir / f"twse_taiex_{m}.csv"
        fp = data_dir / f"taifex_tx_{m}.csv"
        if not tp.exists() or not fp.exists():
            sys.exit(f"找不到資料檔：{m}，請先執行 Phase 1。")
        twse_rows.extend(load_csv(tp))
        tx_rows.extend(load_csv(fp))
    ds = build_dataset(twse_rows, tx_rows)
    n  = len(ds)
    print(f"[Phase 3] {n} 筆交易日（{len(months)} 個月）")

    # ── 1. ADF ────────────────────────────────────────────────────────────────
    print("[Phase 3] ADF 單根檢定…")
    adf_vars = [
        ("TAIEX Level",    vec(ds, "taiex")),
        ("TX Level",       vec(ds, "tx_close")),
        ("TAIEX Chg%",     vec(ds, "taiex_pct")),
        ("TX Chg%",        vec(ds, "tx_pct")),
        ("Basis",          vec(ds, "basis")),
        ("TAIEX Amount",   vec(ds, "amount_bn")),
        ("TX Vol",         vec(ds, "tx_vol")),
        ("TX OI",          vec(ds, "tx_oi")),
        ("Night Ratio%",   vec(ds, "night_ratio")),
    ]
    adf_results = []
    maxlag = max(1, min(3, n // 8))
    for name, series in adf_vars:
        if len(series) < 5:
            continue
        adf_results.append(run_adf(series, name, maxlag=maxlag))
        print(f"  {name:20s}  stat={adf_results[-1]['stat']:7.3f}  p={adf_results[-1]['pval']:.4f}"
              f"  {'✅' if adf_results[-1]['stationary_5'] else '⚠️'}")

    chart_adf(adf_results, chart_dir / "chart_09_adf.png")
    print(f"  ✓ chart_09_adf.png")

    # ── 2. 協整檢定 ──────────────────────────────────────────────────────────
    print("[Phase 3] Engle-Granger 協整檢定…")
    taiex_lv, tx_lv = vec_aligned("taiex", "tx_close", ds=ds)
    coint_result = coint(taiex_lv, tx_lv)
    print(f"  EG stat={coint_result[0]:.4f}  p={coint_result[1]:.4f}")

    # ── 3. Granger 因果 ────────────────────────────────────────────────────────
    print("[Phase 3] Granger 因果檢定…")
    max_granger = max(1, min(2, (n - 5) // 4))

    taiex_pct, tx_pct = vec_aligned("taiex_pct", "tx_pct", ds=ds)
    amount_bn, tx_vol = vec_aligned("amount_bn", "tx_vol", ds=ds)
    basis_v,           = vec_aligned("basis", ds=ds)  # noqa
    night_v,           = vec_aligned("night_ratio", ds=ds)

    # 對齊所有欄位
    aligned_keys = ["taiex_pct", "tx_pct", "amount_bn", "tx_vol", "night_ratio"]
    vecs = vec_aligned(*aligned_keys, ds=ds)
    taiex_pct, tx_pct, amount_a, tx_vol_a, night_a = vecs

    # 僅保留有統計意義的方向：Night%→TAIEX（其餘不顯著，不跑）
    granger_pairs = []
    tests = [
        ("Night%→TAIEX Chg%", night_a, taiex_pct),
    ]
    for pair_name, x, y in tests:
        if len(x) < max_granger * 2 + 3:
            continue
        gres = run_granger(x, y, maxlag=max_granger)
        granger_pairs.append((pair_name, gres))
        best_p = min(v["pval"] for v in gres.values())
        print(f"  {pair_name:30s}  best_p={best_p:.4f}  {'**' if best_p < 0.05 else ''}")

    # ── 3b. VECM ─────────────────────────────────────────────────────────────────
    vecm_result = None
    eg_pval = coint_result[1]
    if eg_pval < 0.05:
        print("[Phase 3] VECM 估計…")
        try:
            data_lv  = np.column_stack([taiex_lv, tx_lv])
            k_ar_diff = max(1, min(2, (n - 4) // 4))
            vecm_mdl = VECMModel(data_lv, k_ar_diff=k_ar_diff,
                                 coint_rank=1, deterministic="co")
            vecm_result = vecm_mdl.fit()
            alpha = vecm_result.alpha
            pv_a  = vecm_result.pvalues_alpha
            print(f"  α_TAIEX={alpha[0,0]:.4f}(p={pv_a[0,0]:.4f})  "
                  f"α_TX={alpha[1,0]:.4f}(p={pv_a[1,0]:.4f})")

            # ECT 時序（對齊到 ds 的日期）
            beta = vecm_result.beta[:, 0]
            b0 = float(beta[0]); b1 = float(beta[1])
            bc = float(beta[2]) if len(beta) > 2 else 0.0
            # 正規化 TAIEX 方程：b0*TAIEX + b1*TX + bc*1 = 0
            ect_full = np.array([
                b0 * r["taiex"] + b1 * r["tx_close"] + bc
                for r in ds
                if r["taiex"] is not None and r["tx_close"] is not None
            ])
            dates_ect = [r["date"] for r in ds
                         if r["taiex"] is not None and r["tx_close"] is not None]

            chart_ect(dates_ect, ect_full, label, chart_dir / "chart_13_ect.png")
            print(f"  ✓ chart_13_ect.png")

            chart_alpha(vecm_result.alpha, vecm_result.stderr_alpha,
                        vecm_result.pvalues_alpha,
                        ["TAIEX", "TX"], chart_dir / "chart_14_alpha.png")
            print(f"  ✓ chart_14_alpha.png")

        except Exception as e:
            print(f"  VECM 擬合失敗：{e}")
            vecm_result = None
    else:
        print("[Phase 3] 協整不顯著，略過 VECM")

    # ── 4. VAR ──────────────────────────────────────────────────────────────────
    print("[Phase 3] VAR 模型…")
    var_names = ["TAIEX Chg%", "TX Chg%", "TX Vol"]
    var_data  = np.column_stack([taiex_pct, tx_pct, tx_vol_a])
    max_var_lag = max(1, min(3, (len(taiex_pct) - 3) // len(var_names) // 2))

    try:
        var_result, best_lag = fit_var(var_data, var_names, maxlags=max_var_lag)
        print(f"  VAR(p={best_lag})  AIC={var_result.aic:.4f}  nobs={var_result.nobs}")

        chart_var_residuals(var_result, var_names, chart_dir / "chart_10_var_residuals.png")
        print(f"  ✓ chart_10_var_residuals.png")

        irf_periods = min(8, n // 3)
        chart_irf(var_result, var_names, irf_periods, chart_dir / "chart_11_irf.png")
        print(f"  ✓ chart_11_irf.png")

        chart_fevd(var_result, var_names, irf_periods, chart_dir / "chart_12_fevd.png")
        print(f"  ✓ chart_12_fevd.png")

    except Exception as e:
        print(f"  VAR 擬合失敗：{e}")
        var_result, best_lag = None, 1
        for fname in ["chart_10_var_residuals.png", "chart_11_irf.png", "chart_12_fevd.png"]:
            fig, ax = plt.subplots()
            ax.text(0.5, 0.5, f"VAR failed:\n{e}", transform=ax.transAxes,
                    ha="center", va="center")
            plt.savefig(chart_dir / fname, dpi=FIG_DPI)
            plt.close()

    # ── 報告 ────────────────────────────────────────────────────────────────────
    if var_result is not None:
        report = build_report(ym, ds, adf_results, granger_pairs,
                              var_result, var_names, best_lag, coint_result,
                              vecm_result=vecm_result)
        report_path = out_dir / f"phase3_report_{ym}.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"\n✓ Phase 3 完成")
        print(f"  報告 → {report_path}")
        print(f"  圖表 → {chart_dir}/chart_09～14.png")
    else:
        print("\n⚠ VAR 未能擬合，報告略過")


if __name__ == "__main__":
    main()
