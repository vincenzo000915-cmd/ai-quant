// Phase 14j-5: 订阅收入 / MRR / invoices panel

import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Grid, Chip, IconButton, Tooltip,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip as ReTooltip, ResponsiveContainer,
} from 'recharts';
import PageHeader from '../components/common/PageHeader';

const API = process.env.REACT_APP_API_URL || '';

function fmtUsd(v) {
  if (v == null) return '—';
  return `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

const STATUS_COLOR = {
  confirmed: 'success', pending: 'warning', expired: 'default', rejected: 'error',
};

export default function AdminRevenue() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/admin/revenue`);
      if (r.ok) setData(await r.json());
    } catch {} finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  if (!data) return <Box sx={{ p: 4, textAlign: 'center' }}><Typography color="text.secondary">加载中…</Typography></Box>;

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <PageHeader title="💰 订阅收入" subtitle="MRR · 累计收入 · 最近 invoices" sx={{ flex: 1, mb: 0 }} />
        <IconButton onClick={refresh} disabled={loading}><RefreshIcon /></IconButton>
      </Box>

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <KpiCard label="累计收入" value={fmtUsd(data.total_revenue_usdt)} color="#34d399" />
        <KpiCard label="本月 MTD" value={fmtUsd(data.mtd_revenue_usdt)} color="#a78bfa" />
        <KpiCard label="总用户" value={data.total_users} sub={`30 天活跃 ${data.active_users_30d}`} />
        <KpiCard
          label="活跃订阅"
          value={Object.values(data.active_subscriptions_by_plan).reduce((a, b) => a + b, 0)}
          sub={Object.entries(data.active_subscriptions_by_plan).map(([p, n]) => `${p}:${n}`).join(' · ') || '无'}
        />
      </Grid>

      {/* 30 day daily revenue */}
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>30 天每日确认收入</Typography>
          <Box sx={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data.daily_revenue_30d}>
                <defs>
                  <linearGradient id="rev-grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#34d399" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#34d399" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} />
                <ReTooltip
                  contentStyle={{ background: 'rgba(20,20,25,0.95)', border: '1px solid #333', borderRadius: 4 }}
                  formatter={(v) => [`$${Number(v).toFixed(2)}`, '收入']}
                />
                <Area type="monotone" dataKey="revenue_usdt" stroke="#34d399" strokeWidth={2} fill="url(#rev-grad)" />
              </AreaChart>
            </ResponsiveContainer>
          </Box>
        </CardContent>
      </Card>

      {/* Recent invoices */}
      <Card>
        <CardContent>
          <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>最近 20 个 invoices</Typography>
          <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>用户</TableCell>
                  <TableCell>Plan / Months</TableCell>
                  <TableCell>金额</TableCell>
                  <TableCell>Chain</TableCell>
                  <TableCell>状态</TableCell>
                  <TableCell>创建</TableCell>
                  <TableCell>确认</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.recent_invoices.map(inv => (
                  <TableRow key={inv.id}>
                    <TableCell>{inv.id}</TableCell>
                    <TableCell>
                      <Typography variant="body2">{inv.user_email || `#${inv.user_id}`}</Typography>
                    </TableCell>
                    <TableCell>{inv.plan} · {inv.months}m</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>{fmtUsd(inv.amount_due)}</TableCell>
                    <TableCell>{inv.chain}</TableCell>
                    <TableCell>
                      <Chip size="small" label={inv.status} color={STATUS_COLOR[inv.status] || 'default'} sx={{ fontSize: 10 }} />
                    </TableCell>
                    <TableCell><Typography variant="caption">{fmtDate(inv.created_at)}</Typography></TableCell>
                    <TableCell><Typography variant="caption">{fmtDate(inv.confirmed_at)}</Typography></TableCell>
                  </TableRow>
                ))}
                {!data.recent_invoices.length && (
                  <TableRow>
                    <TableCell colSpan={8} align="center">
                      <Typography variant="caption" color="text.secondary">没有 invoices 记录</Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    </Box>
  );
}

function KpiCard({ label, value, sub, color }) {
  return (
    <Grid item xs={6} md={3}>
      <Card>
        <CardContent>
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11 }}>{label}</Typography>
          <Typography variant="h5" sx={{ fontWeight: 800, color: color || 'text.primary', mt: 0.5 }}>{value}</Typography>
          {sub && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontSize: 10, mt: 0.3 }}>{sub}</Typography>}
        </CardContent>
      </Card>
    </Grid>
  );
}
