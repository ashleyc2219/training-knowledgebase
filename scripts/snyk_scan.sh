#!/usr/bin/env bash
# Snyk 掃描：依賴（snyk test）＋ 原始碼（snyk code test）。
#
# 前置（🖐️ 手動，只做一次）：
#   brew install snyk-cli        # node 被封鎖，不要用 npm
#   snyk auth                    # 開瀏覽器 OAuth；CI 用 export SNYK_TOKEN=...
#                                # 注意：OAuth token 存在 INTERNAL_OAUTH_TOKEN_STORAGE，
#                                #   `snyk config get api` 會是空的，登入狀態只能用 `snyk whoami` 判斷
#   Snyk Code 要先在網頁開啟（org admin）：
#     https://app.snyk.io/org/<org>/manage/settings → Snyk Code → Enable
#
# 用法： bash scripts/snyk_scan.sh
# 輸出： docs/plan/report/2026-09-11-snyk-scan.txt
#
# exit code（Snyk 官方）：0 沒有漏洞／1 找到漏洞／2 執行失敗／3 沒有支援的專案。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REPORT="docs/plan/report/2026-09-11-snyk-scan.txt"
REQ=".state/requirements.txt"

# 金鑰沒進 git 的自我檢查（計畫 §4 M8）
_report_env_check() {
  {
    echo
    echo "## .env 未進 git 檢查"
    if git status --porcelain 2>/dev/null | grep -q '\.env'; then
      echo "  ❌ git status 看得到 .env，請確認 .gitignore"
    else
      echo "  ✅ git status 看不到 .env"
    fi
    if git check-ignore -v .env > /dev/null 2>&1; then
      echo "  ✅ git check-ignore .env 命中 .gitignore"
    else
      echo "  ❌ .env 沒有被 .gitignore 命中"
    fi
  } >> "$REPORT"
}

mkdir -p "$(dirname "$REPORT")" .state

{
  echo "# Snyk 掃描報告"
  echo "日期：$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "專案：客服自助教學生成器（AWS-Hackathon）"
  echo
} > "$REPORT"

if ! command -v snyk > /dev/null 2>&1; then
  {
    echo "## 狀態：Snyk CLI 未安裝"
    echo "🖐️ 手動：brew install snyk-cli && snyk auth，再重跑 bash scripts/snyk_scan.sh"
  } >> "$REPORT"
  cat "$REPORT"
  exit 2
fi

echo "## Snyk CLI 版本：$(snyk --version)" >> "$REPORT"
echo >> "$REPORT"

# --- 依賴清單（uv 專案；-e . 與註解行 Snyk 的 pip parser 不吃） ---
uv export --format requirements-txt --no-hashes 2>/dev/null | grep -v '^-e ' > "$REQ"
echo "## 依賴清單：${REQ}（$(grep -cv '^#' "$REQ" || echo 0) 行）" >> "$REPORT"
echo >> "$REPORT"

# --- 未登入就停在這裡，不嘗試自動登入（snyk auth 需要瀏覽器） ---
# 新版 snyk auth 走 OAuth，token 不在 `snyk config get api`；用 `snyk whoami` 驗證
# （SNYK_TOKEN 若有設，whoami 也會一併驗證它）。
if ! SNYK_USER="$(snyk whoami 2>/dev/null)"; then
  {
    echo "## 狀態：Snyk CLI 尚未登入（掃描沒有執行）"
    echo
    echo "🖐️ 留給使用者的手動步驟："
    echo "  1. 註冊免費帳號：https://app.snyk.io/signup"
    echo "  2. snyk auth            # 會開瀏覽器做 OAuth；CI 改 export SNYK_TOKEN=<token>"
    echo "  3. bash scripts/snyk_scan.sh   # 重跑本腳本，結果會覆蓋這個檔"
    echo "  4. 截圖 Snyk 網頁儀表板與 CLI 輸出，存到 docs/plan/report/"
    echo
    echo "本腳本登入後會做的事："
    echo "  snyk test --file=${REQ} --package-manager=pip --severity-threshold=high \\"
    echo "            --command=.venv/bin/python --skip-unresolved=true"
    echo "  snyk code test ."
    echo "  驗收只接受兩個指令的 exit code 都是 0。"
  } >> "$REPORT"
  _report_env_check
  cat "$REPORT"
  exit 2
fi

echo "## Snyk 帳號（snyk whoami）：${SNYK_USER}" >> "$REPORT"
echo >> "$REPORT"

# --- Snyk 的 pip 解析器要在「已裝好專案依賴」的 Python 裡跑，而且要 import pip；
#     uv 建的 .venv 預設沒有 pip，缺的話補上（.venv 不進 git）。 ---
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  uv sync > /dev/null 2>&1
fi
if ! "$PY" -c 'import pip' > /dev/null 2>&1; then
  uv pip install pip > /dev/null 2>&1
fi

# --- 掃依賴 ---
# --command 指定 .venv 的 python；--skip-unresolved 略過平台條件不成立、因此沒安裝的套件
# （例如 watchdog ; sys_platform != 'darwin'），否則會 SNYK-OS-PYTHON-0013 Missing required packages。
{
  echo "## snyk test（依賴，--severity-threshold=high）"
  echo '```'
} >> "$REPORT"
snyk test --file="$REQ" --package-manager=pip --severity-threshold=high \
  --command="$PY" --skip-unresolved=true >> "$REPORT" 2>&1
DEPS_EXIT=$?
{
  echo '```'
  echo "exit code: $DEPS_EXIT"
  echo
} >> "$REPORT"

# --- 掃原始碼 ---
{
  echo "## snyk code test（原始碼）"
  echo '```'
} >> "$REPORT"
snyk code test . >> "$REPORT" 2>&1
CODE_EXIT=$?
{
  echo '```'
  echo "exit code: $CODE_EXIT"
  echo
  echo "## 判讀：0 = 無漏洞（驗收只接受 0）／1 = 找到漏洞／2 = 執行失敗／3 = 無支援專案"
} >> "$REPORT"

if grep -q 'SNYK-CODE-0005' "$REPORT"; then
  {
    echo
    echo "⚠️ Snyk Code 尚未在 org「${SNYK_USER}」開啟（SNYK-CODE-0005，登入本身沒問題）。"
    echo "🖐️ 手動（需 org admin）：https://app.snyk.io/org/${SNYK_USER}/manage/settings"
    echo "   → 左側 Snyk Code → Enable Snyk Code → Save，再重跑 bash scripts/snyk_scan.sh"
  } >> "$REPORT"
fi

_report_env_check

cat "$REPORT"
[ "$DEPS_EXIT" -eq 0 ] && [ "$CODE_EXIT" -eq 0 ]
