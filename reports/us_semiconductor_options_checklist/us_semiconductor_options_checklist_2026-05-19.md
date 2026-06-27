# 美股半導體 Options / Futures / PEG Checklist

執行日期：2026-05-19  
資料模式：DRY_RUN sample data  
總燈號：紅

## 1. 一句話總評

本報告用 PCR、IV、call/put wall、PEG、forward PE、NQ / ES futures、QQQ / SOXX 與 VIX 檢查半導體高位多頭是否出現擁擠、避險或估值兌現壓力。

## 2. 個股 Checklist

| 標的 | 型態 | 價格 | 距 52 週高 | PCR Vol | PCR OI | IV mean | Call wall | Put wall | Fwd PE | PEG | 警示 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NVDA | 核心 AI call momentum | 214.00 | -2.3% | 0.150 | 0.306 | 46.5% | 230.00 | 210.00 | 42.0 | 1.20 | 警示：call crowding，追漲部位擁擠 |
| TSM | 核心供應鏈高位避險 | 332.00 | -2.4% | 1.256 | 1.786 | 45.5% | 345.00 | 325.00 | 28.0 | 1.10 | 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重<br>警示：接近 52 週高且 PCR OI > 1，高位避險累積 |
| SMH | 半導體 ETF 高位避險 | 540.10 | -1.8% | 1.367 | 1.275 | 43.5% | 555.00 | 535.00 | 51.0 | NA | 警示：接近 52 週高且 PCR OI > 1，高位避險累積 |
| AMD | Momentum + call exposure | 405.00 | -1.7% | 1.012 | 0.800 | 66.8% | 420.00 | 400.00 | 47.0 | 1.40 | 警示：IV >= 60%，波動偏高 |
| INTC | 高風險轉機 squeeze | 109.50 | -2.2% | 1.821 | 1.700 | 85.0% | 120.00 | 100.00 | 108.0 | 1.54 | 警示：IV >= 80%，市場定價極高波動<br>警示：PCR volume > 1.5，短線 put demand 明顯<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重<br>警示：接近 52 週高且 PCR OI > 1，高位避險累積<br>警示：Forward P/E > 60，估值兌現壓力高 |
| MU | 強基本面 + peak-cycle 疑慮 | 643.00 | -1.1% | 0.846 | 1.218 | 81.9% | 660.00 | 640.00 | 6.2 | 0.04 | 警示：IV >= 80%，市場定價極高波動<br>警示：接近 52 週高且 PCR OI > 1，高位避險累積<br>警示：PEG 極低但 IV 很高，可能是 peak earnings / 週期高峰疑慮 |

## 3. Futures / ETF Context

| 標的 | 價格 | 日變化 | 52 週高 | 資料源 |
|---|---:|---:|---:|---|
| QQQ | 650.00 | 0.50% | 655.00 | Yahoo |
| SOXX | 410.00 | 0.10% | 418.00 | Yahoo |
| NQ=F | 23500.00 | 0.40% | 23650.00 | Yahoo |
| ES=F | 7100.00 | 0.20% | 7150.00 | Yahoo |
| ^VIX | 18.00 | 3.20% | 38.00 | Yahoo |

## 4. 警示

- NVDA: 警示：call crowding，追漲部位擁擠
- TSM: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- TSM: 警示：接近 52 週高且 PCR OI > 1，高位避險累積
- SMH: 警示：接近 52 週高且 PCR OI > 1，高位避險累積
- AMD: 警示：IV >= 60%，波動偏高
- INTC: 警示：IV >= 80%，市場定價極高波動
- INTC: 警示：PCR volume > 1.5，短線 put demand 明顯
- INTC: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- INTC: 警示：接近 52 週高且 PCR OI > 1，高位避險累積
- INTC: 警示：Forward P/E > 60，估值兌現壓力高
- MU: 警示：IV >= 80%，市場定價極高波動
- MU: 警示：接近 52 週高且 PCR OI > 1，高位避險累積
- MU: 警示：PEG 極低但 IV 很高，可能是 peak earnings / 週期高峰疑慮

## 5. 資料缺口

- SMH: PEG unavailable

## 6. 人工確認清單

- [ ] 若任一標的 IV >= 80%，確認是否有財報、產品發表、政策或訴訟事件。
- [ ] 若 PCR volume > 1.5，檢查是否為保護性 put、bearish spread，或單日雜訊。
- [ ] 若 PCR volume < 0.5 且 PCR OI < 0.7，檢查是否為 call crowding 與 gamma squeeze。
- [ ] 若 PEG < 0.5 且 IV 很高，確認是否為 memory / cyclical peak earnings。
- [ ] 若 SOXX 弱於 QQQ，檢查 SMH / SOX 是否跌破近期支撐。

## 7. 參考框架

- docs/us_semiconductor_options_futures_peg_playbook.md
- docs/us_stock_capital_flows_ai_ipo_macro_summary_2026-05-07.md
- docs/meta_peg_ai_saas_adjustment_summary.md
