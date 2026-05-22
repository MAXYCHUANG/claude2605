#!/usr/bin/env bash
# cc_run_us_semiconductor_options_weekly_email.sh
# 取最新的半導體週報 Markdown 並寄信。
#
# 用法：
#   bash scripts/cc_run_us_semiconductor_options_weekly_email.sh
#   RECIPIENT=yc5780 bash scripts/cc_run_us_semiconductor_options_weekly_email.sh
set -euo pipefail

CC_PROJECT_DIR="/home/yc5/workspace/filefold/claude2605"
DOC_DIR="${CC_PROJECT_DIR}/docs"
LOG_DIR="${CC_PROJECT_DIR}/log"
RECIPIENT="${RECIPIENT:-yc5780}"

mkdir -p "${LOG_DIR}"
cd "${CC_PROJECT_DIR}"

LATEST_REPORT_PATH="$(ls -1t "${DOC_DIR}"/us_semiconductor_options_futures_peg_weekly_table_*.md 2>/dev/null | head -n 1 || true)"
if [[ -z "${LATEST_REPORT_PATH}" ]]; then
  echo "ERROR: no weekly table markdown found in ${DOC_DIR}" >&2
  exit 1
fi

source "${CC_PROJECT_DIR}/scripts/cc_load_weather_email_env.sh"

HTML_PATH="$(python3 "${CC_PROJECT_DIR}/scripts/cc_md_to_html.py" "${LATEST_REPORT_PATH}" --print)"

python3 "${CC_PROJECT_DIR}/scripts/cc_send_report_email.py" \
  --to "${RECIPIENT}" \
  --subject "cc_ 美股半導體 Options / Futures / PEG 週報" \
  --body "老闆您好，本週美股半導體 Options / Futures / PEG 週報。" \
  --html-body "${HTML_PATH}"
