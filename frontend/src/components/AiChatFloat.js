// Phase 14k-126: AI chat assistant 右下角 floating button + drawer
// 只 Pro+ tier 且已绑 BYO LLM key 才显示

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box, Fab, Drawer, IconButton, Typography, TextField, Button,
  CircularProgress, Chip, Link as MuiLink, Stack,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import SendIcon from '@mui/icons-material/Send';
import RefreshIcon from '@mui/icons-material/Refresh';
import { Link as RouterLink } from 'react-router-dom';
import { palette, typo } from '../theme';

const ROBOT_SVG = '/chat-robot.svg';

// 把 AI 回答里的 [文字](/path) 转成 RouterLink 单击跳产品页
function renderWithLinks(text) {
  if (!text) return null;
  const parts = [];
  const regex = /\[([^\]]+)\]\(([^)]+)\)/g;
  let lastIdx = 0;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push({ kind: 'text', value: text.slice(lastIdx, match.index) });
    }
    parts.push({ kind: 'link', label: match[1], href: match[2] });
    lastIdx = regex.lastIndex;
  }
  if (lastIdx < text.length) {
    parts.push({ kind: 'text', value: text.slice(lastIdx) });
  }
  return parts.map((p, i) => {
    if (p.kind === 'text') {
      // 保留换行
      return (
        <span key={i}>
          {p.value.split('\n').map((line, j, arr) => (
            <React.Fragment key={j}>
              {line}
              {j < arr.length - 1 && <br />}
            </React.Fragment>
          ))}
        </span>
      );
    }
    // link: 站内 / 部分 path
    if (p.href.startsWith('/')) {
      return (
        <MuiLink key={i} component={RouterLink} to={p.href}
          sx={{ color: palette.ai, fontWeight: 600, textDecoration: 'underline dotted', '&:hover': { color: palette.accentBright } }}>
          {p.label}
        </MuiLink>
      );
    }
    return (
      <MuiLink key={i} href={p.href} target="_blank" rel="noopener noreferrer"
        sx={{ color: palette.ai, fontWeight: 600 }}>
        {p.label}
      </MuiLink>
    );
  });
}

export default function AiChatFloat() {
  const [eligible, setEligible] = useState(false);
  const [quota, setQuota] = useState({ used: 0, limit: 0, remaining: 0 });
  const [tier, setTier] = useState(null);
  const [hasKey, setHasKey] = useState(false);
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);  // {role: 'user'|'ai', text, filtered?: bool}
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const listRef = useRef(null);

  // 拉 quota / eligible 状态
  const refresh = useCallback(async () => {
    try {
      const r = await fetch('/api/me/ai-chat/quota');
      if (!r.ok) {
        setEligible(false);
        return;
      }
      const d = await r.json();
      setEligible(!!d.eligible);
      setQuota({ used: d.used || 0, limit: d.limit || 0, remaining: d.remaining || 0 });
      setTier(d.tier);
      setHasKey(!!d.has_byo_key);
    } catch {
      setEligible(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    // 不轮询 — 用户开抽屉时再 refresh
  }, [refresh]);

  useEffect(() => {
    if (open) {
      refresh();
      // 滚到最新
      setTimeout(() => {
        if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
      }, 100);
    }
  }, [open, messages.length, refresh]);

  const send = async () => {
    const msg = input.trim();
    if (!msg || sending) return;
    setMessages(prev => [...prev, { role: 'user', text: msg }]);
    setInput('');
    setSending(true);
    try {
      const r = await fetch('/api/me/ai-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      });
      const d = await r.json();
      if (r.ok && d.ok) {
        setMessages(prev => [...prev, { role: 'ai', text: d.text, filtered: d.filtered }]);
        if (d.quota) setQuota(d.quota);
      } else {
        const err = d.error || d.text || '出了点问题, 稍后再试';
        setMessages(prev => [...prev, { role: 'ai', text: `⚠️ ${err}`, isError: true }]);
        if (r.status === 429) refresh();
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'ai', text: '⚠️ 网络出错, 稍后再试', isError: true }]);
    } finally {
      setSending(false);
    }
  };

  if (!eligible) return null;  // 不显示 button

  const drawerWidth = { xs: '100vw', sm: 420 };

  return (
    <>
      {/* Floating button — 右下角 */}
      <Fab
        onClick={() => setOpen(true)}
        sx={{
          position: 'fixed',
          bottom: { xs: 16, sm: 24 },
          right: { xs: 16, sm: 24 },
          width: 60, height: 60,
          background: `radial-gradient(circle at 35% 35%, ${palette.accentBright}, ${palette.ai} 55%, #7c3aed 100%)`,
          boxShadow: `0 4px 20px ${palette.accentGlow}, 0 0 0 1px rgba(255,255,255,0.1) inset`,
          transition: 'transform 220ms, box-shadow 220ms',
          zIndex: 1200,
          '&:hover': {
            transform: 'scale(1.06)',
            boxShadow: `0 6px 28px ${palette.accentGlow}, 0 0 0 1px rgba(255,255,255,0.15) inset`,
          },
        }}
        aria-label="AI 助手"
      >
        <Box component="img" src={ROBOT_SVG} alt="" sx={{ width: 42, height: 42 }} />
      </Fab>

      {/* Drawer 抽屉 */}
      <Drawer
        anchor="right"
        open={open}
        onClose={() => setOpen(false)}
        PaperProps={{
          sx: {
            width: drawerWidth,
            maxWidth: '100vw',
            bgcolor: palette.bg,
            color: palette.text,
            borderLeft: `1px solid ${palette.border}`,
          },
        }}
      >
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {/* Header */}
          <Box sx={{
            px: 2, py: 1.5,
            borderBottom: `1px solid ${palette.border}`,
            display: 'flex', alignItems: 'center', gap: 1.5,
          }}>
            <Box component="img" src={ROBOT_SVG} alt="" sx={{ width: 36, height: 36 }} />
            <Box sx={{ flex: 1, minWidth: { xs: 0, sm: 200 } }}>
              <Typography sx={{ fontWeight: 700, fontSize: 15, color: palette.text, lineHeight: 1.2 }}>
                AI 量化助手
              </Typography>
              <Typography sx={{ fontSize: 11, color: palette.textMuted, fontFamily: typo.mono }}>
                {tier?.toUpperCase()} · {quota.remaining}/{quota.limit} 今日剩余
              </Typography>
            </Box>
            <IconButton size="small" onClick={refresh} sx={{ color: palette.textMuted }}>
              <RefreshIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" onClick={() => setOpen(false)} sx={{ color: palette.textMuted }}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>

          {/* Messages list */}
          <Box ref={listRef} sx={{
            flex: 1,
            overflowY: 'auto',
            px: 2, py: 2,
            display: 'flex', flexDirection: 'column', gap: 1.5,
          }}>
            {messages.length === 0 && (
              <Box sx={{ textAlign: 'center', py: 4, color: palette.textMuted }}>
                <Box component="img" src={ROBOT_SVG} alt="" sx={{ width: 64, height: 64, opacity: 0.6, mb: 1.5 }} />
                <Typography sx={{ fontSize: 13.5, lineHeight: 1.7, maxWidth: 320, mx: 'auto' }}>
                  我是你的量化驾驶舱助手 (read-only)
                  <br/>
                  可以问我:
                </Typography>
                <Stack spacing={0.75} sx={{ mt: 2 }}>
                  {[
                    '为什么 AI 调整了 #29 leverage?',
                    'EV 是什么意思? 我的 #61 EV 健康吗?',
                    '怎么手动 pause 一个策略?',
                    '我的资金应该再开新策略吗?',
                  ].map((q, i) => (
                    <Chip key={i} label={q} size="small" onClick={() => setInput(q)}
                      sx={{
                        bgcolor: 'rgba(167,139,250,0.06)',
                        border: `1px solid ${palette.border}`,
                        color: palette.text, fontSize: 11.5,
                        '&:hover': { borderColor: palette.borderAccent, bgcolor: 'rgba(167,139,250,0.12)' },
                      }}/>
                  ))}
                </Stack>
              </Box>
            )}
            {messages.map((m, i) => (
              <Box key={i} sx={{
                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                maxWidth: '85%',
                px: 1.5, py: 1.25,
                borderRadius: 1.5,
                bgcolor: m.role === 'user'
                  ? 'rgba(167,139,250,0.12)'
                  : (m.isError ? 'rgba(239,68,68,0.08)' : palette.surface),
                border: `1px solid ${m.role === 'user' ? palette.borderAccent : palette.border}`,
                color: palette.text,
                fontSize: 13.5,
                lineHeight: 1.65,
              }}>
                {m.role === 'ai' ? renderWithLinks(m.text) : m.text}
                {m.filtered && (
                  <Typography sx={{ mt: 1, fontSize: 10, color: palette.textMuted, fontStyle: 'italic' }}>
                    (此回答经安全过滤)
                  </Typography>
                )}
              </Box>
            ))}
            {sending && (
              <Box sx={{ alignSelf: 'flex-start', display: 'flex', alignItems: 'center', gap: 1, color: palette.textMuted, fontSize: 12 }}>
                <CircularProgress size={14} sx={{ color: palette.ai }} />
                思考中...
              </Box>
            )}
          </Box>

          {/* Input */}
          <Box sx={{
            p: 1.5,
            borderTop: `1px solid ${palette.border}`,
            display: 'flex', gap: 1, alignItems: 'flex-end',
          }}>
            <TextField
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="问我关于你的策略 / 持仓 / AI 决策..."
              multiline
              maxRows={4}
              fullWidth
              size="small"
              disabled={sending || quota.remaining <= 0}
              sx={{
                '& .MuiInputBase-root': {
                  bgcolor: palette.surface,
                  color: palette.text,
                  fontSize: 13.5,
                },
                '& fieldset': { borderColor: palette.border },
              }}
            />
            <Button
              onClick={send}
              disabled={!input.trim() || sending || quota.remaining <= 0}
              variant="contained"
              sx={{
                bgcolor: palette.ai, color: palette.bg,
                minWidth: 0, p: 1.25,
                '&:hover': { bgcolor: palette.accentBright },
                '&:disabled': { bgcolor: palette.border, color: palette.textMuted },
              }}
            >
              <SendIcon fontSize="small" />
            </Button>
          </Box>
          {quota.remaining <= 0 && (
            <Typography sx={{ fontSize: 11, color: palette.textMuted, textAlign: 'center', pb: 1.5 }}>
              今日 {quota.limit} 次额度用完, 明日 UTC 00:00 重置
            </Typography>
          )}
        </Box>
      </Drawer>
    </>
  );
}
