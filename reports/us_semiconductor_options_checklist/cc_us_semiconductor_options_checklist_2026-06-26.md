# 美股半導體 Options / Futures Checklist

執行日期：2026-06-26
資料模式：live fetch
總燈號：紅

## 1. 一句話總評

本報告用 PCR、IV、NQ / ES futures、QQQ / SOXX 與 VIX 檢查半導體高位多頭是否出現擁擠、避險或市場結構壓力。

## 2. 個股 Checklist

| 標的 | 型態 | 價格 | 距 52 週高 | PCR Vol | PCR OI | IV mean | 警示 |
|---|---|---:|---:|---:|---:|---:|---|
| NVDA | 核心 AI call momentum | 195.74 | -17.0% | 0.451 | 0.563 | 38.0% | 警示：call crowding，追漲部位擁擠 |
| TSM | 核心供應鏈高位避險 | 434.99 | -7.0% | 1.807 | 1.766 | 51.7% | 警示：PCR volume > 1.5，短線 put demand 明顯<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重 |
| SMH | 半導體 ETF 高位避險 | 636.88 | -4.8% | 1.349 | 3.216 | 55.9% | 警示：IV >= 45%，波動偏高<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重<br>警示：接近 52 週高且 PCR OI > 1，高位避險累積 |
| AMD | Momentum + call exposure | 532.57 | -3.5% | 1.422 | 1.154 | 75.1% | 警示：IV >= 60%，波動偏高<br>警示：接近 52 週高且 PCR OI > 1，高位避險累積 |
| INTC | 高風險轉機 squeeze | 132.87 | -5.7% | 0.564 | 0.769 | 93.9% | 警示：IV >= 80%，市場定價極高波動 |
| MU | 強基本面 + peak-cycle 疑慮 | 1213.56 | 0.0% | 1.050 | 1.772 | 92.2% | 警示：IV >= 80%，市場定價極高波動<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重<br>警示：接近 52 週高且 PCR OI > 1，高位避險累積 |

## 3. Futures / ETF Context

| 標的 | 價格 | 日變化 | 52 週高 | 資料源 |
|---|---:|---:|---:|---|
| QQQ | 716.38 | -1.31% | 746.16 | Yahoo chart |
| SOXX | 625.20 | -1.90% | 655.01 | Yahoo chart |
| NQ=F | 29415.50 | -1.10% | 30712.75 | Yahoo chart |
| ES=F | 7398.25 | -0.44% | 7623.75 | Yahoo chart |
| ^VIX | 18.89 | 4.31% | 31.05 | CBOE |

## 4. 警示

- NVDA: 警示：call crowding，追漲部位擁擠
- TSM: 警示：PCR volume > 1.5，短線 put demand 明顯
- TSM: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- SMH: 警示：IV >= 45%，波動偏高
- SMH: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- SMH: 警示：接近 52 週高且 PCR OI > 1，高位避險累積
- AMD: 警示：IV >= 60%，波動偏高
- AMD: 警示：接近 52 週高且 PCR OI > 1，高位避險累積
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
