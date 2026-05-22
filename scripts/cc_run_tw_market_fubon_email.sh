#!/usr/bin/env bash
# cc_run_tw_market_fubon_email.sh
# 台股日終量價 + 法人追蹤報告，產出 Markdown 並寄信。
# 建議於台北時間 17:10 之後執行。
#
# 用法：
#   bash scripts/cc_run_tw_market_fubon_email.sh
#   RECIPIENT=yc5780 bash scripts/cc_run_tw_market_fubon_email.sh
set -euo pipefail

CC_PROJECT_DIR="/home/yc5/workspace/filefold/claude2605"
REPORT_DIR="${CC_PROJECT_DIR}/docs/26TW_MARKET_doc"
LOG_DIR="${CC_PROJECT_DIR}/log"
RECIPIENT="${RECIPIENT:-yc5780}"

mkdir -p "${REPORT_DIR}" "${LOG_DIR}"
cd "${CC_PROJECT_DIR}"

# 載入 Fubon env（允許失敗，降級為純 TWSE 模式）
if source "${CC_PROJECT_DIR}/scripts/cc_load_fubon_env.sh" 2>/dev/null; then
  echo "Fubon env loaded."
else
  echo "WARNING: Fubon env not loaded; continuing with TWSE data only." >&2
fi

# 載入 SMTP env（必須成功）
source "${CC_PROJECT_DIR}/scripts/cc_load_weather_email_env.sh"

# 產出報告
REPORT_OUTPUT="$(python3 "${CC_PROJECT_DIR}/scripts/cc_run_tw_market_fubon.py" --output-dir "${REPORT_DIR}")"
printf '%s\n' "${REPORT_OUTPUT}"

REPORT_PATH="$(printf '%s\n' "${REPORT_OUTPUT}" | awk -F= '/^REPORT_PATH=/{print $2}' | tail -n 1)"
if [[ -z "${REPORT_PATH}" ]]; then
  echo "ERROR: REPORT_PATH not found in script output." >&2
  exit 1
fi

# 轉換 Markdown → HTML（Gmail 直接渲染）
HTML_PATH="$(python3 "${CC_PROJECT_DIR}/scripts/cc_md_to_html.py" "${REPORT_PATH}" --print)"

python3 "${CC_PROJECT_DIR}/scripts/cc_send_report_email.py" \
  --to "${RECIPIENT}" \
  --subject "cc_ TW Market Daily Report" \
  --body "老闆您好，本日台股日終量價與法人追蹤報告（TWII / 0050 / 2330 / 00830 / 00891 / 2881 / 2891）。" \
  --html-body "${HTML_PATH}"
