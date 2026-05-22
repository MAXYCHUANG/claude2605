#!/usr/bin/env bash
# cc_run_tw_us_market_weekly_warning_pipeline.sh
# 台美股市每週警訊通報：claude --print 產生 Markdown 報告並寄信。
# 建議於台北時間週二 08:30 執行（檢討週一台股+美股收盤資料）。
#
# 用法：
#   bash scripts/cc_run_tw_us_market_weekly_warning_pipeline.sh
#   DRY_RUN=1 bash scripts/cc_run_tw_us_market_weekly_warning_pipeline.sh
#   RECIPIENT=yc5780 bash scripts/cc_run_tw_us_market_weekly_warning_pipeline.sh
set -euo pipefail

CC_PROJECT_DIR="/home/yc5/workspace/filefold/claude2605"
CODEX_DOC_DIR="/home/yc5/workspace/filefold/codex2605/docs"
REPORT_DIR="${CC_PROJECT_DIR}/reports/tw_us_market_weekly_warning"
LOG_DIR="${CC_PROJECT_DIR}/log"
RECIPIENT="${RECIPIENT:-yc5780}"
DRY_RUN="${DRY_RUN:-0}"
RUN_DATE="$(TZ=Asia/Taipei date +%Y-%m-%d)"
REPORT_PATH="${REPORT_DIR}/cc_tw_us_market_weekly_warning_${RUN_DATE}.md"
PROMPT_FILE="$(mktemp)"

cleanup() {
  rm -f "${PROMPT_FILE}"
}
trap cleanup EXIT

mkdir -p "${REPORT_DIR}" "${LOG_DIR}"
cd "${CC_PROJECT_DIR}"

cat > "${PROMPT_FILE}" <<'PROMPT'
老闆，你好，UX5 專案規則已載入

請產生「台美股市每週警訊通報」Markdown 週報。

執行日期以 Asia/Taipei 今日為準。檢討期間是「最近一個週一台股收盤後，到週一美股收盤後」的一週市場表現。若今天不是週二，仍以最近一個可取得的週一收盤資料作為檢討基準，並在報告中標示。

請先讀取以下本機基礎文件：

- /home/yc5/workspace/filefold/codex2605/docs/us_stock_capital_flows_ai_ipo_macro_summary_2026-05-07.md
- /home/yc5/workspace/filefold/codex2605/docs/twii_2024q1_2026q2_money_flow_session_summary_2026-05-07.md
- /home/yc5/workspace/filefold/codex2605/docs/tw_us_market_weekly_warning_pipeline.md

請使用 agent/subagent orchestration 思維完成分析。若當前執行環境不能真正啟動 subagent，請在同一份報告中用分段方式模擬以下子任務，並明確標示每個子任務輸出：

1. US Market Flow Agent：
   - 檢查 SPX、IXIC、SOX、QQQ、SMH、NVDA、MSFT、AVGO、TSMC ADR。
   - 檢查 ETF flows、buybacks、TIC/BEA、money market、AI Mega-IPO 相關變化。
2. TW Market Flow Agent：
   - 檢查 TWII、櫃買、台積電、電子權值、AI 供應鏈。
   - 檢查外資、投信、自營商、ETF、融資、成交值、M1B/M2、出口、FDI、政策現金。
3. Derivatives / Gamma Risk Agent：
   - 美股：VIX、VVIX、0DTE、dealer gamma、ES/NQ futures、put/call skew。
   - 台股：台指期、外資期貨淨部位、選擇權 put/call、期現貨背離。
4. Cross-Market Transmission Agent：
   - 判斷 NVDA/MSFT/AVGO/SOX 是否傳導到 TSMC ADR、台積電、台指期、台股供應鏈。
5. Report Synthesis Agent：
   - 整合黃燈、橘燈、紅燈警訊。
   - 分別給出台股、美股、跨市場傳導三個燈號。
   - 使用「黃燈 1 分、橘燈 2 分、紅燈 3 分；0-3 綠、4-6 黃、7-10 橘、11 以上紅」規則。
   - 若觸發 /home/yc5/workspace/filefold/codex2605/docs/tw_us_market_weekly_warning_pipeline.md 的關鍵紅線，直接升級。
   - 產生下週必看清單。

資料原則：

- 優先使用官方資料或高可信市場資料。
- 有即時或最新資料就引用日期與數字。
- 無法取得資料時，列入「資料缺口」，不得用弱推論補齊。
- 報告要可直接寄給老闆閱讀。
- 不要做買賣建議；只做風險通報、警訊分級與觀察清單。

輸出格式：

# 台美股市每週警訊通報

## 1. 本週總評
- 警訊等級：台股[綠/黃/橘/紅] / 美股[綠/黃/橘/紅] / 傳導[低/中/高或綠/黃/橘/紅]
- 一句話結論
- 本週最重要三個訊號

## 2. US Market Flow Agent

## 3. TW Market Flow Agent

## 4. Derivatives / Gamma Risk Agent

## 5. Cross-Market Transmission Agent

## 6. 黃橘紅警訊表

## 7. 下週必看資料

## 8. 資料缺口

## 9. 本週結論

請只輸出 Markdown 報告內容，不要輸出額外對話。
PROMPT

set +e
claude --print \
  --output-format text \
  --permission-mode bypassPermissions \
  --add-dir "${CODEX_DOC_DIR}" \
  < "${PROMPT_FILE}" > "${REPORT_PATH}"
CLAUDE_STATUS=$?
set -e

if [[ ! -s "${REPORT_PATH}" ]]; then
  echo "ERROR: report was not created: ${REPORT_PATH}" >&2
  echo "CLAUDE_STATUS=${CLAUDE_STATUS}" >&2
  exit 1
fi

if [[ "${CLAUDE_STATUS}" -ne 0 ]]; then
  echo "WARNING: claude exited with status ${CLAUDE_STATUS}, but report exists: ${REPORT_PATH}" >&2
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "DRY_RUN_REPORT_PATH=${REPORT_PATH}"
  exit 0
fi

source "${CC_PROJECT_DIR}/scripts/cc_load_weather_email_env.sh"

HTML_PATH="$(python3 "${CC_PROJECT_DIR}/scripts/cc_md_to_html.py" "${REPORT_PATH}" --print)"

python3 "${CC_PROJECT_DIR}/scripts/cc_send_report_email.py" \
  --to "${RECIPIENT}" \
  --subject "cc_ 台美股市每週警訊通報 ${RUN_DATE}" \
  --body "老闆您好，本週台美股市警訊通報，依據台美資金流、總經、衍生品與跨市場傳導框架整理。" \
  --html-body "${HTML_PATH}"
