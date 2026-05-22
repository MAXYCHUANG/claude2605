#!/usr/bin/env bash
# cc_load_weather_email_env.sh
# 載入 SMTP 郵件憑證。優先使用 claude2605 本地 .env.weather_email，
# 若不存在則 fallback 到 codex2605 的同名檔案。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FALLBACK_ENV="/home/yc5/workspace/filefold/codex2605/.env.weather_email"

# 決定要載入哪個 env 檔
if [[ -L "${PROJECT_DIR}/.env.weather_email" ]]; then
  # symlink → 解析真實路徑
  ENV_FILE="$(readlink -f "${PROJECT_DIR}/.env.weather_email")"
elif [[ -f "${PROJECT_DIR}/.env.weather_email" ]]; then
  ENV_FILE="${PROJECT_DIR}/.env.weather_email"
elif [[ -f "${FALLBACK_ENV}" ]]; then
  echo "INFO: .env.weather_email not found in ${PROJECT_DIR}; using codex2605 fallback." >&2
  ENV_FILE="${FALLBACK_ENV}"
else
  echo "ERROR: .env.weather_email not found in ${PROJECT_DIR} or codex2605." >&2
  echo "Create it from .env.weather_email.example and chmod 600 it." >&2
  return 1 2>/dev/null || exit 1
fi

perm="$(stat -c '%a' "${ENV_FILE}")"
if [[ "${perm}" != "600" ]]; then
  echo "ERROR: ${ENV_FILE} permission is ${perm}; expected 600." >&2
  echo "Run: chmod 600 ${ENV_FILE}" >&2
  return 1 2>/dev/null || exit 1
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

missing=()
for name in WEATHER_SMTP_HOST WEATHER_SMTP_PORT WEATHER_SMTP_USER WEATHER_SMTP_PASSWORD WEATHER_MAIL_FROM; do
  if [[ -z "${!name:-}" ]]; then
    missing+=("${name}")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "ERROR: Missing values in ${ENV_FILE}: ${missing[*]}" >&2
  return 1 2>/dev/null || exit 1
fi

echo "Weather email env loaded from: ${ENV_FILE}"
