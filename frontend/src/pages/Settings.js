import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Card, CardContent, Button, Grid,
  Divider, Alert, Switch, FormControlLabel, Chip,
  TextField, InputAdornment, CircularProgress,
  Tooltip, Stack, Dialog, DialogTitle, DialogContent, DialogActions, List, ListItem, ListItemIcon, ListItemText,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import LockIcon from '@mui/icons-material/Lock';
import ScienceIcon from '@mui/icons-material/Science';
import OkxBindingCard from '../components/OkxBindingCard';
import LlmBindingCard from '../components/LlmBindingCard';
import SizingAdvisorCard from '../components/SizingAdvisorCard';
import SubscriptionCard from '../components/SubscriptionCard';
import { PageSkeleton } from '../components/Skeleton';
import PageHeader from '../components/common/PageHeader';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import FlightTakeoffIcon from '@mui/icons-material/FlightTakeoff';

const API = process.env.REACT_APP_API_URL || '';

const FIELDS = [
  { key: 'capital_usdt',         label: '模擬本金 (USDT)',       step: 10,   min: 1,    helper: '帳戶總資金。同步影響 Dashboard / Strategies 顯示。' },
  { key: 'trade_size_usdt',      label: '每筆下單金額 (USDT)',   step: 1,    min: 0.1,  helper: '每次開倉用多少本金。$100 切 10 份 → 填 10。' },
  { key: 'leverage',             label: '槓桿倍數',              step: 1,    min: 1,    max: 100, helper: '影響真實 PnL 放大倍數與名義倉位。' },
  { key: 'stop_loss_pct',        label: '止損 PnL %',            step: 0.5,  min: 0.5,  max: 50,  helper: '槓桿後 PnL% 觸發 — 5 = -5% PnL 平倉。' },
  { key: 'take_profit_pct',      label: '止盈 PnL %',            step: 0.5,  min: 0.5,  max: 200, helper: '槓桿後 PnL% 觸發 — 8 = +8% PnL 平倉。' },
  { key: 'max_daily_loss_usdt',  label: '單日虧損上限 (USDT)',   step: 1,    min: 0,    helper: '未啟用 — Phase 6 風控才生效。先填著當參考。' },
];

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
      setMsg({ type: 'error', text: `載入失敗：${e.message}` });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const SIZING_KEYS = ['sizing_mode', 'target_vol_pct', 'sizing_min_mult', 'sizing_max_mult', 'sl_mode', 'atr_period', 'atr_sl_mult', 'atr_tp_mult'];
  const dirty = cfg && original && (
    FIELDS.some(f => cfg[f.key] !== original[f.key]) ||
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
      for (const f of FIELDS) {
        if (cfg[f.key] !== original[f.key] && cfg[f.key] !== '') patch[f.key] = Number(cfg[f.key]);
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
      setMsg({ type: 'success', text: `已儲存。Celery 30 秒內 cache 過期、自動套用新值。` });
      setCfg(body);
      setOriginal(body);
    } catch (e) {
      setMsg({ type: 'error', text: `儲存失敗：${e.message}` });
    } finally {
      setSaving(false);
    }
  };

  if (!cfg) {
    return <PageSkeleton />;
  }

  const isLive = cfg.trading_mode === 'live';

  return (
    <Box>
      <PageHeader
        title="系统设置"
        subtitle={`${cfg.trading_mode === 'live' ? 'LIVE 实盘' : 'PAPER 模拟'} · 杠杆 ${cfg.leverage}x · 每笔 $${cfg.trade_size_usdt} · 修改即时生效（30s cache）`}
      />

      {msg && <Alert severity={msg.type} sx={{ mb: 2 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}

      {/* === Phase 12.24.3: 我的订阅 === */}
      <SubscriptionCard />

      {/* === Phase 11.2: OKX 綁定 (per-user) === */}
      <OkxBindingCard />

      {/* === Phase 11.5: LLM key 綁定 (BYO) === */}
      <LlmBindingCard />

      {/* === Phase 11.5.12: AI 推荐仓位 === */}
      <SizingAdvisorCard onApplied={load} />

      {/* === Trading Mode === */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Stack direction="row" alignItems="center" spacing={2} sx={{ flexWrap: 'wrap', gap: 1, mb: 2 }}>
            <Typography variant="subtitle1" fontWeight={700}>交易模式</Typography>
            <Chip
              icon={isLive ? <WarningAmberIcon /> : <ScienceIcon />}
              label={isLive ? '🔴 LIVE 實盤' : '🟢 PAPER 模擬'}
              color={isLive ? 'error' : 'success'}
              variant="filled"
            />
            <Box sx={{ flexGrow: 1 }} />
            {!isLive ? (
              <PreflightUnlock onLiveActivated={async () => { await load(); }} />
            ) : (
              <Button
                variant="outlined" color="warning"
                onClick={async () => {
                  if (!window.confirm('切回 PAPER 模式？已開倉位繼續管理（不平倉），但新信號改走模擬。')) return;
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
                }}
              >
                切回 PAPER
              </Button>
            )}
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            {isLive ?
              '⚠️ 實盤運行中。下單會真實發送到 OKX swap (BTC-USDT-SWAP, cross margin)。Telegram 會推送每筆開平倉。' :
              '模擬盤：用 OKX 真實價格 + 規則平倉，不發送真實下單。切 LIVE 需通過 pre-flight 檢查。'}
          </Typography>
        </CardContent>
      </Card>

      {/* === Numeric fields === */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 2 }}>倉位 / 風險參數</Typography>
          <Grid container spacing={3}>
            {FIELDS.map(f => (
              <Grid item xs={12} sm={6} key={f.key}>
                <TextField
                  fullWidth
                  size="small"
                  type="number"
                  label={f.label}
                  value={cfg[f.key] ?? ''}
                  onChange={(e) => set(f.key, e.target.value)}
                  inputProps={{ step: f.step, min: f.min, max: f.max }}
                  helperText={f.helper}
                  InputProps={f.key.endsWith('_usdt') ? { startAdornment: <InputAdornment position="start">$</InputAdornment> } : {}}
                />
              </Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>

      {/* === Phase 9.3: 動態倉位設定 === */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>動態倉位（Position Sizing）</Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
            flat = 寫死每筆。vol_target = 高波動時減倉、低波動時加倉，控制日 PnL 波動目標。sharpe_weighted = Sharpe 高的策略加大倉。
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}>
              <TextField
                select fullWidth size="small"
                SelectProps={{ native: true }}
                label="模式"
                value={cfg.sizing_mode || 'flat'}
                onChange={(e) => setCfg(c => ({ ...c, sizing_mode: e.target.value }))}
              >
                <option value="flat">flat (寫死每筆)</option>
                <option value="vol_target">vol_target (波動目標)</option>
                <option value="sharpe_weighted">sharpe_weighted (Sharpe 加權)</option>
              </TextField>
            </Grid>
            <Grid item xs={6} sm={3}>
              <TextField fullWidth size="small" type="number" label="目標日波動 %"
                value={cfg.target_vol_pct ?? ''}
                onChange={(e) => setCfg(c => ({ ...c, target_vol_pct: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 0.1, max: 20 }}
                helperText="vol_target 用"
                disabled={cfg.sizing_mode !== 'vol_target'}
              />
            </Grid>
            <Grid item xs={6} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="min × base"
                value={cfg.sizing_min_mult ?? ''}
                onChange={(e) => setCfg(c => ({ ...c, sizing_min_mult: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 0.1, max: 1 }}
                helperText="夾在這之上"
                disabled={cfg.sizing_mode === 'flat'}
              />
            </Grid>
            <Grid item xs={6} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="max × base"
                value={cfg.sizing_max_mult ?? ''}
                onChange={(e) => setCfg(c => ({ ...c, sizing_max_mult: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 1, max: 10 }}
                helperText="夾在這之下"
                disabled={cfg.sizing_mode === 'flat'}
              />
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* === Phase 9.4: 止損模式 === */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>止損 / 止盈模式</Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
            flat_pct = 用上方寫死的 SL/TP %（不管波動）。atr = 開倉時取 ATR(N)，SL = entry ± k×ATR，TP 同理。高 vol 時停損更遠，低 vol 時更近。
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}>
              <TextField select fullWidth size="small" SelectProps={{ native: true }}
                label="止損模式"
                value={cfg.sl_mode || 'flat_pct'}
                onChange={(e) => setCfg(c => ({ ...c, sl_mode: e.target.value }))}>
                <option value="flat_pct">flat_pct (寫死 %)</option>
                <option value="atr">atr (依波動)</option>
              </TextField>
            </Grid>
            <Grid item xs={4} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="ATR 週期"
                value={cfg.atr_period ?? ''}
                onChange={(e) => setCfg(c => ({ ...c, atr_period: Number(e.target.value) }))}
                inputProps={{ step: 1, min: 5, max: 200 }}
                disabled={cfg.sl_mode !== 'atr'}
              />
            </Grid>
            <Grid item xs={4} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="SL × ATR"
                value={cfg.atr_sl_mult ?? ''}
                onChange={(e) => setCfg(c => ({ ...c, atr_sl_mult: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 0.5, max: 10 }}
                helperText="停損距離 / ATR"
                disabled={cfg.sl_mode !== 'atr'}
              />
            </Grid>
            <Grid item xs={4} sm={2.5}>
              <TextField fullWidth size="small" type="number" label="TP × ATR"
                value={cfg.atr_tp_mult ?? ''}
                onChange={(e) => setCfg(c => ({ ...c, atr_tp_mult: Number(e.target.value) }))}
                inputProps={{ step: 0.1, min: 0.5, max: 20 }}
                helperText="止盈距離 / ATR"
                disabled={cfg.sl_mode !== 'atr'}
              />
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* === Computed preview === */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>預覽（套用後）</Typography>
          <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', gap: 1 }}>
            <Chip label={`本金 $${cfg.capital_usdt}`} color="primary" variant="outlined" />
            <Chip label={`每筆 $${cfg.trade_size_usdt} (${(cfg.trade_size_usdt / cfg.capital_usdt * 100).toFixed(1)}%)`} color="success" variant="outlined" />
            <Chip label={`槓桿 ${cfg.leverage}x`} color="warning" variant="outlined" />
            <Chip label={`名義 $${(cfg.trade_size_usdt * cfg.leverage).toFixed(0)}/筆`} variant="outlined" />
            <Chip label={`SL -${cfg.stop_loss_pct}% / TP +${cfg.take_profit_pct}%`} variant="outlined" />
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
            單筆最大可能損失：${(cfg.trade_size_usdt * cfg.stop_loss_pct / 100).toFixed(2)}
            （槓桿放大已包含在 SL/TP 百分比裡）
          </Typography>
        </CardContent>
      </Card>

      <Stack direction="row" spacing={2}>
        <Button
          variant="contained"
          startIcon={saving ? <CircularProgress size={16} /> : <SaveIcon />}
          onClick={save}
          disabled={saving || !dirty}
        >
          {saving ? '儲存中…' : (dirty ? '儲存設定' : '無變更')}
        </Button>
        <Button
          variant="outlined"
          onClick={() => setCfg(original)}
          disabled={!dirty || saving}
        >
          重置
        </Button>
      </Stack>
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
      `⚠️ 確定切到實盤？\n下單會用真金白銀打 OKX。\n\n輸入大寫 GO LIVE 確認：`,
    );
    if (final !== 'GO LIVE') {
      alert('未輸入正確 phrase，已取消');
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
      <Button
        variant="outlined"
        color="error"
        startIcon={<FlightTakeoffIcon />}
        onClick={() => { setOpen(true); setResult(null); setErr(null); }}
      >
        切實盤 (pre-flight)
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          <Stack direction="row" alignItems="center" spacing={1}>
            <FlightTakeoffIcon color="error" />
            <Typography variant="h6">切到 LIVE — Pre-flight 檢查</Typography>
          </Stack>
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            點下方「跑檢查」會打 OKX + Telegram 真實 API，確認憑證、權限、風控任務都備好。
            全綠才能切實盤。任何一條紅都要先修。
          </Typography>
          {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}

          {!result && (
            <Button
              fullWidth
              variant="contained"
              onClick={runChecks}
              disabled={running}
              startIcon={running ? <CircularProgress size={16} /> : null}
            >
              {running ? '檢查中…（10-30 秒）' : '跑檢查'}
            </Button>
          )}

          {result && (
            <Box>
              <Alert severity={result.ok ? 'success' : 'warning'} sx={{ mb: 2 }}>
                {result.pass_count} / {result.total} 通過
                {result.ok ? ' — 可以切實盤' : ' — 仍有檢查未通過'}
              </Alert>
              <List dense>
                {result.checks.map((c, i) => (
                  <ListItem key={i}>
                    <ListItemIcon sx={{ minWidth: 32 }}>
                      {c.ok ? <CheckCircleIcon color="success" fontSize="small" /> : <CancelIcon color="error" fontSize="small" />}
                    </ListItemIcon>
                    <ListItemText
                      primary={c.name}
                      secondary={c.message}
                      primaryTypographyProps={{ fontWeight: c.ok ? 500 : 700, color: c.ok ? 'text.primary' : 'error.main' }}
                      secondaryTypographyProps={{ fontSize: '0.75rem' }}
                    />
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
              <Button onClick={runChecks} disabled={running}>重跑檢查</Button>
              <Button
                variant="contained"
                color="error"
                disabled={!result.ok || activating}
                onClick={activate}
                startIcon={activating ? <CircularProgress size={16} /> : <FlightTakeoffIcon />}
              >
                {activating ? '切換中…' : '🚀 確定切實盤'}
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>
    </>
  );
}
