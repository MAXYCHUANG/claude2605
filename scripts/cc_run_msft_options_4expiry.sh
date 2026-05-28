#!/usr/bin/env bash
# cc_run_msft_options_4expiry.sh
# 每日美股收盤後抓取 MSFT 4 個到期層的 Cboe 選擇權鏈。
# 分析框架與 cc_run_nvda_options_4expiry.sh 相同：
#   Layer 1: Gamma  — 最近下一個週五
#   Layer 2: Weekly — 再下一個週五
#   Layer 3: Event  — MSFT Q4 FY2026 財報週（預估 2026-07-29）
#   Layer 4: Monthly — 當月或次月第三個週五（機構核心部位）
#
# 用法：
#   bash scripts/cc_run_msft_options_4expiry.sh
#   DRY_RUN=1 bash scripts/cc_run_msft_options_4expiry.sh
#
# 輸出：reports/msft_options/msft_options_4expiry_YYYY-MM-DD.md
# 排程：CRON_TZ=America/New_York，21:30 工作日

set -euo pipefail

CC_PROJECT_DIR="/home/yc5/workspace/filefold/claude2605"
CODEX_DIR="/home/yc5/workspace/filefold/codex2605"
OPTIONS_SCRIPT="${CODEX_DIR}/scripts/us_stock_options_realtime.py"
SYMBOL="MSFT"
MAX_ROWS="${MAX_ROWS:-20}"
DRY_RUN="${DRY_RUN:-0}"
RECIPIENT="${RECIPIENT:-yc5780}"

log() { echo "[$(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S ET')] $*"; }

log "=== MSFT 4-expiry options fetch start ==="

# 以美東時間為基準計算 4 個到期日
EXPIRIES=$(TZ=America/New_York python3 - << 'PYEOF'
import datetime as dt

today = dt.date.today()

def next_friday(from_date):
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

# Layer 2: Weekly — 再下一個週五
secondary = near + dt.timedelta(weeks=1)

# Layer 3: Event  — MSFT Q4 FY2026 財報週（預估 2026-07-29）
event = dt.date(2026, 7, 31)
if event <= today:
    event = next_friday(today + dt.timedelta(weeks=3))

# Layer 4: Monthly — 當月或次月第三個週五
monthly = third_friday(today.year, today.month)
if monthly <= today:
    m, y = today.month + 1, today.year
    if m > 12:
        m, y = 1, y + 1
    monthly = third_friday(y, m)

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
SNAPSHOT_OUT="/tmp/msft_intraday_snapshot_${STAMP}.md"
QQQ_MONITOR_OUT="/tmp/qqq_qyld_${SYMBOL,,}_monitor_${STAMP}.md"
RUN_DATE="$(TZ=America/New_York date '+%Y-%m-%d')"
COMBINED_MD="${CC_PROJECT_DIR}/reports/msft_options/msft_options_4expiry_${RUN_DATE}.md"
mkdir -p "$(dirname "${COMBINED_MD}")"
HTML_PATH=""

_cleanup() { rm -f "${SNAPSHOT_OUT}" "${QQQ_MONITOR_OUT}" ${HTML_PATH:+"${HTML_PATH}"}; }
trap _cleanup EXIT

# ── Intraday snapshot ──────────────────────────────────────────────────────
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

# ── QQQ + QYLD 聯合監控（傳入 MSFT 現價，權重約 8.5%）─────────────────────
QQQ_MONITOR_MD=""
if [[ -z "${SPOT_PRICE}" ]]; then
    log "WARN: no MSFT spot price — skip QQQ+QYLD monitor"
else
    QQQ_OUT=""
    if QQQ_OUT=$(python3 "${CODEX_DIR}/scripts/us_qqq_qyld_monitor.py" \
        --nvda-spot "${SPOT_PRICE}" \
        --symbol MSFT \
        --symbol-weight 0.085 \
        --output "${QQQ_MONITOR_OUT}" 2>&1); then
        echo "${QQQ_OUT}"
        QQQ_MONITOR_MD="${QQQ_MONITOR_OUT}"
        log "QQQ+QYLD monitor OK: $(basename "${QQQ_MONITOR_OUT}")"
    else
        echo "${QQQ_OUT}"
        log "WARN: QQQ+QYLD monitor failed (continuing)"
    fi
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
    log "DRY_RUN: skip email, report at ${COMBINED_MD}"
    exit 0
fi

if [[ "${SUCCESS}" -eq 0 ]]; then
    log "No successful fetches — skip email"
    exit 1
fi

# 合併：快照 + QQQ/QYLD 監控 + MSFT OC 各到期層
{
    echo "# MSFT Options Chain + QQQ/QYLD Monitor — ${RUN_DATE}"
    echo ""
    if [[ -n "${SNAPSHOT_MD}" && -f "${SNAPSHOT_MD}" ]]; then
        cat "${SNAPSHOT_MD}"
        echo ""
        echo "---"
        echo ""
    fi
    if [[ -n "${QQQ_MONITOR_MD}" && -f "${QQQ_MONITOR_MD}" ]]; then
        cat "${QQQ_MONITOR_MD}"
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

python3 "${CC_PROJECT_DIR}/scripts/cc_oc_daily_summary.py" "${COMBINED_MD}" || log "WARN: summary append failed (continuing)"

HTML_PATH="$(python3 "${CC_PROJECT_DIR}/scripts/cc_md_to_html.py" "${COMBINED_MD}" --print)"

source "${CC_PROJECT_DIR}/scripts/cc_load_weather_email_env.sh"

PRICE_TAG="${SPOT_PRICE:+\$${SPOT_PRICE}}"
python3 "${CC_PROJECT_DIR}/scripts/cc_send_report_email.py" \
    --to "${RECIPIENT}" \
    --subject "cc_ MSFT 4-Expiry Options ${RUN_DATE}${PRICE_TAG:+ | ${PRICE_TAG}}" \
    --body "老闆您好，MSFT ${SUCCESS} 個到期層 Cboe 選擇權鏈報告（${RUN_DATE}）。" \
    --html-body "${HTML_PATH}"

log "Email sent to ${RECIPIENT}"
