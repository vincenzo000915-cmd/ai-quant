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
import TouchAppIcon from '@mui/icons-material/TouchApp';
import { palette } from '../theme';
import { tierRank, getUser } from '../auth';

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
  const [cfg, setCfg] = useState(null);   // 系统设定 (手动执行用这套对齐参数)
  const [busy, setBusy] = useState(false);
  const [orderDlg, setOrderDlg] = useState(null);   // {symbol, side, size_usdt, leverage}
  const tier = tierRank();
  const hasGatekeeper = tier >= TIER_RANK.pro;   // Pro+
  const hasManager = tier >= TIER_RANK.team;     // Team
  const [hasLlmKey, setHasLlmKey] = useState(true);  // 绑了 LLM key → 经理判断壳上线 (admin claude_cli 视为有)

  const refresh = useCallback(async () => {
    try {
      const [r, rc] = await Promise.all([
        fetch(`${API}/api/gatekeeper/dashboard`),
        fetch(`${API}/api/config`),
      ]);
      if (r.ok) setData(await r.json());
      if (rc.ok) setCfg(await rc.json());
      // 经理是不是真上线 = 绑没绑 key (新架构: 不再只看 tier; Pro 绑了 key 也有经理)
      const isAdmin = (getUser()?.role === 'admin');
      const llm = await fetch(`${API}/api/me/llm`).then(x => x.json()).catch(() => ({}));
      setHasLlmKey(isAdmin || Object.keys(llm.bound || {}).length > 0);
    } catch {}
  }, []);
  useEffect(() => { refresh(); const t = setInterval(refresh, 30000); return () => clearInterval(t); }, [refresh]);

  // 用系统设定预填手动单 (杠杆/保证金来自「系统设定」, 不再写死 10/5)
  const openManual = (symbol, side) => setOrderDlg({
    symbol, side,
    size_usdt: cfg?.trade_size_usdt ?? 10,
    leverage: cfg?.leverage ?? 5,
  });

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
                    {m.triggering && gkMode === 'off' && (
                      <Button size="small" variant="outlined" sx={{ minWidth: 0, px: 1, py: 0, fontSize: 10 }}
                        onClick={() => openManual(s.symbol, m.side === '做多' ? 'long' : 'short')}>手动跟单</Button>
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

      {/* === ✋ 手动执行 · 用你的设定下单 (守门员一开就锁) === */}
      {(() => {
        const locked = gkMode !== 'off';   // 守门员运行中 → 手动锁定
        const slp = Number(cfg?.sl_price_pct ?? 1);
        const tp1pct = (Number(cfg?.tp1_r ?? 0.5) * slp);
        const triggers = [];
        (data.signal_preview || []).forEach((s) => s.ok && (s.matched || []).forEach((m) => {
          if (m.triggering) triggers.push({ symbol: s.symbol, name: m.name, side: m.side });
        }));
        return (
          <Section icon={<TouchAppIcon sx={{ color: palette.accent }} />} title="手动执行 · 用你的设定下单"
            chip={locked ? <Chip size="small" icon={<LockIcon sx={{ fontSize: 12 }} />} label="守门员托管中" sx={{ height: 18, fontSize: 10, bgcolor: '#00d4aa22', color: '#00d4aa' }} />
              : <Chip size="small" label="可手动" sx={{ height: 18, fontSize: 10, bgcolor: `${palette.accent}22`, color: palette.accent }} />}>
            {/* 这一单会用到的参数 (来自系统设定, 对齐 AI 经理那套) */}
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.75, mb: 1 }}>
              <Chip size="small" variant="outlined" label={`杠杆 ${cfg?.leverage ?? '—'}x`} />
              <Chip size="small" variant="outlined" label={`保证金 $${cfg?.trade_size_usdt ?? '—'}`} />
              <Chip size="small" variant="outlined" label={`止损 -${slp}% 价距`} sx={{ color: palette.error, borderColor: palette.error }} />
              <Chip size="small" variant="outlined" label={`止盈 +${tp1pct.toFixed(2)}% (TP1)`} />
              <Tooltip title="在「系统设定 → 交易参数」改这套默认值"><Chip size="small" label="改参数" onClick={() => { window.location.href = '/settings'; }} sx={{ height: 22, fontSize: 11, cursor: 'pointer', bgcolor: `${palette.accent}18`, color: palette.accent }} /></Tooltip>
            </Stack>
            {locked ? (
              <Box sx={{ p: 1.5, borderRadius: 1, bgcolor: 'rgba(0,212,170,0.06)', border: '1px dashed rgba(0,212,170,0.4)' }}>
                <Typography variant="caption" sx={{ color: '#00d4aa' }}>
                  🛡️ 守门员托管中,手动执行已锁定 —— 避免你和守门员同时对同一账户下单打架。把守门员切到「关」即可恢复手动。
                </Typography>
              </Box>
            ) : triggers.length > 0 ? (
              <Stack spacing={0.75}>
                {triggers.map((t, i) => (
                  <Stack key={i} direction="row" alignItems="center" spacing={1} sx={{ p: 0.75, borderRadius: 1, bgcolor: 'rgba(255,255,255,0.02)', border: `1px solid ${palette.border}` }}>
                    <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: palette.success, boxShadow: `0 0 6px ${palette.success}` }} />
                    <Typography variant="caption" sx={{ flex: 1 }}><b>{t.symbol?.split('/')[0]}</b> · {t.name} · <span style={{ color: t.side === '做多' ? palette.success : palette.error }}>{t.side}</span></Typography>
                    <Button size="small" variant="contained" sx={{ minWidth: 0, px: 1.25, py: 0.2, fontSize: 11 }}
                      onClick={() => openManual(t.symbol, t.side === '做多' ? 'long' : 'short')}>执行</Button>
                  </Stack>
                ))}
              </Stack>
            ) : (
              <Typography variant="caption" color="text.secondary">当前无触发信号 — 空仓等机会。也可在上方「信号预告」看配对进度。</Typography>
            )}
          </Section>
        );
      })()}

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
            打法: 锁 TP 台阶、吃头中段不贪尾 · 参数{hasLlmKey ? ' 由 AI 经理逐单给(你的 LLM key)' : ' 走机械技能(感知+EV闸)按你「系统设定」择参'}
          </Typography>
          {!hasLlmKey && (
            <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: palette.accent, cursor: 'pointer' }}
              onClick={() => { window.location.href = '/settings'; }}>
              🔑 绑定你自己的 LLM key → 解锁 AI 经理逐单临场判断(更聪明)。没绑也照跑机械技能,不影响下单。
            </Typography>
          )}
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

      {/* === 🔄 学习飞轮 (进度感, 不露具体策略edge — moat) === */}
      <Section icon={<AutoGraphIcon sx={{ color: palette.accent }} />} title="学习飞轮 · 越用越聪明">
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.25 }}>
          守门员每一笔决策都在学 — 记下预期、平仓后回填真实盈亏、提炼出"什么有用",再喂回去写更好的策略。这是会复利的护城河。
        </Typography>
        <Grid container spacing={1}>
          {[
            { label: '已学习决策', value: data.learning?.decisions_total ?? 0, sub: `真钱 ${data.learning?.live_decisions ?? 0}` },
            { label: '已结算回填', value: data.learning?.settled ?? 0, sub: '真实盈亏入账' },
            { label: '整体胜率', value: data.learning?.win_rate != null ? `${data.learning.win_rate}%` : '—', sub: '攒越多越准' },
            { label: '提炼经验', value: data.learning?.patterns ?? 0, sub: '个有效模式' },
          ].map((s) => (
            <Grid item xs={6} sm={3} key={s.label}>
              <Box sx={{ p: 1, borderRadius: 1, bgcolor: 'rgba(255,255,255,0.02)', border: `1px solid ${palette.border}`, textAlign: 'center' }}>
                <Typography variant="h6" fontWeight={800} sx={{ color: palette.accent, lineHeight: 1.2 }}>{s.value}</Typography>
                <Typography variant="caption" sx={{ display: 'block', fontWeight: 600 }}>{s.label}</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: 10 }}>{s.sub}</Typography>
              </Box>
            </Grid>
          ))}
        </Grid>
        {(data.learning?.settled ?? 0) < 10 && (
          <Typography variant="caption" sx={{ color: palette.accent, display: 'block', mt: 1 }}>🌱 还在早期积累 — 样本越多,守门员的判断越聪明。</Typography>
        )}
      </Section>

      {/* 手动下单 dialog (Basic) */}
      <Dialog open={!!orderDlg} onClose={() => setOrderDlg(null)} maxWidth="xs" fullWidth>
        <DialogTitle>手动下单</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2"><b>{orderDlg?.symbol}</b> · {orderDlg?.side === 'long' ? '做多 🔺' : '做空 🔻'}</Typography>
            <TextField label="仓位 (USDT 保证金)" type="number" size="small" value={orderDlg?.size_usdt || ''} onChange={(e) => setOrderDlg({ ...orderDlg, size_usdt: parseFloat(e.target.value) })} />
            <TextField label="杠杆" type="number" size="small" value={orderDlg?.leverage || ''} onChange={(e) => setOrderDlg({ ...orderDlg, leverage: parseFloat(e.target.value) })} />
            <Typography variant="caption" color="text.secondary">
              止损 / 止盈按「系统设定」自动挂:止损 -{Number(cfg?.sl_price_pct ?? 1)}% 价距 · 止盈 +{(Number(cfg?.tp1_r ?? 0.5) * Number(cfg?.sl_price_pct ?? 1)).toFixed(2)}% (TP1 先落袋)。
              名义 ≈ ${((orderDlg?.size_usdt || 0) * (orderDlg?.leverage || 0)).toFixed(0)}。
            </Typography>
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
