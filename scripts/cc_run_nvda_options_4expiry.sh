#!/usr/bin/env bash
# cc_run_nvda_options_4expiry.sh
# 每日美股收盤後抓取 NVDA 4 個到期層的 Cboe 選擇權鏈。
#
# 用法：
#   bash scripts/cc_run_nvda_options_4expiry.sh
#   DRY_RUN=1 bash scripts/cc_run_nvda_options_4expiry.sh   # 不寫檔，只驗證流程
#
# 輸出：codex2605/reports/us_stock_options_realtime/nvda_options_realtime_YYYYMMDD_HHMMSS.md
# 排程：CRON_TZ=America/New_York，20:30 工作日

set -euo pipefail

CC_PROJECT_DIR="/home/yc5/workspace/filefold/claude2605"
CODEX_DIR="/home/yc5/workspace/filefold/codex2605"
OPTIONS_SCRIPT="${CODEX_DIR}/scripts/us_stock_options_realtime.py"
SYMBOL="NVDA"
MAX_ROWS="${MAX_ROWS:-20}"
DRY_RUN="${DRY_RUN:-0}"
RECIPIENT="${RECIPIENT:-yc5780}"

log() { echo "[$(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S ET')] $*"; }

log "=== NVDA 4-expiry options fetch start ==="

# 以美東時間為基準計算 4 個到期日
EXPIRIES=$(TZ=America/New_York python3 - << 'PYEOF'
import datetime as dt

today = dt.date.today()

def next_friday(from_date):
    """next Friday strictly after from_date; if from_date is Friday, returns following Friday"""
    days_ahead = (4 - from_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return from_date + dt.timedelta(days=days_ahead)

def third_friday(year, month):
    first = dt.date(year, month, 1)
    days_ahead = (4 - first.weekday()) % 7
    return first + dt.timedelta(days=days_ahead) + dt.timedelta(weeks=2)

# Layer 1: Gamma  — 最近下一個週五
near = next_friday(today)

# Layer 2: Weekly — 再下一個週五（供次週持倉分析）
secondary = near + dt.timedelta(weeks=1)

# Layer 3: Event  — SpaceX IPO 事件週（2026-06-12）
event = dt.date(2026, 6, 12)
if event <= today:
    # 事件已過，改用 4 週後週五作為遠端錨點
    event = next_friday(today + dt.timedelta(weeks=3))

# Layer 4: Monthly — 當月或次月第三個週五（機構核心部位）
monthly = third_friday(today.year, today.month)
if monthly <= today:
    m, y = today.month + 1, today.year
    if m > 12:
        m, y = 1, y + 1
    monthly = third_friday(y, m)

# 去重，保持層次順序
seen: set = set()
result = []
for d in [near, secondary, event, monthly]:
    if d not in seen:
        seen.add(d)
        result.append(str(d))

print(" ".join(result))
PYEOF
)

log "Target expiries: ${EXPIRIES}"

FETCH_ARGS=("--max-rows" "${MAX_ROWS}")
if [[ "${DRY_RUN}" == "1" ]]; then
    FETCH_ARGS+=("--dry-run")
fi

SUCCESS=0
FAIL=0
REPORT_PATHS=()
SPOT_PRICE=""
SNAPSHOT_MD=""
STAMP=$(TZ=America/New_York date '+%Y%m%d_%H%M%S')

# ── Intraday snapshot ──────────────────────────────────────────────────────
SNAPSHOT_OUT="/tmp/${SYMBOL,,}_intraday_snapshot_${STAMP}.md"
SNAP_OUT=""
if SNAP_OUT=$(python3 "${CODEX_DIR}/scripts/us_stock_intraday_snapshot.py" "${SYMBOL}" \
    --output "${SNAPSHOT_OUT}" 2>&1); then
    echo "${SNAP_OUT}"
    [[ -z "${SPOT_PRICE}" ]] && SPOT_PRICE=$(echo "${SNAP_OUT}" | grep "^SPOT_PRICE=" | cut -d= -f2-)
    SNAPSHOT_MD="${SNAPSHOT_OUT}"
    log "Intraday snapshot OK: $(basename "${SNAPSHOT_OUT}")"
else
    echo "${SNAP_OUT}"
    log "WARN: intraday snapshot failed (continuing)"
fi

for EXPIRY in ${EXPIRIES}; do
    log "Fetching ${SYMBOL} expiry=${EXPIRY} ..."
    FETCH_OUT=""
    if FETCH_OUT=$(python3 "${OPTIONS_SCRIPT}" "${SYMBOL}" --expiry "${EXPIRY}" "${FETCH_ARGS[@]}" 2>&1); then
        echo "${FETCH_OUT}"
        RPATH=$(echo "${FETCH_OUT}" | grep "^REPORT_PATH=" | cut -d= -f2-)
        [[ -n "${RPATH}" && -f "${RPATH}" ]] && REPORT_PATHS+=("${RPATH}")
        [[ -z "${SPOT_PRICE}" ]] && SPOT_PRICE=$(echo "${FETCH_OUT}" | grep "^PRICE=" | cut -d= -f2-)
        SUCCESS=$((SUCCESS + 1))
    else
        echo "${FETCH_OUT}"
        log "WARN: fetch failed for expiry=${EXPIRY}"
        FAIL=$((FAIL + 1))
    fi
done

log "=== Done: ${SUCCESS} OK, ${FAIL} failed ==="

# ── Email ──────────────────────────────────────────────────────────────────
if [[ "${DRY_RUN}" == "1" ]]; then
    log "DRY_RUN: skip email"
    exit 0
fi

if [[ "${SUCCESS}" -eq 0 ]]; then
    log "No successful fetches — skip email"
    exit 1
fi

RUN_DATE="$(TZ=America/New_York date '+%Y-%m-%d')"
COMBINED_MD="/tmp/nvda_options_4expiry_${RUN_DATE}.md"

# 合併盤中快照 + 所有到期層報告為一份 .md
{
    echo "# NVDA Options Chain — 4-Expiry Report ${RUN_DATE}"
    echo ""
    if [[ -n "${SNAPSHOT_MD}" && -f "${SNAPSHOT_MD}" ]]; then
        cat "${SNAPSHOT_MD}"
        echo ""
        echo "---"
        echo ""
    fi
    for RPATH in "${REPORT_PATHS[@]}"; do
        cat "${RPATH}"
        echo ""
        echo "---"
        echo ""
    done
} > "${COMBINED_MD}"

HTML_PATH="$(python3 "${CC_PROJECT_DIR}/scripts/cc_md_to_html.py" "${COMBINED_MD}" --print)"

source "${CC_PROJECT_DIR}/scripts/cc_load_weather_email_env.sh"

PRICE_TAG="${SPOT_PRICE:+\$${SPOT_PRICE}}"
python3 "${CC_PROJECT_DIR}/scripts/cc_send_report_email.py" \
    --to "${RECIPIENT}" \
    --subject "cc_ NVDA 4-Expiry Options ${RUN_DATE}${PRICE_TAG:+ | ${PRICE_TAG}}" \
    --body "老闆您好，NVDA ${SUCCESS} 個到期層 Cboe 選擇權鏈報告（${RUN_DATE}）。" \
    --html-body "${HTML_PATH}"

log "Email sent to ${RECIPIENT}"
