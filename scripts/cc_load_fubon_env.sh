#!/usr/bin/env bash
# cc_load_fubon_env.sh
# 載入 Fubon Neo API 憑證。優先使用 claude2605 本地 .env.fubon，
# 若不存在則 fallback 到 codex2605 的同名檔案。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FALLBACK_ENV="/home/yc5/workspace/filefold/codex2605/.env.fubon"

if [[ -L "${PROJECT_DIR}/.env.fubon" ]]; then
  ENV_FILE="$(readlink -f "${PROJECT_DIR}/.env.fubon")"
elif [[ -f "${PROJECT_DIR}/.env.fubon" ]]; then
  ENV_FILE="${PROJECT_DIR}/.env.fubon"
elif [[ -f "${FALLBACK_ENV}" ]]; then
  echo "INFO: .env.fubon not found in ${PROJECT_DIR}; using codex2605 fallback." >&2
  ENV_FILE="${FALLBACK_ENV}"
else
  echo "ERROR: .env.fubon not found in ${PROJECT_DIR} or codex2605." >&2
  echo "Create it from .env.fubon.example and chmod 600 it." >&2
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
for name in FUBON_ID FUBON_PASSWORD FUBON_CERT_PATH FUBON_CERT_PASSWORD; do
  if [[ -z "${!name:-}" ]]; then
    missing+=("${name}")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "ERROR: Missing values in ${ENV_FILE}: ${missing[*]}" >&2
  return 1 2>/dev/null || exit 1
fi

if [[ ! -f "${FUBON_CERT_PATH}" ]]; then
  echo "ERROR: FUBON_CERT_PATH does not exist: ${FUBON_CERT_PATH}" >&2
  return 1 2>/dev/null || exit 1
fi

echo "Fubon env loaded from: ${ENV_FILE} | Cert: ${FUBON_CERT_PATH}"
