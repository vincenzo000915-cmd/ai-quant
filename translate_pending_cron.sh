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
set +e   # 暂时关掉 errexit，让我们捕获非零退出码
TRANSLATE_OUT=$(python3 /opt/quant/translate_cli.py --pending --max 5 2>&1)
RC=$?
set -e
echo "$TRANSLATE_OUT"

# Phase 12.34: cron 失败立即 Telegram 告警
FAILED=$(echo "$TRANSLATE_OUT" | grep -oE '完成：[0-9]+ 成功 / [0-9]+ 失敗' | grep -oE '/ [0-9]+ 失' | grep -oE '[0-9]+' | head -1)
SUCCESS=$(echo "$TRANSLATE_OUT" | grep -oE '完成：[0-9]+ 成功' | grep -oE '[0-9]+' | head -1)
TOTAL_PENDING=$(echo "$TRANSLATE_OUT" | grep -oE '共 [0-9]+ 個 pending' | grep -oE '[0-9]+' | head -1)

# 失败条件：rc != 0  OR  失败数 > 0  OR  pending > 0 但 0 成功（claude CLI 全坏）
ALERT=0
ALERT_REASON=""
if [ "$RC" -ne 0 ]; then
  ALERT=1
  ALERT_REASON="脚本异常 exit code=$RC"
elif [ -n "$FAILED" ] && [ "$FAILED" -gt 0 ]; then
  ALERT=1
  ERR_SAMPLE=$(echo "$TRANSLATE_OUT" | grep -oE 'EXCEPTION: [^$]+' | head -1 | cut -c1-180)
  ALERT_REASON="${FAILED} 个失败：${ERR_SAMPLE}"
elif [ -n "$TOTAL_PENDING" ] && [ "$TOTAL_PENDING" -gt 0 ] && [ "${SUCCESS:-0}" -eq 0 ]; then
  ALERT=1
  ALERT_REASON="${TOTAL_PENDING} pending 但 0 成功（claude CLI 全坏）"
fi

if [ "$ALERT" -eq 1 ] && [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
  MSG=$(echo "🚨 Translate cron 失败
成功 ${SUCCESS:-0} / 失败 ${FAILED:-?}（共 ${TOTAL_PENDING:-?} pending）
${ALERT_REASON}" | head -c 800)
  curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${MSG}" > /dev/null
  echo "[$LOG_TS] alert sent to Telegram"
fi

echo "[$LOG_TS] auto-translate end"
