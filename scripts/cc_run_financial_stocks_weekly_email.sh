#!/bin/bash
# 每週五 18:00 (Asia/Taipei) 自動執行：
#   1. 跑金融股升息情境分析 pipeline
#   2. 寄報告到 yc5780@gmail.com

set -euo pipefail

PROJ="/home/yc5/workspace/filefold/claude2605"
CODEX="/home/yc5/workspace/filefold/codex2605"
LOG_DIR="$PROJ/log"
RUN_DATE=$(date +%Y-%m-%d)
REPORT="$PROJ/docs/26FIN_STOCK_doc/cc_financial_stocks_analysis_${RUN_DATE}.md"
LOG="$LOG_DIR/cc_financial_stocks_weekly.log"

mkdir -p "$LOG_DIR"

echo "==============================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 開始執行金融股週報 Pipeline" >> "$LOG"

# ── Stage 1: 載入 Fubon 環境 (有效時段才有即時報價) ──────────────────
if [ -f "$PROJ/scripts/cc_load_fubon_env.sh" ]; then
    set +e
    source "$PROJ/scripts/cc_load_fubon_env.sh" >> "$LOG" 2>&1
    set -e
fi

# ── Stage 2: 執行分析 Pipeline ──────────────────────────────────────
cd "$PROJ"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 執行 cc_run_financial_stocks_pipeline.py" >> "$LOG"
python3 scripts/cc_run_financial_stocks_pipeline.py --date "$RUN_DATE" >> "$LOG" 2>&1

# ── Stage 3: 確認報告存在 ───────────────────────────────────────────
if [ ! -f "$REPORT" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: 報告未產出 $REPORT" >> "$LOG"
    exit 1
fi

# ── Stage 4: 寄信 ──────────────────────────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 寄信給 yc5780" >> "$LOG"

if [[ ! -d "${CODEX}" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: codex2605 directory not found: ${CODEX}" | tee -a "$LOG" >&2
    exit 1
fi
if [[ ! -f "${CODEX}/.env.weather_email" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: .env.weather_email not found in ${CODEX}" | tee -a "$LOG" >&2
    exit 1
fi
cd "${CODEX}"
set -a
source .env.weather_email
set +a

WEEK_NUM=$(date +%V)
SUBJECT="[claude2605] 金融股週報 W${WEEK_NUM} ${RUN_DATE}（CBC升息情境 Top3分析）"

BODY="老闆您好，

本週金融股升息情境分析報告如附件（${RUN_DATE}）。

【分析情境】台灣 CBC 升息一碼（2×25bps = +50bps）

請參閱附件完整報告，包含：
- 13 家金融股分類（銀行型 / 壽險型 / 綜合金控）
- 各類型升息傳導機制與 3 個月預估漲跌
- Top 3 推薦個股含進場時機、目標價與停損設定
- 等待觀察名單與需要迴避個股

Claude2605 週報系統自動產出（每週五 18:00）"

# 優先使用同名 .html（若 pipeline 已產出），否則從 .md 轉換
HTML_REPORT="${REPORT%.md}.html"
if [[ ! -f "$HTML_REPORT" ]]; then
  HTML_REPORT="$(python3 "${PROJ}/scripts/cc_md_to_html.py" "$REPORT" --print)"
fi

python3 "${PROJ}/scripts/cc_send_report_email.py" \
    --to yc5780 \
    --subject "$SUBJECT" \
    --body "$BODY" \
    --html-body "$HTML_REPORT" >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 完成，報告: $REPORT" >> "$LOG"
echo "==============================" >> "$LOG"
