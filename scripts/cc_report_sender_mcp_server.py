#!/usr/bin/env python3
"""Report Sender MCP Server — stdio transport.

Wraps cc_send_report_email.py + SMTP credentials from .env.weather_email
(symlink → codex2605/.env.weather_email) as MCP tools for Claude Code.

Tools:
  check_smtp_config      — 驗證 SMTP 環境變數是否完整（不回傳密碼）
  list_available_reports — 列出三類可用報告目錄與最新檔案
  send_email             — 寄送任意郵件（subject / body / 可選附件）
  send_latest_report     — 依報告類型自動找最新檔並寄出

Usage (stdio, registered in .mcp.json):
  .venv-fubon/bin/python3 scripts/cc_report_sender_mcp_server.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
ENV_FILE = PROJECT_DIR / ".env.weather_email"

DEFAULT_RECIPIENT = "yc5780"

# Report catalogue: name → (glob_dirs, glob_patterns)
REPORT_CATALOGUE: dict[str, tuple[Path, list[str]]] = {
    "tw_market": (
        PROJECT_DIR / "docs" / "26TW_MARKET_doc",
        ["cc_tw_market_fubon_daily_*.md", "tw_market_fubon_daily_*.md"],
    ),
    "us_bond_daily": (
        PROJECT_DIR / "docs" / "26US_BOND_doc",
        ["cc_us_bond_daily_*.md", "us_bond_daily_*.md"],
    ),
    "us_bond_weekly": (
        PROJECT_DIR / "docs" / "26US_BOND_doc",
        ["cc_us_bond_weekly_*.md", "us_bond_weekly_*.md"],
    ),
    "us_bond_monthly": (
        PROJECT_DIR / "docs" / "26US_BOND_doc",
        ["cc_us_bond_monthly_*.md", "us_bond_monthly_*.md"],
    ),
    "us_semiconductor": (
        PROJECT_DIR / "reports" / "us_semiconductor_options_checklist",
        ["cc_us_semiconductor_options_checklist_*.md",
         "us_semiconductor_options_checklist_*.md"],
    ),
    "tw_us_warning": (
        PROJECT_DIR / "reports" / "tw_us_market_weekly_warning",
        ["cc_tw_us_market_weekly_warning_*.md",
         "tw_us_market_weekly_warning_*.md"],
    ),
}

DEFAULT_SUBJECTS: dict[str, str] = {
    "tw_market":      "cc_ TW Market Daily Report",
    "us_bond_daily":  "cc_ US Bond Market Daily Report",
    "us_bond_weekly": "cc_ US Bond Market Weekly Report",
    "us_bond_monthly": "cc_ US Bond Market Monthly Report",
    "us_semiconductor": "cc_ 美股半導體 Options / Futures / PEG Checklist",
    "tw_us_warning":  "cc_ 台美股市每週警訊通報",
}

DEFAULT_BODIES: dict[str, str] = {
    "tw_market":      "老闆您好，附件為台股日終量價與法人追蹤報告。",
    "us_bond_daily":  "老闆您好，附件為美債市場日報。",
    "us_bond_weekly": "老闆您好，附件為美債市場週報。",
    "us_bond_monthly": "老闆您好，附件為美債市場月報。",
    "us_semiconductor": "老闆您好，附件為美股半導體 Options / Futures / PEG checklist。",
    "tw_us_warning":  "老闆您好，附件為本週台美股市警訊通報。",
}

mcp = FastMCP("report-sender")

# ---------------------------------------------------------------------------
# Load email sender module
# ---------------------------------------------------------------------------

def _load_sender_module():
    spec = importlib.util.spec_from_file_location(
        "cc_send_report_email",
        SCRIPTS_DIR / "cc_send_report_email.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod
    spec.loader.exec_module(mod)
    return mod

_sender = _load_sender_module()


def _load_env() -> None:
    """Load .env.weather_email into os.environ (skip already-set keys)."""
    if not ENV_FILE.exists():
        return
    with ENV_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_env()


def _sort_key(path: Path) -> str:
    """Sort reports by the YYYY-MM-DD date embedded in the filename.

    Falls back to the full stem so files without a date still sort stably.
    Mixing prefixes like 'cc_' and '' would otherwise break reverse-alpha sort.
    """
    import re
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return m.group(1) if m else path.stem


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def check_smtp_config() -> str:
    """驗證 SMTP 環境變數是否完整載入（不回傳密碼）。

    回傳 JSON：{ok, host, port, user, from, missing_vars}
    """
    required = (
        "WEATHER_SMTP_HOST",
        "WEATHER_SMTP_PORT",
        "WEATHER_SMTP_USER",
        "WEATHER_SMTP_PASSWORD",
        "WEATHER_MAIL_FROM",
    )
    missing = [k for k in required if not os.environ.get(k)]
    return json.dumps({
        "ok": len(missing) == 0,
        "host": os.environ.get("WEATHER_SMTP_HOST"),
        "port": os.environ.get("WEATHER_SMTP_PORT"),
        "user": os.environ.get("WEATHER_SMTP_USER"),
        "from": os.environ.get("WEATHER_MAIL_FROM"),
        "password_set": bool(os.environ.get("WEATHER_SMTP_PASSWORD")),
        "missing_vars": missing,
        "env_file": str(ENV_FILE),
        "env_file_exists": ENV_FILE.exists(),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def list_available_reports() -> str:
    """列出所有報告目錄中的可用報告與最新檔案路徑。

    回傳 JSON：{report_type: {latest, count, files: [...]}}
    """
    result: dict[str, dict] = {}
    for rtype, (rdir, patterns) in REPORT_CATALOGUE.items():
        files: list[Path] = []
        for pat in patterns:
            files.extend(rdir.glob(pat))
        files = sorted(set(files), key=_sort_key, reverse=True)
        result[rtype] = {
            "directory": str(rdir),
            "latest": str(files[0]) if files else None,
            "count": len(files),
            "files": [str(f) for f in files[:5]],
        }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def send_email(
    to: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
) -> str:
    """寄送郵件（核心工具）。

    to: 收件人，Gmail 帳號簡稱或完整 email（例如 "yc5780" 或 "yc5780@gmail.com"）
    subject: 郵件主旨
    body: 郵件本文
    attachment_path: 附件的絕對路徑（可選）
    回傳 JSON：{ok, email_sent_to, attachment}
    """
    _load_env()

    attachment: Path | None = None
    if attachment_path:
        attachment = Path(attachment_path)
        if not attachment.exists():
            return json.dumps({"ok": False,
                               "error": f"Attachment not found: {attachment_path}"},
                              ensure_ascii=False)

    try:
        to_addr = _sender.normalize_email(to)
        _sender.send(to_addr, subject, body, attachment)
        return json.dumps({
            "ok": True,
            "email_sent_to": to_addr,
            "subject": subject,
            "attachment": str(attachment) if attachment else None,
        }, ensure_ascii=False, indent=2)
    except SystemExit as exc:
        return json.dumps({"ok": False, "error": f"send failed (exit {exc.code})"},
                          ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def send_latest_report(
    report_type: str,
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> str:
    """依報告類型自動找最新檔並寄出。

    report_type: 以下之一
      tw_market       — 台股日終報告
      us_bond_daily   — 美債日報
      us_bond_weekly  — 美債週報
      us_bond_monthly — 美債月報
      us_semiconductor — 半導體 Options/Futures/PEG checklist
      tw_us_warning   — 台美每週警訊通報
    to: 收件人（省略時使用 yc5780）
    subject: 自訂主旨（省略時使用預設）
    body: 自訂本文（省略時使用預設）
    回傳 JSON：{ok, report_path, email_sent_to, subject}
    """
    if report_type not in REPORT_CATALOGUE:
        return json.dumps({
            "ok": False,
            "error": f"Unknown report_type: {report_type}",
            "valid_types": list(REPORT_CATALOGUE.keys()),
        }, ensure_ascii=False)

    rdir, patterns = REPORT_CATALOGUE[report_type]
    files: list[Path] = []
    for pat in patterns:
        files.extend(rdir.glob(pat))
    files = sorted(set(files), key=_sort_key, reverse=True)

    if not files:
        return json.dumps({
            "ok": False,
            "error": f"No reports found for type: {report_type}",
            "directory": str(rdir),
        }, ensure_ascii=False)

    latest = files[0]
    recipient = to or DEFAULT_RECIPIENT
    mail_subject = subject or DEFAULT_SUBJECTS[report_type]
    mail_body = body or DEFAULT_BODIES[report_type]

    return send_email(recipient, mail_subject, mail_body, str(latest))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
