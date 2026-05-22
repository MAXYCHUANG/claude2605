# Cron 自動化部署說明

## 已部署的排程

### 1. 台股日終自動化
```
10 17 * * 1-5 cd /home/yc5/workspace/filefold/claude2605 && python3 scripts/cc_run_tw_market_fubon.py >> log/cc_run_tw_market_fubon.log 2>&1
```
- **觸發時間**: 台北時間每日 17:10（工作日 Mon-Fri）
- **腳本**: `scripts/cc_run_tw_market_fubon.py`
- **Log 位置**: `log/cc_run_tw_market_fubon.log`
- **依賴**: `.env.fubon` (Fubon API 憑證)
- **特性**: 現已擴展含 P0（完整選擇權鍊）、P1（Greeks）、P3（大單彙總）

### 2. 美債追蹤
```
CRON_TZ=America/New_York
30 20 * * 1-5 cd /home/yc5/workspace/filefold/claude2605 && python3 scripts/cc_run_us_bond_tracking.py >> log/cc_run_us_bond_tracking.log 2>&1
```
- **觸發時間**: 美東時間每日 20:30（工作日 Mon-Fri）
- **台北時間**: 隔天凌晨 04:30-05:30（因時區差異）
- **腳本**: `scripts/cc_run_us_bond_tracking.py`
- **Log 位置**: `log/cc_run_us_bond_tracking.log`
- **依賴**: `.env.weather_email` (郵件設定)

### 3. 美股選擇權檢查清單
```
CRON_TZ=America/New_York
30 20 * * 1-5 cd /home/yc5/workspace/filefold/claude2605 && python3 scripts/cc_run_us_semiconductor_options_checklist.py >> log/cc_run_us_semiconductor_options_checklist.log 2>&1
```
- **觸發時間**: 美東時間每日 20:30（工作日 Mon-Fri）
- **台北時間**: 隔天凌晨 04:30-05:30（因時區差異）
- **腳本**: `scripts/cc_run_us_semiconductor_options_checklist.py`
- **Log 位置**: `log/cc_run_us_semiconductor_options_checklist.log`
- **依賴**: `.env.weather_email` (郵件設定)

### 4. 盤中大單監聽（P3 WebSocket）
```
0 9 * * 1-5 cd /home/yc5/workspace/filefold/claude2605 && source .env.fubon && python3 scripts/cc_run_tw_bigorder_monitor.py >> log/bigorder_monitor.log 2>&1 &
35 13 * * 1-5 kill $(cat /home/yc5/workspace/filefold/claude2605/log/bigorder_monitor.pid 2>/dev/null) 2>/dev/null || true
```
- **啟動時間**: 台北時間每日 09:00（工作日）
- **停止時間**: 台北時間每日 13:35（工作日）
- **腳本**: `scripts/cc_run_tw_bigorder_monitor.py`
- **Log 位置**: `log/bigorder_monitor_*.log`、`log/bigorder_YYYYMMDD.jsonl`
- **依賴**: `.env.fubon` (Fubon API 憑證 + WebSocket)
- **大單閾值**: TXO ≥ 100 口、個股（2330/00891/00830/2881）≥ 500 張
- **監聽標的**: TXO 所有近月合約、2330、00891、00830、2881
- **輸出**: 實時記錄至 NDJSON 檔，日終報告自動讀取並彙總

## 驗證排程

### 查看已安裝的 Cron 排程
```bash
crontab -l | grep -E "cc_run|bigorder"
```

### 檢查 Log 檔案
```bash
tail -f log/cc_run_tw_market_fubon.log
tail -f log/cc_run_us_bond_tracking.log
tail -f log/cc_run_us_semiconductor_options_checklist.log
tail -f log/bigorder_monitor.log        # P3 監聽進程 log
tail -f log/bigorder_YYYYMMDD.jsonl    # P3 大單記錄（NDJSON）
```

### 測試排程（手動執行）
```bash
cd /home/yc5/workspace/filefold/claude2605

# 日終報告（含 P0/P1/P3）
python3 scripts/cc_run_tw_market_fubon.py

# 美債追蹤
python3 scripts/cc_run_us_bond_tracking.py

# 美股選擇權
python3 scripts/cc_run_us_semiconductor_options_checklist.py

# P3 盤中大單監聽（非交易時間短暫連線測試）
source .env.fubon && timeout 5 python3 scripts/cc_run_tw_bigorder_monitor.py || true
```

## 部署檢核清單

- [x] 腳本邏輯已驗證
- [x] 無真實憑證寫入 repo（用 `.env` 檔案管理）
- [x] Log 輸出位置：`log/` 目錄
- [x] Report 輸出位置：`reports/` 目錄
- [x] 失敗時的人工檢查方式：查看 Log 檔案

## 常見問題

### Cron 未執行
1. 檢查 Cron 是否啟動：`sudo systemctl status cron`
2. 查看 log：`log/cc_run_*.log`
3. 檢查環境變數是否正確：`source .env.fubon && source .env.weather_email`

### Log 權限問題
```bash
chmod 755 log/
```

### 臨時停用排程
```bash
crontab -e
# 註解掉需要停用的行（加 #）
```

### 移除排程
```bash
crontab -r  # 小心！會移除所有排程
```

## 配置檔案位置

- **Cron 配置**: `automation/cron/crontab.txt`
- **部署說明**: `automation/cron/DEPLOYMENT.md`（本檔案）
