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
TEMP_OC_MD="/tmp/msft_oc_full_${STAMP}.md"
CARD_MD="/tmp/msft_card_${STAMP}.md"
RUN_DATE="$(TZ=America/New_York date '+%Y-%m-%d')"
COMBINED_MD="${CC_PROJECT_DIR}/reports/msft_options/msft_options_4expiry_${RUN_DATE}.md"
OI_CACHE_DIR="${CC_PROJECT_DIR}/data/oi_cache"
mkdir -p "$(dirname "${COMBINED_MD}")"
HTML_PATH=""

_cleanup() { rm -f "${SNAPSHOT_OUT}" "${TEMP_OC_MD}" "${CARD_MD}" ${HTML_PATH:+"${HTML_PATH}"}; }
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

# ── QQQ L1 fetch（大盤燈號，不產生獨立報告）───────────────────────────────────
QQQ_RPATH=""
QQQ_EXPIRY="$(echo "${EXPIRIES}" | awk '{print $1}')"
log "Fetching QQQ L1 (expiry=${QQQ_EXPIRY}) for 大盤燈號..."
QQQ_FETCH_OUT=""
if QQQ_FETCH_OUT=$(python3 "${OPTIONS_SCRIPT}" "QQQ" --expiry "${QQQ_EXPIRY}" \
        --max-rows "${MAX_ROWS}" 2>&1); then
    echo "${QQQ_FETCH_OUT}"
    QQQ_RPATH=$(echo "${QQQ_FETCH_OUT}" | grep "^REPORT_PATH=" | cut -d= -f2-)
    log "QQQ L1 fetch OK"
else
    echo "${QQQ_FETCH_OUT}"
    log "WARN: QQQ L1 fetch failed — 大盤燈號 will show N/A"
fi

# ── Step 1：全 expiry OC 暫存（用於錨點卡計算）─────────────────────────────
{
    echo "# MSFT Options Chain — ${RUN_DATE}"
    echo ""
    for RPATH in "${REPORT_PATHS[@]}"; do
        cat "${RPATH}"
        echo ""
        echo "---"
        echo ""
    done
} > "${TEMP_OC_MD}"

# ── Step 2：OI 快取（△OI + Beta + HV30）──────────────────────────────────────
python3 "${CC_PROJECT_DIR}/scripts/cc_oc_cache_writer.py" \
    --symbol "${SYMBOL}" \
    --date "${RUN_DATE}" \
    --combined-md "${TEMP_OC_MD}" \
    --cache-dir "${OI_CACHE_DIR}" || log "WARN: OI cache write failed (continuing)"

# ── Step 3：生成錨點卡（讀全 expiry 計算 term structure）────────────────────
CARD_ARGS=(--cache-dir "${OI_CACHE_DIR}" --output "${CARD_MD}")
[[ -n "${QQQ_RPATH}" ]] && CARD_ARGS+=(--qqq-oc "${QQQ_RPATH}")
python3 "${CC_PROJECT_DIR}/scripts/cc_oc_daily_summary.py" "${TEMP_OC_MD}" \
    "${CARD_ARGS[@]}" || log "WARN: anchor card generate failed (continuing)"

# ── Step 4：組合最終報告（錨點卡 → 盤中快照 → L1 OC 原始數據）──────────────
{
    echo "# MSFT Options Chain — ${RUN_DATE}"
    echo ""
    [[ -f "${CARD_MD}" ]] && cat "${CARD_MD}"
    if [[ -n "${SNAPSHOT_MD}" && -f "${SNAPSHOT_MD}" ]]; then
        echo ""
        echo "---"
        echo ""
        cat "${SNAPSHOT_MD}"
    fi
    if [[ ${#REPORT_PATHS[@]} -gt 0 && -f "${REPORT_PATHS[0]}" ]]; then
        echo ""
        echo "---"
        echo ""
        cat "${REPORT_PATHS[0]}"
    fi
    echo ""
    echo "---"
    echo ""
} > "${COMBINED_MD}"

HTML_PATH="$(python3 "${CC_PROJECT_DIR}/scripts/cc_md_to_html.py" "${COMBINED_MD}" --print)"

source "${CC_PROJECT_DIR}/scripts/cc_load_weather_email_env.sh"

PRICE_TAG="${SPOT_PRICE:+\$${SPOT_PRICE}}"
python3 "${CC_PROJECT_DIR}/scripts/cc_send_report_email.py" \
    --to "${RECIPIENT}" \
    --subject "cc_ MSFT 4-Expiry Options ${RUN_DATE}${PRICE_TAG:+ | ${PRICE_TAG}}" \
    --body "老闆您好，MSFT ${SUCCESS} 個到期層 Cboe 選擇權鏈報告（${RUN_DATE}）。" \
    --html-body "${HTML_PATH}"

log "Email sent to ${RECIPIENT}"
