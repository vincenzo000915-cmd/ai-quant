import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Chip, LinearProgress,
  IconButton, Tooltip,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import EmojiEventsIcon from '@mui/icons-material/EmojiEvents';
import BoltIcon from '@mui/icons-material/Bolt';
import {
  AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer,
} from 'recharts';

const API = process.env.REACT_APP_API_URL || '';

const C = {
  primary: '#6366f1',
  primaryGlow: 'rgba(99, 102, 241, 0.4)',
  accent: '#06b6d4',
  accentGlow: 'rgba(6, 182, 212, 0.4)',
  success: '#22c55e',
  error: '#ef4444',
  warning: '#f59e0b',
  text: '#e2e8f0',
  textDim: '#94a3b8',
  border: 'rgba(99, 102, 241, 0.18)',
};

const CATEGORY_META = {
  ultra: { label: '⚡ ULTRA', color: '#a855f7', bg: 'rgba(168, 85, 247, 0.15)' },
  short: { label: '🔥 SHORT', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)' },
  swing: { label: '◈ SWING', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' },
  long:  { label: '◆ LONG',  color: '#22c55e', bg: 'rgba(34, 197, 94, 0.15)' },
};

// 戰術風 header 角裝飾
const CornerDecor = ({ position = 'tl' }) => {
  const styles = {
    tl: { top: -1, left: -1, borderTop: `2px solid ${C.primary}`, borderLeft: `2px solid ${C.primary}` },
    tr: { top: -1, right: -1, borderTop: `2px solid ${C.primary}`, borderRight: `2px solid ${C.primary}` },
    bl: { bottom: -1, left: -1, borderBottom: `2px solid ${C.primary}`, borderLeft: `2px solid ${C.primary}` },
    br: { bottom: -1, right: -1, borderBottom: `2px solid ${C.primary}`, borderRight: `2px solid ${C.primary}` },
  };
  return (
    <Box sx={{
      position: 'absolute', width: 12, height: 12,
      filter: `drop-shadow(0 0 4px ${C.primaryGlow})`,
      ...styles[position],
    }} />
  );
};

// 脈衝點
const PulseDot = ({ color = C.success, size = 8 }) => (
  <Box sx={{ position: 'relative', width: size, height: size, display: 'inline-block' }}>
    <Box className="pulse-dot" sx={{
      width: size, height: size, borderRadius: '50%',
      bgcolor: color, position: 'absolute',
      boxShadow: `0 0 ${size * 1.5}px ${color}`,
    }} />
  </Box>
);

export default function Dashboard() {
  const [account, setAccount] = useState(null);
  const [btcPrice, setBtcPrice] = useState(null);
  const [btcChart, setBtcChart] = useState([]);
  const [positions, setPositions] = useState([]);
  const [pnlData, setPnlData] = useState([]);
  const [pnlSummary, setPnlSummary] = useState(null);
  const [perfList, setPerfList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);

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

      setLastUpdate(new Date());
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const sortedPerf = useMemo(() => {
    return [...perfList].sort((a, b) => {
      if (a.has_open_position !== b.has_open_position) return a.has_open_position ? -1 : 1;
      if (b.total_pnl !== a.total_pnl) return b.total_pnl - a.total_pnl;
      return b.total_trades - a.total_trades;
    });
  }, [perfList]);

  const KPICard = ({ label, value, sublabel, icon, accent = 'primary', glow = false, highlight = false }) => {
    const accentMap = {
      primary: { color: C.primary, glow: C.primaryGlow, glowClass: 'glow-text-primary' },
      success: { color: C.success, glow: 'rgba(34,197,94,0.45)', glowClass: 'glow-text-success' },
      error:   { color: C.error,   glow: 'rgba(239,68,68,0.45)', glowClass: 'glow-text-error' },
      warning: { color: C.warning, glow: 'rgba(245,158,11,0.45)', glowClass: '' },
      accent:  { color: C.accent,  glow: C.accentGlow, glowClass: '' },
    };
    const a = accentMap[accent] || accentMap.primary;
    return (
      <Box
        className={highlight ? 'glow-border glass-card' : 'glass-card'}
        sx={{ p: 2.25, height: '100%', position: 'relative', overflow: 'hidden' }}
      >
        <CornerDecor position="tl" />
        <CornerDecor position="br" />

        {/* 背景幾何裝飾 */}
        <Box sx={{
          position: 'absolute', top: -20, right: -20, width: 120, height: 120,
          background: `radial-gradient(circle, ${a.glow} 0%, transparent 70%)`,
          opacity: 0.25, pointerEvents: 'none',
        }} />

        <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 1, position: 'relative' }}>
          <Typography variant="overline" sx={{ color: 'text.secondary', lineHeight: 1, letterSpacing: 1.2 }}>
            {label}
          </Typography>
          <Box sx={{
            width: 32, height: 32, borderRadius: 1.5,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            bgcolor: `${a.color}1a`, color: a.color,
            border: `1px solid ${a.color}33`,
          }}>
            {React.cloneElement(icon, { sx: { fontSize: 18 } })}
          </Box>
        </Box>

        <Typography
          className={`num-mono ${glow ? a.glowClass : ''}`}
          sx={{
            fontSize: { xs: '1.3rem', sm: '1.7rem' },
            fontWeight: 700,
            color: a.color,
            lineHeight: 1.1,
            mb: 0.5,
            position: 'relative',
          }}
        >
          {value}
        </Typography>

        {sublabel && (
          <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.72rem', position: 'relative' }}>
            {sublabel}
          </Typography>
        )}
      </Box>
    );
  };

  const PerfChip = ({ pnl, withGlow = false }) => {
    if (pnl === 0 || pnl == null) return <Typography variant="body2" className="num-mono" sx={{ color: 'text.secondary' }}>—</Typography>;
    const positive = pnl > 0;
    const color = positive ? C.success : C.error;
    return (
      <Typography
        className="num-mono"
        sx={{
          color, fontSize: '0.85rem', fontWeight: 600,
          ...(withGlow && { textShadow: `0 0 12px ${color}66` }),
        }}
      >
        {positive ? '+' : ''}${pnl.toFixed(2)}
      </Typography>
    );
  };

  const utcTime = lastUpdate
    ? lastUpdate.toISOString().slice(11, 19) + ' UTC'
    : '—— UTC';

  return (
    <Box sx={{ position: 'relative', zIndex: 1 }}>
      {/* Tactical Header */}
      <Box sx={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        mb: 3, pb: 2, borderBottom: '1px solid rgba(99,102,241,0.12)',
      }}>
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 0.5 }}>
            <PulseDot />
            <Typography variant="overline" sx={{ color: C.success, fontSize: '0.7rem' }}>
              系統運行中 · SIMULATION
            </Typography>
          </Box>
          <Typography
            variant="h4"
            sx={{
              fontWeight: 800,
              background: `linear-gradient(135deg, ${C.primary} 0%, ${C.accent} 100%)`,
              backgroundClip: 'text',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              fontSize: { xs: '1.4rem', sm: '1.9rem' },
              letterSpacing: -0.5,
            }}
          >
            QUANT TERMINAL
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontFamily: 'JetBrains Mono, monospace' }}>
            OKX · BTC/USDT · LEV 15× · {utcTime}
          </Typography>
        </Box>
        <Tooltip title="立即刷新">
          <IconButton
            onClick={fetchData}
            sx={{
              border: `1px solid ${C.border}`,
              color: C.primary,
              '&:hover': { background: 'rgba(99,102,241,0.1)', borderColor: 'rgba(99,102,241,0.4)' },
            }}
          >
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      {loading && <LinearProgress sx={{ mb: 2, height: 2, borderRadius: 1 }} />}

      {/* KPI Cards */}
      <Grid container spacing={2.5} sx={{ mb: 3 }}>
        <Grid item xs={6} md={3}>
          <KPICard
            label="帳戶餘額"
            value={account ? `$${(account.balance || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '---'}
            sublabel={pnlSummary != null
              ? `${pnlSummary.unrealized_pnl >= 0 ? '+' : ''}$${pnlSummary.unrealized_pnl.toFixed(2)} 未實現`
              : 'USDT'}
            icon={<AccountBalanceWalletIcon />}
            accent="primary"
            glow
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <KPICard
            label="累積 PnL"
            value={pnlSummary
              ? `${pnlSummary.total_pnl >= 0 ? '+' : ''}$${pnlSummary.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
              : '---'}
            sublabel={pnlSummary
              ? `${pnlSummary.total_trades} 筆 · DD -$${pnlSummary.max_drawdown}`
              : '尚未交易'}
            icon={pnlSummary?.total_pnl >= 0 ? <TrendingUpIcon /> : <TrendingDownIcon />}
            accent={pnlSummary?.total_pnl > 0 ? 'success' : pnlSummary?.total_pnl < 0 ? 'error' : 'primary'}
            glow
            highlight
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <KPICard
            label="勝率"
            value={pnlSummary ? `${pnlSummary.win_rate.toFixed(1)}%` : '---'}
            sublabel={pnlSummary
              ? `${pnlSummary.winning_trades}W · ${pnlSummary.losing_trades}L`
              : '尚無交易'}
            icon={<EmojiEventsIcon />}
            accent={pnlSummary?.win_rate >= 50 ? 'success' : pnlSummary?.win_rate >= 40 ? 'warning' : 'error'}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <KPICard
            label="活躍策略"
            value={pnlSummary ? `${pnlSummary.running_strategies}` : '---'}
            sublabel={pnlSummary ? `${pnlSummary.open_positions} 持倉中` : ''}
            icon={<BoltIcon />}
            accent="accent"
          />
        </Grid>
      </Grid>

      {/* Charts Row */}
      <Grid container spacing={2.5} sx={{ mb: 3 }}>
        <Grid item xs={12} md={8}>
          <Box className="glass-card" sx={{ p: 2.5, position: 'relative', overflow: 'hidden' }}>
            <CornerDecor position="tl" />
            <CornerDecor position="tr" />

            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 2 }}>
              <Box>
                <Typography variant="overline" sx={{ color: 'text.secondary' }}>累積 PnL · 30D</Typography>
                <Typography
                  className="num-mono"
                  variant="h5"
                  sx={{
                    fontWeight: 700,
                    color: pnlSummary?.total_pnl >= 0 ? C.success : C.error,
                    textShadow: pnlSummary?.total_pnl !== 0
                      ? `0 0 24px ${pnlSummary?.total_pnl >= 0 ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)'}`
                      : 'none',
                  }}
                >
                  {pnlSummary
                    ? `${pnlSummary.total_pnl >= 0 ? '+' : ''}$${pnlSummary.total_pnl.toFixed(2)}`
                    : '$0.00'}
                </Typography>
              </Box>
              <Box sx={{ textAlign: 'right' }}>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Profit Factor
                </Typography>
                <Typography className="num-mono" sx={{ fontSize: '0.95rem', fontWeight: 600, color: C.primary }}>
                  {(() => {
                    const all = perfList.reduce((acc, s) => {
                      acc.wins += (s.avg_win || 0) * (s.winning_trades || 0);
                      acc.losses += Math.abs((s.avg_loss || 0) * (s.losing_trades || 0));
                      return acc;
                    }, { wins: 0, losses: 0 });
                    if (all.losses === 0) return all.wins > 0 ? '∞' : '—';
                    return (all.wins / all.losses).toFixed(2);
                  })()}
                </Typography>
              </Box>
            </Box>

            <Box sx={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={pnlData}>
                  <defs>
                    <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={C.primary} stopOpacity={0.5} />
                      <stop offset="50%" stopColor={C.accent} stopOpacity={0.25} />
                      <stop offset="100%" stopColor={C.accent} stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="pnlStroke" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor={C.primary} />
                      <stop offset="100%" stopColor={C.accent} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 6" stroke="rgba(99,102,241,0.08)" />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: C.textDim }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: C.textDim }} axisLine={false} tickLine={false} />
                  <ReTooltip />
                  <Area
                    type="monotone"
                    dataKey="cumulative"
                    name="累積 PnL"
                    stroke="url(#pnlStroke)"
                    fill="url(#pnlGradient)"
                    strokeWidth={2.5}
                    dot={{ fill: C.accent, r: 0 }}
                    activeDot={{ r: 5, fill: C.accent, stroke: '#fff', strokeWidth: 2 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Box>
          </Box>
        </Grid>

        <Grid item xs={12} md={4}>
          <Box className="glass-card" sx={{ p: 2.5, position: 'relative', overflow: 'hidden', height: '100%' }}>
            <CornerDecor position="tl" />
            <CornerDecor position="tr" />

            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 2 }}>
              <Box>
                <Typography variant="overline" sx={{ color: 'text.secondary' }}>BTC · LIVE</Typography>
                <Typography
                  className="num-mono"
                  variant="h5"
                  sx={{ fontWeight: 700, color: C.warning, textShadow: '0 0 16px rgba(245,158,11,0.3)' }}
                >
                  ${(btcPrice?.price || 0).toLocaleString()}
                </Typography>
              </Box>
              {btcPrice && (
                <Box sx={{ textAlign: 'right' }}>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>24H</Typography>
                  <Typography
                    className="num-mono"
                    sx={{
                      fontSize: '0.95rem', fontWeight: 600,
                      color: btcPrice.change_24h >= 0 ? C.success : C.error,
                    }}
                  >
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
                      <stop offset="0%" stopColor={C.warning} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={C.warning} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 6" stroke="rgba(99,102,241,0.08)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: C.textDim }} axisLine={false} tickLine={false} />
                  <YAxis
                    domain={['dataMin - 500', 'dataMax + 500']}
                    tick={{ fontSize: 10, fill: C.textDim }}
                    axisLine={false} tickLine={false}
                    tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
                  />
                  <ReTooltip formatter={(value) => [`$${value.toLocaleString()}`, 'BTC']} />
                  <Area
                    type="monotone" dataKey="price"
                    stroke={C.warning}
                    fill="url(#btcGradient)"
                    strokeWidth={2}
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Box>
          </Box>
        </Grid>
      </Grid>

      {/* 策略表現面板 */}
      <Box className="glass-card" sx={{ p: 2.5, mb: 3, position: 'relative', overflow: 'hidden' }}>
        <CornerDecor position="tl" />
        <CornerDecor position="tr" />
        <CornerDecor position="bl" />
        <CornerDecor position="br" />

        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Box>
            <Typography variant="overline" sx={{ color: 'text.secondary' }}>策略表現</Typography>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              STRATEGY MATRIX
              <Typography component="span" variant="caption" sx={{ ml: 1.5, color: 'text.secondary', fontWeight: 400 }}>
                {perfList.length} active modules
              </Typography>
            </Typography>
          </Box>
        </Box>

        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>策略</TableCell>
                <TableCell>類型</TableCell>
                <TableCell>狀態</TableCell>
                <TableCell align="right">交易</TableCell>
                <TableCell align="right">勝率</TableCell>
                <TableCell align="right">累積 PnL</TableCell>
                <TableCell align="right">平均</TableCell>
                <TableCell align="right">P.F.</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sortedPerf.map((s) => {
                const cat = CATEGORY_META[s.category] || { label: s.category, color: C.textDim, bg: 'transparent' };
                return (
                  <TableRow
                    key={s.id}
                    hover
                    sx={{
                      '&:hover': { background: 'rgba(99,102,241,0.04)' },
                      borderLeft: s.has_open_position ? `3px solid ${C.success}` : '3px solid transparent',
                      transition: 'all 200ms',
                    }}
                  >
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        {s.has_open_position && <PulseDot color={C.success} size={6} />}
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>{s.name}</Typography>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Box sx={{
                        display: 'inline-flex', alignItems: 'center',
                        px: 1, py: 0.25, borderRadius: 1,
                        bgcolor: cat.bg, color: cat.color,
                        fontSize: 10, fontWeight: 700,
                        letterSpacing: 0.6,
                        border: `1px solid ${cat.color}33`,
                      }}>
                        {cat.label}
                      </Box>
                    </TableCell>
                    <TableCell>
                      {s.status === 'running' ? (
                        <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                          <Box className="pulse-dot" sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: C.success, boxShadow: `0 0 8px ${C.success}` }} />
                          <Typography variant="caption" sx={{ color: C.success, fontWeight: 600 }}>ACTIVE</Typography>
                        </Box>
                      ) : (
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>STOPPED</Typography>
                      )}
                    </TableCell>
                    <TableCell align="right" className="num-mono" sx={{ color: 'text.secondary' }}>
                      {s.total_trades}
                    </TableCell>
                    <TableCell align="right" className="num-mono">
                      {s.total_trades > 0
                        ? <span style={{ color: s.win_rate >= 50 ? C.success : s.win_rate >= 40 ? C.warning : C.error }}>{s.win_rate}%</span>
                        : <span style={{ color: C.textDim }}>—</span>}
                    </TableCell>
                    <TableCell align="right">
                      <PerfChip pnl={s.total_pnl} withGlow={Math.abs(s.total_pnl) > 10} />
                    </TableCell>
                    <TableCell align="right" className="num-mono">
                      {s.total_trades > 0 ? (
                        <span style={{ color: s.avg_pnl >= 0 ? C.success : C.error, fontSize: '0.8rem' }}>
                          {s.avg_pnl >= 0 ? '+' : ''}${s.avg_pnl}
                        </span>
                      ) : <span style={{ color: C.textDim }}>—</span>}
                    </TableCell>
                    <TableCell align="right" className="num-mono" sx={{ fontSize: '0.8rem' }}>
                      {s.profit_factor != null && s.total_trades > 0 ? s.profit_factor : <span style={{ color: C.textDim }}>—</span>}
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
      </Box>

      {/* 持倉表 */}
      <Box className="glass-card" sx={{ p: 2.5, position: 'relative', overflow: 'hidden' }}>
        <CornerDecor position="tl" />
        <CornerDecor position="br" />

        <Box sx={{ mb: 2 }}>
          <Typography variant="overline" sx={{ color: 'text.secondary' }}>當前持倉</Typography>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            OPEN POSITIONS
            <Typography component="span" variant="caption" sx={{ ml: 1.5, color: 'text.secondary', fontWeight: 400 }}>
              {positions.length} active
            </Typography>
          </Typography>
        </Box>

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
                  <TableCell colSpan={7} align="center" sx={{ py: 5, color: 'text.secondary' }}>
                    <Typography variant="body2">目前無持倉</Typography>
                    <Typography variant="caption">等待策略觸發信號⋯</Typography>
                  </TableCell>
                </TableRow>
              ) : (
                positions.map((pos) => {
                  const stratName = sortedPerf.find((p) => p.id === pos.strategy_id)?.name || `#${pos.strategy_id}`;
                  return (
                    <TableRow key={pos.id} hover sx={{ '&:hover': { background: 'rgba(99,102,241,0.04)' } }}>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <PulseDot color={pos.side === 'long' ? C.success : C.error} size={6} />
                          <Typography variant="body2" sx={{ fontWeight: 500 }}>{stratName}</Typography>
                        </Box>
                      </TableCell>
                      <TableCell className="num-mono">{pos.symbol}</TableCell>
                      <TableCell>
                        <Box sx={{
                          display: 'inline-flex', alignItems: 'center',
                          px: 1, py: 0.25, borderRadius: 1,
                          bgcolor: pos.side === 'long' ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                          color: pos.side === 'long' ? C.success : C.error,
                          fontSize: 10, fontWeight: 700, letterSpacing: 0.6,
                          border: `1px solid ${pos.side === 'long' ? C.success : C.error}33`,
                        }}>
                          {pos.side === 'long' ? '◤ LONG' : '◣ SHORT'}
                        </Box>
                      </TableCell>
                      <TableCell align="right" className="num-mono">{pos.size}</TableCell>
                      <TableCell align="right" className="num-mono">${(pos.entry_price || 0).toLocaleString()}</TableCell>
                      <TableCell align="right" className="num-mono">${(pos.current_price || 0).toLocaleString()}</TableCell>
                      <TableCell align="right">
                        <PerfChip pnl={pos.unrealized_pnl} withGlow />
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>
    </Box>
  );
}
