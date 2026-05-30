// Phase 15 UI 重构: 守门员驾驶舱 — 信号预告 + 守门员台(Pro) + AI经理台(Team) + 策略库 + 飞轮
// 规格 project-ui-redesign-spec. tier 分层 (Basic/Pro/Team), 手机响应式.
import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Stack, Chip, Grid, Button, Tooltip, LinearProgress,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField, ToggleButton, ToggleButtonGroup,
} from '@mui/material';
import RadarIcon from '@mui/icons-material/Radar';
import ShieldIcon from '@mui/icons-material/Shield';
import PsychologyIcon from '@mui/icons-material/Psychology';
import InventoryIcon from '@mui/icons-material/Inventory2';
import AutoGraphIcon from '@mui/icons-material/AutoGraph';
import LockIcon from '@mui/icons-material/Lock';
import { palette } from '../theme';
import { tierRank } from '../auth';

const API = process.env.REACT_APP_API_URL || '';
const TIER_RANK = { free: 0, basic: 1, pro: 2, team: 3 };
const GK_MODES = [['off', '关'], ['shadow', '影子'], ['paper', '纸面'], ['live', '真钱']];

function Section({ icon, title, accent, chip, children, sx }) {
  return (
    <Box className="glass-card" sx={{ p: { xs: 1.5, sm: 2.25 }, mb: 2, position: 'relative', overflow: 'hidden', ...sx }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.25 }}>
        {icon}
        <Typography variant="subtitle1" fontWeight={700} sx={{ color: accent || palette.accent }}>{title}</Typography>
        {chip}
      </Stack>
      {children}
    </Box>
  );
}

export default function GatekeeperCockpit() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [orderDlg, setOrderDlg] = useState(null);   // {symbol, side, size_usdt, leverage}
  const tier = tierRank();
  const hasGatekeeper = tier >= TIER_RANK.pro;   // Pro+
  const hasManager = tier >= TIER_RANK.team;     // Team

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/gatekeeper/dashboard`);
      if (r.ok) setData(await r.json());
    } catch {}
  }, []);
  useEffect(() => { refresh(); const t = setInterval(refresh, 30000); return () => clearInterval(t); }, [refresh]);

  const setGkMode = async (mode) => {
    if (mode === 'live' && !window.confirm('守门员真下单 (真钱)?\n实时扫描→引擎回测达标→真下单 (原生 TP/SL).\n现有策略让路, KILL 可一键停.\n确定?')) return;
    setBusy(true);
    try {
      const body = { gatekeeper_live_mode: mode };
      if (mode === 'live') body.confirm_gatekeeper_live = true;
      const r = await fetch(`${API}/api/config`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!r.ok) { const e = await r.json().catch(() => ({})); alert(e.error || '切换失败'); }
      await refresh();
    } finally { setBusy(false); }
  };

  const [synthMsg, setSynthMsg] = useState(null);
  const synthesize = async () => {
    setBusy(true); setSynthMsg(null);
    try {
      const r = await fetch(`${API}/api/gatekeeper/synthesize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const j = await r.json().catch(() => ({}));
      setSynthMsg(r.ok ? { ok: true, text: j.message || '已派发合成任务' } : { ok: false, text: j.error || '触发失败' });
    } finally { setBusy(false); }
  };

  const submitOrder = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/manual-order`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(orderDlg) });
      const j = await r.json().catch(() => ({}));
      if (r.ok) { alert(`已下单 @ ${j.entry} (SL ${j.sl?.toFixed?.(2)} / TP ${j.tp?.toFixed?.(2)})${j.simulated ? ' [模拟]' : ''}`); setOrderDlg(null); }
      else alert(j.error || '下单失败');
    } finally { setBusy(false); }
  };

  if (!data) return <Box sx={{ mb: 2 }}><LinearProgress sx={{ height: 2, bgcolor: palette.border, '& .MuiLinearProgress-bar': { bgcolor: palette.accent } }} /></Box>;

  const gkMode = data.gatekeeper?.mode || 'off';
  const REG = { range: '震荡', trend: '趋势', unknown: '未知' };
  const DIR = { up: '偏多', down: '偏空', flat: '横盘' };

  return (
    <>
      {/* === 📡 信号预告 (全 tier, Basic 核心) === */}
      <Section icon={<RadarIcon sx={{ color: palette.accent }} />} title="信号预告 · 当下行情即将触发什么"
        chip={<Chip size="small" label="实时" sx={{ height: 18, fontSize: 10, bgcolor: `${palette.accent}22`, color: palette.accent }} />}>
        <Grid container spacing={1.5}>
          {(data.signal_preview || []).map((s) => (
            <Grid item xs={12} md={6} key={s.symbol}>
              <Box sx={{ p: 1.25, borderRadius: 1, bgcolor: 'rgba(255,255,255,0.02)', border: `1px solid ${palette.border}` }}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.75 }}>
                  <Typography fontWeight={700}>{s.symbol?.split('/')[0]}</Typography>
                  {s.ok ? <>
                    <Chip size="small" label={`${REG[s.regime] || s.regime} / ${DIR[s.direction] || s.direction}`} sx={{ height: 18, fontSize: 10 }} />
                    <Chip size="small" label={`波动${s.volatility} 量${s.volume}`} variant="outlined" sx={{ height: 18, fontSize: 10 }} />
                  </> : <Typography variant="caption" color="text.secondary">{s.reason}</Typography>}
                </Stack>
                {s.ok && (s.matched || []).map((m) => (
                  <Stack key={m.strategy} direction="row" alignItems="center" spacing={0.75} sx={{ py: 0.25 }}>
                    <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: m.triggering ? palette.success : palette.border, boxShadow: m.triggering ? `0 0 6px ${palette.success}` : 'none' }} />
                    <Typography variant="caption" sx={{ flex: 1 }}>
                      <b>{m.name}</b> {m.triggering ? <span style={{ color: palette.success }}>· 即将触发 {m.side}</span> : <span style={{ color: palette.textMuted }}>· 配对分 {m.score}</span>}
                    </Typography>
                    {m.triggering && !hasGatekeeper && (
                      <Button size="small" variant="outlined" sx={{ minWidth: 0, px: 1, py: 0, fontSize: 10 }}
                        onClick={() => setOrderDlg({ symbol: s.symbol, side: m.side === '做多' ? 'long' : 'short', size_usdt: 10, leverage: 5 })}>手动跟单</Button>
                    )}
                  </Stack>
                ))}
                {s.ok && (s.matched || []).length === 0 && <Typography variant="caption" color="text.secondary">当下无匹配策略 (空仓等机会)</Typography>}
              </Box>
            </Grid>
          ))}
        </Grid>
        {!hasGatekeeper && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>💡 你是 Basic — 看到"即将触发"可手动跟单。升级 Pro 解锁守门员自动执行。</Typography>}
      </Section>

      {/* === 🛡️ 守门员实时托管 (Pro+) === */}
      {hasGatekeeper && (
        <Section icon={<ShieldIcon sx={{ color: '#00d4aa' }} />} title="守门员实时托管" accent="#00d4aa"
          chip={gkMode === 'live' ? <Chip size="small" label="真钱运行中" color="error" sx={{ height: 18, fontSize: 10 }} /> : null}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ alignItems: { sm: 'center' } }}>
            <ToggleButtonGroup size="small" exclusive value={gkMode} onChange={(e, v) => v && setGkMode(v)} disabled={busy}>
              {GK_MODES.map(([m, l]) => <ToggleButton key={m} value={m} sx={{ px: 1.5, py: 0.3, fontSize: 12, ...(gkMode === m && m === 'live' ? { color: '#fff', bgcolor: '#f87171 !important' } : {}) }}>{l}</ToggleButton>)}
            </ToggleButtonGroup>
            <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>
              扫 {(data.gatekeeper?.watched || []).map(x => x.split('/')[0]).join('/')} · {data.gatekeeper?.library_size} 策略库 · 持仓 {data.gatekeeper?.open_count}
            </Typography>
          </Stack>
          {(data.hero?.open_positions || []).length > 0 && (
            <Box sx={{ mt: 1 }}>
              {data.hero.open_positions.map((p, i) => (
                <Typography key={i} variant="caption" sx={{ display: 'block' }}>
                  🔹 {p.symbol?.split('/')[0]} {p.side} · {p.strategy} · 浮盈 <b style={{ color: (p.unrealized_pnl || 0) >= 0 ? palette.success : palette.error }}>{(p.unrealized_pnl || 0) >= 0 ? '+' : ''}{(p.unrealized_pnl || 0).toFixed(3)}</b>
                </Typography>
              ))}
            </Box>
          )}
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>
            打法: 锁 TP 台阶、吃头中段不贪尾 · 参数{hasManager ? ' 由 AI 经理给' : '在「系统设定」自设'}
          </Typography>
        </Section>
      )}

      {/* AI 经理判断流已并入顶部「目标驱动」卡 (同一个 AI 经理, 不拆两块). Pro 升级提示见守门员台. */}

      {/* === 📦 策略库 + 覆盖 === */}
      <Section icon={<InventoryIcon sx={{ color: palette.accent }} />} title={`策略库 · ${data.library?.count} 个模版`}
        chip={hasGatekeeper ? (
          <Button size="small" variant="outlined" disabled={busy} onClick={synthesize}
            sx={{ minWidth: 0, px: 1.25, py: 0.1, fontSize: 11, ml: 'auto' }}>
            🧬 合成补库
          </Button>
        ) : null}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>守门员从这个库按行情匹配策略 (regime×周期覆盖):</Typography>
        {synthMsg && <Typography variant="caption" sx={{ display: 'block', mb: 1, color: synthMsg.ok ? palette.success : palette.error }}>{synthMsg.text}</Typography>}
        <Grid container spacing={0.5}>
          {['trend', 'range'].map((reg) => ['5m', '15m', '1h', '4h'].map((tf) => {
            const n = (data.library?.coverage?.[reg]?.[tf] || []).length;
            const thin = n < 3; const core = tf === '5m' || tf === '15m';
            return (
              <Grid item xs={3} key={`${reg}-${tf}`}>
                <Box sx={{ p: 0.5, textAlign: 'center', borderRadius: 0.5, bgcolor: n === 0 ? `${palette.error}18` : thin ? `${palette.warning || '#f59e0b'}18` : `${palette.success}12`, border: core ? `1px solid ${palette.accent}55` : 'none' }}>
                  <Typography variant="caption" sx={{ fontSize: 9, display: 'block', color: palette.textMuted }}>{REG[reg]}/{tf}{core ? '★' : ''}</Typography>
                  <Typography variant="caption" fontWeight={700}>{n}</Typography>
                </Box>
              </Grid>
            );
          }))}
        </Grid>
        {(data.library?.core_thin || []).length > 0 && <Typography variant="caption" sx={{ color: palette.accent, display: 'block', mt: 0.75 }}>🎯 核心 5m/15m 维度薄弱 → 合成飞轮优先补这里</Typography>}
      </Section>

      {/* === 🔄 学习飞轮 === */}
      <Section icon={<AutoGraphIcon sx={{ color: palette.accent }} />} title="学习飞轮 · 什么策略 × 什么市场 → 真EV">
        {(data.flywheel || []).length > 0 ? (data.flywheel || []).map((e, i) => (
          <Stack key={i} direction="row" alignItems="center" spacing={1} sx={{ py: 0.3 }}>
            <Typography variant="caption" sx={{ flex: 1 }}>{e.strategy} @ {REG[e.regime] || e.regime}/{e.timeframe}</Typography>
            <Typography variant="caption" sx={{ color: (e.avg_realized_pnl || 0) >= 0 ? palette.success : palette.error }}>实测均 {(e.avg_realized_pnl || 0) >= 0 ? '+' : ''}{e.avg_realized_pnl} · 胜率{(e.win_rate * 100).toFixed(0)}% (n={e.samples})</Typography>
          </Stack>
        )) : <Typography variant="caption" color="text.secondary">飞轮在积累中 — 守门员每笔真盈亏决策都记录,攒够后整合写更好的策略。</Typography>}
      </Section>

      {/* 手动下单 dialog (Basic) */}
      <Dialog open={!!orderDlg} onClose={() => setOrderDlg(null)} maxWidth="xs" fullWidth>
        <DialogTitle>手动下单</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2"><b>{orderDlg?.symbol}</b> · {orderDlg?.side === 'long' ? '做多 🔺' : '做空 🔻'}</Typography>
            <TextField label="仓位 (USDT 保证金)" type="number" size="small" value={orderDlg?.size_usdt || ''} onChange={(e) => setOrderDlg({ ...orderDlg, size_usdt: parseFloat(e.target.value) })} />
            <TextField label="杠杆" type="number" size="small" value={orderDlg?.leverage || ''} onChange={(e) => setOrderDlg({ ...orderDlg, leverage: parseFloat(e.target.value) })} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOrderDlg(null)}>取消</Button>
          <Button variant="contained" disabled={busy} onClick={submitOrder}>确认下单</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
