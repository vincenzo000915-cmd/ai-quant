// Phase 14k-22: 目标进度卡 — Dashboard 顶部
// 显示: 起始 / 当前 / 目标 / 进度 bar / DD / 剩余天数

import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Stack, Chip, LinearProgress,
  IconButton, Button, Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Alert,
} from '@mui/material';
import TrackChangesIcon from '@mui/icons-material/TrackChanges';
import EditIcon from '@mui/icons-material/Edit';
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium';
import { useNavigate } from 'react-router-dom';

const PURPLE = '#a78bfa';

export default function ProfitTargetCard() {
  const navigate = useNavigate();
  const [target, setTarget] = useState(null);
  const [needsPro, setNeedsPro] = useState(false);
  const [needsExchange, setNeedsExchange] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [form, setForm] = useState({ target_pct: 20, days: 30, max_dd_pct: 15, daily_loss_halt_pct: 5 });
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      // 1. check Pro tier
      const r = await fetch('/api/me/profit-target');
      if (r.status === 402) {
        setNeedsPro(true);
        return;
      }
      setNeedsPro(false);
      const d = await r.json();
      setTarget(d.target);
      // 2. check exchange bound
      if (!d.target) {
        const bind = await fetch('/api/me/exchange-binding').then(x => x.json()).catch(() => ({}));
        setNeedsExchange(!bind.bound || !bind.bound.length);
      }
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60000);
    return () => clearInterval(t);
  }, [refresh]);

  const handleSet = async () => {
    setBusy(true);
    try {
      await fetch('/api/me/profit-target', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      setEditOpen(false);
      await refresh();
    } finally { setBusy(false); }
  };

  // 需要 Pro 订阅
  if (needsPro) {
    return (
      <Card sx={{ mb: 2, border: '1px dashed #fbbf24aa', bgcolor: 'rgba(251,191,36,0.04)' }}>
        <CardContent sx={{ py: 1.5, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <WorkspacePremiumIcon sx={{ color: '#fbbf24' }} />
          <Box sx={{ flex: 1, minWidth: 200 }}>
            <Typography variant="body2" fontWeight={700}>🤖 AI 量化经理 (Pro 功能)</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              设定盈利目标 → AI 跟踪进度 / 回撤保护 / 策略轮换 / 资金跨档自动扩张
            </Typography>
          </Box>
          <Button size="small" variant="contained" color="warning" onClick={() => navigate('/pricing')}>
            升级 Pro
          </Button>
        </CardContent>
      </Card>
    );
  }

  // Pro 但还没绑交易所
  if (needsExchange) {
    return (
      <Card sx={{ mb: 2, border: '1px dashed #60a5faaa', bgcolor: 'rgba(96,165,250,0.04)' }}>
        <CardContent sx={{ py: 1.5, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <TrackChangesIcon sx={{ color: '#60a5fa' }} />
          <Box sx={{ flex: 1, minWidth: 200 }}>
            <Typography variant="body2" fontWeight={700}>设定盈利目标前先绑交易所</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              系统需要拉你的真实余额来跟踪进度. 绑 OKX 或 Hyperliquid 即可.
            </Typography>
          </Box>
          <Button size="small" variant="contained" onClick={() => navigate('/settings')}>
            去 Settings 绑定
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!target) {
    return (
      <>
        <Card sx={{ mb: 2, border: `1px dashed ${PURPLE}44` }}>
          <CardContent sx={{ py: 1.5, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
            <TrackChangesIcon sx={{ color: PURPLE }} />
            <Box sx={{ flex: 1, minWidth: 200 }}>
              <Typography variant="body2" fontWeight={700}>🤖 启用 AI 量化经理</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                设个目标 (例 +20% / 30 天), AI 自动跟踪 + 回撤保护 + 策略轮换
              </Typography>
            </Box>
            <Button size="small" variant="contained" sx={{ bgcolor: PURPLE }} onClick={() => setEditOpen(true)}>
              开始托管
            </Button>
          </CardContent>
        </Card>
        <TargetDialog open={editOpen} onClose={() => setEditOpen(false)}
                       form={form} setForm={setForm} onSave={handleSet} busy={busy} title="启用 AI 量化经理" />
      </>
    );
  }

  const cur = target.current_equity_usdt || target.start_capital_usdt;
  const gain = cur - target.start_capital_usdt;
  const lag = target.expected_equity_now - cur;
  const isAhead = lag <= 0;
  const progressBar = Math.min(100, Math.max(0, target.progress_pct));
  const ddWarn = target.dd_pct > 0 && target.dd_pct >= target.max_dd_pct * 0.6;

  return (
    <>
      <Card sx={{ mb: 2, border: `1px solid ${PURPLE}33`, bgcolor: 'rgba(167,139,250,0.04)' }}>
        <CardContent sx={{ py: 1.5 }}>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
            <TrackChangesIcon sx={{ color: PURPLE, fontSize: 20 }} />
            <Typography variant="subtitle1" fontWeight={700}>
              AI 目标驱动
            </Typography>
            <Chip
              label={`+${target.target_pct}% / ${target.days_elapsed + target.days_remaining}天`}
              size="small"
              sx={{ bgcolor: `${PURPLE}22`, color: PURPLE, fontSize: 11 }}
            />
            <Box sx={{ flex: 1 }} />
            <IconButton size="small" onClick={() => setEditOpen(true)}>
              <EditIcon fontSize="small" />
            </IconButton>
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 1.5, alignItems: { sm: 'baseline' } }}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="caption" color="text.secondary">起始 → 当前 → 目标</Typography>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                ${target.start_capital_usdt?.toFixed(2)}
                {' → '}
                <Box component="span" sx={{ color: gain >= 0 ? '#34d399' : '#f87171' }}>
                  ${cur?.toFixed(2)} ({gain >= 0 ? '+' : ''}${gain.toFixed(2)})
                </Box>
                {' → '}
                <Box component="span" sx={{ color: PURPLE }}>
                  ${target.target_equity_usdt?.toFixed(2)}
                </Box>
              </Typography>
            </Box>
            <Box sx={{ textAlign: { sm: 'right' } }}>
              <Typography variant="caption" color="text.secondary">剩余</Typography>
              <Typography variant="body2" fontWeight={700}>
                {target.days_remaining} 天
              </Typography>
            </Box>
          </Stack>

          <Box sx={{ mb: 1 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.3 }}>
              <Typography variant="caption" color="text.secondary">
                进度 {target.progress_pct}%
                {isAhead
                  ? <Box component="span" sx={{ ml: 1, color: '#34d399' }}>✅ 领先 ${Math.abs(lag).toFixed(2)}</Box>
                  : <Box component="span" sx={{ ml: 1, color: '#fbbf24' }}>🟡 落后 ${lag.toFixed(2)}</Box>
                }
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={progressBar}
              sx={{
                height: 8, borderRadius: 1,
                bgcolor: 'rgba(255,255,255,0.06)',
                '& .MuiLinearProgress-bar': { bgcolor: progressBar >= 100 ? '#34d399' : PURPLE },
              }}
            />
          </Box>

          {target.dd_pct > 0 && (
            <Alert severity={ddWarn ? 'warning' : 'info'} sx={{ py: 0.3, fontSize: 12 }}>
              当前回撤 {target.dd_pct}% (上限 {target.max_dd_pct}%)
              {ddWarn && ` — 接近警戒线!`}
            </Alert>
          )}
        </CardContent>
      </Card>

      <TargetDialog open={editOpen} onClose={() => setEditOpen(false)}
                     form={form} setForm={setForm} onSave={handleSet} busy={busy}
                     title="更新盈利目标" existing={target} />
    </>
  );
}

function TargetDialog({ open, onClose, form, setForm, onSave, busy, title, existing }) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Alert severity="info" sx={{ fontSize: 12 }}>
            AI 会自动跟踪进度、控制回撤、扩张策略数。新目标会**替换**现有 active 目标。
          </Alert>
          {existing && (
            <Typography variant="caption" color="text.secondary">
              当前目标: ${existing.start_capital_usdt?.toFixed(2)} → +{existing.target_pct}% / {existing.days_elapsed + existing.days_remaining}天 · 完成 {existing.progress_pct}%
            </Typography>
          )}
          <TextField
            label="目标增幅 %" type="number"
            value={form.target_pct}
            onChange={(e) => setForm(f => ({ ...f, target_pct: Number(e.target.value) }))}
            helperText="月化 20% 是 stretch goal · 10-15% 较稳健"
            size="small"
          />
          <TextField
            label="周期 (天)" type="number"
            value={form.days}
            onChange={(e) => setForm(f => ({ ...f, days: Number(e.target.value) }))}
            size="small"
          />
          <TextField
            label="最大回撤 %" type="number"
            value={form.max_dd_pct}
            onChange={(e) => setForm(f => ({ ...f, max_dd_pct: Number(e.target.value) }))}
            helperText="达此回撤系统自动 halt"
            size="small"
          />
          <TextField
            label="单日亏损 halt %" type="number"
            value={form.daily_loss_halt_pct}
            onChange={(e) => setForm(f => ({ ...f, daily_loss_halt_pct: Number(e.target.value) }))}
            size="small"
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>取消</Button>
        <Button onClick={onSave} variant="contained" disabled={busy} sx={{ bgcolor: PURPLE }}>
          保存
        </Button>
      </DialogActions>
    </Dialog>
  );
}
