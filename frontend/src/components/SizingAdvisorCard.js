// Phase 11.5.12: AI 仓位/杠杆推荐卡片 — Settings 页用

import React, { useState } from 'react';
import {
  Card, CardContent, Typography, Stack, Button, Chip, Box, Alert,
  CircularProgress, Grid,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { palette } from '../theme';

function DiffRow({ label, current, recommended, unit = '', dp = 1 }) {
  const fmt = (v) => v == null ? '—' : Number(v).toFixed(dp) + unit;
  const changed = current !== recommended;
  const direction = changed && recommended > current ? '↑' : changed && recommended < current ? '↓' : '';
  const color = !changed ? palette.textMuted
    : recommended > current ? palette.warning
    : palette.success;
  return (
    <Stack direction="row" alignItems="center" sx={{ py: 0.75, borderBottom: `1px solid ${palette.border}` }}>
      <Typography sx={{ flex: 1, fontSize: 12, color: palette.textMuted }}>{label}</Typography>
      <Typography sx={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 12, color: palette.textMuted, mr: 1, minWidth: 60, textAlign: 'right' }}>
        {fmt(current)}
      </Typography>
      <Box sx={{ fontSize: 11, color: palette.textFaint, mx: 0.5 }}>→</Box>
      <Typography sx={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 13, fontWeight: 700, color, minWidth: 70, textAlign: 'right' }}>
        {direction} {fmt(recommended)}
      </Typography>
    </Stack>
  );
}

export default function SizingAdvisorCard({ onApplied }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);

  const requestAdvice = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setApplied(false);
    try {
      const r = await fetch('/api/me/sizing-advice', { method: 'POST' });
      const body = await r.json();
      if (!r.ok || !body.ok) setError(body.error || `HTTP ${r.status}`);
      else setResult(body);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const applyToConfig = async () => {
    if (!result?.recommended) return;
    setApplying(true);
    try {
      const patch = {
        trade_size_usdt: result.recommended.trade_size_usdt,
        leverage: result.recommended.leverage,
        stop_loss_pct: result.recommended.stop_loss_pct,
        take_profit_pct: result.recommended.take_profit_pct,
        max_daily_loss_usdt: result.recommended.max_daily_loss_usdt,
      };
      const r = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        setError(body.error || `HTTP ${r.status}`);
      } else {
        setApplied(true);
        onApplied?.();
      }
    } catch (e) { setError(e.message); }
    finally { setApplying(false); }
  };

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <AutoAwesomeIcon sx={{ color: palette.ai }} />
          <Typography variant="h6">AI 仓位推荐</Typography>
          <Chip label="PRO" size="small" sx={{ bgcolor: palette.aiBg, color: palette.ai, border: `1px solid ${palette.ai}55` }} />
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          AI 看你余额 + 运行策略 + 7 日表现 → 推荐 trade_size / 杠杆 / SL / TP / 日损上限
        </Typography>

        {!result && !error && (
          <Button variant="outlined" onClick={requestAdvice} disabled={loading}
            startIcon={loading ? <CircularProgress size={14} /> : <AutoAwesomeIcon />}
            sx={{ color: palette.ai, borderColor: `${palette.ai}55`, textTransform: 'none', '&:hover': { borderColor: palette.ai, bgcolor: palette.aiBg } }}>
            {loading ? 'AI 分析中…' : '让 AI 推荐参数'}
          </Button>
        )}

        {error && (
          <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {result && (
          <Box>
            <Typography variant="overline" sx={{ color: palette.textMuted, mb: 1, display: 'block' }}>
              推荐参数 (当前 → AI 推荐)
            </Typography>
            <DiffRow label="每笔下单 (USDT)" current={result.current.trade_size_usdt} recommended={result.recommended.trade_size_usdt} />
            <DiffRow label="杠杆" current={result.current.leverage} recommended={result.recommended.leverage} unit="x" dp={0} />
            <DiffRow label="止损 PnL%" current={result.current.stop_loss_pct} recommended={result.recommended.stop_loss_pct} unit="%" />
            <DiffRow label="止盈 PnL%" current={result.current.take_profit_pct} recommended={result.recommended.take_profit_pct} unit="%" />
            <DiffRow label="日损上限 (USDT)" current={result.current.max_daily_loss_usdt} recommended={result.recommended.max_daily_loss_usdt} />

            {result.recommended.rationale && (
              <Box sx={{ mt: 2, p: 1.5, bgcolor: palette.aiBg, border: `1px solid ${palette.ai}33`, borderRadius: 1 }}>
                <Typography variant="caption" sx={{ color: palette.ai, fontWeight: 600, display: 'block', mb: 0.5, fontSize: 10, letterSpacing: 0.5, textTransform: 'uppercase' }}>
                  AI 解释
                </Typography>
                <Typography variant="body2" sx={{ color: palette.text, fontSize: 12, lineHeight: 1.6 }}>
                  {result.recommended.rationale}
                </Typography>
              </Box>
            )}

            <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
              {!applied ? (
                <Button variant="contained" onClick={applyToConfig} disabled={applying}
                  startIcon={applying ? <CircularProgress size={14} /> : <CheckCircleIcon />}
                  sx={{ bgcolor: palette.ai, color: palette.bg, textTransform: 'none', '&:hover': { bgcolor: palette.aiDim } }}>
                  {applying ? '应用中…' : '一键 apply 这套参数'}
                </Button>
              ) : (
                <Chip icon={<CheckCircleIcon />} label="已应用" sx={{ bgcolor: `${palette.success}22`, color: palette.success, border: `1px solid ${palette.success}55` }} />
              )}
              <Button variant="outlined" size="small" onClick={requestAdvice}
                sx={{ color: palette.textMuted, borderColor: palette.border, textTransform: 'none' }}>
                重新生成
              </Button>
            </Stack>

            {result.llm_meta && (
              <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                <Chip size="small" label={result.llm_meta.provider_used} variant="outlined" />
                <Chip size="small" label={result.llm_meta.model_used} variant="outlined" />
                {result.llm_meta.cached && <Chip size="small" label="缓存" variant="outlined" />}
              </Stack>
            )}
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
