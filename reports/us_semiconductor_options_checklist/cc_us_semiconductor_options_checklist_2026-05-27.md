# 美股半導體 Options / Futures / PEG Checklist

執行日期：2026-05-27  
資料模式：live fetch  
總燈號：橘

## 1. 一句話總評

本報告用 PCR、IV、call/put wall、PEG、forward PE、NQ / ES futures、QQQ / SOXX 與 VIX 檢查半導體高位多頭是否出現擁擠、避險或估值兌現壓力。

## 2. 個股 Checklist

| 標的 | 型態 | 價格 | 距 52 週高 | PCR Vol | PCR OI | IV mean | Call wall | Put wall | Fwd PE | PEG | 警示 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NVDA | 核心 AI call momentum | 214.86 | NA | 0.357 | 0.628 | 38.2% | NA | NA | NA | NA | 警示：call crowding，追漲部位擁擠 |
| TSM | 核心供應鏈高位避險 | 412.32 | NA | 3.863 | 3.540 | 44.5% | NA | NA | NA | NA | 警示：PCR volume > 1.5，短線 put demand 明顯<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重 |
| SMH | 半導體 ETF 高位避險 | 602.14 | NA | 7.442 | 2.439 | 48.4% | NA | NA | NA | NA | 警示：IV >= 45%，波動偏高<br>警示：PCR volume > 1.5，短線 put demand 明顯<br>警示：PCR OI > 1.5，存量避險或 bearish 部位偏重 |
| AMD | Momentum + call exposure | 503.89 | NA | 0.709 | 0.891 | 73.0% | NA | NA | NA | NA | 警示：IV >= 60%，波動偏高 |
| INTC | 高風險轉機 squeeze | 123.52 | NA | 0.732 | 1.094 | 85.9% | NA | NA | NA | NA | 警示：IV >= 80%，市場定價極高波動 |
| MU | 強基本面 + peak-cycle 疑慮 | 895.88 | NA | 0.869 | 0.875 | 100.8% | NA | NA | NA | NA | 警示：IV >= 80%，市場定價極高波動 |

## 3. Futures / ETF Context

| 標的 | 價格 | 日變化 | 52 週高 | 資料源 |
|---|---:|---:|---:|---|
| QQQ | 730.28 | 0.60% | NA | Stooq |
| SOXX | 570.09 | 2.35% | NA | Stooq |
| NQ=F | NA | NA | NA | Yahoo |
| ES=F | NA | NA | NA | Yahoo |
| ^VIX | NA | NA | NA | Yahoo |

## 4. 警示

- NVDA: 警示：call crowding，追漲部位擁擠
- TSM: 警示：PCR volume > 1.5，短線 put demand 明顯
- TSM: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- SMH: 警示：IV >= 45%，波動偏高
- SMH: 警示：PCR volume > 1.5，短線 put demand 明顯
- SMH: 警示：PCR OI > 1.5，存量避險或 bearish 部位偏重
- AMD: 警示：IV >= 60%，波動偏高
- INTC: 警示：IV >= 80%，市場定價極高波動
- MU: 警示：IV >= 80%，市場定價極高波動

## 5. 資料缺口

- NVDA: Yahoo strike-level options chain unavailable; AlphaQuery aggregate PCR/IV used
- NVDA: call wall / put wall unavailable without strike-level chain
- NVDA: PEG unavailable
- TSM: Yahoo strike-level options chain unavailable; AlphaQuery aggregate PCR/IV used
- TSM: call wall / put wall unavailable without strike-level chain
- TSM: PEG unavailable
- SMH: Yahoo strike-level options chain unavailable; AlphaQuery aggregate PCR/IV used
- SMH: call wall / put wall unavailable without strike-level chain
- SMH: PEG unavailable
- AMD: Yahoo strike-level options chain unavailable; AlphaQuery aggregate PCR/IV used
- AMD: call wall / put wall unavailable without strike-level chain
- AMD: PEG unavailable
- INTC: Yahoo strike-level options chain unavailable; AlphaQuery aggregate PCR/IV used
- INTC: call wall / put wall unavailable without strike-level chain
- INTC: PEG unavailable
- MU: Yahoo strike-level options chain unavailable; AlphaQuery aggregate PCR/IV used
- MU: call wall / put wall unavailable without strike-level chain
- MU: PEG unavailable

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
