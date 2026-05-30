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
import { tierRank } from '../auth';

const PURPLE = '#a78bfa';
const TIER_RANK = { free: 0, basic: 1, pro: 2, team: 3 };
// HERO 卖点: 谁在替你驱动向目标 (tier 自适应)
function driverMeta(tier) {
  if (tier >= TIER_RANK.team) return { icon: '🧠', who: 'AI 经理', desc: 'AI 看行情+懂策略临场给参,守门员执行 · 实时判断见下方「AI 经理」台' };
  if (tier >= TIER_RANK.pro) return { icon: '🛡️', who: '守门员', desc: '按你在「系统设定」的参数自动扫描→回测→下单 · 控制见下方「守门员台」' };
  return { icon: '📡', who: '你自己', desc: '看下方「信号预告」手动跟单 (升级 Pro 解锁守门员自动)' };
}

export default function ProfitTargetCard() {
  const navigate = useNavigate();
  const [target, setTarget] = useState(null);
  const [needsTeam, setNeedsTeam] = useState(false);
  const [needsExchange, setNeedsExchange] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [form, setForm] = useState({ target_pct: 20, days: 30, max_dd_pct: 15, daily_loss_halt_pct: 5 });
  const [busy, setBusy] = useState(false);
  const [gkMode, setGkMode] = useState('off');   // Phase 15: 守门员 live 档 off/shadow/paper/live

  const refresh = useCallback(async () => {
    try {
      // 1. check Team tier (Phase 14k-23 升级后此 endpoint 要 Team, 14k-118 修变量名 needsPro→needsTeam)
      const r = await fetch('/api/me/profit-target');
      if (r.status === 402) {
        setNeedsTeam(true);
        return;
      }
      setNeedsTeam(false);
      const d = await r.json();
      setTarget(d.target);
      // Phase 15: 守门员 live 档
      const cfg = await fetch('/api/config').then(x => x.json()).catch(() => ({}));
      if (cfg && cfg.gatekeeper_live_mode) setGkMode(cfg.gatekeeper_live_mode);
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

  // Phase 15: 切守门员 live 档 (off/影子/纸面/真钱)
  const handleGkMode = async (mode) => {
    if (mode === 'live' && !window.confirm(
      '守门员真下单 (真钱)?\n\n• 实时扫描 ETH/AVAX, 信号触发→引擎回测达标→真下单 (原生 TP/SL)\n'
      + '• 现有策略让路 (守门员独占), 资金全给守门员\n• 首页 KILL SWITCH 可一键停\n\n确定?')) return;
    setBusy(true);
    try {
      const body = { gatekeeper_live_mode: mode };
      if (mode === 'live') body.confirm_gatekeeper_live = true;
      const r = await fetch('/api/config', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (r.ok) setGkMode(mode);
      else { const e = await r.json().catch(() => ({})); alert(e.error || '切换失败'); }
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
  if (needsTeam) {
    return (
      <Card sx={{ mb: 2, border: '1px dashed #fbbf24aa', bgcolor: 'rgba(251,191,36,0.04)' }}>
        <CardContent sx={{ py: 1.5, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <WorkspacePremiumIcon sx={{ color: '#fbbf24' }} />
          <Box sx={{ flex: 1, minWidth: { xs: 0, sm: 200 } }}>
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
          <Box sx={{ flex: 1, minWidth: { xs: 0, sm: 200 } }}>
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
            <Box sx={{ flex: 1, minWidth: { xs: 0, sm: 200 } }}>
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
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.75 }}>
            <TrackChangesIcon sx={{ color: PURPLE, fontSize: 20 }} />
            <Typography variant="subtitle1" fontWeight={700}>
              🎯 目标驱动
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
            <Tooltip title="暂停目标托管 (停止监控 / DD 保护 / 周轮换; 守门员/AI经理的实时交易在下方台单独控制)">
              <IconButton size="small" color="warning" onClick={handlePause} disabled={busy}>
                <PauseCircleIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>

          {/* HERO 卖点: 谁在替你驱动向目标 (tier 自适应) */}
          {(() => {
            const drv = driverMeta(tierRank());
            return (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 1.25, p: 0.75, borderRadius: 1, bgcolor: `${PURPLE}10` }}>
                <Typography sx={{ fontSize: 18 }}>{drv.icon}</Typography>
                <Typography variant="caption" sx={{ flex: 1 }}>
                  <b style={{ color: PURPLE }}>{drv.who}</b> 在替你开向目标 · <span style={{ color: 'text.secondary' }}>{drv.desc}</span>
                </Typography>
              </Box>
            );
          })()}

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
  // Phase 15: 难度判断改调后端 API (单一真相源 profit_difficulty, 不再前端本地写死阈值/文案)
  const [diff, setDiff] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    const tp = Number(form.target_pct), dy = Number(form.days);
    if (!tp || !dy || dy <= 0) { setDiff(null); return; }
    const h = setTimeout(() => {
      fetch('/api/me/profit-target/difficulty', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_pct: tp, days: dy }),
      }).then(r => r.json()).then(setDiff).catch(() => setDiff(null));
    }, 300);
    return () => clearTimeout(h);
  }, [form.target_pct, form.days]);
  const monthlyEq = diff?.monthly_eq ?? 0;
  const levelColor = diff?.color || '#34d399';
  const levelLabel = diff?.label || '🟢 稳健';
  const warning = diff?.warning || '';
  const canSave = diff ? diff.can_save : true;
  const needsConfirm = diff ? diff.needs_confirm : false;

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
