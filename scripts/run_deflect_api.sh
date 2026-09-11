#!/usr/bin/env bash
# Phase 3：啟動 Rote Play 要打的本機 deflect API（demo 全程要開著）。
# 用法：scripts/run_deflect_api.sh [port]
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run uvicorn app.api.deflect_api:app --port "${1:-8765}"
