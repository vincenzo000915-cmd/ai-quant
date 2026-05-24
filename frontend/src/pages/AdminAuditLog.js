// Phase 14j-6: 跨 user audit log (admin 专用, 带 filter)

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Card, CardContent, Typography, Chip, TextField, IconButton, Tooltip,
  Select, MenuItem, FormControl, InputLabel,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import FilterAltIcon from '@mui/icons-material/FilterAlt';
import PageHeader from '../components/common/PageHeader';

const API = process.env.REACT_APP_API_URL || '';

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

export default function AdminAuditLog() {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [eventTypes, setEventTypes] = useState([]);
  const [filterUser, setFilterUser] = useState('');
  const [filterEvent, setFilterEvent] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterUser) params.set('user_id', filterUser);
      if (filterEvent) params.set('event_type', filterEvent);
      params.set('limit', '200');
      const r = await fetch(`${API}/api/admin/audit-log?${params}`);
      if (r.ok) {
        const data = await r.json();
        setRows(data.rows || []);
        setEventTypes(data.event_types || []);
      }
    } catch {} finally {
      setLoading(false);
    }
  }, [filterUser, filterEvent]);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <PageHeader title="📋 跨用户审计日志" subtitle={`显示 ${rows.length} 条记录 (最多 200)`} sx={{ flex: 1, mb: 0 }} />
        <IconButton onClick={refresh} disabled={loading}><RefreshIcon /></IconButton>
      </Box>

      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <FilterAltIcon fontSize="small" color="action" />
          <TextField
            size="small"
            label="user_id"
            value={filterUser}
            onChange={(e) => setFilterUser(e.target.value)}
            sx={{ width: 120 }}
          />
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>event_type</InputLabel>
            <Select
              value={filterEvent}
              label="event_type"
              onChange={(e) => setFilterEvent(e.target.value)}
            >
              <MenuItem value="">全部</MenuItem>
              {eventTypes.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
            </Select>
          </FormControl>
        </CardContent>
      </Card>

      <Card>
        <CardContent sx={{ px: 1.5, py: 1 }}>
          <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>时间</TableCell>
                  <TableCell>Actor</TableCell>
                  <TableCell>User</TableCell>
                  <TableCell>Event</TableCell>
                  <TableCell>Context</TableCell>
                  <TableCell>IP</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map(r => (
                  <TableRow key={r.id} hover>
                    <TableCell><Typography variant="caption">{fmtDate(r.created_at)}</Typography></TableCell>
                    <TableCell>
                      <Chip size="small" label={r.actor || '—'} sx={{ fontSize: 10, height: 18 }} />
                    </TableCell>
                    <TableCell>
                      {r.user_id ? (
                        <Tooltip title={r.user_email || '—'} arrow>
                          <Typography
                            variant="body2"
                            sx={{ cursor: 'pointer', textDecoration: 'underline', color: 'primary.light' }}
                            onClick={() => navigate(`/admin/users/${r.user_id}`)}
                          >
                            #{r.user_id}
                          </Typography>
                        </Tooltip>
                      ) : (
                        <Typography variant="caption" color="text.disabled">system</Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={r.event_type}
                        sx={{ fontSize: 10, height: 18 }}
                        color={r.event_type?.includes('error') ? 'error' : r.event_type?.startsWith('admin_') ? 'secondary' : 'default'}
                      />
                    </TableCell>
                    <TableCell sx={{ maxWidth: 400 }}>
                      <Tooltip title={JSON.stringify(r.context, null, 2)} arrow>
                        <Typography variant="caption" sx={{
                          fontFamily: 'monospace', fontSize: 10,
                          overflow: 'hidden', textOverflow: 'ellipsis',
                          display: '-webkit-box', WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          color: 'text.secondary',
                        }}>
                          {r.context ? JSON.stringify(r.context) : '—'}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell><Typography variant="caption" color="text.secondary">{r.ip || '—'}</Typography></TableCell>
                  </TableRow>
                ))}
                {!rows.length && !loading && (
                  <TableRow>
                    <TableCell colSpan={6} align="center">
                      <Typography variant="caption" color="text.secondary">没有匹配的记录</Typography>
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
