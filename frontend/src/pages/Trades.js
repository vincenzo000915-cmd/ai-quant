import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Chip, Button, IconButton,
  TextField, Select, MenuItem, FormControl, InputLabel, InputAdornment,
  LinearProgress, Tooltip, TablePagination, Snackbar, Alert,
  Menu, ListItemIcon, ListItemText,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import SearchIcon from '@mui/icons-material/Search';
import FilterListIcon from '@mui/icons-material/FilterList';
import GetAppIcon from '@mui/icons-material/GetApp';
import InfoIcon from '@mui/icons-material/Info';
import { palette } from '../theme';
import PageHeader from '../components/common/PageHeader';

const API = process.env.REACT_APP_API_URL || '';

const SIDE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'buy', label: '買入' },
  { value: 'sell', label: '賣出' },
];

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'filled', label: '已成交' },
  { value: 'partial', label: '部分成交' },
  { value: 'cancelled', label: '已取消' },
];

export default function Trades() {
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [totalCount, setTotalCount] = useState(0);

  // Filters
  const [filters, setFilters] = useState({
    symbol: '',
    side: '',
    status: '',
    startDate: '',
    endDate: '',
  });
  const [showFilters, setShowFilters] = useState(false);
  const [filterAnchor, setFilterAnchor] = useState(null);

  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });

  // Generate mock trades for fallback
  const generateMockTrades = useCallback(() => {
    const symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOGEUSDT', 'ADAUSDT'];
    const sides = ['buy', 'sell'];
    const statuses = ['filled', 'filled', 'filled', 'partial', 'cancelled'];
    const now = Date.now();
    const trades = [];
    for (let i = 0; i < 87; i++) {
      const symbol = symbols[i % symbols.length];
      const side = sides[i % 2];
      const price = symbol === 'BTCUSDT' ? 65000 + Math.random() * 4000
        : symbol === 'ETHUSDT' ? 3300 + Math.random() * 300
        : symbol === 'SOLUSDT' ? 130 + Math.random() * 30
        : 0.5 + Math.random() * 2;
      const qty = side === 'buy' ? 0.1 + Math.random() * 1.5 : 0.05 + Math.random() * 0.8;
      const status = statuses[i % statuses.length];
      trades.push({
        id: `T${String(1000 + i).padStart(6, '0')}`,
        symbol,
        side,
        price: Math.round(price * 100) / 100,
        qty: Math.round(qty * 10000) / 10000,
        total: Math.round(price * qty * 100) / 100,
        fee: Math.round(price * qty * 0.001 * 100) / 100,
        status,
        time: new Date(now - i * 3600000 - Math.random() * 3600000).toISOString(),
        exchange: ['Binance', 'Bybit', 'OKX'][i % 3],
      });
    }
    return trades;
  }, []);

  const fetchTrades = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filters.symbol) params.append('symbol', filters.symbol);
      if (filters.side) params.append('side', filters.side);
      if (filters.status) params.append('status', filters.status);
      if (filters.startDate) params.append('start_date', filters.startDate);
      if (filters.endDate) params.append('end_date', filters.endDate);
      params.append('limit', rowsPerPage);
      params.append('offset', page * rowsPerPage);

      const res = await fetch(`${API}/api/trades?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        // Phase 12.12.3: API returns flat array; older code expected {trades,total} wrapper
        const list = Array.isArray(data) ? data : (data.trades || []);
        setTrades(list);
        setTotalCount(Array.isArray(data) ? list.length : (data.total || list.length));
      } else {
        throw new Error('Fetch failed');
      }
    } catch {
      setTrades([]);
      setTotalCount(0);
    }
    setLoading(false);
  }, [filters, page, rowsPerPage, generateMockTrades]);

  useEffect(() => {
    fetchTrades();
  }, [fetchTrades]);

  const handleFilterChange = (field) => (e) => {
    setFilters((prev) => ({ ...prev, [field]: e.target.value }));
    setPage(0);
  };

  const handleApplyFilters = () => {
    setFilterAnchor(null);
    fetchTrades();
  };

  const handleResetFilters = () => {
    setFilters({ symbol: '', side: '', status: '', startDate: '', endDate: '' });
    setPage(0);
    setFilterAnchor(null);
  };

  const handleChangePage = (event, newPage) => {
    setPage(newPage);
  };

  const handleChangeRowsPerPage = (event) => {
    setRowsPerPage(parseInt(event.target.value, 10));
    setPage(0);
  };

  const handleExportCSV = () => {
    try {
      const headers = ['交易ID,時間,交易對,方向,價格,數量,總額,手續費,狀態,交易所'];
      const rows = trades.map((t) =>
        `${t.id},${new Date(t.time).toISOString()},${t.symbol},${t.side === 'buy' ? '買入' : '賣出'},${t.price},${t.qty},${t.total},${t.fee},${t.status === 'filled' ? '已成交' : t.status === 'partial' ? '部分成交' : '已取消'},${t.exchange}`
      );
      const csv = [...headers, ...rows].join('\n');
      const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `trades_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      setSnackbar({ open: true, message: 'CSV 匯出成功', severity: 'success' });
    } catch {
      setSnackbar({ open: true, message: 'CSV 匯出失敗', severity: 'error' });
    }
  };

  const getSideLabel = (side) => (side === 'buy' ? '買入' : '賣出');
  const getStatusLabel = (status) => {
    const map = { filled: '已成交', partial: '部分成交', cancelled: '已取消' };
    return map[status] || status;
  };

  const getStatusColor = (status) => {
    if (status === 'filled') return 'success';
    if (status === 'partial') return 'warning';
    return 'default';
  };

  const formatTime = (iso) => {
    const d = new Date(iso);
    return d.toLocaleString('zh-TW', { hour12: false });
  };

  return (
    <Box>
      {/* === Phase 12.15.5: 統一 PageHeader === */}
      <PageHeader
        title="交易记录"
        subtitle={`${trades.length} 笔 trade · 含 paper + LIVE`}
        actions={[
          <TextField
            key="search"
            size="small"
            placeholder="搜尋交易對..."
            value={filters.symbol}
            onChange={handleFilterChange('symbol')}
            sx={{
              width: 200,
              '& .MuiOutlinedInput-root': {
                bgcolor: palette.surface,
                fontSize: 13,
                '& fieldset': { borderColor: palette.border },
                '&:hover fieldset': { borderColor: palette.borderHot },
                '&.Mui-focused fieldset': { borderColor: palette.accent },
              },
            }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" sx={{ color: palette.textMuted }} />
                </InputAdornment>
              ),
            }}
          />,
          <Tooltip key="filter" title="進階篩選">
            <IconButton size="small" sx={{ border: `1px solid ${palette.border}`, color: palette.textMuted, '&:hover': { borderColor: palette.borderHot } }} onClick={(e) => setFilterAnchor(e.currentTarget)}>
              <FilterListIcon fontSize="small" />
            </IconButton>
          </Tooltip>,
          <Tooltip key="csv" title="匯出 CSV">
            <IconButton size="small" sx={{ border: `1px solid ${palette.border}`, color: palette.textMuted, '&:hover': { borderColor: palette.borderHot } }} onClick={handleExportCSV}>
              <GetAppIcon fontSize="small" />
            </IconButton>
          </Tooltip>,
          <Tooltip key="refresh" title="重新整理">
            <IconButton size="small" sx={{ border: `1px solid ${palette.border}`, color: palette.textMuted, '&:hover': { borderColor: palette.borderHot } }} onClick={fetchTrades}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>,
        ]}
      />

      {/* Loading */}
      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {/* Filter Menu */}
      <Menu
        anchorEl={filterAnchor}
        open={Boolean(filterAnchor)}
        onClose={() => setFilterAnchor(null)}
        PaperProps={{
          sx: { bgcolor: '#111827', backgroundImage: 'none', width: 280, p: 2 },
        }}
      >
        <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 2 }}>進階篩選</Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <FormControl size="small" fullWidth>
            <InputLabel>方向</InputLabel>
            <Select value={filters.side} onChange={handleFilterChange('side')} label="方向">
              {SIDE_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel>狀態</InputLabel>
            <Select value={filters.status} onChange={handleFilterChange('status')} label="狀態">
              {STATUS_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="開始日期"
            type="date"
            size="small"
            value={filters.startDate}
            onChange={handleFilterChange('startDate')}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
          <TextField
            label="結束日期"
            type="date"
            size="small"
            value={filters.endDate}
            onChange={handleFilterChange('endDate')}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
          <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
            <Button size="small" variant="outlined" onClick={handleResetFilters} fullWidth>
              重設
            </Button>
            <Button size="small" variant="contained" onClick={handleApplyFilters} fullWidth>
              套用
            </Button>
          </Box>
        </Box>
      </Menu>

      {/* Trades Table */}
      <Card sx={{ bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
        <CardContent sx={{ p: 0, '&:last-child': { pb: 0 } }}>
          <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>ID</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>平倉時間</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>策略</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>幣種</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>方向</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">入場</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">出場</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">數量</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">盈虧 (含手續費)</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">盈虧%</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>原因</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {trades.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={11} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                      暫無交易紀錄
                    </TableCell>
                  </TableRow>
                ) : (
                  trades.map((trade) => {
                    const pnl = Number(trade.pnl ?? 0);
                    const pnlPct = Number(trade.pnl_percent ?? 0);
                    const pnlColor = pnl > 0 ? '#00d4aa' : pnl < 0 ? '#ff4757' : '#94a3b8';
                    const sideZh = trade.side === 'long' ? '多' : trade.side === 'short' ? '空' : trade.side;
                    const reasonZh = {
                      stop_loss: '🛑 止損',
                      take_profit: '🎯 止盈',
                      signal: '🔄 信號',
                      reconcile_orphan: '⚠ 對賬補平',
                      manual_close_oversize: '✋ 手動平超額',
                    }[trade.reason] || trade.reason || '—';
                    return (
                      <TableRow
                        key={trade.id}
                        sx={{ '&:hover': { bgcolor: 'rgba(255,255,255,0.03)' } }}
                      >
                        <TableCell>
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                            {trade.id}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontSize: 12 }}>
                            {formatTime(trade.exit_time)}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontSize: 12, color: 'text.secondary' }}>
                            #{trade.strategy_id}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" fontWeight={600}>{trade.symbol}</Typography>
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={sideZh}
                            size="small"
                            color={trade.side === 'long' ? 'success' : 'error'}
                            variant="outlined"
                            sx={{ fontWeight: 600, fontSize: 11, minWidth: 36 }}
                          />
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                            ${Number(trade.entry_price)?.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                            ${Number(trade.exit_price)?.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                            {trade.quantity}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 700, color: pnlColor }}>
                            {pnl >= 0 ? '+' : ''}${pnl.toFixed(3)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', color: pnlColor, fontSize: 12 }}>
                            {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="caption" sx={{ fontSize: 11 }}>{reasonZh}</Typography>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </TableContainer>

          {/* Pagination */}
          <TablePagination
            component="div"
            count={totalCount}
            page={page}
            onPageChange={handleChangePage}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={handleChangeRowsPerPage}
            rowsPerPageOptions={[10, 20, 50, 100]}
            sx={{
              borderTop: '1px solid rgba(255,255,255,0.06)',
              '.MuiTablePagination-toolbar': { color: 'text.secondary' },
              '.MuiTablePagination-selectIcon': { color: 'text.secondary' },
            }}
          />
        </CardContent>
      </Card>

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={3000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={snackbar.severity} variant="filled" sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
