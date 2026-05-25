// Phase 14k-22: 目标进度卡 — Dashboard 顶部
// 显示: 起始 / 当前 / 目标 / 进度 bar / DD / 剩余天数

import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Stack, Chip, LinearProgress,
  IconButton, Button, Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Alert, Tooltip,
} from '@mui/material';
import TrackChangesIcon from '@mui/icons-material/TrackChanges';
import EditIcon from '@mui/icons-material/Edit';
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium';
import PauseCircleIcon from '@mui/icons-material/PauseCircle';
import PlayCircleIcon from '@mui/icons-material/PlayCircle';
import CancelIcon from '@mui/icons-material/Cancel';
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

  const handlePause = async () => {
    if (!target) return;
    if (!window.confirm('暂停 AI 托管? 监控 / DD 保护 / 周轮换 都会停止. 你可以随时恢复.')) return;
    setBusy(true);
    try {
      await fetch(`/api/me/profit-target/${target.id}`, { method: 'DELETE' });
      await refresh();
    } finally { setBusy(false); }
  };

  const handleResume = async () => {
    setBusy(true);
    try {
      // 找最近 paused/expired 的恢复
      const paused = await fetch('/api/me/profit-target/paused').then(r => r.json());
      const t = (paused.targets || [])[0];
      if (!t) {
        setEditOpen(true);  // 没有可恢复 → 设新的
        return;
      }
      await fetch(`/api/me/profit-target/${t.id}/resume`, { method: 'POST' });
      await refresh();
    } finally { setBusy(false); }
  };

  // 需要 Team 订阅 (14k-23 升级)
  if (needsPro) {
    return (
      <Card sx={{ mb: 2, border: '1px dashed #fbbf24aa', bgcolor: 'rgba(251,191,36,0.04)' }}>
        <CardContent sx={{ py: 1.5, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <WorkspacePremiumIcon sx={{ color: '#fbbf24' }} />
          <Box sx={{ flex: 1, minWidth: 200 }}>
            <Typography variant="body2" fontWeight={700}>🤖 AI 自动托管 (Team 顶级方案)</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              设盈利目标 → AI 全权管理: 进度跟踪 / 回撤保护 / 策略轮换 / 资金跨档扩张 / 多交易所
            </Typography>
          </Box>
          <Button size="small" variant="contained" color="warning" onClick={() => navigate('/pricing')}>
            升级 Team
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
              <Typography variant="body2" fontWeight={700}>🤖 启用 AI 自动托管</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                设个目标 (例 +20% / 30 天), AI 跟踪 + 回撤保护 + 策略轮换 + 资金跨档扩张
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              <Button size="small" variant="outlined" startIcon={<PlayCircleIcon />} onClick={handleResume} disabled={busy}
                       sx={{ borderColor: PURPLE, color: PURPLE }}>
                恢复上次
              </Button>
              <Button size="small" variant="contained" sx={{ bgcolor: PURPLE }} onClick={() => setEditOpen(true)}>
                开始托管
              </Button>
            </Stack>
          </CardContent>
        </Card>
        <TargetDialog open={editOpen} onClose={() => setEditOpen(false)}
                       form={form} setForm={setForm} onSave={handleSet} busy={busy} title="启用 AI 自动托管" />
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
              AI 自动托管中
            </Typography>
            <Chip
              label={`+${target.target_pct}% / ${target.days_elapsed + target.days_remaining}天`}
              size="small"
              sx={{ bgcolor: `${PURPLE}22`, color: PURPLE, fontSize: 11 }}
            />
            <Box sx={{ flex: 1 }} />
            <Tooltip title="改目标">
              <IconButton size="small" onClick={() => setEditOpen(true)}>
                <EditIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="暂停 AI 托管 (停止监控 / DD / 周轮换, 现有 running 策略不受影响)">
              <IconButton size="small" color="warning" onClick={handlePause} disabled={busy}>
                <PauseCircleIcon fontSize="small" />
              </IconButton>
            </Tooltip>
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
  // 14k-25: 现实性等级判定
  const monthlyEq = form.days > 0
    ? (Math.pow(1 + form.target_pct / 100, 30 / form.days) - 1) * 100
    : 0;
  let level = 'safe', levelColor = '#34d399', levelLabel = '🟢 稳健';
  let warning = '';
  if (monthlyEq > 50) {
    level = 'reject'; levelColor = '#f87171'; levelLabel = '⛔ 超出上限';
    warning = `月化 ${monthlyEq.toFixed(0)}% 超出系统支持上限 (50%). 一流量化年化 ~30%, 此设置不切实际. 请降目标或拉长周期.`;
  } else if (monthlyEq > 30) {
    level = 'aggressive'; levelColor = '#f87171'; levelLabel = '🔴 激进';
    warning = `月化 ${monthlyEq.toFixed(0)}% 属顶级量化水平, 停损会非常频繁. 需要 user 心理承受波动.`;
  } else if (monthlyEq > 15) {
    level = 'ambitious'; levelColor = '#fbbf24'; levelLabel = '🟡 进取';
    warning = `月化 ${monthlyEq.toFixed(0)}% 高于一线基金平均 (年化 30% ≈ 月 2.4%), 现实但有挑战.`;
  } else {
    levelLabel = '🟢 稳健';
  }
  const canSave = level !== 'reject';
  const needsConfirm = level === 'aggressive';
  const [confirmed, setConfirmed] = useState(false);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {/* 14k-25: 现实性 live preview */}
          <Box sx={{ p: 1.5, borderRadius: 1, bgcolor: `${levelColor}15`, border: `1px solid ${levelColor}55` }}>
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
              <Typography variant="body2" fontWeight={700}>难度等级:</Typography>
              <Chip label={levelLabel} size="small" sx={{ bgcolor: `${levelColor}33`, color: levelColor, fontWeight: 700 }} />
              <Box sx={{ flex: 1 }} />
              <Typography variant="caption" color="text.secondary">月化 ≈ {monthlyEq.toFixed(1)}%</Typography>
            </Stack>
            {warning && (
              <Typography variant="caption" sx={{ color: levelColor, display: 'block' }}>
                {warning}
              </Typography>
            )}
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 0.5, mt: 1, fontSize: 10 }}>
              <Box sx={{ textAlign: 'center', color: '#34d399' }}>≤15% 🟢</Box>
              <Box sx={{ textAlign: 'center', color: '#fbbf24' }}>15-30% 🟡</Box>
              <Box sx={{ textAlign: 'center', color: '#f87171' }}>30-50% 🔴</Box>
              <Box sx={{ textAlign: 'center', color: '#94a3b8' }}>{'>'}50% ⛔</Box>
            </Box>
          </Box>

          <Alert severity="info" sx={{ fontSize: 12 }}>
            <Typography variant="body2" fontWeight={700} sx={{ mb: 0.5 }}>🤖 启用后 AI 全权管理:</Typography>
            <Box component="ul" sx={{ pl: 2, m: 0, fontSize: 11.5, lineHeight: 1.6 }}>
              <li>自动启用<b>全自动智能驾驶</b> (AI 推荐 + 自动应用)</li>
              <li>自动开启<b>操作建议执行</b> (调参 / 暂停 / 退役 / fan-out / 上线)</li>
              <li>每小时跟踪进度, 落后 → 主动加策略</li>
              <li>回撤 ≥ {form.max_dd_pct}% → 自动 halt 全部新开仓</li>
              <li>单日亏 ≥ {form.daily_loss_halt_pct}% → 当日止血</li>
              <li>资金跨 $100/$500/$2000 → 自动扩张策略数</li>
              <li>每周日 复盘: 淘汰亏损 + 补新</li>
            </Box>
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
      <DialogActions sx={{ flexDirection: 'column', alignItems: 'stretch', gap: 1, px: 3, py: 2 }}>
        {needsConfirm && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <input
              type="checkbox"
              id="confirm-aggressive"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <Typography component="label" htmlFor="confirm-aggressive" variant="caption" sx={{ color: '#f87171', cursor: 'pointer' }}>
              我已理解月化 {monthlyEq.toFixed(0)}% 是激进目标, 停损会很频繁, 可能短期内频繁触发 DD halt
            </Typography>
          </Box>
        )}
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
          <Button onClick={onClose} disabled={busy}>取消</Button>
          <Button onClick={onSave} variant="contained"
                   disabled={busy || !canSave || (needsConfirm && !confirmed)}
                   sx={{ bgcolor: canSave ? PURPLE : 'grey.500' }}>
            {!canSave ? '超出上限, 不能保存' : (busy ? '保存中…' : '保存')}
          </Button>
        </Box>
      </DialogActions>
    </Dialog>
  );
}
