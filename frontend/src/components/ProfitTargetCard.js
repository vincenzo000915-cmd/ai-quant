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

const PURPLE = '#a78bfa';

export default function ProfitTargetCard() {
  const [target, setTarget] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [form, setForm] = useState({ target_pct: 20, days: 30, max_dd_pct: 15, daily_loss_halt_pct: 5 });
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch('/api/me/profit-target');
      const d = await r.json();
      setTarget(d.target);
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

  if (!target) {
    return (
      <>
        <Card sx={{ mb: 2, border: `1px dashed ${PURPLE}44` }}>
          <CardContent sx={{ py: 1.5, display: 'flex', alignItems: 'center', gap: 2 }}>
            <TrackChangesIcon sx={{ color: PURPLE }} />
            <Box sx={{ flex: 1 }}>
              <Typography variant="body2" fontWeight={700}>设定盈利目标</Typography>
              <Typography variant="caption" color="text.secondary">
                AI 跟踪进度 + DD 保护 + 自动扩张策略
              </Typography>
            </Box>
            <Button size="small" variant="contained" sx={{ bgcolor: PURPLE }} onClick={() => setEditOpen(true)}>
              设定目标
            </Button>
          </CardContent>
        </Card>
        <TargetDialog open={editOpen} onClose={() => setEditOpen(false)}
                       form={form} setForm={setForm} onSave={handleSet} busy={busy} title="设定盈利目标" />
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
