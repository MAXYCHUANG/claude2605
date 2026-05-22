#!/usr/bin/env python3
"""Send P0/P1/P3 usage guide via email to Google Drive shared folders."""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# Configuration
PROJECT_DIR = Path(__file__).resolve().parents[1]
GUIDE_FILE = PROJECT_DIR / "P0_P1_P3_使用指南.md"
SENDER_EMAIL = os.environ.get("GMAIL_USER", "pdc.ych@gmail.com")
SENDER_PASSWORD = os.environ.get("GMAIL_PASSWORD", "")
RECIPIENTS = [
    "pdc.ych@gmail.com",  # 預設寄給自己
]

def send_guide():
    """Send the usage guide via email."""
    if not GUIDE_FILE.exists():
        print(f"❌ 檔案不存在：{GUIDE_FILE}")
        return False

    if not SENDER_PASSWORD:
        print("❌ 缺少 GMAIL_PASSWORD 環境變數")
        return False

    try:
        with open(GUIDE_FILE, "r", encoding="utf-8") as f:
            guide_content = f.read()

        # Prepare email
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = ", ".join(RECIPIENTS)
        msg["Subject"] = "[自動化] P0/P1/P3 使用指南"

        body = f"""
親愛的 pdc.ych：

以下是最新的 P0/P1/P3 功能使用指南，已在 ux5 自動生成。

您可以複製內容到 Google Drive cc_vs_2605/tw_ccvs_2605 資料夾。

---

{guide_content}

---

此郵件由 ux5 自動化系統發送。
"""
        msg.attach(MIMEText(body, "plain", _charset="utf-8"))

        # Send via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)

        print(f"✅ 已發送到：{', '.join(RECIPIENTS)}")
        return True

    except Exception as e:
        print(f"❌ 發送失敗：{e}")
        return False

if __name__ == "__main__":
    import sys
    success = send_guide()
    sys.exit(0 if success else 1)
