import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Chip, Button, IconButton,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField,
  Select, MenuItem, FormControl, InputLabel, Switch, FormControlLabel,
  LinearProgress, Tooltip, Alert, Snackbar, Grid, Checkbox,
} from '@mui/material';
import PodcastsIcon from '@mui/icons-material/Podcasts';
import TuneIcon from '@mui/icons-material/Tune';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import ParamOptimizeDialog from '../components/ParamOptimizeDialog';
import ExplainStrategyDialog from '../components/ExplainStrategyDialog';
import GenerateStrategyDialog from '../components/GenerateStrategyDialog';
import ImproveStrategiesDialog from '../components/ImproveStrategiesDialog';
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
import {
  AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer,
} from 'recharts';
import CorrelationHeatmap from '../components/CorrelationHeatmap';
import { palette } from '../theme';
import PageHeader from '../components/common/PageHeader';
import StatusChip from '../components/common/StatusChip';
import { prettifyType } from '../utils/strategyTypeLabels';
import LiveStrategyCard from '../components/LiveStrategyCard';

const API = process.env.REACT_APP_API_URL || '';

const STRATEGY_TYPES = [
  // ---- Wave 1 新策略 ----
  { value: 'ichimoku', label: '⭐ Ichimoku 雲帶 (4h)' },
  { value: 'vwap_reversion', label: '⭐ VWAP 回歸 (15m)' },
  { value: 'stochastic', label: '✅ Stochastic 反轉 (15m)' },
  { value: 'weekly_pivot', label: '✅ 週樞軸點突破 (4h)' },
  { value: 'psar', label: '✅ Parabolic SAR (4h)' },
  { value: 'tema', label: 'TEMA 三重 EMA (4h)' },
  { value: 'keltner_channel', label: 'Keltner 通道 (15m)' },
  { value: 'cci_reversal', label: 'CCI 反轉 (1h)' },
  { value: 'atr_breakout', label: 'ATR 通道突破 (1h)' },
  { value: 'heikin_ashi', label: 'Heikin Ashi 趨勢 (1h)' },
  { value: 'golden_cross', label: '黃金交叉 50/200 (4h/1d)' },
  { value: 'macd_trend_filter', label: 'MACD + 200MA 趨勢' },
  // ---- 原始 ----
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
  const [config, setConfig] = useState(null);
  const [supportedSymbols, setSupportedSymbols] = useState([]);
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
  const [backtestDialog, setBacktestDialog] = useState(false);
  const [backtestData, setBacktestData] = useState(null);
  const [backtestRunning, setBacktestRunning] = useState(null); // strategy_id running
  // Phase 10.6: fan-out modal
  const [fanOutOpen, setFanOutOpen] = useState(false);
  const [fanOutSource, setFanOutSource] = useState(null);
  const [fanOutSelected, setFanOutSelected] = useState([]);
  const [fanOutSubmitting, setFanOutSubmitting] = useState(false);
  // Phase 10.2: optimize modal
  const [optimizeOpen, setOptimizeOpen] = useState(false);
  const [optimizeTarget, setOptimizeTarget] = useState(null);
  const [explainOpen, setExplainOpen] = useState(false);
  const [explainTarget, setExplainTarget] = useState(null);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [improveOpen, setImproveOpen] = useState(false);

  const handleOpenFanOut = (strategy) => {
    setFanOutSource(strategy);
    setFanOutSelected([]);
    setFanOutOpen(true);
  };

  const handleSubmitFanOut = async () => {
    if (!fanOutSource || fanOutSelected.length === 0) return;
    setFanOutSubmitting(true);
    try {
      const r = await fetch(`${API}/api/strategies/${fanOutSource.id}/fan-out`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: fanOutSelected }),
      });
      const body = await r.json();
      if (r.ok) {
        const made = body.created?.length || 0;
        const skipped = body.skipped?.length || 0;
        setSnackbar({
          open: true,
          severity: made > 0 ? 'success' : 'warning',
          message: `已建立 ${made} 個兄弟策略${skipped ? `（${skipped} 個跳過）` : ''}，全部 status=stopped`,
        });
        setFanOutOpen(false);
        await fetchStrategies();
      } else {
        setSnackbar({ open: true, severity: 'error', message: body.error || '擴充失敗' });
      }
    } catch (e) {
      setSnackbar({ open: true, severity: 'error', message: `失敗：${e.message}` });
    } finally {
      setFanOutSubmitting(false);
    }
  };

  const handleRunBacktest = async (strategy) => {
    setBacktestRunning(strategy.id);
    setSnackbar({ open: true, message: `正在回測 ${strategy.name}...`, severity: 'info' });
    try {
      const res = await fetch(`${API}/api/strategies/${strategy.id}/backtest`, { method: 'POST' });
      if (res.ok) {
        // 取詳細版本（含 equity curve）
        const detailRes = await fetch(`${API}/api/strategies/${strategy.id}/backtest?detailed=1`);
        if (detailRes.ok) {
          const data = await detailRes.json();
          setBacktestData({ strategy, result: data });
          setBacktestDialog(true);
          setSnackbar({ open: true, message: '✅ 回測完成', severity: 'success' });
        }
      } else {
        const err = await res.text();
        setSnackbar({ open: true, message: `回測失敗: ${err}`, severity: 'error' });
      }
    } catch (e) {
      setSnackbar({ open: true, message: `回測錯誤: ${e.message}`, severity: 'error' });
    }
    setBacktestRunning(null);
  };

  // 打開回測 dialog：先試讀最新結果，沒有的話自動觸發新回測
  const handleOpenBacktest = async (strategy) => {
    try {
      const res = await fetch(`${API}/api/strategies/${strategy.id}/backtest?detailed=1`);
      if (res.ok) {
        const data = await res.json();
        setBacktestData({ strategy, result: data });
        setBacktestDialog(true);
      } else {
        // 尚無結果，直接跑一次
        await handleRunBacktest(strategy);
      }
    } catch (e) {
      setSnackbar({ open: true, message: `讀取失敗`, severity: 'error' });
    }
  };

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

  // Phase 14i: 共享 perf 数据 (live_card), 每 30s 刷新
  const [livePerf, setLivePerf] = useState({});      // { [id]: row }
  useEffect(() => {
    const fetchLive = async () => {
      try {
        const r = await fetch(`${API}/api/strategies/performance?include=live_card`);
        if (!r.ok) return;
        const arr = await r.json();
        const map = {};
        (arr || []).forEach(row => { map[row.id] = row; });
        setLivePerf(map);
      } catch {}
    };
    fetchLive();
    const t = setInterval(fetchLive, 30000);
    return () => clearInterval(t);
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
    fetch(`${API}/api/config`).then(r => r.json()).then(setConfig).catch(() => {});
    fetch(`${API}/api/symbols`).then(r => r.json()).then(d => setSupportedSymbols(Array.isArray(d) ? d : [])).catch(() => {});
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
    if (found) return found.label;
    // 兜底走 catalog util (cat_xxx / cat_xxx_uN_TS)
    const p = prettifyType(type);
    return p.label !== type ? (p.emoji ? `${p.emoji} ${p.label}` : p.label) : type;
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
                  <React.Fragment key={strategy.id}>
                  <TableRow sx={{ '&:hover': { bgcolor: 'rgba(255,255,255,0.03)' }, '& td': strategy.status === 'running' ? { borderBottom: 'none' } : {} }}>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600} sx={{ fontSize: 13 }}>{strategy.name}</Typography>
                    </TableCell>
                    <TableCell>
                      <Tooltip title={`原始 type: ${strategy.type || '—'}`} arrow>
                        <Chip label={getTypeLabel(strategy.type)} size="small" variant="outlined" sx={{ fontSize: 10, cursor: 'help' }} />
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      <Chip label={strategy.timeframe} size="small" variant="outlined" color="info" sx={{ fontSize: 10 }} />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600} sx={{ fontSize: 12 }}>{strategy.symbol}</Typography>
                    </TableCell>
                    <TableCell>
                      {strategy.status === 'retired' ? (
                        <Tooltip title={strategy.retire_reason || '已自動退役'}>
                          <Chip
                            label="🪦 已退役"
                            size="small"
                            color="warning"
                            sx={{ fontWeight: 600, fontSize: 10 }}
                          />
                        </Tooltip>
                      ) : (
                        <Chip
                          label={strategy.active ? '運行中' : '已停止'}
                          size="small"
                          color={strategy.active ? 'success' : 'default'}
                          sx={{ fontWeight: 600, fontSize: 10 }}
                        />
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 0.5 }}>
                        {strategy.status === 'retired' ? (
                          <Tooltip title="從退役狀態救回（變回已停止，需再次啟動）">
                            <IconButton
                              size="small"
                              color="warning"
                              onClick={async () => {
                                if (!window.confirm(`救回「${strategy.name}」？\n退役原因：${strategy.retire_reason || '無'}`)) return;
                                try {
                                  await fetch(`${API}/api/strategies/${strategy.id}/revive`, { method: 'POST' });
                                  setSnackbar({ open: true, message: '已救回為「已停止」', severity: 'success' });
                                  loadStrategies();
                                } catch (e) {
                                  setSnackbar({ open: true, message: `失敗：${e.message}`, severity: 'error' });
                                }
                              }}
                            >
                              <RefreshIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        ) : (
                          <Tooltip title={strategy.active ? '停止' : '啟動'}>
                            <IconButton size="small" color={strategy.active ? 'error' : 'success'} onClick={() => handleToggleActive(strategy)}>
                              {strategy.active ? <StopIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
                            </IconButton>
                          </Tooltip>
                        )}
                        <Tooltip title="查看 / 跑回測">
                          <span>
                            <IconButton
                              size="small"
                              color="info"
                              disabled={backtestRunning === strategy.id}
                              onClick={() => handleOpenBacktest(strategy)}
                            >
                              <ScienceIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                        <Tooltip title="編輯">
                          <IconButton size="small" color="primary" onClick={() => handleOpenDialog(strategy)}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="AI 解读策略（Pro）">
                          <IconButton size="small" sx={{ color: '#a78bfa' }} onClick={() => { setExplainTarget(strategy); setExplainOpen(true); }}>
                            <AutoAwesomeIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        {strategy.status !== 'retired' && (
                          <Tooltip title="參數網格搜尋（walk-forward）">
                            <IconButton size="small" sx={{ color: '#a78bfa' }} onClick={() => { setOptimizeTarget(strategy); setOptimizeOpen(true); }}>
                              <TuneIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                        {strategy.status !== 'retired' && (
                          <Tooltip title="一鍵複製此策略到其他幣種">
                            <IconButton size="small" sx={{ color: '#a78bfa' }} onClick={() => handleOpenFanOut(strategy)}>
                              <PodcastsIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                        <Tooltip title="刪除">
                          <IconButton size="small" color="error" onClick={() => handleDelete(strategy)}>
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </TableCell>
                  </TableRow>
                  {/* Phase 14i: running 策略卖点 strip */}
                  {strategy.status === 'running' && (
                    <TableRow>
                      <TableCell colSpan={6} sx={{ pt: 0, pb: 1.5, px: 1 }}>
                        <LiveStrategyCard strategyId={strategy.id} data={livePerf[strategy.id]} />
                      </TableCell>
                    </TableRow>
                  )}
                  </React.Fragment>
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
      {/* === Phase 12.15.5: 統一 PageHeader === */}
      <PageHeader
        title="策略管理"
        subtitle={`${strategies.filter(s => s.status === 'running').length} 运行中 · ${strategies.length} 总策略 · OOS 门槛 1.5`}
        actions={[
          <Button key="ai-improve" variant="outlined" startIcon={<AutoAwesomeIcon />} onClick={() => setImproveOpen(true)} size="small"
            sx={{ color: palette.warmAccent, borderColor: `${palette.warmAccent}55`, textTransform: 'none', '&:hover': { borderColor: palette.warmAccent, bgcolor: `${palette.warmAccent}11` } }}>
            AI 改进建议
          </Button>,
          <Button key="ai-gen" variant="outlined" startIcon={<AutoAwesomeIcon />} onClick={() => setGenerateOpen(true)} size="small"
            sx={{ color: palette.accent, borderColor: `${palette.accent}55`, textTransform: 'none', '&:hover': { borderColor: palette.accent, bgcolor: `${palette.accent}11` } }}>
            AI 生成
          </Button>,
          <Button key="estimate" variant="outlined" size="small" onClick={fetchEstimate}
            sx={{ color: palette.textMuted, borderColor: palette.border, textTransform: 'none', '&:hover': { borderColor: palette.borderHot } }}>
            收益估算
          </Button>,
          <Button
            key="health"
            variant="outlined"
            size="small"
            sx={{ color: palette.textMuted, borderColor: palette.border, textTransform: 'none', '&:hover': { borderColor: palette.borderHot } }}
            onClick={async () => {
              if (!window.confirm('立即跑健康檢查？對每個運行中的策略做新 walk-forward 回測（~5s/策略，可能 30-60s）。')) return;
              try {
                setLoading(true);
                const r = await fetch(`${API}/api/strategies/health/check`, { method: 'POST' });
                const body = await r.json();
                setSnackbar({ open: true, message: body.result?.slice(0, 200) || '完成', severity: 'success' });
                await fetchStrategies();
              } catch (e) {
                setSnackbar({ open: true, message: `失敗：${e.message}`, severity: 'error' });
              } finally {
                setLoading(false);
              }
            }}
          >
            健康检查
          </Button>,
          <Tooltip key="refresh" title="重新整理">
            <IconButton onClick={fetchStrategies} size="small" sx={{ border: `1px solid ${palette.border}`, color: palette.textMuted, '&:hover': { borderColor: palette.borderHot } }}><RefreshIcon fontSize="small" /></IconButton>
          </Tooltip>,
          <Button key="add" variant="contained" size="small" startIcon={<AddIcon />} onClick={() => handleOpenDialog()}
            sx={{ textTransform: 'none', bgcolor: palette.accent, '&:hover': { bgcolor: palette.accentDim } }}>
            新增策略
          </Button>,
        ]}
      />

      {/* Loading */}
      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {/* 模擬盤摘要 */}
      <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid #334155' }}>
        <CardContent sx={{ px: 2, py: 1.5 }}>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">模擬本金</Typography>
              <Typography variant="h6" fontWeight={700} color="primary">${config?.capital_usdt ?? '—'}</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">槓桿倍數</Typography>
              <Typography variant="h6" fontWeight={700} color="warning.main">{config?.leverage ?? '—'}x</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">每單倉位</Typography>
              <Typography variant="h6" fontWeight={700} color="success.main">
                ${config?.trade_size_usdt ?? '—'}
                {config && config.capital_usdt > 0 && (
                  <Typography component="span" variant="caption" sx={{ ml: 0.5, color: 'text.secondary' }}>
                    ({(config.trade_size_usdt / config.capital_usdt * 100).toFixed(0)}%)
                  </Typography>
                )}
              </Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">運行策略</Typography>
              <Typography variant="h6" fontWeight={700}>{strategies.filter(s => s.active).length} / {strategies.length}</Typography>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* Phase 10.1: 策略相關性熱力圖 */}
      <CorrelationHeatmap />

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
            <FormControl fullWidth size="small">
              <InputLabel>交易對</InputLabel>
              <Select value={form.symbol} onChange={(e) => setForm(f => ({...f, symbol: e.target.value}))} label="交易對">
                {(supportedSymbols.length ? supportedSymbols : [{ symbol: 'BTC/USDT' }]).map(s => (
                  <MenuItem key={s.symbol} value={s.symbol}>
                    {s.symbol}
                    {s.contract_size && <Typography component="span" variant="caption" sx={{ ml: 1, color: 'text.secondary' }}>
                      (合約 {s.contract_size} {s.symbol.split('/')[0]}/張)
                    </Typography>}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
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

      {/* === Backtest Dialog === */}
      <Dialog open={backtestDialog} onClose={() => setBacktestDialog(false)} maxWidth="lg" fullWidth
        PaperProps={{ sx: { bgcolor: 'background.paper' } }}>
        <DialogTitle sx={{ fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1 }}>
          🧪 BACKTEST · {backtestData?.strategy?.name}
        </DialogTitle>
        <DialogContent>
          {backtestData?.result && backtestData.result.status === 'completed' && (() => {
            const r = backtestData.result;
            const profitable = r.total_pnl > 0;
            const liquidated = r.max_drawdown_pct >= 100;
            const ratingColor = liquidated ? '#ff4757' : profitable && r.sharpe_ratio >= 1.5 ? '#00d4aa' : profitable ? '#f7a600' : '#ff4757';
            const ratingLabel = liquidated ? '💀 LIQUIDATED' : r.sharpe_ratio >= 3 ? '⭐ EXCELLENT' : r.sharpe_ratio >= 1.5 ? '✅ GOOD' : r.sharpe_ratio >= 0 ? '⚠️ MARGINAL' : '❌ NEGATIVE';

            return (
              <Box sx={{ mt: 1 }}>
                {/* 評級 + 關鍵 4 指標 */}
                <Box sx={{
                  display: 'inline-flex', mb: 2, px: 2, py: 1, borderRadius: 1,
                  bgcolor: `${ratingColor}22`, color: ratingColor,
                  fontWeight: 700, letterSpacing: 1, fontFamily: 'JetBrains Mono, monospace',
                  border: `1px solid ${ratingColor}66`,
                }}>{ratingLabel}</Box>

                <Grid container spacing={2} sx={{ mb: 2 }}>
                  {[
                    { label: '累積 PnL', value: `${profitable ? '+' : ''}$${(r.total_pnl||0).toFixed(2)}`, color: profitable ? '#00d4aa' : '#ff4757' },
                    { label: '年化收益', value: `${(r.annual_return_pct||0).toFixed(1)}%`, color: r.annual_return_pct >= 0 ? '#00d4aa' : '#ff4757' },
                    { label: 'Sharpe', value: r.sharpe_ratio == null ? '—' : r.sharpe_ratio.toFixed(2), color: r.sharpe_ratio >= 1.5 ? '#00d4aa' : r.sharpe_ratio >= 0 ? '#f7a600' : '#ff4757' },
                    { label: '最大回撤', value: `-${(r.max_drawdown_pct||0).toFixed(1)}%`, color: r.max_drawdown_pct < 30 ? '#00d4aa' : r.max_drawdown_pct < 60 ? '#f7a600' : '#ff4757' },
                  ].map((k, i) => (
                    <Grid item xs={6} md={3} key={i}>
                      <Box sx={{ p: 1.5, border: '1px solid rgba(167,139,250,0.2)', borderRadius: 1.5, bgcolor: 'rgba(8,10,24,0.4)' }}>
                        <Typography variant="caption" sx={{ color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.5 }}>{k.label}</Typography>
                        <Typography className="num-mono" sx={{ fontSize: '1.3rem', fontWeight: 700, color: k.color }}>{k.value}</Typography>
                      </Box>
                    </Grid>
                  ))}
                </Grid>

                {/* 次要指標 */}
                <Box sx={{
                  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 1.5, mb: 2,
                  p: 1.5, border: '1px solid rgba(167,139,250,0.15)', borderRadius: 1, bgcolor: 'rgba(8,10,24,0.3)',
                  fontFamily: 'JetBrains Mono, monospace',
                }}>
                  <Box><Typography variant="caption" sx={{ color: 'text.secondary' }}>總交易</Typography><Typography sx={{ fontWeight: 600 }}>{r.total_trades}</Typography></Box>
                  <Box><Typography variant="caption" sx={{ color: 'text.secondary' }}>勝率</Typography><Typography sx={{ fontWeight: 600 }}>{r.win_rate}%</Typography></Box>
                  <Box><Typography variant="caption" sx={{ color: 'text.secondary' }}>勝/敗</Typography><Typography sx={{ fontWeight: 600 }}><span style={{color:'#00d4aa'}}>{r.winning_trades}</span> / <span style={{color:'#ff4757'}}>{r.losing_trades}</span></Typography></Box>
                  <Box><Typography variant="caption" sx={{ color: 'text.secondary' }}>平均盈</Typography><Typography sx={{ fontWeight: 600, color: '#00d4aa' }}>+${r.avg_win}</Typography></Box>
                  <Box><Typography variant="caption" sx={{ color: 'text.secondary' }}>平均虧</Typography><Typography sx={{ fontWeight: 600, color: '#ff4757' }}>${r.avg_loss}</Typography></Box>
                  <Box><Typography variant="caption" sx={{ color: 'text.secondary' }}>Profit Factor</Typography><Typography sx={{ fontWeight: 600 }}>{r.profit_factor ?? '—'}</Typography></Box>
                  <Box><Typography variant="caption" sx={{ color: 'text.secondary' }}>K 線數</Typography><Typography sx={{ fontWeight: 600 }}>{r.candle_count}</Typography></Box>
                  <Box><Typography variant="caption" sx={{ color: 'text.secondary' }}>耗時</Typography><Typography sx={{ fontWeight: 600 }}>{r.duration_ms}ms</Typography></Box>
                </Box>

                {/* Equity curve */}
                {r.equity_curve && r.equity_curve.length > 0 && (
                  <Box>
                    <Typography variant="overline" sx={{ color: 'text.secondary' }}>EQUITY CURVE</Typography>
                    <Box sx={{ height: 280 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={r.equity_curve.map(p => ({ ts: new Date(p.ts*1000).toISOString().slice(0,10), equity: p.equity }))}>
                          <defs>
                            <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor={profitable ? '#00d4aa' : '#ff4757'} stopOpacity={0.4} />
                              <stop offset="100%" stopColor={profitable ? '#00d4aa' : '#ff4757'} stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="2 6" stroke="rgba(167,139,250,0.1)" />
                          <XAxis dataKey="ts" tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                          <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                          <ReTooltip />
                          <Area type="monotone" dataKey="equity" stroke={profitable ? '#00d4aa' : '#ff4757'} fill="url(#eqGrad)" strokeWidth={2} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </Box>
                  </Box>
                )}

                <Typography variant="caption" sx={{ color: 'text.secondary', mt: 2, display: 'block' }}>
                  回測時間：{r.created_at} · 槓桿 {r.leverage}× · 倉位 ${r.position_size_usdt} · 止損 {r.stop_loss_pct}% · 止盈 {r.take_profit_pct}%
                </Typography>
              </Box>
            );
          })()}
          {backtestData?.result && backtestData.result.status === 'error' && (
            <Alert severity="error">{backtestData.result.error_message}</Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => backtestData && handleRunBacktest(backtestData.strategy)} variant="outlined" disabled={!!backtestRunning}>
            {backtestRunning ? '回測中⋯' : '重新跑回測'}
          </Button>
          <Button onClick={() => setBacktestDialog(false)} variant="contained">關閉</Button>
        </DialogActions>
      </Dialog>

      {/* Phase 10.2: Optimize Modal */}
      <ParamOptimizeDialog
        open={optimizeOpen}
        strategy={optimizeTarget}
        onClose={() => setOptimizeOpen(false)}
        onApplied={() => {
          setSnackbar({ open: true, severity: 'success', message: '已套用新參數，建議到健康檢查或單獨跑回測重新驗證' });
          fetchStrategies();
        }}
      />

      {/* Phase 11.5.3: AI 解读策略 */}
      <ExplainStrategyDialog
        open={explainOpen}
        strategy={explainTarget}
        onClose={() => setExplainOpen(false)}
      />

      {/* Phase 11.5.4: AI 生成策略 */}
      <GenerateStrategyDialog
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        onCreated={() => { fetchStrategies(); }}
      />

      {/* Phase 11.5.10: AI 改進建議（閉環最後一環） */}
      <ImproveStrategiesDialog
        open={improveOpen}
        onClose={() => setImproveOpen(false)}
        onCreated={() => { fetchStrategies(); }}
      />

      {/* Phase 10.6: Fan-out Modal */}
      <Dialog open={fanOutOpen} onClose={() => setFanOutOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <PodcastsIcon sx={{ color: '#a78bfa' }} />
          一鍵擴充策略到多幣種
        </DialogTitle>
        <DialogContent>
          {fanOutSource && (
            <>
              <Alert severity="info" sx={{ mb: 2 }}>
                來源策略：<strong>{fanOutSource.name}</strong>（{fanOutSource.symbol} · {fanOutSource.timeframe} · {fanOutSource.type}）
                <br />
                將以相同參數複製到下面勾選的幣種。新策略以 <strong>已停止</strong> 狀態建立，需手動啟動。
              </Alert>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>選擇要擴充的目標幣種：</Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                {supportedSymbols
                  .filter(s => s.symbol !== fanOutSource.symbol)
                  .map(s => {
                    const checked = fanOutSelected.includes(s.symbol);
                    const alreadyInFamily = strategies.some(
                      st => st.template_group && st.template_group === (fanOutSource.template_group || fanOutSource.id) && st.symbol === s.symbol,
                    );
                    return (
                      <Box
                        key={s.symbol}
                        onClick={() => {
                          if (alreadyInFamily) return;
                          setFanOutSelected(prev =>
                            prev.includes(s.symbol)
                              ? prev.filter(x => x !== s.symbol)
                              : [...prev, s.symbol],
                          );
                        }}
                        sx={{
                          minWidth: 110,
                          display: 'flex',
                          alignItems: 'center',
                          gap: 0.5,
                          px: 1.5,
                          py: 0.8,
                          border: '1px solid',
                          borderColor: checked ? '#a78bfa' : 'rgba(255,255,255,0.12)',
                          bgcolor: checked ? 'rgba(167,139,250,0.12)' : 'transparent',
                          borderRadius: 1,
                          cursor: alreadyInFamily ? 'not-allowed' : 'pointer',
                          opacity: alreadyInFamily ? 0.35 : 1,
                          '&:hover': { borderColor: alreadyInFamily ? 'rgba(255,255,255,0.12)' : '#a78bfa' },
                        }}
                      >
                        <Checkbox
                          checked={checked}
                          disabled={alreadyInFamily}
                          size="small"
                          sx={{ p: 0.3, color: '#a78bfa', '&.Mui-checked': { color: '#a78bfa' } }}
                          tabIndex={-1}
                        />
                        <Typography variant="body2" fontWeight={600}>
                          {s.symbol}
                          {alreadyInFamily && (
                            <Typography component="span" variant="caption" sx={{ ml: 0.5, color: 'text.secondary' }}>
                              （已有）
                            </Typography>
                          )}
                        </Typography>
                      </Box>
                    );
                  })}
              </Box>
              {fanOutSelected.length > 0 && (
                <Box sx={{ mt: 2, p: 1.5, bgcolor: 'rgba(167,139,250,0.08)', borderRadius: 1 }}>
                  <Typography variant="caption" color="text.secondary">即將建立：</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>
                    {fanOutSelected.map(s => `${fanOutSource.name.replace(/\s*\([A-Z]{2,6}\)\s*$/, '')} (${s.split('/')[0]})`).join('、')}
                  </Typography>
                </Box>
              )}
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFanOutOpen(false)}>取消</Button>
          <Button
            variant="contained"
            disabled={fanOutSelected.length === 0 || fanOutSubmitting}
            onClick={handleSubmitFanOut}
            sx={{ bgcolor: '#a78bfa', '&:hover': { bgcolor: '#8b5cf6' } }}
          >
            {fanOutSubmitting ? '建立中…' : `建立 ${fanOutSelected.length} 個兄弟策略`}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar open={snackbar.open} autoHideDuration={3000} onClose={() => setSnackbar(s => ({...s, open: false}))}>
        <Alert severity={snackbar.severity} variant="filled">{snackbar.message}</Alert>
      </Snackbar>
    </Box>
  );
}
