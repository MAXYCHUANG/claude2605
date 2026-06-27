# 美股半導體 Options / Futures Checklist

執行日期：2026-06-22
資料模式：live fetch
總燈號：紅

## 1. 一句話總評

本報告用 PCR、IV、NQ / ES futures、QQQ / SOXX 與 VIX 檢查半導體高位多頭是否出現擁擠、避險或市場結構壓力。

## 2. 個股 Checklist

| 標的 | 型態 | 價格 | 距 52 週高 | PCR Vol | PCR OI | IV mean | 警示 |
|---|---|---:|---:|---:|---:|---:|---|
| NVDA | 核心 AI call momentum | 210.69 | -10.6% | 0.306 | 0.790 | 35.8% |  |
| TSM | 核心供應鏈高位避險 | 462.12 | 0.0% | 1.646 | 1.861 | 51.3% | 警示：PCR volume > 1.5，短線 put demand 明顯<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重<br>警示：接近 52 週高且 PCR OI > 1，高位避險累積 |
| SMH | 半導體 ETF 高位避險 | 659.88 | 0.0% | 1.657 | 3.455 | 55.1% | 警示：IV >= 45%，波動偏高<br>警示：PCR volume > 1.5，短線 put demand 明顯<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重<br>警示：接近 52 週高且 PCR OI > 1，高位避險累積 |
| AMD | Momentum + call exposure | 537.37 | -1.8% | 0.734 | 0.916 | 69.7% | 警示：IV >= 60%，波動偏高 |
| INTC | 高風險轉機 squeeze | 133.99 | 0.0% | 0.394 | 0.863 | 86.2% | 警示：IV >= 80%，市場定價極高波動 |
| MU | 強基本面 + peak-cycle 疑慮 | 1133.99 | 0.0% | 1.390 | 1.589 | 103.5% | 警示：IV >= 80%，市場定價極高波動<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重<br>警示：接近 52 週高且 PCR OI > 1，高位避險累積 |

## 3. Futures / ETF Context

| 標的 | 價格 | 日變化 | 52 週高 | 資料源 |
|---|---:|---:|---:|---|
| QQQ | 740.62 | 0.46% | 746.16 | Yahoo chart |
| SOXX | 639.45 | 2.06% | 639.45 | Yahoo chart |
| NQ=F | 30783.75 | 0.68% | 30783.75 | Yahoo chart |
| ES=F | 7569.75 | 0.35% | 7623.75 | Yahoo chart |
| ^VIX | 16.78 | -1.53% | 31.05 | CBOE |

## 4. 警示

- TSM: 警示：PCR volume > 1.5，短線 put demand 明顯
- TSM: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- TSM: 警示：接近 52 週高且 PCR OI > 1，高位避險累積
- SMH: 警示：IV >= 45%，波動偏高
- SMH: 警示：PCR volume > 1.5，短線 put demand 明顯
- SMH: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- SMH: 警示：接近 52 週高且 PCR OI > 1，高位避險累積
- AMD: 警示：IV >= 60%，波動偏高
- INTC: 警示：IV >= 80%，市場定價極高波動
- MU: 警示：IV >= 80%，市場定價極高波動
- MU: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- MU: 警示：接近 52 週高且 PCR OI > 1，高位避險累積

## 5. 資料缺口

- NVDA: Yahoo strike-level chain unavailable; AlphaQuery aggregate PCR/IV used
- TSM: Yahoo strike-level chain unavailable; AlphaQuery aggregate PCR/IV used
- SMH: Yahoo strike-level chain unavailable; AlphaQuery aggregate PCR/IV used
- AMD: Yahoo strike-level chain unavailable; AlphaQuery aggregate PCR/IV used
- INTC: Yahoo strike-level chain unavailable; AlphaQuery aggregate PCR/IV used
- MU: Yahoo strike-level chain unavailable; AlphaQuery aggregate PCR/IV used

## 6. 人工確認清單

- [ ] 若任一標的 IV >= 80%，確認是否有財報、產品發表、政策或訴訟事件。
- [ ] 若 PCR volume > 1.5，檢查是否為保護性 put、bearish spread，或單日雜訊。
- [ ] 若 PCR volume < 0.5 且 PCR OI < 0.7，檢查是否為 call crowding 與 gamma squeeze。
- [ ] 若 SOXX 弱於 QQQ，檢查 SMH / SOX 是否跌破近期支撐。

## 7. 參考框架

- docs/us_semiconductor_options_futures_peg_playbook.md
- docs/us_stock_capital_flows_ai_ipo_macro_summary_2026-05-07.md
