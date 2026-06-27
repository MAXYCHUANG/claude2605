#!/usr/bin/env bash
# cc_run_us_semiconductor_options_checklist.sh
# 美股半導體 Options / Futures / PEG checklist 產出並寄信。
#
# 用法：
#   bash scripts/cc_run_us_semiconductor_options_checklist.sh
#   DRY_RUN=1 bash scripts/cc_run_us_semiconductor_options_checklist.sh   # 只產報告，不寄信
#   RECIPIENT=yc5780 bash scripts/cc_run_us_semiconductor_options_checklist.sh
set -euo pipefail

CC_PROJECT_DIR="/home/yc5/workspace/filefold/claude2605"
REPORT_DIR="${CC_PROJECT_DIR}/reports/us_semiconductor_options_checklist"
LOG_DIR="${CC_PROJECT_DIR}/log"
RECIPIENT="${RECIPIENT:-yc5780}"
DRY_RUN="${DRY_RUN:-0}"
RUN_DATE="$(TZ=America/New_York date +%Y-%m-%d)"
REPORT_PATH="${REPORT_DIR}/cc_us_semiconductor_options_checklist_${RUN_DATE}.md"

mkdir -p "${REPORT_DIR}" "${LOG_DIR}"
cd "${CC_PROJECT_DIR}"

ARGS=(--output "${REPORT_PATH}")
if [[ "${DRY_RUN}" == "1" ]]; then
  ARGS+=(--dry-run)
fi

python3 "${CC_PROJECT_DIR}/scripts/cc_run_us_semiconductor_options_checklist.py" "${ARGS[@]}"

if [[ ! -s "${REPORT_PATH}" ]]; then
  echo "ERROR: report was not created: ${REPORT_PATH}" >&2
  exit 1
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "DRY_RUN_REPORT_PATH=${REPORT_PATH}"
  exit 0
fi

source "${CC_PROJECT_DIR}/scripts/cc_load_weather_email_env.sh"

HTML_PATH="$(python3 "${CC_PROJECT_DIR}/scripts/cc_md_to_html.py" "${REPORT_PATH}" --print)"

python3 "${CC_PROJECT_DIR}/scripts/cc_send_report_email.py" \
  --to "${RECIPIENT}" \
  --subject "cc_ 美股半導體 Options / Futures / PEG Checklist ${RUN_DATE}" \
  --body "老闆您好，本次美股半導體 Options / Futures / PEG checklist。警示項已標記，資料缺口已列出。" \
  --html-body "${HTML_PATH}"

if [[ -n "${REPORT_PATH}" ]]; then
  bash "${CC_PROJECT_DIR}/scripts/gdrive_push.sh" "${REPORT_PATH}" 06_exports || \
    echo "WARNING: gdrive_push 略過（掛載不可用或失敗）" >&2
fi
