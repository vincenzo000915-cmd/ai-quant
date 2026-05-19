import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Chip, LinearProgress,
  IconButton, Tooltip,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import EmojiEventsIcon from '@mui/icons-material/EmojiEvents';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import {
  AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer,
} from 'recharts';

const API = process.env.REACT_APP_API_URL || '';

const COLORS = {
  bg: '#0f172a',
  card: '#1e293b',
  border: '#334155',
  text: '#f1f5f9',
  textDim: '#94a3b8',
  primary: '#3b82f6',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
};

const CATEGORY_META = {
  ultra: { label: '極短 15m', color: '#8b5cf6' },
  short: { label: '短線 1h', color: '#ef4444' },
  swing: { label: '波段 4h', color: '#f59e0b' },
  long: { label: '長線 4h', color: '#10b981' },
};

export default function Dashboard() {
  const [account, setAccount] = useState(null);
  const [btcPrice, setBtcPrice] = useState(null);
  const [btcChart, setBtcChart] = useState([]);
  const [positions, setPositions] = useState([]);
  const [pnlData, setPnlData] = useState([]);
  const [pnlSummary, setPnlSummary] = useState(null);
  const [perfList, setPerfList] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [acctRes, priceRes, posRes, pnlHistRes, pnlSumRes, perfRes] = await Promise.allSettled([
        fetch(`${API}/api/account`),
        fetch(`${API}/api/market/btc-price`),
        fetch(`${API}/api/positions`),
        fetch(`${API}/api/pnl/history?days=30`),
        fetch(`${API}/api/pnl/summary`),
        fetch(`${API}/api/strategies/performance`),
      ]);

      if (acctRes.status === 'fulfilled' && acctRes.value.ok) setAccount(await acctRes.value.json());
      if (priceRes.status === 'fulfilled' && priceRes.value.ok) setBtcPrice(await priceRes.value.json());
      if (posRes.status === 'fulfilled' && posRes.value.ok) {
        const json = await posRes.value.json();
        setPositions(Array.isArray(json) ? json : []);
      }
      if (pnlHistRes.status === 'fulfilled' && pnlHistRes.value.ok) {
        const json = await pnlHistRes.value.json();
        setPnlData(Array.isArray(json) ? json : []);
      }
      if (pnlSumRes.status === 'fulfilled' && pnlSumRes.value.ok) {
        setPnlSummary(await pnlSumRes.value.json());
      }
      if (perfRes.status === 'fulfilled' && perfRes.value.ok) {
        const json = await perfRes.value.json();
        setPerfList(Array.isArray(json) ? json : []);
      }

      try {
        const chartRes = await fetch(`${API}/api/market/btc-chart`);
        if (chartRes.ok) {
          const chartJson = await chartRes.json();
          setBtcChart(Array.isArray(chartJson) ? chartJson : []);
        }
      } catch {/* ignore */}
    } catch {
      // silent fail; cards show '---'
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // 按表現排序的策略（活躍持倉 → PnL 高 → 交易次數多）
  const sortedPerf = useMemo(() => {
    return [...perfList].sort((a, b) => {
      if (a.has_open_position !== b.has_open_position) return a.has_open_position ? -1 : 1;
      if (b.total_pnl !== a.total_pnl) return b.total_pnl - a.total_pnl;
      return b.total_trades - a.total_trades;
    });
  }, [perfList]);

  const StatCard = ({ title, value, subtitle, icon, color = 'primary' }) => {
    const iconColorMap = {
      primary: COLORS.primary,
      success: COLORS.success,
      error: COLORS.error,
      warning: COLORS.warning,
    };
    const iconColor = iconColorMap[color] || COLORS.primary;
    return (
      <Card sx={{ height: '100%' }}>
        <CardContent sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, px: 2, py: 2 }}>
          <Box sx={{
            p: 1.25, borderRadius: 1.5,
            bgcolor: `${iconColor}1a`,  // 10% alpha
            color: iconColor,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {React.cloneElement(icon, { sx: { fontSize: 22 } })}
          </Box>
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: 0.5 }}>
              {title}
            </Typography>
            <Typography
              className="num-mono"
              variant="h5"
              sx={{ mt: 0.25, fontSize: { xs: '1.1rem', sm: '1.4rem' }, fontWeight: 700, color: 'text.primary' }}
            >
              {value}
            </Typography>
            {subtitle && (
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.75rem', mt: 0.25, display: 'block' }}>
                {subtitle}
              </Typography>
            )}
          </Box>
        </CardContent>
      </Card>
    );
  };

  const PerfChip = ({ pnl }) => {
    if (pnl === 0 || pnl == null) return <Chip label="—" size="small" variant="outlined" sx={{ fontSize: 11 }} />;
    const positive = pnl > 0;
    return (
      <Chip
        size="small"
        label={`${positive ? '+' : ''}$${pnl.toFixed(2)}`}
        sx={{
          fontSize: 11, fontWeight: 600,
          bgcolor: positive ? `${COLORS.success}22` : `${COLORS.error}22`,
          color: positive ? COLORS.success : COLORS.error,
          border: 'none',
        }}
      />
    );
  };

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>儀表板</Typography>
          <Typography variant="caption" color="text.secondary">
            模擬盤 · OKX BTC/USDT · 每 30 秒刷新
          </Typography>
        </Box>
        <Tooltip title="立即刷新">
          <IconButton onClick={fetchData} size="small" sx={{ color: 'primary.main' }}>
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      {loading && <LinearProgress sx={{ mb: 2, height: 2 }} />}

      {/* KPI Cards */}
      <Grid container spacing={2.5} sx={{ mb: 3 }}>
        <Grid item xs={6} md={3}>
          <StatCard
            title="帳戶餘額"
            value={account ? `$${(account.balance || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '---'}
            subtitle={pnlSummary != null
              ? `USDT · ${pnlSummary.unrealized_pnl >= 0 ? '+' : ''}$${pnlSummary.unrealized_pnl.toFixed(2)} 未實現`
              : 'USDT'}
            icon={<AccountBalanceWalletIcon />}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard
            title="累積 PnL"
            value={pnlSummary ? `${pnlSummary.total_pnl >= 0 ? '+' : ''}$${pnlSummary.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '---'}
            subtitle={pnlSummary ? `${pnlSummary.total_trades} 筆交易 · 最大回撤 -$${pnlSummary.max_drawdown}` : '尚未交易'}
            icon={pnlSummary?.total_pnl >= 0 ? <TrendingUpIcon /> : <TrendingDownIcon />}
            color={pnlSummary?.total_pnl >= 0 ? 'success' : 'error'}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard
            title="勝率"
            value={pnlSummary ? `${pnlSummary.win_rate.toFixed(1)}%` : '---'}
            subtitle={pnlSummary ? `${pnlSummary.winning_trades} 勝 / ${pnlSummary.losing_trades} 敗` : '尚無交易紀錄'}
            icon={<EmojiEventsIcon />}
            color={pnlSummary?.win_rate >= 50 ? 'success' : pnlSummary?.win_rate >= 40 ? 'warning' : 'error'}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard
            title="運行中策略"
            value={pnlSummary ? `${pnlSummary.running_strategies}` : '---'}
            subtitle={pnlSummary ? `${pnlSummary.open_positions} 個持倉中` : ''}
            icon={<ShowChartIcon />}
          />
        </Grid>
      </Grid>

      {/* Charts Row */}
      <Grid container spacing={2.5} sx={{ mb: 3 }}>
        <Grid item xs={12} md={8}>
          <Card>
            <CardContent sx={{ px: 2.5, py: 2 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1.5 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>累積 PnL（30 天）</Typography>
                {pnlSummary && (
                  <Typography
                    className="num-mono"
                    variant="body2"
                    sx={{ color: pnlSummary.total_pnl >= 0 ? COLORS.success : COLORS.error, fontWeight: 600 }}
                  >
                    {pnlSummary.total_pnl >= 0 ? '+' : ''}${pnlSummary.total_pnl.toFixed(2)}
                  </Typography>
                )}
              </Box>
              <Box sx={{ height: 280 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={pnlData}>
                    <defs>
                      <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COLORS.primary} stopOpacity={0.4} />
                        <stop offset="95%" stopColor={COLORS.primary} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} opacity={0.5} />
                    <XAxis dataKey="date" tick={{ fontSize: 11, fill: COLORS.textDim }} axisLine={{ stroke: COLORS.border }} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: COLORS.textDim }} axisLine={false} tickLine={false} />
                    <ReTooltip />
                    <Area type="monotone" dataKey="cumulative" name="累積 PnL" stroke={COLORS.primary} fill="url(#pnlGradient)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </Box>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent sx={{ px: 2.5, py: 2 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1.5 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>BTC 價格</Typography>
                {btcPrice && (
                  <Box className="num-mono" sx={{ textAlign: 'right' }}>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      ${(btcPrice.price || 0).toLocaleString()}
                    </Typography>
                    <Typography variant="caption" sx={{ color: btcPrice.change_24h >= 0 ? COLORS.success : COLORS.error }}>
                      {btcPrice.change_24h >= 0 ? '+' : ''}{(btcPrice.change_24h || 0).toFixed(2)}%
                    </Typography>
                  </Box>
                )}
              </Box>
              <Box sx={{ height: 280 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={btcChart}>
                    <defs>
                      <linearGradient id="btcGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COLORS.warning} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={COLORS.warning} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} opacity={0.5} />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: COLORS.textDim }} axisLine={{ stroke: COLORS.border }} tickLine={false} />
                    <YAxis domain={['dataMin - 500', 'dataMax + 500']} tick={{ fontSize: 10, fill: COLORS.textDim }} axisLine={false} tickLine={false} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                    <ReTooltip formatter={(value) => [`$${value.toLocaleString()}`, 'BTC']} />
                    <Area type="monotone" dataKey="price" stroke={COLORS.warning} fill="url(#btcGradient)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* 策略表現面板 */}
      <Card sx={{ mb: 3 }}>
        <CardContent sx={{ px: 2.5, py: 2 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1.5 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>策略表現</Typography>
            <Typography variant="caption" color="text.secondary">
              排序：持倉中 → 累積 PnL → 交易次數
            </Typography>
          </Box>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>策略</TableCell>
                  <TableCell>類型</TableCell>
                  <TableCell>狀態</TableCell>
                  <TableCell align="right">交易數</TableCell>
                  <TableCell align="right">勝率</TableCell>
                  <TableCell align="right">累積 PnL</TableCell>
                  <TableCell align="right">平均盈虧</TableCell>
                  <TableCell align="right">Profit Factor</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {sortedPerf.map((s) => {
                  const cat = CATEGORY_META[s.category] || { label: s.category, color: COLORS.textDim };
                  return (
                    <TableRow key={s.id} hover>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                          {s.has_open_position && (
                            <Tooltip title={`持倉中 ${s.open_position_pnl >= 0 ? '+' : ''}$${s.open_position_pnl}`}>
                              <FiberManualRecordIcon sx={{ fontSize: 10, color: COLORS.success }} />
                            </Tooltip>
                          )}
                          <Typography variant="body2" sx={{ fontWeight: 500 }}>{s.name}</Typography>
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={cat.label}
                          size="small"
                          sx={{
                            bgcolor: `${cat.color}22`,
                            color: cat.color,
                            fontSize: 11,
                            border: 'none',
                            height: 20,
                          }}
                        />
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={s.status === 'running' ? '運行中' : '已停止'}
                          size="small"
                          sx={{
                            bgcolor: s.status === 'running' ? `${COLORS.success}22` : `${COLORS.textDim}22`,
                            color: s.status === 'running' ? COLORS.success : COLORS.textDim,
                            fontSize: 11,
                            border: 'none',
                            height: 20,
                          }}
                        />
                      </TableCell>
                      <TableCell align="right" className="num-mono">
                        {s.total_trades}
                      </TableCell>
                      <TableCell align="right" className="num-mono">
                        {s.total_trades > 0 ? `${s.win_rate}%` : '—'}
                      </TableCell>
                      <TableCell align="right">
                        <PerfChip pnl={s.total_pnl} />
                      </TableCell>
                      <TableCell align="right" className="num-mono">
                        {s.total_trades > 0 ? (
                          <span style={{ color: s.avg_pnl >= 0 ? COLORS.success : COLORS.error }}>
                            {s.avg_pnl >= 0 ? '+' : ''}${s.avg_pnl}
                          </span>
                        ) : '—'}
                      </TableCell>
                      <TableCell align="right" className="num-mono">
                        {s.profit_factor != null && s.total_trades > 0 ? s.profit_factor : '—'}
                      </TableCell>
                    </TableRow>
                  );
                })}
                {sortedPerf.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={8} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                      尚無策略
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      {/* 持倉表 */}
      <Card>
        <CardContent sx={{ px: 2.5, py: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1.5 }}>當前持倉</Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>策略</TableCell>
                  <TableCell>交易對</TableCell>
                  <TableCell>方向</TableCell>
                  <TableCell align="right">倉位</TableCell>
                  <TableCell align="right">開倉價</TableCell>
                  <TableCell align="right">標記價</TableCell>
                  <TableCell align="right">未實現 PnL</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {positions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                      目前無持倉
                    </TableCell>
                  </TableRow>
                ) : (
                  positions.map((pos) => {
                    const stratName = sortedPerf.find((p) => p.id === pos.strategy_id)?.name || `#${pos.strategy_id}`;
                    return (
                      <TableRow key={pos.id} hover>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontWeight: 500 }}>{stratName}</Typography>
                        </TableCell>
                        <TableCell className="num-mono">{pos.symbol}</TableCell>
                        <TableCell>
                          <Chip
                            label={pos.side === 'long' ? '做多' : '做空'}
                            size="small"
                            sx={{
                              bgcolor: pos.side === 'long' ? `${COLORS.success}22` : `${COLORS.error}22`,
                              color: pos.side === 'long' ? COLORS.success : COLORS.error,
                              fontSize: 11, fontWeight: 600, border: 'none', height: 20,
                            }}
                          />
                        </TableCell>
                        <TableCell align="right" className="num-mono">{pos.size}</TableCell>
                        <TableCell align="right" className="num-mono">${(pos.entry_price || 0).toLocaleString()}</TableCell>
                        <TableCell align="right" className="num-mono">${(pos.current_price || 0).toLocaleString()}</TableCell>
                        <TableCell align="right">
                          <PerfChip pnl={pos.unrealized_pnl} />
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    </Box>
  );
}
