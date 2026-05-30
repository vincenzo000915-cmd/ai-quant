import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Card, CardContent, Button, Grid,
  Divider, Alert, Chip,
  TextField, InputAdornment, CircularProgress,
  Stack, Dialog, DialogTitle, DialogContent, DialogActions, List, ListItem, ListItemIcon, ListItemText,
  Accordion, AccordionSummary, AccordionDetails,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import ScienceIcon from '@mui/icons-material/Science';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import TuneIcon from '@mui/icons-material/Tune';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import SettingsSuggestIcon from '@mui/icons-material/SettingsSuggest';
import ExchangeBindingSection from '../components/ExchangeBindingSection';
import LlmBindingCard from '../components/LlmBindingCard';
import SizingAdvisorCard from '../components/SizingAdvisorCard';
import SubscriptionCard from '../components/SubscriptionCard';
import { PageSkeleton } from '../components/Skeleton';
import PageHeader from '../components/common/PageHeader';
import { tierRank } from '../auth';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import FlightTakeoffIcon from '@mui/icons-material/FlightTakeoff';
import { palette } from '../theme';

const API = process.env.REACT_APP_API_URL || '';

const _TIER_RANK = { free: 0, basic: 1, pro: 2, team: 3 };
// 参数文案随 tier: Team→AI经理覆盖 / Pro→守门员用你设的 / Basic→手动下单默认
// 含「参数影响战绩 + 拿不准就升级」的转化提示 (user 2026-05-30): Basic 强、Pro 中、Team 不提示.
function paramTierNote(tier) {
  if (tier >= _TIER_RANK.team) {
    return { sev: 'info', upgrade: null,
      text: '🧠 你是 Team — 下面这些是默认底线。AI 经理会按每一单的行情在「难度信封」内动态优化(杠杆 / 止损距离 / 多段止盈 / 分批 / 保证金),不用你逐单填。' };
  }
  if (tier >= _TIER_RANK.pro) {
    return { sev: 'success', upgrade: 'team', upgradeLabel: '升级 Team',
      text: '🛡️ 你是 Pro — 守门员就按你下面设的参数自动下单。⚠️ 这些参数直接影响盈利率和胜率,设错会反映在战绩上;拿不准可用上方「AI 推荐参数」,或升级 Team 让 AI 经理按行情逐单优化。' };
  }
  return { sev: 'warning', upgrade: 'pro', upgradeLabel: '升级 Pro / Team',
    text: '📡 你是 Basic — 下面是你手动下单的默认值,跟 AI 经理同一套参数模型。⚠️ 这些参数直接影响策略的盈利率和胜率。不确定怎么设?升级 Pro 让守门员按你的参数自动执行、Team 让 AI 经理按行情逐单优化 —— 把猜参数的活交给系统。' };
}

// === 核心交易参数 (镜像 AI 经理 ai_manager_params 输出 schema) ===
const PARAM_FIELDS = [
  { key: 'capital_usdt',        label: '账户本金',             unit: '$', step: 10, min: 1,           helper: '账户总资金。同步 Dashboard / Strategies 显示。' },
  { key: 'trade_size_usdt',     label: '每笔保证金 (margin)',  unit: '$', step: 1,  min: 0.1,         helper: '每次开仓投入的保证金。名义 = 保证金 × 杠杆。' },
  { key: 'leverage',            label: '杠杆倍数',             unit: 'x', step: 1,  min: 1, max: 100,  helper: '名义放大倍数。Team 经理按月目标难度自动给上限。' },
  { key: 'sl_price_pct',        label: '初始止损 · 价格距离%', unit: '%', step: 0.1, min: 0.1, max: 20, helper: '价格反向走多少% 触发止损(杠杆前)。= 经理 init_sl_pct。杠杆后 PnL ≈ 此值 × 杠杆。' },
  { key: 'max_daily_loss_usdt', label: '单日亏损上限',         unit: '$', step: 1,  min: 0,           helper: '单日累计亏损达此值触发风控暂停。' },
];
const PARAM_KEYS = PARAM_FIELDS.map(f => f.key);
const LADDER_KEYS = ['tp1_r', 'tp2_r', 'tp3_r', 'tp1_frac', 'tp2_frac'];
const SIZING_KEYS = ['sizing_mode', 'target_vol_pct', 'sizing_min_mult', 'sizing_max_mult', 'sl_mode', 'atr_period', 'atr_sl_mult', 'atr_tp_mult'];
const ALL_NUM_KEYS = [...PARAM_KEYS, ...LADDER_KEYS];

function SectionTitle({ icon, title, sub }) {
  return (
    <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mt: 4, mb: 1.5 }}>
      <Box sx={{ color: palette.accent, display: 'flex' }}>{icon}</Box>
      <Box>
        <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.1 }}>{title}</Typography>
        {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
      </Box>
    </Stack>
  );
}

export default function Settings() {
  const [cfg, setCfg] = useState(null);
  const [original, setOriginal] = useState(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/config`);
      const data = await r.json();
      setCfg(data);
      setOriginal(data);
    } catch (e) {
      setMsg({ type: 'error', text: `载入失败：${e.message}` });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const dirty = cfg && original && (
    ALL_NUM_KEYS.some(k => cfg[k] !== original[k]) ||
    cfg.trading_mode !== original?.trading_mode ||
    SIZING_KEYS.some(k => cfg[k] !== original?.[k])
  );

  const set = (key, raw) => {
    const v = raw === '' ? '' : Number(raw);
    setCfg(c => ({ ...c, [key]: v }));
  };

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    setMsg(null);
    try {
      const patch = {};
      for (const k of ALL_NUM_KEYS) {
        if (cfg[k] !== original[k] && cfg[k] !== '' && cfg[k] !== undefined) patch[k] = Number(cfg[k]);
      }
      if (cfg.trading_mode !== original.trading_mode) patch.trading_mode = cfg.trading_mode;
      for (const k of SIZING_KEYS) {
        if (cfg[k] !== original[k] && cfg[k] !== '' && cfg[k] !== undefined) {
          patch[k] = (k === 'sizing_mode' || k === 'sl_mode') ? cfg[k] : Number(cfg[k]);
        }
      }

      const r = await fetch(`${API}/api/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || JSON.stringify(body));
      setMsg({ type: 'success', text: `已保存。Celery 30 秒内 cache 过期、自动套用新值。` });
      setCfg(body);
      setOriginal(body);
    } catch (e) {
      setMsg({ type: 'error', text: `保存失败：${e.message}` });
    } finally {
      setSaving(false);
    }
  };

  if (!cfg) {
    return <PageSkeleton />;
  }

  const isLive = cfg.trading_mode === 'live';
  const tailFrac = Math.max(0, 1 - (Number(cfg.tp1_frac) || 0) - (Number(cfg.tp2_frac) || 0));
  const slLevPnl = (Number(cfg.sl_price_pct) || 0) * (Number(cfg.leverage) || 0);
  const notional = (Number(cfg.trade_size_usdt) || 0) * (Number(cfg.leverage) || 0);
  const maxLoss = notional * (Number(cfg.sl_price_pct) || 0) / 100;

  return (
    <Box>
      <PageHeader
        title="系统设置"
        subtitle={`${isLive ? 'LIVE 实盘' : 'PAPER 模拟'} · 杠杆 ${cfg.leverage}x · 每笔保证金 $${cfg.trade_size_usdt} · 止损 ${cfg.sl_price_pct}% 价距 · 修改即时生效（30s cache）`}
      />

      {msg && <Alert severity={msg.type} sx={{ mb: 2 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}

      {/* ============ 账户与连接 ============ */}
      <SectionTitle icon={<AccountBalanceWalletIcon />} title="账户与连接" sub="订阅 · 交易所绑定 · AI 模型 key" />
      <SubscriptionCard />
      <ExchangeBindingSection />
      <LlmBindingCard />

      {/* ============ 交易参数 (与 AI 经理对齐) ============ */}
      <SectionTitle icon={<TuneIcon />} title="交易参数 · 与 AI 经理对齐"
        sub="跟 AI 经理同一套语言:价格距离止损 + 多段 R 止盈 + 分批" />

      {(() => { const n = paramTierNote(tierRank()); return (
        <Alert severity={n.sev} sx={{ mb: 2 }}
          action={n.upgrade ? <Button color="inherit" size="small" onClick={() => { window.location.href = '/pricing'; }}>{n.upgradeLabel}</Button> : null}>
          {n.text}
        </Alert>
      ); })()}

      {/* AI 推荐参数 helper */}
      <SizingAdvisorCard onApplied={load} />

      {/* 核心参数 */}
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 2 }}>仓位 / 风险</Typography>
          <Grid container spacing={3}>
            {PARAM_FIELDS.map(f => (
              <Grid item xs={12} sm={6} key={f.key}>
                <TextField
                  fullWidth size="small" type="number"
                  label={f.label}
                  value={cfg[f.key] ?? ''}
                  onChange={(e) => set(f.key, e.target.value)}
                  inputProps={{ step: f.step, min: f.min, max: f.max }}
                  helperText={f.helper}
                  InputProps={f.unit === '$' ? { startAdornment: <InputAdornment position="start">$</InputAdornment> }
                    : f.unit === 'x' ? { endAdornment: <InputAdornment position="end">x</InputAdornment> }
                    : f.unit === '%' ? { endAdornment: <InputAdornment position="end">%</InputAdornment> } : {}}
                />
              </Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>

      {/* 多段止盈 + 分批 (镜像经理 tp1/2/3_r + tp1/2_frac) */}
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.5 }}>多段止盈 + 分批 (吃头中段不贪尾)</Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
            止盈位置用「R 倍数」= 初始止损价距的几倍。R=1 即赚回一个止损距离。每段平一部分仓,尾段留着跑趋势。
            跟 AI 经理 tp1/2/3_r + 分批比例同一套。
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={4}><TextField fullWidth size="small" type="number" label="TP1 · R" value={cfg.tp1_r ?? ''} onChange={e => set('tp1_r', e.target.value)} inputProps={{ step: 0.1, min: 0.1, max: 5 }} helperText="头档止盈位 (R)" /></Grid>
            <Grid item xs={4}><TextField fullWidth size="small" type="number" label="TP2 · R" value={cfg.tp2_r ?? ''} onChange={e => set('tp2_r', e.target.value)} inputProps={{ step: 0.1, min: 0.2, max: 8 }} helperText="中段止盈位 (R)" /></Grid>
            <Grid item xs={4}><TextField fullWidth size="small" type="number" label="TP3 · R" value={cfg.tp3_r ?? ''} onChange={e => set('tp3_r', e.target.value)} inputProps={{ step: 0.1, min: 0.3, max: 12 }} helperText="尾段止盈位 (R)" /></Grid>
            <Grid item xs={6}><TextField fullWidth size="small" type="number" label="TP1 平仓比例" value={cfg.tp1_frac ?? ''} onChange={e => set('tp1_frac', e.target.value)} inputProps={{ step: 0.05, min: 0.1, max: 0.7 }} helperText="头档平多少 (0.1~0.7)" InputProps={{ endAdornment: <InputAdornment position="end">×仓</InputAdornment> }} /></Grid>
            <Grid item xs={6}><TextField fullWidth size="small" type="number" label="TP2 平仓比例" value={cfg.tp2_frac ?? ''} onChange={e => set('tp2_frac', e.target.value)} inputProps={{ step: 0.05, min: 0.1, max: 0.7 }} helperText="中段平多少 (0.1~0.7)" InputProps={{ endAdornment: <InputAdornment position="end">×仓</InputAdornment> }} /></Grid>
          </Grid>
          <Alert severity={tailFrac < 0.15 ? 'warning' : 'info'} sx={{ mt: 2, py: 0.3 }}>
            {tailFrac < 0.15
              ? `⚠️ 尾段仅剩 ${(tailFrac * 100).toFixed(0)}% — 头+中段比例之和过大,保存时会被夹到尾段≥15%。`
              : `尾段(剩余)= ${(tailFrac * 100).toFixed(0)}% 留着跑趋势 (TP3 触发或反转平)。`}
          </Alert>
        </CardContent>
      </Card>

      {/* 实时预览 */}
      <Card sx={{ mb: 2, border: `1px solid ${palette.border}` }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1.5 }}>预览（套用后,以做多为例）</Typography>
          <Stack direction="row" spacing={1.5} sx={{ flexWrap: 'wrap', gap: 1, mb: 1.5 }}>
            <Chip label={`本金 $${cfg.capital_usdt}`} color="primary" variant="outlined" />
            <Chip label={`保证金 $${cfg.trade_size_usdt} (${(cfg.trade_size_usdt / cfg.capital_usdt * 100).toFixed(1)}%)`} color="success" variant="outlined" />
            <Chip label={`杠杆 ${cfg.leverage}x → 名义 $${notional.toFixed(0)}`} color="warning" variant="outlined" />
          </Stack>
          <Stack direction="row" spacing={1.5} sx={{ flexWrap: 'wrap', gap: 1 }}>
            <Chip label={`止损 -${cfg.sl_price_pct}% 价距 (杠杆后 ≈ -${slLevPnl.toFixed(1)}% PnL)`} sx={{ color: palette.error, borderColor: palette.error }} variant="outlined" />
            <Chip label={`TP1 +${(cfg.tp1_r * cfg.sl_price_pct).toFixed(2)}% 价 · 平${(cfg.tp1_frac * 100).toFixed(0)}%`} variant="outlined" />
            <Chip label={`TP2 +${(cfg.tp2_r * cfg.sl_price_pct).toFixed(2)}% 价 · 平${(cfg.tp2_frac * 100).toFixed(0)}%`} variant="outlined" />
            <Chip label={`TP3 +${(cfg.tp3_r * cfg.sl_price_pct).toFixed(2)}% 价 · 尾${(tailFrac * 100).toFixed(0)}%`} variant="outlined" />
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
            单笔最大可能损失：${maxLoss.toFixed(2)}（= 名义 × 止损价距%；杠杆放大已含在内）
          </Typography>
        </CardContent>
      </Card>

      <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
        <Button variant="contained" startIcon={saving ? <CircularProgress size={16} /> : <SaveIcon />}
          onClick={save} disabled={saving || !dirty}>
          {saving ? '保存中…' : (dirty ? '保存设置' : '无变更')}
        </Button>
        <Button variant="outlined" onClick={() => setCfg(original)} disabled={!dirty || saving}>重置</Button>
      </Stack>

      {/* ============ 高级 (默认折叠) ============ */}
      <SectionTitle icon={<SettingsSuggestIcon />} title="高级" sub="动态仓位 · ATR 自适应止损 · 交易模式" />

      <Accordion sx={{ mb: 1.5, bgcolor: 'transparent', border: `1px solid ${palette.border}` }} disableGutters>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2" fontWeight={700}>动态仓位 (Position Sizing)</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
            flat = 写死每笔。vol_target = 高波动减仓、低波动加仓,控制日 PnL 波动目标。sharpe_weighted = Sharpe 高的策略加大仓。
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}>
              <TextField select fullWidth size="small" SelectProps={{ native: true }} label="模式"
                value={cfg.sizing_mode || 'flat'}
                onChange={(e) => setCfg(c => ({ ...c, sizing_mode: e.target.value }))}>
                <option value="flat">flat (写死每笔)</option>
                <option value="vol_target">vol_target (波动目标)</option>
                <option value="sharpe_weighted">sharpe_weighted (Sharpe 加权)</option>
              </TextField>
            </Grid>
            <Grid item xs={6} sm={3}>
              <TextField fullWidth size="small" type="number" label="目标日波动 %"
                value={cfg.target_vol_pct ?? ''} onChange={(e) => setCfg(c => ({ ...c, target_vol_pct: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 0.1, max: 20 }} helperText="vol_target 用" disabled={cfg.sizing_mode !== 'vol_target'} />
            </Grid>
            <Grid item xs={6} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="min × base"
                value={cfg.sizing_min_mult ?? ''} onChange={(e) => setCfg(c => ({ ...c, sizing_min_mult: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 0.1, max: 1 }} helperText="夹在这之上" disabled={cfg.sizing_mode === 'flat'} />
            </Grid>
            <Grid item xs={6} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="max × base"
                value={cfg.sizing_max_mult ?? ''} onChange={(e) => setCfg(c => ({ ...c, sizing_max_mult: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 1, max: 10 }} helperText="夹在这之下" disabled={cfg.sizing_mode === 'flat'} />
            </Grid>
          </Grid>
        </AccordionDetails>
      </Accordion>

      <Accordion sx={{ mb: 1.5, bgcolor: 'transparent', border: `1px solid ${palette.border}` }} disableGutters>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2" fontWeight={700}>ATR 自适应止损</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
            flat_pct = 用上方的「价格距离%」止损(不管波动)。atr = 开仓时取 ATR(N),SL = entry ± k×ATR,TP 同理。高 vol 时停损更远、低 vol 更近。
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}>
              <TextField select fullWidth size="small" SelectProps={{ native: true }} label="止损模式"
                value={cfg.sl_mode || 'flat_pct'}
                onChange={(e) => setCfg(c => ({ ...c, sl_mode: e.target.value }))}>
                <option value="flat_pct">flat_pct (用价格距离%)</option>
                <option value="atr">atr (依波动)</option>
              </TextField>
            </Grid>
            <Grid item xs={4} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="ATR 周期"
                value={cfg.atr_period ?? ''} onChange={(e) => setCfg(c => ({ ...c, atr_period: Number(e.target.value) }))}
                inputProps={{ step: 1, min: 5, max: 200 }} disabled={cfg.sl_mode !== 'atr'} />
            </Grid>
            <Grid item xs={4} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="SL × ATR"
                value={cfg.atr_sl_mult ?? ''} onChange={(e) => setCfg(c => ({ ...c, atr_sl_mult: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 0.5, max: 10 }} helperText="停损距离 / ATR" disabled={cfg.sl_mode !== 'atr'} />
            </Grid>
            <Grid item xs={4} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="TP × ATR"
                value={cfg.atr_tp_mult ?? ''} onChange={(e) => setCfg(c => ({ ...c, atr_tp_mult: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 0.5, max: 20 }} helperText="止盈距离 / ATR" disabled={cfg.sl_mode !== 'atr'} />
            </Grid>
          </Grid>
        </AccordionDetails>
      </Accordion>

      {/* 交易模式 */}
      <Card sx={{ mb: 3, border: isLive ? `1px solid ${palette.error}` : `1px solid ${palette.border}` }}>
        <CardContent>
          <Stack direction="row" alignItems="center" spacing={2} sx={{ flexWrap: 'wrap', gap: 1, mb: 2 }}>
            <Typography variant="subtitle1" fontWeight={700}>交易模式</Typography>
            <Chip icon={isLive ? <WarningAmberIcon /> : <ScienceIcon />}
              label={isLive ? '🔴 LIVE 实盘' : '🟢 PAPER 模拟'}
              color={isLive ? 'error' : 'success'} variant="filled" />
            <Box sx={{ flexGrow: 1 }} />
            {!isLive ? (
              <PreflightUnlock onLiveActivated={async () => { await load(); }} />
            ) : (
              <Button variant="outlined" color="warning"
                onClick={async () => {
                  if (!window.confirm('切回 PAPER 模式？已开仓位继续管理（不平仓），但新信号改走模拟。')) return;
                  setSaving(true);
                  try {
                    const r = await fetch(`${API}/api/config`, {
                      method: 'PUT', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ trading_mode: 'paper' }),
                    });
                    const body = await r.json();
                    if (!r.ok) throw new Error(body.error || JSON.stringify(body));
                    setCfg(body); setOriginal(body);
                    setMsg({ type: 'success', text: '已切回 PAPER。' });
                  } catch (e) {
                    setMsg({ type: 'error', text: e.message });
                  } finally { setSaving(false); }
                }}>
                切回 PAPER
              </Button>
            )}
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            {isLive ?
              '⚠️ 实盘运行中。下单会真实发送到你绑定的交易所(永续合约)。Telegram 会推送每笔开平仓。' :
              '模拟盘：用真实价格 + 规则平仓,不发送真实下单。切 LIVE 需通过 pre-flight 检查。'}
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}


function PreflightUnlock({ onLiveActivated }) {
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [activating, setActivating] = useState(false);
  const [err, setErr] = useState(null);

  const runChecks = async () => {
    setRunning(true);
    setErr(null);
    try {
      const r = await fetch(`${API}/api/preflight`);
      const body = await r.json();
      setResult(body);
    } catch (e) {
      setErr(e.message);
    } finally {
      setRunning(false);
    }
  };

  const activate = async () => {
    if (!result?.ok) return;
    const final = window.prompt(
      `⚠️ 确定切到实盘？\n下单会用真金白银打交易所。\n\n输入大写 GO LIVE 确认：`,
    );
    if (final !== 'GO LIVE') {
      alert('未输入正确 phrase，已取消');
      return;
    }
    setActivating(true);
    try {
      const r = await fetch(`${API}/api/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trading_mode: 'live', confirm_live: true }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || JSON.stringify(body));
      setOpen(false);
      setResult(null);
      onLiveActivated && onLiveActivated();
    } catch (e) {
      setErr(e.message);
    } finally {
      setActivating(false);
    }
  };

  return (
    <>
      <Button variant="outlined" color="error" startIcon={<FlightTakeoffIcon />}
        onClick={() => { setOpen(true); setResult(null); setErr(null); }}>
        切实盘 (pre-flight)
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          <Stack direction="row" alignItems="center" spacing={1}>
            <FlightTakeoffIcon color="error" />
            <Typography variant="h6">切到 LIVE — Pre-flight 检查</Typography>
          </Stack>
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            点下方「跑检查」会打交易所 + Telegram 真实 API，确认凭证、权限、风控任务都备好。
            全绿才能切实盘。任何一条红都要先修。
          </Typography>
          {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}

          {!result && (
            <Button fullWidth variant="contained" onClick={runChecks} disabled={running}
              startIcon={running ? <CircularProgress size={16} /> : null}>
              {running ? '检查中…（10-30 秒）' : '跑检查'}
            </Button>
          )}

          {result && (
            <Box>
              <Alert severity={result.ok ? 'success' : 'warning'} sx={{ mb: 2 }}>
                {result.pass_count} / {result.total} 通过
                {result.ok ? ' — 可以切实盘' : ' — 仍有检查未通过'}
              </Alert>
              <List dense>
                {result.checks.map((c, i) => (
                  <ListItem key={i}>
                    <ListItemIcon sx={{ minWidth: 32 }}>
                      {c.ok ? <CheckCircleIcon color="success" fontSize="small" /> : <CancelIcon color="error" fontSize="small" />}
                    </ListItemIcon>
                    <ListItemText primary={c.name} secondary={c.message}
                      primaryTypographyProps={{ fontWeight: c.ok ? 500 : 700, color: c.ok ? 'text.primary' : 'error.main' }}
                      secondaryTypographyProps={{ fontSize: '0.75rem' }} />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>取消</Button>
          {result && (
            <>
              <Button onClick={runChecks} disabled={running}>重跑检查</Button>
              <Button variant="contained" color="error" disabled={!result.ok || activating}
                onClick={activate} startIcon={activating ? <CircularProgress size={16} /> : <FlightTakeoffIcon />}>
                {activating ? '切换中…' : '🚀 确定切实盘'}
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>
    </>
  );
}
