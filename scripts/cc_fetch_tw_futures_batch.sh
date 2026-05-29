#!/bin/bash
# 批次抓取台指期×加權指數歷史資料
# 用法：bash scripts/cc_fetch_tw_futures_batch.sh 202401 202512
# 每月呼叫一次 Phase 1；TAIFEX 逐日請求（內含 1.2 秒 sleep），全程約 10-12 分鐘

set -euo pipefail
cd "$(dirname "$0")/.."

START_YM="${1:-202401}"
END_YM="${2:-202512}"

SY=${START_YM:0:4}; SM=${START_YM:4:2}
EY=${END_YM:0:4};   EM=${END_YM:4:2}

Y=$SY; M=$SM
total=0; ok=0; skip=0; fail=0

while [[ $Y -lt $EY || ( $Y -eq $EY && $M -le $EM ) ]]; do
    YM=$(printf "%04d%02d" $Y $M)
    TWSE="data/tw_futures/twse_taiex_${YM}.csv"
    TAIFEX="data/tw_futures/taifex_tx_${YM}.csv"

    if [[ -f "$TWSE" && -f "$TAIFEX" ]]; then
        echo "[SKIP] $YM 已存在，跳過"
        ((skip++)) || true
    else
        echo "====== $YM ======"
        if python3 scripts/cc_fetch_tw_futures_phase1.py --ym "$YM"; then
            ((ok++)) || true
        else
            echo "[ERROR] $YM 抓取失敗" >&2
            ((fail++)) || true
        fi
        # 月份之間加一點間隔，避免連續請求被限流
        sleep 2
    fi
    ((total++)) || true

    ((M++)) || true
    if [[ $M -gt 12 ]]; then M=1; ((Y++)) || true; fi
done

echo ""
echo "====== 批次完成 ======"
echo "總月數：$total  新抓：$ok  跳過：$skip  失敗：$fail"
