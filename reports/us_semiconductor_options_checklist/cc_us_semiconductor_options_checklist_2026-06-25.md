# 美股半導體 Options / Futures Checklist

執行日期：2026-06-25
資料模式：live fetch
總燈號：橘

## 1. 一句話總評

本報告用 PCR、IV、NQ / ES futures、QQQ / SOXX 與 VIX 檢查半導體高位多頭是否出現擁擠、避險或市場結構壓力。

## 2. 個股 Checklist

| 標的 | 型態 | 價格 | 距 52 週高 | PCR Vol | PCR OI | IV mean | 警示 |
|---|---|---:|---:|---:|---:|---:|---|
| NVDA | 核心 AI call momentum | 199.00 | -15.6% | 0.396 | 0.595 | 37.7% | 警示：call crowding，追漲部位擁擠 |
| TSM | 核心供應鏈高位避險 | 440.83 | -5.7% | 1.244 | 1.744 | 53.4% | 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重 |
| SMH | 半導體 ETF 高位避險 | 618.92 | -7.5% | 2.811 | 3.521 | 57.2% | 警示：IV >= 45%，波動偏高<br>警示：PCR volume > 1.5，短線 put demand 明顯<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重 |
| AMD | Momentum + call exposure | 519.74 | -5.8% | 1.154 | 1.080 | 75.8% | 警示：IV >= 60%，波動偏高 |
| INTC | 高風險轉機 squeeze | 131.65 | -6.6% | 0.396 | 0.713 | 96.4% | 警示：IV >= 80%，市場定價極高波動 |
| MU | 強基本面 + peak-cycle 疑慮 | 1048.51 | -13.4% | 0.480 | 1.946 | 103.5% | 警示：IV >= 80%，市場定價極高波動<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重 |

## 3. Futures / ETF Context

| 標的 | 價格 | 日變化 | 52 週高 | 資料源 |
|---|---:|---:|---:|---|
| QQQ | 710.62 | -0.66% | 746.16 | Yahoo chart |
| SOXX | 601.50 | -0.77% | 655.01 | Yahoo chart |
| NQ=F | 30125.75 | 0.12% | 30712.75 | Yahoo chart |
| ES=F | 7475.25 | -0.01% | 7623.75 | Yahoo chart |
| ^VIX | 18.63 | -2.61% | 31.05 | CBOE |

## 4. 警示

- NVDA: 警示：call crowding，追漲部位擁擠
- TSM: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- SMH: 警示：IV >= 45%，波動偏高
- SMH: 警示：PCR volume > 1.5，短線 put demand 明顯
- SMH: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- AMD: 警示：IV >= 60%，波動偏高
- INTC: 警示：IV >= 80%，市場定價極高波動
- MU: 警示：IV >= 80%，市場定價極高波動
- MU: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重

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
