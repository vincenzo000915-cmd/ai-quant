// Phase 14j-4: 单 user 详情页 + admin 操作 (改 tier / 封号)

import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box, Card, CardContent, Typography, Grid, Chip, Button, Stack, Tabs, Tab,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper,
  Select, MenuItem, FormControl, InputLabel, Switch, FormControlLabel, Alert,
  Snackbar, IconButton, Tooltip,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import RefreshIcon from '@mui/icons-material/Refresh';
import PageHeader from '../components/common/PageHeader';
import { prettifyType } from '../utils/strategyTypeLabels';

const API = process.env.REACT_APP_API_URL || '';

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

export default function AdminUserDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [tab, setTab] = useState(0);
  const [snack, setSnack] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/admin/users/${id}`);
      if (r.ok) setData(await r.json());
    } catch {}
  }, [id]);

  useEffect(() => { refresh(); }, [refresh]);

  const handleTierChange = async (newTier) => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/admin/users/${id}/tier`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: newTier }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) throw new Error(body.error || 'failed');
      setSnack({ severity: 'success', msg: `tier 改为 ${newTier}` });
      refresh();
    } catch (e) {
      setSnack({ severity: 'error', msg: e.message });
    } finally {
      setBusy(false);
    }
  };

  const handleToggleActive = async (next) => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/admin/users/${id}/toggle-active`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: next }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) throw new Error(body.error || 'failed');
      setSnack({ severity: 'success', msg: next ? '已启用' : '已封停' });
      refresh();
    } catch (e) {
      setSnack({ severity: 'error', msg: e.message });
    } finally {
      setBusy(false);
    }
  };

  if (!data) return (
    <Box sx={{ p: 4, textAlign: 'center' }}>
      <Typography color="text.secondary">加载中…</Typography>
    </Box>
  );

  const { user, subscription, bindings, stats, strategies, recent_trades } = data;

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <IconButton size="small" onClick={() => navigate('/admin/users')}>
          <ArrowBackIcon />
        </IconButton>
        <PageHeader title={`🛡️ ${user.email}`} subtitle={`user #${user.id} · ${user.role}`} sx={{ flex: 1, mb: 0 }} />
        <IconButton onClick={refresh}><RefreshIcon /></IconButton>
      </Stack>

      <Grid container spacing={2} sx={{ mb: 2 }}>
        {/* User Info */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>账户信息</Typography>
              <Stack spacing={0.75}>
                <Row k="ID" v={user.id} />
                <Row k="邮箱" v={user.email} />
                <Row k="角色" v={<Chip size="small" label={user.role} color={user.role === 'admin' ? 'secondary' : 'default'} />} />
                <Row k="注册时间" v={fmtDate(user.created_at)} />
                <Row k="最后登录" v={fmtDate(user.last_login_at)} />
                <Row k="账户状态" v={user.is_active ? <Chip size="small" label="active" color="success" /> : <Chip size="small" label="封停" color="error" />} />
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        {/* Admin 操作 */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>🛠 admin 操作</Typography>
              <FormControl size="small" sx={{ mt: 1, mb: 2, minWidth: 200 }}>
                <InputLabel>subscription_tier</InputLabel>
                <Select
                  value={user.subscription_tier || 'free'}
                  label="subscription_tier"
                  onChange={(e) => handleTierChange(e.target.value)}
                  disabled={busy}
                >
                  {['free', 'basic', 'pro', 'team'].map(t => (
                    <MenuItem key={t} value={t}>{t}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Box>
                <FormControlLabel
                  control={
                    <Switch
                      checked={!!user.is_active}
                      onChange={(e) => handleToggleActive(e.target.checked)}
                      disabled={busy}
                    />
                  }
                  label={user.is_active ? '账户启用中 (toggle 封停)' : '已封停 (toggle 恢复)'}
                />
              </Box>
              <Alert severity="info" sx={{ mt: 2 }}>
                改 tier 即时生效。封停会让 user 无法登录 / 调 API。
              </Alert>
            </CardContent>
          </Card>
        </Grid>

        {/* Subscription + Bindings */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>当前订阅</Typography>
              {subscription.plan ? (
                <Stack spacing={0.75}>
                  <Row k="Plan" v={<Chip size="small" label={subscription.plan} color="success" />} />
                  <Row k="状态" v={subscription.status} />
                  <Row k="开始" v={fmtDate(subscription.activated_at)} />
                  <Row k="到期" v={fmtDate(subscription.expires_at)} />
                  <Row k="自动续费" v={subscription.auto_renew ? '✅' : '❌'} />
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">无 active 订阅 (legacy_tier={user.subscription_tier})</Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>外部绑定</Typography>
              <Stack spacing={0.75}>
                <Row k="OKX API" v={bindings.okx_bound ? <Chip size="small" label="已绑定" color="success" /> : <Chip size="small" label="未绑定" />} />
                <Row k="LLM providers" v={(bindings.llm_providers || []).length === 0 ? '无' : bindings.llm_providers.map(l => l.provider).join(', ')} />
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        {/* Stats KPI */}
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>📊 数据汇总</Typography>
              <Grid container spacing={2}>
                <KpiCell label="总策略" value={stats.strategies_total} />
                <KpiCell label="运行中" value={stats.strategies_running} color="#34d399" />
                <KpiCell label="总 trades" value={stats.trades_count} />
                <KpiCell label="胜/负" value={`${stats.trades_wins} / ${stats.trades_losses}`} />
                <KpiCell label="累计 PnL" value={`${stats.total_pnl_usd >= 0 ? '+' : ''}$${stats.total_pnl_usd?.toFixed(2)}`} color={stats.total_pnl_usd >= 0 ? '#34d399' : '#f87171'} />
                <KpiCell label="最后交易" value={fmtDate(stats.last_trade_at)} />
                <KpiCell label="AI 调用" value={Object.values(stats.ai_actions || {}).reduce((a, b) => a + b, 0)} />
              </Grid>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Tab label={`策略 (${strategies.length})`} />
          <Tab label={`最近 trades (${recent_trades.length})`} />
        </Tabs>
        <CardContent>
          {tab === 0 && (
            <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>ID</TableCell>
                    <TableCell>名称</TableCell>
                    <TableCell>类型</TableCell>
                    <TableCell>Symbol / TF</TableCell>
                    <TableCell>状态</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {strategies.map(s => {
                    const p = prettifyType(s.type);
                    return (
                      <TableRow key={s.id}>
                        <TableCell>{s.id}</TableCell>
                        <TableCell>{s.name}</TableCell>
                        <TableCell>
                          <Tooltip title={s.type || '—'} arrow>
                            <Chip size="small" label={`${p.emoji} ${p.label}`} sx={{ fontSize: 10 }} />
                          </Tooltip>
                        </TableCell>
                        <TableCell>{s.symbol} · {s.timeframe}</TableCell>
                        <TableCell>
                          <Chip size="small" label={s.status} color={s.status === 'running' ? 'success' : 'default'} sx={{ fontSize: 10 }} />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          )}
          {tab === 1 && (
            <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>ID</TableCell>
                    <TableCell>Strategy</TableCell>
                    <TableCell>Symbol</TableCell>
                    <TableCell>Side</TableCell>
                    <TableCell>PnL</TableCell>
                    <TableCell>%</TableCell>
                    <TableCell>Reason</TableCell>
                    <TableCell>Exit</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {recent_trades.map(t => (
                    <TableRow key={t.id}>
                      <TableCell>{t.id}</TableCell>
                      <TableCell>#{t.strategy_id}</TableCell>
                      <TableCell>{t.symbol}</TableCell>
                      <TableCell>{t.side}</TableCell>
                      <TableCell sx={{ color: t.pnl >= 0 ? '#34d399' : '#f87171', fontWeight: 600 }}>
                        {t.pnl >= 0 ? '+' : ''}${t.pnl}
                      </TableCell>
                      <TableCell sx={{ color: t.pnl_percent >= 0 ? '#34d399' : '#f87171' }}>
                        {t.pnl_percent >= 0 ? '+' : ''}{t.pnl_percent}%
                      </TableCell>
                      <TableCell><Typography variant="caption">{t.reason || '—'}</Typography></TableCell>
                      <TableCell><Typography variant="caption">{fmtDate(t.exit_time)}</Typography></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </CardContent>
      </Card>

      <Snackbar open={!!snack} autoHideDuration={3000} onClose={() => setSnack(null)}>
        {snack && <Alert severity={snack.severity} onClose={() => setSnack(null)}>{snack.msg}</Alert>}
      </Snackbar>
    </Box>
  );
}

function Row({ k, v }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 90 }}>{k}</Typography>
      <Typography variant="body2" component="span">{v}</Typography>
    </Box>
  );
}

function KpiCell({ label, value, color }) {
  return (
    <Grid item xs={6} md={3}>
      <Box sx={{ p: 1.5, borderRadius: 1, bgcolor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontSize: 10 }}>{label}</Typography>
        <Typography variant="h6" sx={{ fontWeight: 700, color: color || 'text.primary', mt: 0.3 }}>{value}</Typography>
      </Box>
    </Grid>
  );
}
