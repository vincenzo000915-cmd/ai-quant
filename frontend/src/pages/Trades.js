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
        if (data.trades && data.trades.length > 0) {
          setTrades(data.trades);
          setTotalCount(data.total || data.trades.length);
        } else {
          throw new Error('Empty data');
        }
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
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5" fontWeight={700}>交易紀錄</Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <TextField
            size="small"
            placeholder="搜尋交易對..."
            value={filters.symbol}
            onChange={handleFilterChange('symbol')}
            sx={{ width: 180 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                </InputAdornment>
              ),
            }}
          />
          <Tooltip title="進階篩選">
            <IconButton color="primary" onClick={(e) => setFilterAnchor(e.currentTarget)}>
              <FilterListIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title="匯出 CSV">
            <IconButton color="primary" onClick={handleExportCSV}>
              <GetAppIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title="重新整理">
            <IconButton onClick={fetchTrades} color="primary">
              <RefreshIcon />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

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
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>交易ID</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>時間</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>交易對</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>方向</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">價格</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">數量</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">總額</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">手續費</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>狀態</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>交易所</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {trades.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                      暫無交易紀錄
                    </TableCell>
                  </TableRow>
                ) : (
                  trades.map((trade) => (
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
                          {formatTime(trade.time)}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" fontWeight={600}>{trade.symbol}</Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={getSideLabel(trade.side)}
                          size="small"
                          color={trade.side === 'buy' ? 'success' : 'error'}
                          variant="outlined"
                          sx={{ fontWeight: 600, fontSize: 11 }}
                        />
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                          ${trade.price?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                          {trade.qty}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                          ${trade.total?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', color: 'text.secondary', fontSize: 12 }}>
                          ${trade.fee?.toFixed(2)}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={getStatusLabel(trade.status)}
                          size="small"
                          color={getStatusColor(trade.status)}
                          sx={{ fontWeight: 600, fontSize: 11 }}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontSize: 12 }}>
                          {trade.exchange}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ))
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
