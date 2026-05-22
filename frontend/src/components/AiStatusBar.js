// Phase 12.15.10: AI 状态条 — Dashboard 顶部「AI 驾驶中」紫色心跳条
//
// 让 user 一眼看到「AI 正在背后跑」— 区别于 cyan 系统色，紫色专属 AI 元素。
// 内容：
// - 「AI 驾驶中」标签 + 紫色心跳 dot
// - 滚动文字：最近 AI 动作（来自 audit log: auto_ai_improve_done / advisor_auto_apply / candidate_translate 等）
// - 右侧：下次自动 AI 任务时间（cron 计算）

import React, { useEffect, useState } from 'react';
import { Box, Typography, Stack } from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import { palette } from '../theme';

const AI_EVENTS = {
  auto_ai_improve_done: '🧠 AI 改进顾问：生成补完性候选',
  strategy_ai_generated: '✨ AI 生成新策略候选',
  strategy_ai_improve: '💡 AI 主动建议',
  candidate_translate: '🔤 AI 翻译候选策略',
  candidate_backtest: '📊 候选回测完成',
  advisor_auto_apply: '🚀 智能托管自动 promote 上线',
  auto_promote: '🎯 自动 promote 合格候选',
  strategy_retire: '🗑️ 自动退役低效策略',
  strategy_revive: '🌱 自动复活策略',
};

function timeAgo(iso) {
  if (!iso) return '';
  const t = new Date(iso);
  const sec = Math.floor((Date.now() - t.getTime()) / 1000);
  if (sec < 60) return `${sec}s 前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h 前`;
  return `${Math.floor(hr / 24)}d 前`;
}

export default function AiStatusBar() {
  const [events, setEvents] = useState([]);
  const [tick, setTick] = useState(0);   // 强制 re-render 让「Ns 前」更新

  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch('/api/audit?limit=20');
        if (!r.ok) return;
        const data = await r.json();
        // 过滤出 AI 相关事件
        const aiEvents = (Array.isArray(data) ? data : [])
          .filter(e => AI_EVENTS[e.event_type])
          .slice(0, 5);
        setEvents(aiEvents);
      } catch (_) { /* */ }
    };
    load();
    const t = setInterval(load, 60_000);
    const tickT = setInterval(() => setTick(x => x + 1), 30_000);
    return () => { clearInterval(t); clearInterval(tickT); };
  }, []);

  // 下次 cron AI 任务时间（11.5.11: 周一 04:00 UTC AI 改进顾问）
  const nextAiCron = (() => {
    const now = new Date();
    const next = new Date(Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate(),
      4, 0, 0, 0
    ));
    // 找下个周一
    const dayOfWeek = next.getUTCDay();
    const daysUntilMon = (dayOfWeek === 1 && now < next) ? 0 : (8 - dayOfWeek) % 7 || 7;
    next.setUTCDate(next.getUTCDate() + daysUntilMon);
    return next;
  })();

  const latest = events[0];

  return (
    <Box sx={{
      mb: 2,
      px: 1.75, py: 1,
      bgcolor: palette.aiBg,
      border: `1px solid ${palette.ai}33`,
      borderRadius: 1,
      display: 'flex', alignItems: 'center', gap: 1.5,
      position: 'relative',
      overflow: 'hidden',
      // 紫色心跳光晕沿底部一条 line
      '&::before': {
        content: '""',
        position: 'absolute',
        bottom: 0, left: 0, right: 0, height: 1,
        background: `linear-gradient(90deg, transparent, ${palette.ai}88, transparent)`,
        animation: 'ai-pulse-line 3s ease-in-out infinite',
      },
      '@keyframes ai-pulse-line': {
        '0%, 100%': { opacity: 0.3 },
        '50%': { opacity: 1 },
      },
    }}>
      {/* 紫色心跳 dot + AI 标签 */}
      <Stack direction="row" alignItems="center" spacing={0.75} sx={{ flexShrink: 0 }}>
        <Box sx={{
          width: 8, height: 8, borderRadius: '50%',
          bgcolor: palette.ai,
          boxShadow: `0 0 8px ${palette.ai}, 0 0 16px ${palette.aiGlow}`,
          animation: 'ai-pulse-dot 1.5s ease-in-out infinite',
          '@keyframes ai-pulse-dot': {
            '0%, 100%': { transform: 'scale(1)', opacity: 1 },
            '50%': { transform: 'scale(1.4)', opacity: 0.6 },
          },
        }} />
        <AutoAwesomeIcon sx={{ fontSize: 14, color: palette.ai, filter: `drop-shadow(0 0 4px ${palette.ai})` }} />
        <Typography sx={{
          fontSize: 11, fontWeight: 700, color: palette.ai,
          letterSpacing: 0.5, textTransform: 'uppercase',
        }}>
          AI 驾驶中
        </Typography>
      </Stack>

      {/* 中间最近事件 */}
      <Box sx={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>
        {latest ? (
          <Typography sx={{
            fontSize: 12, color: palette.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>
            <span style={{ color: palette.ai, marginRight: 8 }}>{AI_EVENTS[latest.event_type]}</span>
            <span style={{ color: palette.textMuted, fontSize: 11 }}>· {timeAgo(latest.created_at)}</span>
          </Typography>
        ) : (
          <Typography sx={{ fontSize: 12, color: palette.textMuted, fontStyle: 'italic' }}>
            待命中（最近 24h 无 AI 决策）
          </Typography>
        )}
      </Box>

      {/* 右侧下次 cron 时间 */}
      <Box sx={{ flexShrink: 0, textAlign: 'right' }}>
        <Typography sx={{ fontSize: 9, color: palette.textMuted, fontWeight: 600, letterSpacing: 0.3, textTransform: 'uppercase', lineHeight: 1 }}>
          下次 AI 改进
        </Typography>
        <Typography sx={{
          fontSize: 11, color: palette.ai, fontFamily: '"JetBrains Mono", monospace',
          fontWeight: 600, lineHeight: 1.2,
        }}>
          {nextAiCron.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' })}
        </Typography>
      </Box>
    </Box>
  );
}
