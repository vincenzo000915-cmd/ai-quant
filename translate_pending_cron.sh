#!/bin/bash
# Host-side cron helper — 用本機 claude CLI 自動翻譯 pending 候選。
# 沒 ANTHROPIC_API_KEY 時的 Phase 5.1 自動化方案。
#
# 安裝（root crontab）：
#   crontab -e
#   # 加一行：每天 02:30 跑（不要跟 celery beat 02:30 撞）
#   30 2 * * *  /opt/quant/translate_pending_cron.sh >> /var/log/quant_translate.log 2>&1
#
# 想立即測試：
#   /opt/quant/translate_pending_cron.sh

set -e
cd /opt/quant
LOG_TS=$(date +'%F %T')
echo "[$LOG_TS] auto-translate start"

# 不要併發兩次跑（避免 claude CLI 同時兩個 session）
LOCK=/tmp/quant_translate_cron.lock
if ! ( set -o noclobber; echo "$$" > "$LOCK" ) 2>/dev/null; then
  echo "[$LOG_TS] another translate run holds $LOCK, skipping"
  exit 0
fi
trap 'rm -f "$LOCK"' EXIT

# 限制每次最多翻 5 個（保護 user 的 Claude Pro/Max 訂閱額度）
python3 /opt/quant/translate_cli.py --pending --max 5

echo "[$LOG_TS] auto-translate end"
