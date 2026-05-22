#!/usr/bin/env bash
# cc_run_us_bond_weekly_email.sh
# 產出美債週報並寄信。建議每週日晚上執行。
#
# 用法：
#   bash scripts/cc_run_us_bond_weekly_email.sh
#   RECIPIENT=yc5780 bash scripts/cc_run_us_bond_weekly_email.sh
set -euo pipefail

CC_PROJECT_DIR="/home/yc5/workspace/filefold/claude2605"
RECIPIENT="${RECIPIENT:-yc5780}"

cd "${CC_PROJECT_DIR}"

REPORT_OUTPUT="$(bash "${CC_PROJECT_DIR}/scripts/cc_run_us_bond_tracking.sh" weekly)"
printf '%s\n' "${REPORT_OUTPUT}"

REPORT_PATH="$(printf '%s\n' "${REPORT_OUTPUT}" | awk -F= '/^REPORT_PATH=/{print $2}' | tail -n 1)"
if [[ -z "${REPORT_PATH}" ]]; then
  echo "ERROR: weekly report path not found." >&2
  exit 1
fi

source "${CC_PROJECT_DIR}/scripts/cc_load_weather_email_env.sh"

HTML_PATH="$(python3 "${CC_PROJECT_DIR}/scripts/cc_md_to_html.py" "${REPORT_PATH}" --print)"

python3 "${CC_PROJECT_DIR}/scripts/cc_send_report_email.py" \
  --to "${RECIPIENT}" \
  --subject "cc_ US Bond Market Weekly Report" \
  --body "老闆您好，本週 US Bond Market Weekly Report。已依日線 / 週線 / 月線架構整理，並保留資料缺口標記。" \
  --html-body "${HTML_PATH}"
