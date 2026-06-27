#!/usr/bin/env bash
# cc_run_us_bond_tracking.sh
# 美債市場追蹤報告產生器（daily / weekly / monthly）。
#
# 用法：
#   bash scripts/cc_run_us_bond_tracking.sh daily
#   bash scripts/cc_run_us_bond_tracking.sh weekly
#   bash scripts/cc_run_us_bond_tracking.sh monthly
set -euo pipefail

CC_PROJECT_DIR="/home/yc5/workspace/filefold/claude2605"
MODE="${1:-daily}"

if [[ "${MODE}" != "daily" && "${MODE}" != "weekly" && "${MODE}" != "monthly" ]]; then
  echo "ERROR: mode must be one of: daily, weekly, monthly" >&2
  exit 1
fi

mkdir -p "${CC_PROJECT_DIR}/log"
cd "${CC_PROJECT_DIR}"

REPORT_OUTPUT="$(python3 "${CC_PROJECT_DIR}/scripts/cc_run_us_bond_tracking.py" --mode "${MODE}")"
printf '%s\n' "${REPORT_OUTPUT}"

REPORT_PATH="$(printf '%s\n' "${REPORT_OUTPUT}" | awk -F= '/^REPORT_PATH=/{print $2}' | tail -n 1)"
if [[ -z "${REPORT_PATH}" ]]; then
  echo "ERROR: REPORT_PATH not found in script output." >&2
  exit 1
fi

echo "REPORT_PATH=${REPORT_PATH}"

bash "${CC_PROJECT_DIR}/scripts/gdrive_push.sh" "${REPORT_PATH}" 06_exports || \
  echo "WARNING: gdrive_push 略過（掛載不可用或失敗）" >&2
