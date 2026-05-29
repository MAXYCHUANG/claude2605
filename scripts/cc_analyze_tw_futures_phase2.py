#!/usr/bin/env python3
"""
Phase 2：台指期 × 加權指數 敘述統計與視覺化
輸入：data/tw_futures/twse_taiex_YYYYMM.csv
      data/tw_futures/taifex_tx_YYYYMM.csv
輸出：reports/tw_futures_analysis/
        charts/  (8 張 PNG)
        phase2_report_LABEL.md

用法（單月）：
  python3 scripts/cc_analyze_tw_futures_phase2.py --ym 202603
用法（多月範圍）：
  python3 scripts/cc_analyze_tw_futures_phase2.py --ym-range 202603 202605
"""

import argparse
import csv
import math
import re
import statistics
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── 設定 ──────────────────────────────────────────────────────────────────────
STYLE = {
    "taiex":    "#1f77b4",
    "tx":       "#d62728",
    "basis":    "#ff7f0e",
    "vol_taiex":"#2ca02c",
    "vol_tx":   "#9467bd",
    "oi":       "#8c564b",
    "night":    "#e377c2",
    "grid":     "#e0e0e0",
}
FIG_DPI = 150


# ── 資料載入 ──────────────────────────────────────────────────────────────────

def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_float(v: str) -> float | None:
    v = v.strip().replace(",", "")
    if not v or v == "-":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def build_dataset(twse_rows: list[dict], tx_rows: list[dict]) -> list[dict]:
    """Join on date, compute derived fields."""
    tx_by_date = {r["date"]: r for r in tx_rows}
    result = []
    prev_taiex = None
    prev_tx_close = None

    for row in twse_rows:
        d = row["date"]
        tx = tx_by_date.get(d)
        if not tx:
            continue

        taiex      = parse_float(row["taiex"])
        taiex_chg  = parse_float(row["change"])
        vol_shares = parse_float(row["volume_shares"])
        amount_twd = parse_float(row["amount_twd"])
        amount_bn  = amount_twd / 1e9 if amount_twd else None  # 億元 TWD

        tx_close   = parse_float(tx["close"])
        tx_chg     = parse_float(tx["change"])
        tx_vol     = parse_float(tx["vol_total"])
        tx_vol_day = parse_float(tx["vol_day"])
        tx_night   = parse_float(tx["vol_night"])
        tx_oi      = parse_float(tx["oi"])
        tx_settle  = parse_float(tx["settlement"])

        # basis = 期貨 - 現貨
        basis = (tx_close - taiex) if (tx_close and taiex) else None

        # 夜盤比例
        night_ratio = (tx_night / tx_vol * 100) if (tx_night and tx_vol and tx_vol > 0) else None

        # 現貨漲跌 %
        taiex_chg_pct = (taiex_chg / (taiex - taiex_chg) * 100) if (taiex_chg and taiex) else None
        tx_chg_pct    = (tx_chg / (tx_close - tx_chg) * 100) if (tx_chg and tx_close) else None

        result.append({
            "date":          d,
            "taiex":         taiex,
            "taiex_chg":     taiex_chg,
            "taiex_chg_pct": taiex_chg_pct,
            "amount_bn":     amount_bn,
            "vol_shares_bn": vol_shares / 1e9 if vol_shares else None,
            "tx_close":      tx_close,
            "tx_chg":        tx_chg,
            "tx_chg_pct":    tx_chg_pct,
            "tx_vol":        tx_vol,
            "tx_vol_day":    tx_vol_day,
            "tx_night":      tx_night,
            "tx_night_ratio":night_ratio,
            "tx_oi":         tx_oi,
            "basis":         basis,
            "contract":      tx["contract"],
        })
    return result


# ── 統計輔助 ──────────────────────────────────────────────────────────────────

def stats_dict(values: list[float]) -> dict:
    vs = [v for v in values if v is not None]
    if not vs:
        return {}
    return {
        "n":    len(vs),
        "mean": statistics.mean(vs),
        "std":  statistics.stdev(vs) if len(vs) > 1 else 0,
        "min":  min(vs),
        "max":  max(vs),
        "med":  statistics.median(vs),
    }


def corr(x: list, y: list) -> float | None:
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx  = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy  = math.sqrt(sum((b - my) ** 2 for b in ys))
    return num / (dx * dy) if dx * dy else None


# ── 圖表 ──────────────────────────────────────────────────────────────────────

def _xticks(dates: list[str], ax, every: int = 3):
    n = len(dates)
    idx = list(range(0, n, every))
    if (n - 1) not in idx:
        idx.append(n - 1)
    ax.set_xticks(idx)
    ax.set_xticklabels([dates[i][5:] for i in idx], rotation=45, ha="right", fontsize=8)


def chart_price_overlay(ds: list[dict], out: Path, label: str = ""):
    """Chart 1: TAIEX vs TX close dual-axis."""
    dates   = [r["date"] for r in ds]
    taiex   = [r["taiex"] for r in ds]
    tx      = [r["tx_close"] for r in ds]
    x       = range(len(dates))

    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax2 = ax1.twinx()
    ax1.plot(x, taiex, color=STYLE["taiex"], lw=1.8, label="TAIEX (left)")
    ax2.plot(x, tx,    color=STYLE["tx"],    lw=1.8, ls="--", label="TX Close (right)")
    ax1.set_ylabel("TAIEX", color=STYLE["taiex"])
    ax2.set_ylabel("TX Close", color=STYLE["tx"])
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax1.grid(color=STYLE["grid"], lw=0.5)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="lower left", fontsize=8)
    ax1.set_title(f"Chart 1 | TAIEX vs TX Close  {label}")
    _xticks(dates, ax1)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_basis(ds: list[dict], out: Path, label: str = ""):
    """Chart 2: Basis (TX − TAIEX) time series."""
    dates = [r["date"] for r in ds]
    basis = [r["basis"] for r in ds]
    x     = range(len(dates))
    mean_b = statistics.mean(b for b in basis if b is not None)

    fig, ax = plt.subplots(figsize=(10, 4))
    colors = [STYLE["tx"] if b and b < 0 else STYLE["taiex"] for b in basis]
    ax.bar(x, basis, color=colors, width=0.7, label="Basis = TX − TAIEX")
    ax.axhline(0, color="black", lw=0.8)
    ax.axhline(mean_b, color=STYLE["basis"], lw=1.2, ls="--",
               label=f"Mean basis = {mean_b:+.1f}")
    ax.set_ylabel("Points")
    ax.grid(axis="y", color=STYLE["grid"], lw=0.5)
    ax.legend(fontsize=8)
    ax.set_title(f"Chart 2 | Basis = TX Close − TAIEX  {label}")
    _xticks(dates, ax)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_daily_change_scatter(ds: list[dict], out: Path, label: str = ""):
    """Chart 3: TAIEX % change vs TX % change scatter."""
    xv = [r["taiex_chg_pct"] for r in ds if r["taiex_chg_pct"] is not None and r["tx_chg_pct"] is not None]
    yv = [r["tx_chg_pct"]    for r in ds if r["taiex_chg_pct"] is not None and r["tx_chg_pct"] is not None]
    labels = [r["date"][5:] for r in ds if r["taiex_chg_pct"] is not None and r["tx_chg_pct"] is not None]
    r_val = corr(xv, yv)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(xv, yv, color=STYLE["taiex"], s=50, zorder=3)
    for i, lbl in enumerate(labels):
        ax.annotate(lbl, (xv[i], yv[i]), fontsize=6, xytext=(3, 3),
                    textcoords="offset points")
    # regression line
    if len(xv) > 2:
        m, b = np.polyfit(xv, yv, 1)
        xl = np.linspace(min(xv), max(xv), 100)
        ax.plot(xl, m * xl + b, color=STYLE["tx"], lw=1.2, ls="--",
                label=f"OLS slope={m:.3f}")
    ax.axhline(0, color="grey", lw=0.6)
    ax.axvline(0, color="grey", lw=0.6)
    ax.set_xlabel("TAIEX daily chg %")
    ax.set_ylabel("TX daily chg %")
    ax.set_title(f"Chart 3 | Price Change Scatter  r={r_val:.4f}" if r_val else "Chart 3 | Price Change Scatter")
    ax.legend(fontsize=8)
    ax.grid(color=STYLE["grid"], lw=0.5)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_taiex_volume(ds: list[dict], out: Path, label: str = ""):
    """Chart 4: TAIEX 成交金額 (億 TWD) bar."""
    dates = [r["date"] for r in ds]
    amt   = [r["amount_bn"] for r in ds]
    mean_a = statistics.mean(a for a in amt if a is not None)
    x     = range(len(dates))

    fig, ax = plt.subplots(figsize=(10, 4))
    colors = [STYLE["taiex"] if a and a >= mean_a else "#aec7e8" for a in amt]
    ax.bar(x, amt, color=colors, width=0.7)
    ax.axhline(mean_a, color=STYLE["basis"], lw=1.2, ls="--",
               label=f"Mean {mean_a:.0f}B TWD")
    ax.set_ylabel("TWD (billion)")
    ax.grid(axis="y", color=STYLE["grid"], lw=0.5)
    ax.legend(fontsize=8)
    ax.set_title(f"Chart 4 | TAIEX Daily Turnover (TWD billion)  {label}")
    _xticks(dates, ax)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_tx_volume(ds: list[dict], out: Path, label: str = ""):
    """Chart 5: TX 成交量 (口) stacked: day + night."""
    dates = [r["date"] for r in ds]
    day   = [r["tx_vol_day"]  or 0 for r in ds]
    night = [r["tx_night"]    or 0 for r in ds]
    x     = range(len(dates))
    mean_total = statistics.mean((d + n) for d, n in zip(day, night))

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(x, day,   color=STYLE["vol_tx"],  width=0.7, label="Day session")
    ax.bar(x, night, color=STYLE["night"],   width=0.7, bottom=day, label="Night session")
    ax.axhline(mean_total, color=STYLE["basis"], lw=1.2, ls="--",
               label=f"Mean total {mean_total:,.0f}")
    ax.set_ylabel("Contracts")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v/1e3:.0f}K"))
    ax.grid(axis="y", color=STYLE["grid"], lw=0.5)
    ax.legend(fontsize=8)
    ax.set_title(f"Chart 5 | TX Daily Volume (Day + Night)  {label}")
    _xticks(dates, ax)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_volume_scatter(ds: list[dict], out: Path, label: str = ""):
    """Chart 6: TAIEX amount vs TX volume scatter."""
    xv = [r["amount_bn"] for r in ds if r["amount_bn"] and r["tx_vol"]]
    yv = [r["tx_vol"]    for r in ds if r["amount_bn"] and r["tx_vol"]]
    labels = [r["date"][5:] for r in ds if r["amount_bn"] and r["tx_vol"]]
    r_val = corr(xv, yv)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(xv, yv, color=STYLE["vol_tx"], s=50, zorder=3)
    for i, lbl in enumerate(labels):
        ax.annotate(lbl, (xv[i], yv[i]), fontsize=6, xytext=(3, 3),
                    textcoords="offset points")
    if len(xv) > 2:
        m, b = np.polyfit(xv, yv, 1)
        xl = np.linspace(min(xv), max(xv), 100)
        ax.plot(xl, m * xl + b, color=STYLE["tx"], lw=1.2, ls="--")
    ax.set_xlabel("TAIEX Turnover (TWD billion)")
    ax.set_ylabel("TX Total Volume (contracts)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v/1e3:.0f}K"))
    ax.set_title(f"Chart 6 | Volume Correlation  r={r_val:.4f}" if r_val else "Chart 6 | Volume Correlation")
    ax.grid(color=STYLE["grid"], lw=0.5)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_oi_price(ds: list[dict], out: Path, label: str = ""):
    """Chart 7: TX OI vs TAIEX price dual-axis."""
    dates = [r["date"] for r in ds]
    oi    = [r["tx_oi"]   for r in ds]
    taiex = [r["taiex"]   for r in ds]
    x     = range(len(dates))

    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax2 = ax1.twinx()
    ax1.bar(x, oi, color=STYLE["oi"], width=0.7, alpha=0.7, label="TX OI (left)")
    ax2.plot(x, taiex, color=STYLE["taiex"], lw=1.8, label="TAIEX (right)")
    ax1.set_ylabel("Open Interest", color=STYLE["oi"])
    ax2.set_ylabel("TAIEX", color=STYLE["taiex"])
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v/1e3:.0f}K"))
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax1.grid(axis="y", color=STYLE["grid"], lw=0.5)
    labels_l = ["TX OI", "TAIEX"]
    from matplotlib.patches import Patch
    legend_handles = [Patch(color=STYLE["oi"], label="TX OI"), ax2.get_lines()[0]]
    ax1.legend(handles=legend_handles, labels=labels_l, loc="upper right", fontsize=8)
    ax1.set_title(f"Chart 7 | TX Open Interest vs TAIEX  {label}")
    _xticks(dates, ax1)
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()


def chart_correlation_heatmap(ds: list[dict], out: Path, label: str = "") -> list[list]:
    """Chart 8: Correlation heatmap of key variables."""
    var_keys = [
        ("TAIEX",        "taiex"),
        ("TAIEX Chg%",   "taiex_chg_pct"),
        ("TAIEX Amount", "amount_bn"),
        ("TX Close",     "tx_close"),
        ("TX Chg%",      "tx_chg_pct"),
        ("TX Vol",       "tx_vol"),
        ("TX Night%",    "tx_night_ratio"),
        ("TX OI",        "tx_oi"),
        ("Basis",        "basis"),
    ]
    labels = [v[0] for v in var_keys]
    keys   = [v[1] for v in var_keys]
    n = len(keys)
    mat = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            xi = [r[keys[i]] for r in ds]
            xj = [r[keys[j]] for r in ds]
            mat[i][j] = corr(xi, xj) if i != j else 1.0

    arr = np.array([[v if v is not None else 0 for v in row] for row in mat])

    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.imshow(arr, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    plt.colorbar(im, ax=ax, shrink=0.8)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)
    for i in range(n):
        for j in range(n):
            v = arr[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                    fontsize=8, color="black" if abs(v) < 0.7 else "white")
    ax.set_title(f"Chart 8 | Correlation Matrix  {label}")
    plt.tight_layout()
    plt.savefig(out, dpi=FIG_DPI)
    plt.close()
    return mat, labels


# ── Markdown 報告 ─────────────────────────────────────────────────────────────

def fmt(v, decimals=2, prefix="", suffix=""):
    if v is None:
        return "N/A"
    return f"{prefix}{v:,.{decimals}f}{suffix}"


def build_report(ym: str, ds: list[dict], mat, corr_labels: list[str]) -> str:
    lines = []

    lines.append(f"# Phase 2 分析報告：台指期 × 加權指數 ({ym[:4]}/{ym[4:]})")
    lines.append("")
    lines.append(f"- 分析期間：{ds[0]['date']} ～ {ds[-1]['date']}")
    lines.append(f"- 交易日數：{len(ds)} 天")
    lines.append(f"- 台指期契約：{ds[0]['contract']} → {ds[-1]['contract']}（換月於月中）")
    lines.append("")

    # ── 1. 價格統計 ──────────────────────────────────────────────────────────
    lines.append("## 1. 價格統計")
    lines.append("")

    st = stats_dict([r["taiex"] for r in ds])
    lines.append("### 加權指數 (TAIEX)")
    lines.append(f"| 統計 | 數值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 月初 | {fmt(ds[0]['taiex'], 2)} |")
    lines.append(f"| 月末 | {fmt(ds[-1]['taiex'], 2)} |")
    lines.append(f"| 月漲跌 | {fmt(ds[-1]['taiex'] - ds[0]['taiex'] if ds[0]['taiex'] and ds[-1]['taiex'] else None, 2)} pts ({fmt((ds[-1]['taiex'] - ds[0]['taiex']) / ds[0]['taiex'] * 100 if ds[0]['taiex'] and ds[-1]['taiex'] else None, 2)} %) |")
    lines.append(f"| 最高 | {fmt(st['max'], 2)} |")
    lines.append(f"| 最低 | {fmt(st['min'], 2)} |")
    lines.append(f"| 日均漲跌 | {fmt(statistics.mean(r['taiex_chg'] for r in ds if r['taiex_chg'] is not None), 2)} pts |")
    lines.append(f"| 日漲跌標準差 | {fmt(statistics.stdev(r['taiex_chg'] for r in ds if r['taiex_chg'] is not None), 2)} pts |")
    lines.append("")

    st2 = stats_dict([r["tx_close"] for r in ds])
    lines.append("### 台指期近月 (TX)")
    lines.append(f"| 統計 | 數值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 月初收盤 | {fmt(ds[0]['tx_close'], 0)} |")
    lines.append(f"| 月末收盤 | {fmt(ds[-1]['tx_close'], 0)} |")
    lines.append(f"| 最高 | {fmt(st2['max'], 0)} |")
    lines.append(f"| 最低 | {fmt(st2['min'], 0)} |")
    lines.append("")

    # ── 2. 基差分析 ──────────────────────────────────────────────────────────
    lines.append("## 2. 基差分析（Basis = TX − TAIEX）")
    lines.append("")
    bvals = [r["basis"] for r in ds if r["basis"] is not None]
    sb = stats_dict(bvals)
    lines.append(f"| 統計 | 數值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 均值 | {fmt(sb['mean'], 1)} pts |")
    lines.append(f"| 標準差 | {fmt(sb['std'], 1)} pts |")
    lines.append(f"| 最大溢價 | {fmt(sb['max'], 1)} pts |")
    lines.append(f"| 最大折價 | {fmt(sb['min'], 1)} pts |")
    premium_days = sum(1 for b in bvals if b > 0)
    lines.append(f"| 溢價天數 | {premium_days} / {len(bvals)} |")
    lines.append(f"| 折價天數 | {len(bvals) - premium_days} / {len(bvals)} |")
    lines.append("")

    # ── 3. 成交量統計 ─────────────────────────────────────────────────────────
    lines.append("## 3. 成交量統計")
    lines.append("")
    lines.append("### 現貨市場")
    sa = stats_dict([r["amount_bn"] for r in ds if r["amount_bn"]])
    lines.append(f"| 統計 | 日均成交額 |")
    lines.append(f"|------|------------|")
    lines.append(f"| 均值 | {fmt(sa['mean'], 0)} 億 TWD |")
    lines.append(f"| 標準差 | {fmt(sa['std'], 0)} 億 TWD |")
    lines.append(f"| 最大 | {fmt(sa['max'], 0)} 億 TWD ({[r['date'] for r in ds if r['amount_bn'] == sa['max']][0][5:]} ) |")
    lines.append(f"| 最小 | {fmt(sa['min'], 0)} 億 TWD |")
    lines.append("")

    lines.append("### 台指期")
    sv = stats_dict([r["tx_vol"] for r in ds if r["tx_vol"]])
    night_ratios = [r["tx_night_ratio"] for r in ds if r["tx_night_ratio"] is not None]
    lines.append(f"| 統計 | 日均成交量 |")
    lines.append(f"|------|------------|")
    lines.append(f"| 均值 | {fmt(sv['mean'], 0)} 口 |")
    lines.append(f"| 標準差 | {fmt(sv['std'], 0)} 口 |")
    lines.append(f"| 最大 | {fmt(sv['max'], 0)} 口 |")
    lines.append(f"| 最小 | {fmt(sv['min'], 0)} 口 |")
    if night_ratios:
        lines.append(f"| 平均夜盤佔比 | {fmt(statistics.mean(night_ratios), 1)} % |")
    lines.append("")

    # ── 4. 相關係數摘要 ────────────────────────────────────────────────────────
    lines.append("## 4. 關鍵相關係數")
    lines.append("")
    n = len(corr_labels)
    lines.append("| 變數對 | Pearson r | 解讀 |")
    lines.append("|--------|-----------|------|")

    def interp(r):
        if r is None:
            return "N/A"
        ar = abs(r)
        direction = "正" if r > 0 else "負"
        if ar > 0.9:
            return f"{direction}相關（極強）"
        elif ar > 0.7:
            return f"{direction}相關（強）"
        elif ar > 0.5:
            return f"{direction}相關（中）"
        elif ar > 0.3:
            return f"{direction}相關（弱）"
        else:
            return "無顯著相關"

    key_pairs = [
        ("TAIEX Chg%",   "TX Chg%"),
        ("TAIEX Amount", "TX Vol"),
        ("TAIEX Amount", "TAIEX Chg%"),
        ("TX Vol",       "TX Chg%"),
        ("TX OI",        "TAIEX"),
        ("Basis",        "TAIEX Chg%"),
        ("TX Night%",    "TX Chg%"),
    ]
    for a, b in key_pairs:
        if a in corr_labels and b in corr_labels:
            i, j = corr_labels.index(a), corr_labels.index(b)
            v = mat[i][j]
            r_str = f"{v:.4f}" if v is not None else "N/A"
            lines.append(f"| {a} ↔ {b} | {r_str} | {interp(v)} |")
    lines.append("")

    # ── 5. 圖表索引 ────────────────────────────────────────────────────────────
    lines.append("## 5. 圖表")
    lines.append("")
    charts = [
        ("Chart 1", "TAIEX vs TX 收盤價雙軸走勢",      "chart_01_price_overlay.png"),
        ("Chart 2", "Basis（基差）時序圖",              "chart_02_basis.png"),
        ("Chart 3", "每日漲跌% 散佈圖（現貨 vs 期貨）", "chart_03_change_scatter.png"),
        ("Chart 4", "TAIEX 成交金額（億 TWD）條形圖",   "chart_04_taiex_volume.png"),
        ("Chart 5", "TX 成交量（日盤 + 夜盤）堆疊圖",   "chart_05_tx_volume.png"),
        ("Chart 6", "成交量散佈圖（TAIEX 額 vs TX 口）","chart_06_volume_scatter.png"),
        ("Chart 7", "TX 未平倉量（OI）與 TAIEX 對比",  "chart_07_oi_price.png"),
        ("Chart 8", "相關係數矩陣熱力圖",               "chart_08_correlation.png"),
    ]
    for c_id, c_title, c_file in charts:
        lines.append(f"- **{c_id}** {c_title}  →  `charts/{c_file}`")
    lines.append("")

    # ── 6. 初步觀察 ────────────────────────────────────────────────────────────
    lines.append("## 6. 初步觀察（供 Phase 3 計量模型參考）")
    lines.append("")

    # auto generate observations
    # Price correlation
    pi = corr_labels.index("TAIEX Chg%")
    pj = corr_labels.index("TX Chg%")
    r_price = mat[pi][pj]
    if r_price and abs(r_price) > 0.9:
        lines.append(f"- **價格同步性極高**：TAIEX 與 TX 日漲跌% 相關係數 r={r_price:.4f}，兩者幾乎同步移動，期貨折溢價主要來自成本攜帶與到期預期。")
    elif r_price:
        lines.append(f"- 價格相關係數 r={r_price:.4f}，兩者有明顯同向關係但非完全一致。")

    # Volume correlation
    vi = corr_labels.index("TAIEX Amount")
    vj = corr_labels.index("TX Vol")
    r_vol = mat[vi][vj]
    if r_vol:
        lines.append(f"- **量量相關**：TAIEX 成交額 vs TX 成交量 r={r_vol:.4f}，{'同步放量明顯（宜共同觀察作為市場情緒指標）' if abs(r_vol) > 0.5 else '相關程度中等，顯示期現貨市場有各自驅動因子'}。")

    # Basis observation
    premium_pct = premium_days / len(bvals) * 100 if bvals else 0
    lines.append(f"- **基差偏折價**：{ym[:4]}/{ym[4:]} 月份折價天數佔 {100 - premium_pct:.0f}%，均值基差 {fmt(sb['mean'], 1)} pts，反映空方壓力或外資期貨持倉偏空。")

    # Night session
    if night_ratios:
        avg_night = statistics.mean(night_ratios)
        lines.append(f"- **夜盤佔比均值 {avg_night:.1f}%**：夜盤流動性{'顯著（> 40%），美股走勢對隔日台股有明顯傳導' if avg_night > 40 else '低於 40%，美股影響相對透過現貨開盤反映'}。")

    lines.append("")
    lines.append("---")
    lines.append("*下一步：Phase 3 — VAR 模型 Granger 因果檢定*")

    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def _ym_range(start: str, end: str) -> list[str]:
    """產生從 start 到 end 的月份清單，格式 YYYYMM。"""
    sy, sm = int(start[:4]), int(start[4:])
    ey, em = int(end[:4]), int(end[4:])
    months = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def main():
    parser = argparse.ArgumentParser(description="Phase 2 台指期 × 加權指數 統計分析")
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
            sys.exit("--ym 格式錯誤，請用 YYYYMM")
        months = [args.ym]
        label  = args.ym
    else:
        sys.exit("請指定 --ym YYYYMM 或 --ym-range START END")

    data_dir   = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    chart_dir  = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Phase 2] 載入資料：{months}…")
    twse_rows, tx_rows = [], []
    for ym in months:
        twse_path = data_dir / f"twse_taiex_{ym}.csv"
        tx_path   = data_dir / f"taifex_tx_{ym}.csv"
        if not twse_path.exists() or not tx_path.exists():
            sys.exit(f"找不到資料檔：{ym}，請先執行 Phase 1。")
        twse_rows.extend(load_csv(twse_path))
        tx_rows.extend(load_csv(tx_path))

    ds = build_dataset(twse_rows, tx_rows)
    print(f"[Phase 2] 合併後 {len(ds)} 筆交易日（{len(months)} 個月）")
    ym = label  # 傳入 report 的標籤

    # ── 產生圖表 ────────────────────────────────────────────────────────────
    charts = [
        ("chart_01_price_overlay.png",  chart_price_overlay),
        ("chart_02_basis.png",          chart_basis),
        ("chart_03_change_scatter.png", chart_daily_change_scatter),
        ("chart_04_taiex_volume.png",   chart_taiex_volume),
        ("chart_05_tx_volume.png",      chart_tx_volume),
        ("chart_06_volume_scatter.png", chart_volume_scatter),
        ("chart_07_oi_price.png",       chart_oi_price),
    ]
    for fname, fn in charts:
        out = chart_dir / fname
        fn(ds, out, label=label)
        print(f"  ✓ {out}")

    mat, corr_labels = chart_correlation_heatmap(ds, chart_dir / "chart_08_correlation.png", label=label)
    print(f"  ✓ {chart_dir / 'chart_08_correlation.png'}")

    # ── 產生 Markdown 報告 ──────────────────────────────────────────────────
    report_text = build_report(ym, ds, mat, corr_labels)
    report_path = output_dir / f"phase2_report_{ym}.md"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\n✓ Phase 2 完成")
    print(f"  報告 → {report_path}")
    print(f"  圖表 → {chart_dir}/  (8 張 PNG)")


if __name__ == "__main__":
    main()
