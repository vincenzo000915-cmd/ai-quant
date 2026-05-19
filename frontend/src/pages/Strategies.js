import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Chip, Button, IconButton,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField,
  Select, MenuItem, FormControl, InputLabel, Switch, FormControlLabel,
  LinearProgress, Tooltip, Alert, Snackbar, Grid,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import ScienceIcon from '@mui/icons-material/Science';
import RefreshIcon from '@mui/icons-material/Refresh';
import WhatshotIcon from '@mui/icons-material/Whatshot';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import TimelineIcon from '@mui/icons-material/Timeline';
import BoltIcon from '@mui/icons-material/Bolt';

const API = process.env.REACT_APP_API_URL || '';

const STRATEGY_TYPES = [
  { value: 'trend_following', label: '🏆 趨勢跟蹤 (ADX+EMA)' },
  { value: 'volatility_breakout', label: '📈 波動率突破 (Donchian)' },
  { value: 'supertrend', label: '🔽 SuperTrend' },
  { value: 'mean_reversion', label: '🧠 均值回歸 (布林+RSI)' },
  { value: 'ma_crossover', label: '經典-均線交叉' },
  { value: 'rsi', label: '經典-RSI超買超賣' },
  { value: 'macd', label: '經典-MACD' },
  { value: 'bollinger', label: '經典-布林帶' },
];

const CATEGORIES = [
  { value: 'ultra', label: '⚡ 極短 (15m)', icon: <BoltIcon fontSize="small" /> },
  { value: 'short', label: '🔴 短線 (1h)', icon: <WhatshotIcon fontSize="small" /> },
  { value: 'swing', label: '🟡 波段 (4h)', icon: <ShowChartIcon fontSize="small" /> },
  { value: 'long', label: '🟢 長線 (4h)', icon: <TimelineIcon fontSize="small" /> },
];

const CATEGORY_MAP = {
  ultra: { label: '⚡ 極短', color: 'secondary', icon: <BoltIcon fontSize="small" /> },
  short: { label: '🔴 短線', color: 'error', icon: <WhatshotIcon fontSize="small" /> },
  swing: { label: '🟡 波段', color: 'warning', icon: <ShowChartIcon fontSize="small" /> },
  long: { label: '🟢 長線', color: 'success', icon: <TimelineIcon fontSize="small" /> },
};

const TIMEFRAMES = ['15m', '1h', '4h', '1d'];

export default function Strategies() {
  const [strategies, setStrategies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState(null);
  const [form, setForm] = useState({
    name: '', type: 'ma_crossover', category: 'swing', symbol: 'BTC/USDT',
    timeframe: '4h', params: '{}', active: false,
  });
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });
  const [estimateDialog, setEstimateDialog] = useState(false);
  const [estimateData, setEstimateData] = useState(null);

  const fetchStrategies = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/strategies`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          setStrategies(data);
        } else {
          setStrategies([]);
        }
      } else {
        setStrategies([]);
      }
    } catch {
      setStrategies([]);
    }
    setLoading(false);
  }, []);

  const fetchEstimate = async () => {
    try {
      const res = await fetch(`${API}/api/simulation/estimate?capital=100&leverage=15`);
      if (res.ok) {
        const data = await res.json();
        setEstimateData(data);
        setEstimateDialog(true);
      }
    } catch {}
  };

  useEffect(() => {
    fetchStrategies();
  }, [fetchStrategies]);

  const handleOpenDialog = (strategy = null) => {
    if (strategy) {
      setEditingStrategy(strategy);
      setForm({
        name: strategy.name || '',
        type: strategy.type || 'ma_crossover',
        category: strategy.category || 'swing',
        symbol: strategy.symbol || 'BTC/USDT',
        timeframe: strategy.timeframe || '4h',
        params: strategy.params ? JSON.stringify(strategy.params, null, 2) : '{}',
        active: strategy.active || false,
      });
    } else {
      setEditingStrategy(null);
      setForm({
        name: '', type: 'ma_crossover', category: 'swing',
        symbol: 'BTC/USDT', timeframe: '4h', params: '{}', active: false,
      });
    }
    setDialogOpen(true);
  };

  const handleSave = async () => {
    const payload = {
      ...form,
      params: JSON.parse(form.params),
    };
    try {
      const url = editingStrategy
        ? `${API}/api/strategies/${editingStrategy.id}`
        : `${API}/api/strategies`;
      const method = editingStrategy ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setSnackbar({ open: true, message: editingStrategy ? '策略已更新' : '策略已建立', severity: 'success' });
        handleCloseDialog();
        fetchStrategies();
      } else {
        throw new Error('Save failed');
      }
    } catch (err) {
      setSnackbar({ open: true, message: '儲存失敗', severity: 'error' });
    }
  };

  const handleToggleActive = async (strategy) => {
    try {
      const res = await fetch(`${API}/api/strategies/${strategy.id}/${strategy.active ? 'stop' : 'start'}`, { method: 'POST' });
      if (res.ok) {
        setSnackbar({ open: true, message: strategy.active ? '策略已停止' : '策略已啟動', severity: 'success' });
        fetchStrategies();
      }
    } catch {}
  };

  const handleDelete = async (strategy) => {
    try {
      await fetch(`${API}/api/strategies/${strategy.id}`, { method: 'DELETE' });
      setSnackbar({ open: true, message: '策略已刪除', severity: 'success' });
      fetchStrategies();
    } catch {}
  };

  const getTypeLabel = (type) => {
    const found = STRATEGY_TYPES.find((t) => t.value === type);
    return found ? found.label : type;
  };

  // 按分類分組
  const grouped = {
    ultra: strategies.filter(s => s.category === 'ultra'),
    short: strategies.filter(s => s.category === 'short'),
    swing: strategies.filter(s => s.category === 'swing'),
    long: strategies.filter(s => s.category === 'long'),
  };

  const renderStrategyTable = (categoryKey, title) => {
    const cat = CATEGORY_MAP[categoryKey];
    const items = grouped[categoryKey];
    if (items.length === 0) return null;

    return (
      <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
        <CardContent sx={{ px: 2, py: 1.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
            {cat.icon}
            <Typography variant="subtitle1" fontWeight={700} sx={{ color: `${cat.color}.main` }}>
              {title}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              ({items.length} 個策略)
            </Typography>
          </Box>
          <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: 12 }}>策略名稱</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: 12 }}>類型</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: 12 }}>時框</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: 12 }}>交易對</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: 12 }}>狀態</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: 12 }} align="right">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((strategy) => (
                  <TableRow key={strategy.id} sx={{ '&:hover': { bgcolor: 'rgba(255,255,255,0.03)' } }}>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600} sx={{ fontSize: 13 }}>{strategy.name}</Typography>
                    </TableCell>
                    <TableCell>
                      <Chip label={getTypeLabel(strategy.type)} size="small" variant="outlined" sx={{ fontSize: 10 }} />
                    </TableCell>
                    <TableCell>
                      <Chip label={strategy.timeframe} size="small" variant="outlined" color="info" sx={{ fontSize: 10 }} />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600} sx={{ fontSize: 12 }}>{strategy.symbol}</Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={strategy.active ? '運行中' : '已停止'}
                        size="small"
                        color={strategy.active ? 'success' : 'default'}
                        sx={{ fontWeight: 600, fontSize: 10 }}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 0.5 }}>
                        <Tooltip title={strategy.active ? '停止' : '啟動'}>
                          <IconButton size="small" color={strategy.active ? 'error' : 'success'} onClick={() => handleToggleActive(strategy)}>
                            {strategy.active ? <StopIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="回測（Phase 3 開發中）">
                          <span>
                            <IconButton size="small" disabled>
                              <ScienceIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                        <Tooltip title="編輯">
                          <IconButton size="small" color="primary" onClick={() => handleOpenDialog(strategy)}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="刪除">
                          <IconButton size="small" color="error" onClick={() => handleDelete(strategy)}>
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    );
  };

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2.5 }}>
        <Typography variant="h5" fontWeight={700}>策略管理</Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button variant="outlined" color="warning" size="small" onClick={fetchEstimate}>
            📊 收益估算
          </Button>
          <Tooltip title="重新整理">
            <IconButton onClick={fetchStrategies} color="primary"><RefreshIcon /></IconButton>
          </Tooltip>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => handleOpenDialog()}>
            新增策略
          </Button>
        </Box>
      </Box>

      {/* Loading */}
      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {/* 模擬盤摘要 */}
      <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid #334155' }}>
        <CardContent sx={{ px: 2, py: 1.5 }}>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">模擬本金</Typography>
              <Typography variant="h6" fontWeight={700} color="primary">$100</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">槓桿倍數</Typography>
              <Typography variant="h6" fontWeight={700} color="warning.main">15x</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">每單倉位</Typography>
              <Typography variant="h6" fontWeight={700} color="success.main">$50 (50%)</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">運行策略</Typography>
              <Typography variant="h6" fontWeight={700}>{strategies.filter(s => s.active).length} / {strategies.length}</Typography>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* 極短 */}
      {renderStrategyTable('ultra', '⚡ 極短策略 (15m K線，每15分鐘信號)')}
      {/* 短線 */}
      {renderStrategyTable('short', '🔴 短線策略 (1h K線，快進快出)')}
      {/* 波段 */}
      {renderStrategyTable('swing', '🟡 波段策略 (4h K線，持倉1-3天)')}
      {/* 長線 */}
      {renderStrategyTable('long', '🟢 長線策略 (4h K線，持倉3-7天)')}

      {strategies.length === 0 && !loading && (
        <Card sx={{ bgcolor: 'background.paper' }}>
          <CardContent sx={{ textAlign: 'center', py: 6 }}>
            <Typography variant="body1" color="text.secondary">尚無策略，請點擊「新增策略」開始</Typography>
          </CardContent>
        </Card>
      )}

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth
        PaperProps={{ sx: { bgcolor: '#111827', backgroundImage: 'none' } }}>
        <DialogTitle sx={{ fontWeight: 600 }}>{editingStrategy ? '編輯策略' : '新增策略'}</DialogTitle>
        <DialogContent dividers sx={{ borderColor: 'rgba(255,255,255,0.06)' }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5, mt: 1 }}>
            <TextField label="策略名稱" value={form.name} onChange={(e) => setForm(f => ({...f, name: e.target.value}))} fullWidth size="small" required />
            <FormControl size="small" fullWidth required>
              <InputLabel>策略類型</InputLabel>
              <Select value={form.type} onChange={(e) => setForm(f => ({...f, type: e.target.value}))} label="策略類型">
                {STRATEGY_TYPES.map(t => <MenuItem key={t.value} value={t.value}>{t.label}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>策略分類</InputLabel>
              <Select value={form.category} onChange={(e) => setForm(f => ({...f, category: e.target.value}))} label="策略分類">
                {CATEGORIES.map(c => <MenuItem key={c.value} value={c.value}>{c.label}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>時間框架</InputLabel>
              <Select value={form.timeframe} onChange={(e) => setForm(f => ({...f, timeframe: e.target.value}))} label="時間框架">
                {TIMEFRAMES.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField label="交易對" value={form.symbol} onChange={(e) => setForm(f => ({...f, symbol: e.target.value}))} fullWidth size="small" placeholder="BTC/USDT" />
            <TextField label="策略參數 (JSON)" value={form.params} onChange={(e) => setForm(f => ({...f, params: e.target.value}))} fullWidth size="small" multiline rows={3} />
            <FormControlLabel control={<Switch checked={form.active} onChange={(e) => setForm(f => ({...f, active: e.target.checked}))} />} label="建立後立即啟動" />
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button onClick={() => setDialogOpen(false)} color="inherit">取消</Button>
          <Button onClick={handleSave} variant="contained" color="primary">{editingStrategy ? '更新' : '建立'}</Button>
        </DialogActions>
      </Dialog>

      {/* 收益估算對話框 */}
      <Dialog open={estimateDialog} onClose={() => setEstimateDialog(false)} maxWidth="md" fullWidth
        PaperProps={{ sx: { bgcolor: '#111827', backgroundImage: 'none' } }}>
        <DialogTitle sx={{ fontWeight: 600 }}>📊 $100 + 15x槓桿 預期收益估算</DialogTitle>
        <DialogContent dividers sx={{ borderColor: 'rgba(255,255,255,0.06)' }}>
          {estimateData && (
            <Box>
              <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
                <Chip label={`本金 $${estimateData.capital}`} color="primary" variant="outlined" />
                <Chip label={`槓桿 ${estimateData.leverage}x`} color="warning" variant="outlined" />
                <Chip label={`有效資金 $${estimateData.effective_capital}`} color="success" variant="outlined" />
              </Box>
              <TableContainer component={Paper} sx={{ bgcolor: 'transparent' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }}>策略</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">年化</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">最大回撤</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">勝率</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">每月</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">每日</TableCell>
                      <TableCell sx={{ color: 'text.secondary', fontWeight: 600 }} align="right">1年後</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {estimateData.strategies.map((s, i) => (
                      <TableRow key={i}>
                        <TableCell><Typography variant="body2" fontWeight={600}>{s.name}</Typography></TableCell>
                        <TableCell align="right" sx={{ color: 'success.main' }}>{s.annual_return_pct}%</TableCell>
                        <TableCell align="right" sx={{ color: 'error.main' }}>{s.max_drawdown_pct}%</TableCell>
                        <TableCell align="right">{s.win_rate_pct}%</TableCell>
                        <TableCell align="right" sx={{ color: 'warning.main', fontWeight: 600 }}>${s.estimated_monthly}</TableCell>
                        <TableCell align="right">${s.estimated_daily}</TableCell>
                        <TableCell align="right" sx={{ color: 'primary.main', fontWeight: 700 }}>${s.estimated_1y}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
              <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
                ⚠️ {estimateData.note}
              </Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button onClick={() => setEstimateDialog(false)} variant="contained">關閉</Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar open={snackbar.open} autoHideDuration={3000} onClose={() => setSnackbar(s => ({...s, open: false}))}>
        <Alert severity={snackbar.severity} variant="filled">{snackbar.message}</Alert>
      </Snackbar>
    </Box>
  );
}
