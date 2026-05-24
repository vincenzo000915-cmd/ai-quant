// Phase 14j-3: 会员管理列表页 (admin-only)

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Card, CardContent, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Chip, TextField, InputAdornment, IconButton, Tooltip,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import RefreshIcon from '@mui/icons-material/Refresh';
import LockIcon from '@mui/icons-material/Lock';
import PageHeader from '../components/common/PageHeader';

const API = process.env.REACT_APP_API_URL || '';

const TIER_COLOR = {
  free: 'default', basic: 'info', pro: 'success', team: 'warning',
};

function relativeTime(iso) {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return '刚刚';
  const min = Math.floor(ms / 60000);
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const d = Math.floor(hr / 24);
  return `${d} 天前`;
}

export default function AdminUsers() {
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/admin/users${q ? `?q=${encodeURIComponent(q)}` : ''}`);
      if (r.ok) {
        const data = await r.json();
        setUsers(data.users || []);
      }
    } catch {} finally {
      setLoading(false);
    }
  }, [q]);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <Box>
      <PageHeader title="🛡️ 会员管理" subtitle={`共 ${users.length} 个注册用户`} />

      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <TextField
            size="small"
            placeholder="搜邮箱..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && refresh()}
            InputProps={{
              startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
            }}
            sx={{ flex: 1, maxWidth: 400 }}
          />
          <Tooltip title="刷新">
            <IconButton onClick={refresh} disabled={loading}>
              <RefreshIcon />
            </IconButton>
          </Tooltip>
        </CardContent>
      </Card>

      <Card>
        <CardContent sx={{ px: 1.5, py: 1 }}>
          <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>邮箱</TableCell>
                  <TableCell>角色</TableCell>
                  <TableCell>订阅</TableCell>
                  <TableCell>状态</TableCell>
                  <TableCell>策略</TableCell>
                  <TableCell>累计 PnL</TableCell>
                  <TableCell>绑定</TableCell>
                  <TableCell>最后登录</TableCell>
                  <TableCell>注册</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {users.map(u => (
                  <TableRow
                    key={u.id}
                    hover
                    sx={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/admin/users/${u.id}`)}
                  >
                    <TableCell>{u.id}</TableCell>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600}>{u.email}</Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={u.role}
                        color={u.role === 'admin' ? 'secondary' : 'default'}
                        sx={{ fontSize: 10, height: 18 }}
                      />
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={u.subscription_tier}
                        color={TIER_COLOR[(u.subscription_tier || '').toLowerCase()] || 'default'}
                        sx={{ fontSize: 10, height: 18 }}
                      />
                    </TableCell>
                    <TableCell>
                      {u.is_active ? (
                        <Chip size="small" label="active" color="success" sx={{ fontSize: 10, height: 18 }} />
                      ) : (
                        <Chip size="small" label="封停" color="error" icon={<LockIcon sx={{ fontSize: 12 }} />} sx={{ fontSize: 10, height: 18 }} />
                      )}
                    </TableCell>
                    <TableCell>
                      <Tooltip title={`总 ${u.strategies_count} 条 / running ${u.strategies_running} 条`} arrow>
                        <Typography variant="body2">{u.strategies_running}<Typography component="span" variant="caption" color="text.secondary"> / {u.strategies_count}</Typography></Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell sx={{ color: u.total_pnl_usd >= 0 ? '#34d399' : '#f87171', fontWeight: 600 }}>
                      {u.total_pnl_usd >= 0 ? '+' : ''}${u.total_pnl_usd?.toFixed(2)}
                    </TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 0.3 }}>
                        <Chip size="small" label="OKX" sx={{ fontSize: 9, height: 16, opacity: u.okx_bound ? 1 : 0.3, bgcolor: u.okx_bound ? '#34d39933' : 'rgba(255,255,255,0.04)' }} />
                        <Chip size="small" label="LLM" sx={{ fontSize: 9, height: 16, opacity: u.llm_bound ? 1 : 0.3, bgcolor: u.llm_bound ? '#a78bfa33' : 'rgba(255,255,255,0.04)' }} />
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">{relativeTime(u.last_login_at)}</Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">{relativeTime(u.created_at)}</Typography>
                    </TableCell>
                  </TableRow>
                ))}
                {!users.length && !loading && (
                  <TableRow>
                    <TableCell colSpan={10} align="center">
                      <Typography variant="caption" color="text.secondary">没有匹配的用户</Typography>
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
