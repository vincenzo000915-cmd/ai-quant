// Phase 12.15.11: AI Stream — 右下角浮动 panel，实时显示 AI cron + audit AI 决策流
//
// 跟 AiStatusBar (顶部一行) 互补：
// - AiStatusBar 只显示「当前正在做 + 下次时间」(单行)
// - AiStream 显示「过去 N 条 AI 决策清单」(可折叠)
//
// 默认展开，user 可点 chevron 折叠成紫色 ✨ 浮按钮

import React, { useEffect, useState } from 'react';
import { Box, Typography, IconButton, Stack, Collapse, Tooltip, Badge } from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CloseIcon from '@mui/icons-material/Close';
import { palette } from '../theme';

// AI 事件类型 → 图标 + 中文描述
const AI_EVENT_META = {
  auto_ai_improve_done:     { icon: '🧠', label: 'AI 改进顾问完成', color: palette.ai },
  auto_ai_improve_skipped:  { icon: '⏭️', label: 'AI 改进跳过', color: palette.textMuted },
  auto_ai_improve_error:    { icon: '⚠️', label: 'AI 改进错误', color: palette.error },
  strategy_ai_generated:    { icon: '✨', label: 'AI 生成新策略', color: palette.ai },
  strategy_ai_improve:      { icon: '💡', label: 'AI 建议改进', color: palette.ai },
  candidate_translate:      { icon: '🔤', label: 'AI 翻译候选', color: palette.accent },
  candidate_backtest:       { icon: '📊', label: '候选回测完成', color: palette.accent },
  advisor_auto_apply:       { icon: '🚀', label: '自动 promote 上线', color: palette.success },
  auto_promote:             { icon: '🎯', label: '自动 promote 候选', color: palette.success },
  candidate_promote:        { icon: '🎯', label: 'Promote 候选', color: palette.success },
  strategy_retire:          { icon: '🗑️', label: '退役策略', color: palette.warning },
  strategy_revive:          { icon: '🌱', label: '复活策略', color: palette.success },
  strategy_params_applied:  { icon: '🔧', label: '套用新参数', color: palette.accent },
  cleanup_candidates:       { icon: '🧹', label: '清理候选池', color: palette.textMuted },
};

function timeAgo(iso) {
  if (!iso) return '';
  const t = new Date(iso);
  const sec = Math.floor((Date.now() - t.getTime()) / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  return `${Math.floor(hr / 24)}d`;
}

function truncateContext(ctx) {
  if (!ctx) return '';
  if (typeof ctx === 'string') return ctx.substring(0, 60);
  // 提取最有信息量的字段
  if (ctx.generated_count != null) return `${ctx.generated_count} 个候选`;
  if (ctx.candidate_id != null) return `cand #${ctx.candidate_id}`;
  if (ctx.strategy_id != null) return `策略 #${ctx.strategy_id}`;
  if (ctx.candidates_deleted != null) return `删 ${ctx.candidates_deleted} 个`;
  if (ctx.name) return ctx.name.substring(0, 30);
  return '';
}

export default function AiStream() {
  const [events, setEvents] = useState([]);
  const [expanded, setExpanded] = useState(true);
  const [hidden, setHidden] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch('/api/audit?limit=50');
        if (!r.ok) return;
        const data = await r.json();
        const aiEvents = (Array.isArray(data) ? data : [])
          .filter(e => AI_EVENT_META[e.event_type])
          .slice(0, 15);
        setEvents(aiEvents);
      } catch (_) { /* */ }
    };
    load();
    const t = setInterval(load, 30_000);
    const tickT = setInterval(() => setTick(x => x + 1), 30_000);
    return () => { clearInterval(t); clearInterval(tickT); };
  }, []);

  if (hidden) return null;

  // 折叠时：紫色 ✨ 浮按钮 + badge 显示未看事件数
  if (!expanded) {
    return (
      <Tooltip title={`AI Stream（${events.length} 条最近）`} placement="left">
        <Box
          onClick={() => setExpanded(true)}
          sx={{
            position: 'fixed', bottom: 24, right: 24, zIndex: 1100,
            width: 48, height: 48, borderRadius: '50%',
            bgcolor: palette.surface2,
            border: `1px solid ${palette.ai}55`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: `0 0 24px ${palette.aiGlow}, 0 8px 24px rgba(0,0,0,0.5)`,
            transition: 'transform 200ms, box-shadow 200ms',
            '&:hover': {
              transform: 'translateY(-2px)',
              boxShadow: `0 0 32px ${palette.aiGlow}, 0 12px 32px rgba(0,0,0,0.6)`,
            },
          }}
        >
          <Badge badgeContent={events.length} max={9} sx={{
            '& .MuiBadge-badge': { bgcolor: palette.ai, color: palette.bg, fontWeight: 700, fontSize: 10 },
          }}>
            <AutoAwesomeIcon sx={{ color: palette.ai, fontSize: 22, filter: `drop-shadow(0 0 6px ${palette.ai})` }} />
          </Badge>
        </Box>
      </Tooltip>
    );
  }

  return (
    <Box sx={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 1100,
      width: 320,
      bgcolor: palette.surface,
      border: `1px solid ${palette.ai}33`,
      borderRadius: 1.5,
      boxShadow: `0 0 32px ${palette.aiGlow}, 0 16px 40px rgba(0,0,0,0.6)`,
      overflow: 'hidden',
    }}>
      {/* Header — 紫色 accent bar */}
      <Box sx={{
        px: 1.5, py: 1,
        bgcolor: palette.aiBg,
        borderBottom: `1px solid ${palette.ai}33`,
        display: 'flex', alignItems: 'center', gap: 1,
        position: 'relative',
        '&::before': {
          content: '""',
          position: 'absolute',
          left: 0, top: 0, bottom: 0, width: 2,
          background: palette.ai,
          boxShadow: `0 0 6px ${palette.ai}`,
        },
      }}>
        <Box sx={{
          width: 7, height: 7, borderRadius: '50%',
          bgcolor: palette.ai,
          boxShadow: `0 0 6px ${palette.ai}`,
          animation: 'ai-stream-dot 1.5s ease-in-out infinite',
          '@keyframes ai-stream-dot': {
            '0%, 100%': { opacity: 1, transform: 'scale(1)' },
            '50%': { opacity: 0.5, transform: 'scale(1.3)' },
          },
        }} />
        <AutoAwesomeIcon sx={{ fontSize: 14, color: palette.ai }} />
        <Typography sx={{ flex: 1, fontSize: 11, fontWeight: 700, color: palette.ai, letterSpacing: 0.5, textTransform: 'uppercase' }}>
          AI Stream · {events.length}
        </Typography>
        <IconButton size="small" onClick={() => setExpanded(false)} sx={{ color: palette.textMuted, p: 0.25, '&:hover': { color: palette.ai } }}>
          <ExpandMoreIcon sx={{ fontSize: 16 }} />
        </IconButton>
        <IconButton size="small" onClick={() => setHidden(true)} sx={{ color: palette.textMuted, p: 0.25, '&:hover': { color: palette.error } }}>
          <CloseIcon sx={{ fontSize: 14 }} />
        </IconButton>
      </Box>

      {/* Event list */}
      <Box sx={{
        maxHeight: 380, overflowY: 'auto',
        '&::-webkit-scrollbar': { width: 4 },
        '&::-webkit-scrollbar-thumb': { bgcolor: palette.border, borderRadius: 2 },
      }}>
        {events.length === 0 ? (
          <Box sx={{ p: 2, textAlign: 'center' }}>
            <Typography sx={{ fontSize: 11, color: palette.textMuted, fontStyle: 'italic' }}>
              暂无 AI 决策记录
            </Typography>
            <Typography sx={{ fontSize: 10, color: palette.textFaint, mt: 0.5 }}>
              每周一 04:00 UTC 自动跑 AI 改进
            </Typography>
          </Box>
        ) : (
          <Stack divider={<Box sx={{ height: 1, bgcolor: palette.border }} />}>
            {events.map((e) => {
              const meta = AI_EVENT_META[e.event_type] || { icon: '·', label: e.event_type, color: palette.textMuted };
              const ctx = truncateContext(e.context);
              return (
                <Box key={e.id} sx={{
                  px: 1.5, py: 0.85,
                  display: 'flex', alignItems: 'flex-start', gap: 0.85,
                  transition: 'background 120ms',
                  '&:hover': { bgcolor: `${palette.ai}08` },
                }}>
                  <Box sx={{ fontSize: 14, lineHeight: 1.3, flexShrink: 0 }}>{meta.icon}</Box>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography sx={{ fontSize: 11, color: meta.color, fontWeight: 600, lineHeight: 1.3 }}>
                      {meta.label}
                    </Typography>
                    {ctx && (
                      <Typography sx={{ fontSize: 10, color: palette.textMuted, fontFamily: '"JetBrains Mono", monospace', lineHeight: 1.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {ctx}
                      </Typography>
                    )}
                  </Box>
                  <Typography sx={{ fontSize: 10, color: palette.textFaint, fontFamily: '"JetBrains Mono", monospace', flexShrink: 0, mt: 0.15 }}>
                    {timeAgo(e.created_at)}
                  </Typography>
                </Box>
              );
            })}
          </Stack>
        )}
      </Box>
    </Box>
  );
}
