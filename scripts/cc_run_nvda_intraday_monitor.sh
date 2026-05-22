#!/usr/bin/env bash
# cc_run_nvda_intraday_monitor.sh WINDOW
#
# NVDA 開盤後 N 分鐘盤中監控，產生 HTML email 並寄出。
# WINDOW: 5 | 15 | 30 | 90 | 150（minutes from market open）
#
# 用法（手動）：
#   bash scripts/cc_run_nvda_intraday_monitor.sh 30
#   DRY_RUN=1 bash scripts/cc_run_nvda_intraday_monitor.sh 5
#
# 排程觸發：
#   09:35 → 5m   09:45 → 15m   10:00 → 30m   11:00 → 90m   12:00 → 150m (America/New_York)

set -euo pipefail

WINDOW="${1:?Usage: cc_run_nvda_intraday_monitor.sh WINDOW (5|15|30|90|150)}"
CODEX_DIR="/home/yc5/workspace/filefold/codex2605"
RECIPIENT="${RECIPIENT:-yc5780}"
DRY_RUN="${DRY_RUN:-0}"

log() { echo "[$(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S ET')] $*"; }

log "=== NVDA intraday monitor: window=${WINDOW}m start ==="

set -a
source "${CODEX_DIR}/.env.weather_email"
set +a

EXTRA_ARGS=()
[[ "${DRY_RUN}" == "1" ]] && EXTRA_ARGS+=("--dry-run")

python3 "${CODEX_DIR}/scripts/us_stock_intraday_monitor.py" \
    --window "${WINDOW}" \
    --to     "${RECIPIENT}" \
    "${EXTRA_ARGS[@]}"

log "=== Done ==="
