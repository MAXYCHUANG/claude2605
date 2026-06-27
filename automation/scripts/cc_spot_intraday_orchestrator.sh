#!/usr/bin/env bash
# cc_spot_intraday_orchestrator.sh WINDOW
#
# 3-Layer Spot Monitor (NVDA, SMH, QQQ, SPY) incorporating static OC metadata.
# WINDOW: 5 | 15 | 30 | 90 | 150（minutes from market open）
#
# 用法（手動）：
#   bash automation/scripts/cc_spot_intraday_orchestrator.sh 30
#   DRY_RUN=1 bash automation/scripts/cc_spot_intraday_orchestrator.sh 5

set -euo pipefail

WINDOW="${1:?Usage: cc_spot_intraday_orchestrator.sh WINDOW (5|15|30|90|150)}"
CLAUDE_DIR="/home/yc5/workspace/filefold/claude2605"
RECIPIENT="${RECIPIENT:-yc5780}"
DRY_RUN="${DRY_RUN:-0}"

log() { echo "[$(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S ET')] $*"; }

log "=== 3-Layer Spot Intraday Monitor: window=${WINDOW}m start ==="

# ── 交易日判斷：Yahoo Finance 最後成交時間是否為今日（美東）──────────────
if ! python3 - <<'PYEOF' 2>/dev/null
import urllib.request, json, datetime
try:
    from zoneinfo import ZoneInfo; ET = ZoneInfo("America/New_York")
except ImportError:
    from datetime import timezone, timedelta; ET = timezone(timedelta(hours=-4))
today = datetime.datetime.now(tz=ET).date()
req = urllib.request.Request(
    "https://query1.finance.yahoo.com/v8/finance/chart/NVDA?interval=1m&range=1d",
    headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=10) as r:
    d = json.loads(r.read())
last_ts = d["chart"]["result"][0]["meta"].get("regularMarketTime", 0)
last_date = datetime.datetime.fromtimestamp(last_ts, tz=ET).date()
exit(0 if last_date == today else 1)
PYEOF
then
    log "Not a US trading day — skip"
    exit 0
fi

if [[ ! -d "${CLAUDE_DIR}" ]]; then
    log "ERROR: claude2605 directory not found: ${CLAUDE_DIR}" >&2
    exit 1
fi
if [[ ! -f "${CLAUDE_DIR}/.env.weather_email" ]]; then
    log "ERROR: .env.weather_email not found in ${CLAUDE_DIR}" >&2
    exit 1
fi
if [[ ! -f "${CLAUDE_DIR}/scripts/cc_spot_intraday_monitor.py" ]]; then
    log "ERROR: cc_spot_intraday_monitor.py not found in ${CLAUDE_DIR}/scripts/" >&2
    exit 1
fi

set -a
source "${CLAUDE_DIR}/.env.weather_email"
set +a

EXTRA_ARGS=()
[[ "${DRY_RUN}" == "1" ]] && EXTRA_ARGS+=("--dry-run")

python3 "${CLAUDE_DIR}/scripts/cc_spot_intraday_monitor.py" \
    --window "${WINDOW}" \
    --to     "${RECIPIENT}" \
    "${EXTRA_ARGS[@]}"

log "=== Done ==="
