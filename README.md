# claude2605

UX5（ASUS UX510UXK，Ubuntu Server）上的金融自動化執行工作區。

## 設計原則

- **B920**（Windows）— 策略設計、Prompt 撰寫
- **UX5**（本機）— 實際執行：Python scripts、cron 排程、Fubon API

## 自動化 Pipelines

| Pipeline | 觸發時間 | 腳本 | Log |
|---|---|---|---|
| 台股日終報告 | 工作日 17:10（台北）| `cc_run_tw_market_fubon_email.sh` | `log/cc_run_tw_market_fubon_email.log` |
| 美債日追蹤 | 工作日 20:30（美東）| `cc_run_us_bond_tracking.sh` | `log/cc_run_us_bond_tracking.log` |
| 美債週報 | 週日 20:30（美東）| `cc_run_us_bond_weekly_email.sh` | `log/cc_run_us_bond_weekly_email.log` |
| 半導體選擇權 Checklist | 工作日 20:30（美東）| `cc_run_us_semiconductor_options_checklist.sh` | `log/cc_run_us_semiconductor_options_checklist.log` |
| NVDA 4-Expiry 選擇權鏈 | 工作日 20:45（美東）| `cc_run_nvda_options_4expiry.sh` | `log/cc_run_nvda_options_4expiry.log` |
| 半導體選擇權週報 | 週六 08:10（台北）| `cc_run_us_semiconductor_options_weekly_email.sh` | `log/cc_run_us_semiconductor_options_weekly_email.log` |
| 金融股週報 | 週五 18:00（台北）| `cc_run_financial_stocks_weekly_email.sh` | `log/cc_financial_stocks_weekly.log` |
| 台美週警訊通報 | 週二 08:30（台北）| `cc_run_tw_us_market_weekly_warning_pipeline.sh` | `log/cc_run_tw_us_market_weekly_warning.log` |
| 台股盤中大單監控 | 工作日 09:00–13:35（台北）| `cc_run_tw_bigorder_monitor.py` | `log/bigorder_monitor.log` |

## 目錄結構

```
scripts/       # 執行腳本（Python / Bash）
automation/
  cron/        # crontab 範本與部署說明
  prompts/     # 穩定 prompt 文字
  runbooks/    # 人工操作流程
log/           # 執行 log（不納入版控）
docs/          # 產出報告 Markdown（不納入版控）
reports/       # 結構化輸出（不納入版控）
```

## 環境需求

- Python 3.13+
- Fubon Neo SDK venv：`.venv-fubon/`（`fubon_neo 2.2.8`）
- 憑證：`.env.fubon`、`.env.weather_email`（symlink 至 `codex2605/`，不納入版控）

## 快速指令

```bash
# 環境確認
hostname && python3 --version && git status --short

# 手動執行台股日報
python3 scripts/cc_run_tw_market_fubon.py --date YYYY-MM-DD

# 手動執行 NVDA 4-Expiry 並寄信
bash scripts/cc_run_nvda_options_4expiry.sh

# DRY_RUN（不寄信）
DRY_RUN=1 bash scripts/cc_run_nvda_options_4expiry.sh

# 安裝 crontab
crontab < automation/cron/crontab.txt
```

## 相關工作區

| 工作區 | GitHub | 職責 |
|---|---|---|
| codex2605 | [MAXYCHUANG/yc5](https://github.com/MAXYCHUANG/yc5) | 共用工具、send_report_email、options realtime |
| claude2605 | [MAXYCHUANG/claude2605](https://github.com/MAXYCHUANG/claude2605) | 執行腳本、crontab（本 repo）|
