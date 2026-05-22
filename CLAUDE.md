# Claude 工作區指示

這份 Markdown 是給 `/home/yc5/workspace/filefold/claude2605` 使用的工作區規則。
若 Claude Code 在此目錄啟動，請優先讀取本檔。

## 基本互動規則

- 一律稱呼使用者為「老闆」。
- 一律使用正體中文回答，除非老闆明確要求其他語言。
- 回答要清楚、可執行、避免空泛描述。
- 若需要修改檔案，先理解現有結構，再做最小必要變更。
- 不要覆蓋、還原或刪除老闆既有修改，除非老闆明確要求。
- 遇到權限、憑證、部署、遠端服務或破壞性操作時，先說明目的與影響，再請老闆確認。

## 執行環境

- 本專案預期在 Linux / Ubuntu Server 類環境執行。
- 不使用 PowerShell，預設 shell 為 `bash` 或 `sh`。
- 若透過遠端連線工作，優先在遠端專案目錄中操作，不假設本機工具狀態可直接套用。

## 預設工作區

- 所有專案探索、檔案讀寫、測試與 automation 設計，預設都以目前此檔所在的專案根目錄為工作區。
- 若任務需要跨到其他資料夾、其他 server、系統路徑或外部服務，先向老闆說明目的與影響。

## 遠端環境檢查

開始需要工具或 automation 的任務前，優先確認遠端環境：

```bash
hostname
pwd
git --version
node --version
npm --version
python3 --version
```

若工具不存在，先回報缺少的項目與建議安裝方式，不要假設可以直接修改系統設定。

## Claude Code 使用原則

- 優先在目前工作區內完成任務，不要擴大到無關目錄。
- 若專案有既有測試、lint、格式化或建置指令，優先沿用。
- 若不確定指令，先檢查 `README.md`、`package.json`、`pyproject.toml`、`Makefile`、`justfile` 或 CI 設定。
- 執行測試前先說明會跑什麼、可能耗時多久、是否需要網路或憑證。
- 若無法執行測試，回報原因與替代驗證方式。

## Orchestration Pipeline 工作流程

執行任務時，使用 Orchestration 的 Pipeline 思維組織工作。預設流程如下：

1. **Intake**：確認老闆的目標、輸入、限制與成功條件。
2. **Context**：盤點目前專案、相關檔案、工具、環境與既有流程。
3. **Plan**：把任務拆成可執行步驟，標明相依關係與風險。
4. **Execute**：依序執行必要步驟，保持變更小而明確。
5. **Verify**：執行可行的檢查、測試、語法驗證或人工檢閱。
6. **Report**：用正體中文回報完成內容、檔案位置、驗證結果與下一步。

對 automation 任務，優先設計成可重複執行的 Pipeline，並說明下列各項：

- **Trigger**：觸發條件，例如手動、排程、檔案變更、Webhook。
- **Inputs**：輸入資料、環境變數、憑證與設定。
- **Stages**：每個階段的責任、輸入、輸出與錯誤處理。
- **Artifacts**：產物位置，例如 log、報表、暫存檔、輸出資料。
- **Observability**：記錄執行狀態、錯誤訊息與可追蹤資訊。
- **Recovery**：失敗時的重試、回滾、人工介入或安全停止方式。

## Automation 目錄結構

新增 automation 腳本或設定時，優先放在以下位置：

```text
automation/
  prompts/       # 穩定的 prompt 文字
  scripts/       # 可重複執行的 shell / Python 腳本
  env/           # .env.example，不放真實憑證
  systemd/       # .service 與 .timer 範本
  cron/          # cron 排程範本
  runbooks/      # 人工操作與除錯流程
reports/         # 輸出報表 (Markdown / HTML)
log/             # 執行 log
docs/            # 技術文件與 pipeline 說明
scripts/         # 一般腳本（既有慣例位置）
```

## Automation 分層建議

| 層級 | 工具 | 適合 |
| --- | --- | --- |
| 1 | Shell Script | 可預測流程：載入 env、呼叫 Python、寫 log |
| 2 | Cron | 簡單時間排程，每日 / 每週觸發 |
| 3 | systemd timer | 正式 server automation，可用 `systemctl` 與 `journalctl` 監控 |
| 4 | GitHub Actions | repo / PR / CI 綁定的流程 |

Cron 範本格式：

```bash
# 台北時間 17:10 後執行（台股日終）
10 17 * * 1-5 cd /home/yc5/workspace/filefold/claude2605 && /bin/bash scripts/example.sh >> log/example.log 2>&1

# 美東收盤後執行（美股日終）
CRON_TZ=America/New_York
30 20 * * 1-5 cd /home/yc5/workspace/filefold/claude2605 && /bin/bash scripts/example.sh >> log/example.log 2>&1
```

## Git 與檔案安全

修改前先檢查工作樹：

```bash
git status --short
```

- 不要還原老闆已修改的檔案。
- 不要執行 `git reset --hard`、`git checkout -- <file>`、大量刪除或覆蓋操作，除非老闆明確要求。
- 若工作樹已有與任務相關的未提交修改，先理解內容，再決定如何最小變更。
- 若需要新增腳本或設定檔，優先放在專案既有慣例位置。
- 不要把真實憑證、密碼或 `.env` 寫進 repo；只放 `.env.example`。

## 驗證原則

- 優先使用專案既有測試、lint、格式化或建置指令。
- 若不確定指令，先檢查 README、`package.json`、`pyproject.toml`、`Makefile`、`justfile`、Taskfile 或 CI 設定。
- 執行測試前說明會跑什麼、可能耗時多久、是否需要網路或憑證。
- 若無法執行測試，回報原因與替代驗證方式。

## 除錯流程

### 1. 環境確認

```bash
hostname && pwd
git status --short
ls
```

### 2. 環境變數問題

```bash
# 確認 .env 存在
test -f .env && echo "ok" || echo "missing"
# 確認 example 是否有缺少的欄位
diff .env.example .env
```

### 3. 腳本執行失敗

先確認語法：

```bash
bash -n scripts/example.sh
python3 -m py_compile scripts/example.py
```

再以最小副作用模式排查，不要直接跑有寫入或寄信效果的步驟。

### 4. Cron / systemd 問題

- 把 stdout、stderr 分開存 log（`>> log/x.log 2>&1`）。
- 長期任務使用 systemd timer，可用 `journalctl -u service-name` 追 log。
- 高風險任務先在測試目錄或 container 內驗證，確認後再掛排程。

## ux5 郵件發送流程

ux5 可透過 codex2605 workspace 的郵件系統發送報告給團隊。以下是完整流程：

### 環境設定

郵件配置存於 codex2605 workspace：
```bash
/home/yc5/workspace/filefold/codex2605/.env.weather_email
```

包含：
- WEATHER_SMTP_HOST / WEATHER_SMTP_PORT / WEATHER_SMTP_USER / WEATHER_SMTP_PASSWORD
- WEATHER_MAIL_FROM（寄件者）
- WEATHER_MAIL_TO（預設收件人）

**重點**：此檔案含真實憑證，權限為 600，不應寫入 repo。

### 郵件發送命令

使用 codex2605 的 `send_report_email.py` 腳本：

```bash
cd /home/yc5/workspace/filefold/codex2605 && \
set -a && \
source .env.weather_email && \
set +a && \
python3 scripts/send_report_email.py \
  --to 收件人 \
  --subject "郵件主旨" \
  --body "郵件內容" \
  --attachment /path/to/file.md
```

**關鍵點**：
1. **必須用 `set -a / set +a`** — 確保環境變數正確導出
2. 收件人簡寫自動補 @gmail.com（例：yc5780 → yc5780@gmail.com）
3. 附件路徑須絕對路徑

### 使用範例

發送日終報告給 yc5780：
```bash
cd /home/yc5/workspace/filefold/codex2605 && \
set -a && \
source .env.weather_email && \
set +a && \
python3 scripts/send_report_email.py \
  --to yc5780 \
  --subject "[claude2605] 日終報告" \
  --body "親愛的 yc5780：\n\n日終報告已生成。" \
  --attachment /home/yc5/workspace/filefold/claude2605/docs/26TW_MARKET_doc/cc_tw_market_fubon_daily_2026-05-19.md
```

### 常見問題排查

| 問題 | 原因 | 解決 |
|------|------|------|
| Missing WEATHER_SMTP_* | 環境變數未導出 | 用 `set -a / set +a` 包裹 source |
| 收件人格式錯誤 | 忘記 @gmail.com | 直接寫簡稱（yc5780），腳本自動補 |
| 找不到附件 | 路徑錯誤或相對路徑 | 用 `ls -l /path/to/file` 驗證，必須絕對路徑 |

### 調試技巧

**直接檢查環境變數**（不要假設或搜尋）：
```bash
cat /home/yc5/workspace/filefold/codex2605/.env.weather_email
```

**測試環境加載**：
```bash
cd /home/yc5/workspace/filefold/codex2605 && \
set -a && \
source .env.weather_email && \
set +a && \
echo "SMTP_HOST=$WEATHER_SMTP_HOST" && \
echo "MAIL_FROM=$WEATHER_MAIL_FROM"
```

## Automation 部署檢核清單

部署前：

- [ ] Prompt 或腳本邏輯已人工驗證。
- [ ] 腳本不依賴 Windows path 或本機工具。
- [ ] 沒有把真實憑證寫進 repo，只有 `.env.example`。
- [ ] 有 log 與 report 輸出位置。
- [ ] 有失敗時的人工檢查方式（Recovery 步驟）。

部署後驗證：

- [ ] 腳本可手動執行並產出預期 artifact。
- [ ] Log 可正常寫入與追蹤。
- [ ] Cron / systemd timer 可啟動且狀態正常。
- [ ] 失敗時不會刪除或覆蓋重要資料。

## 回報格式

回報時優先包含：

- 做了什麼。
- 改了哪些檔案。
- 如何驗證。
- 老闆接下來可以怎麼執行。

保持簡潔，但遇到 automation、部署、遠端連線、憑證或權限相關工作時，要明確列出風險與確認點。
