import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Chip, IconButton, LinearProgress,
  TextField, MenuItem, Stack, Alert,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { Navigate } from 'react-router-dom';
import { palette } from '../theme';
import PageHeader from '../components/common/PageHeader';
import { getUser } from '../auth';

const API = process.env.REACT_APP_API_URL || '';

const EVENT_COLORS = {
  halt: 'warning',
  unhalt: 'success',
  kill_switch: 'error',
  config_change: 'info',
  live_mode_flip: 'error',
  candidate_promote: 'success',
  strategy_revive: 'info',
  strategy_retire: 'warning',
};

const ACTOR_COLORS = {
  user: 'primary',
  system: 'default',
};

export default function Audit() {
  // Phase 12.44: admin-only — 非 admin 跳回 dashboard
  const u = getUser();
  if (u && u.role !== 'admin') {
    return <Navigate to="/dashboard" replace />;
  }
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState('');
  const [actorFilter, setActorFilter] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (typeFilter) params.set('type', typeFilter);
      if (actorFilter) params.set('actor', actorFilter);
      const r = await fetch(`${API}/api/audit?${params.toString()}`);
      const data = await r.json();
      setRows(Array.isArray(data) ? data : []);
    } finally { setLoading(false); }
  }, [typeFilter, actorFilter]);

  useEffect(() => { load(); }, [load]);

  // 取所有不同的 type / actor 给 filter dropdown
  const types = Array.from(new Set(rows.map(r => r.event_type))).sort();
  const actors = Array.from(new Set(rows.map(r => r.actor))).sort();

  const fmtAge = (iso) => {
    if (!iso) return '';
    const ms = Date.now() - new Date(iso).getTime();
    const sec = Math.floor(ms / 1000);
    if (sec < 60) return `${sec}s 前`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m 前`;
    const h = Math.floor(min / 60);
    if (h < 24) return `${h}h 前`;
    return `${Math.floor(h / 24)}d 前`;
  };

  return (
    <Box>
      <PageHeader
        title="审计日志"
        subtitle="所有 mutating 事件 — config 改动 / halt / kill / retire / promote"
        actions={[
          <TextField key="type" select size="small" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} label="事件类型" sx={{ minWidth: 160 }}>
            <MenuItem value="">全部</MenuItem>
            {types.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
          </TextField>,
          <TextField key="actor" select size="small" value={actorFilter} onChange={(e) => setActorFilter(e.target.value)} label="动作来源" sx={{ minWidth: 160 }}>
            <MenuItem value="">全部</MenuItem>
            {actors.map(a => <MenuItem key={a} value={a}>{a}</MenuItem>)}
          </TextField>,
          <IconButton key="refresh" size="small" onClick={load} sx={{ border: `1px solid ${palette.border}`, color: palette.textMuted, '&:hover': { borderColor: palette.borderHot } }}>
            <RefreshIcon fontSize="small" />
          </IconButton>,
        ]}
      />

      {loading && <LinearProgress sx={{ mb: 1 }} />}

      <TableContainer component={Paper} sx={{ bgcolor: 'transparent' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell width={60}>ID</TableCell>
              <TableCell>事件</TableCell>
              <TableCell>動作來源</TableCell>
              <TableCell>內容</TableCell>
              <TableCell width={100}>IP</TableCell>
              <TableCell width={120}>時間</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 && !loading && (
              <TableRow><TableCell colSpan={6} align="center" sx={{ py: 4, color: 'text.secondary' }}>無記錄</TableCell></TableRow>
            )}
            {rows.map(r => (
              <TableRow key={r.id} hover>
                <TableCell>{r.id}</TableCell>
                <TableCell>
                  <Chip
                    label={r.event_type}
                    size="small"
                    color={EVENT_COLORS[r.event_type] || 'default'}
                  />
                </TableCell>
                <TableCell>
                  <Chip label={r.actor} size="small" variant="outlined"
                    color={ACTOR_COLORS[r.actor.split(':')[0]] || 'default'} />
                </TableCell>
                <TableCell>
                  <Typography variant="caption" sx={{ fontFamily: 'JetBrains Mono', fontSize: '0.7rem', wordBreak: 'break-all' }}>
                    {JSON.stringify(r.context)}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption" sx={{ fontFamily: 'JetBrains Mono', fontSize: '0.7rem', color: 'text.secondary' }}>
                    {r.ip || '—'}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption" sx={{ fontFamily: 'JetBrains Mono', fontSize: '0.7rem' }}>
                    {fmtAge(r.created_at)}
                  </Typography>
                  <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', fontSize: '0.65rem' }}>
                    {r.created_at?.slice(11, 19)}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}
