#!/usr/bin/env python3
"""Send a report email using WEATHER_* SMTP environment variables.

改善自 codex2605/scripts/send_report_email.py：
- --attachment 改為可選（原版強制必填）
- 支援純文字寄信（無附件模式）
- 寄件人 / 收件人未含 @ 時自動補 @gmail.com
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

REQUIRED_ENV = (
    "WEATHER_SMTP_HOST",
    "WEATHER_SMTP_PORT",
    "WEATHER_SMTP_USER",
    "WEATHER_SMTP_PASSWORD",
    "WEATHER_MAIL_FROM",
)

DEFAULT_EMAIL_DOMAIN = "gmail.com"


def fail(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def config() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        fail("Missing environment variables: " + ", ".join(missing))
    return {name: os.environ[name] for name in REQUIRED_ENV}


def normalize_email(value: str) -> str:
    value = value.strip()
    if not value:
        fail("Email address is empty")
    return value if "@" in value else f"{value}@{DEFAULT_EMAIL_DOMAIN}"


def send(
    to_addr: str,
    subject: str,
    body: str,
    attachment: Path | None,
    html_body: Path | None = None,
) -> None:
    cfg = config()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = normalize_email(cfg["WEATHER_MAIL_FROM"])
    msg["To"] = to_addr
    msg.set_content(body)

    if html_body is not None:
        msg.add_alternative(html_body.read_text(encoding="utf-8"), subtype="html")

    if attachment is not None:
        content_type, _ = mimetypes.guess_type(attachment)
        maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            attachment.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=attachment.name,
        )

    host = cfg["WEATHER_SMTP_HOST"]
    port = int(cfg["WEATHER_SMTP_PORT"])
    use_ssl = os.environ.get("WEATHER_SMTP_SSL", "0") == "1"
    use_starttls = os.environ.get("WEATHER_SMTP_STARTTLS", "1") == "1"

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as smtp:
                smtp.login(cfg["WEATHER_SMTP_USER"], cfg["WEATHER_SMTP_PASSWORD"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                if use_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                smtp.login(cfg["WEATHER_SMTP_USER"], cfg["WEATHER_SMTP_PASSWORD"])
                smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        fail(
            "SMTP authentication failed. If this is Gmail, use a Gmail App Password. "
            f"SMTP response: {exc.smtp_code} {exc.smtp_error!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a report email via SMTP.")
    parser.add_argument("--to", required=True, help="Recipient (email or Gmail username)")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--attachment", type=Path, default=None, help="Optional file attachment")
    parser.add_argument("--html-body", type=Path, default=None, dest="html_body",
                        help="HTML file to use as email body (renders inline in Gmail)")
    args = parser.parse_args()

    if args.attachment is not None and not args.attachment.exists():
        fail(f"Attachment does not exist: {args.attachment}")
    if args.html_body is not None and not args.html_body.exists():
        fail(f"HTML body file does not exist: {args.html_body}")

    to_addr = normalize_email(args.to)
    send(to_addr, args.subject, args.body, args.attachment, args.html_body)

    print(f"EMAIL_SENT_TO={to_addr}")
    if args.attachment:
        print(f"ATTACHMENT={args.attachment.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
