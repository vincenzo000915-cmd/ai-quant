import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Chip, LinearProgress, Button,
  IconButton, Tooltip,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer, Legend,
} from 'recharts';

// ===== GLOBAL STYLE OVERRIDE for Recharts tooltips =====
// Recharts injects inline styles that override contentStyle props
const tooltipStyle = document.createElement('style');
tooltipStyle.textContent = `
  .recharts-default-tooltip {
    background-color: #0d0d1a !important;
    border: 1px solid rgba(0, 240, 255, 0.4) !important;
    border-radius: 8px !important;
    box-shadow: 0 0 20px rgba(0, 240, 255, 0.2) !important;
    padding: 10px 14px !important;
  }
  .recharts-tooltip-label {
    color: #00f0ff !important;
    font-weight: 700 !important;
    font-size: 13px !important;
    margin-bottom: 6px !important;
  }
  .recharts-tooltip-item {
    color: #ffffff !important;
  }
  .recharts-tooltip-item-value {
    color: #00e5ff !important;
  }
  .recharts-tooltip-item-list {
    margin: 0 !important;
    padding: 0 !important;
  }
`;
document.head.appendChild(tooltipStyle);
// =======================================================

const API = process.env.REACT_APP_API_URL || '';

export default function Dashboard() {
  const [account, setAccount] = useState(null);
  const [btcPrice, setBtcPrice] = useState(null);
  const [btcChart, setBtcChart] = useState([]);
  const [positions, setPositions] = useState([]);
  const [pnlData, setPnlData] = useState([]);
  const [loading, setLoading] = useState(true);

  // --- PnL mock generator ---
  const generatePnlData = useCallback(() => {
    const now = Date.now();
    const data = [];
    let cum = 0;
    for (let i = 29; i >= 0; i--) {
      const pnl = (Math.random() - 0.45) * 2000;
      cum += pnl;
      data.push({
        date: new Date(now - i * 86400000).toISOString().slice(5, 10),
        daily: Math.round(pnl * 100) / 100,
        cumulative: Math.round(cum * 100) / 100,
      });
    }
    return data;
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [acctRes, priceRes, posRes] = await Promise.allSettled([
        fetch(`${API}/api/account`),
        fetch(`${API}/api/market/btc-price`),
        fetch(`${API}/api/positions`),
      ]);

      if (acctRes.status === 'fulfilled') {
        const json = await acctRes.value.json();
        setAccount(json);
      } else {
        setAccount(null);
      }

      if (priceRes.status === 'fulfilled') {
        const json = await priceRes.value.json();
        setBtcPrice(json);
      } else {
        setBtcPrice(null);
      }

      if (posRes.status === 'fulfilled') {
        const json = await posRes.value.json();
        setPositions(Array.isArray(json) ? json : []);
      } else {
        setPositions([]);
      }

      // BTC 歷史圖表（額外請求，每30秒刷新）
      try {
        const chartRes = await fetch(`${API}/api/market/btc-chart`);
        if (chartRes.ok) {
          const chartJson = await chartRes.json();
          setBtcChart(Array.isArray(chartJson) ? chartJson : []);
        }
      } catch {/* ignore */}
    } catch {
      setAccount(null);
      setBtcPrice(null);
      setPositions([]);
    }
    setPnlData(generatePnlData());
    setLoading(false);
  }, [generatePnlData]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const StatCard = ({ title, value, subtitle, icon, color }) => (
    <Card sx={{ height: '100%', bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
      <CardContent sx={{ display: 'flex', alignItems: 'flex-start', gap: { xs: 1, sm: 2 }, px: { xs: 1.5, sm: 2 }, py: { xs: 1.5, sm: 2 } }}>
        <Box sx={{ p: { xs: 1, sm: 1.5 }, borderRadius: 2, bgcolor: `${color}20` }}>
          {React.cloneElement(icon, { sx: { fontSize: { xs: 20, sm: 24 } } })}
        </Box>
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: { xs: '0.65rem', sm: '0.75rem' } }}>{title}</Typography>
          <Typography variant="h5" fontWeight={700} sx={{ mt: 0.5, fontSize: { xs: '1rem', sm: '1.4rem' }, wordBreak: 'break-all' }}>
            {value}
          </Typography>
          {subtitle && (
            <Typography variant="caption" color="text.secondary" sx={{ fontSize: { xs: '0.6rem', sm: '0.75rem' } }}>{subtitle}</Typography>
          )}
        </Box>
      </CardContent>
    </Card>
  );

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: { xs: 1.5, sm: 3 } }}>
        <Typography variant="h5" fontWeight={700} sx={{ fontSize: { xs: '1rem', sm: '1.4rem' } }}>帳戶概覽</Typography>
        <Tooltip title="重新整理">
          <IconButton onClick={fetchData} color="primary" size="small">
            <RefreshIcon sx={{ fontSize: { xs: 20, sm: 24 } }} />
          </IconButton>
        </Tooltip>
      </Box>

      {/* Loading */}
      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {/* KPI Cards */}
      <Grid container spacing={{ xs: 1, sm: 2.5 }} sx={{ mb: { xs: 1.5, sm: 3 } }}>
        <Grid item xs={6} md={3}>
          <StatCard
            title="帳戶餘額"
            value={account ? `$${(account.balance || 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}` : '---'}
            subtitle="USDT"
            icon={<AccountBalanceWalletIcon />}
            color="primary"
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard
            title="權益總額"
            value={account ? `$${(account.equity || 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}` : '---'}
            subtitle="USDT"
            icon={<ShowChartIcon />}
            color="success"
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard
            title="未實現 PnL"
            value={account ? `$${(account.unrealized_pnl || 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}` : '---'}
            subtitle="USDT"
            icon={account?.unrealized_pnl >= 0 ? <TrendingUpIcon /> : <TrendingDownIcon />}
            color={account?.unrealized_pnl >= 0 ? 'success' : 'error'}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard
            title="BTC 價格"
            value={btcPrice ? `$${(btcPrice.price || 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}` : '---'}
            subtitle={btcPrice ? `24h: ${btcPrice.change_24h >= 0 ? '+' : ''}${(btcPrice.change_24h || 0).toFixed(2)}%` : ''}
            icon={<ShowChartIcon />}
            color={btcPrice?.change_24h >= 0 ? 'success' : 'error'}
          />
        </Grid>
      </Grid>

      {/* Charts Row */}
      <Grid container spacing={{ xs: 1, sm: 2.5 }} sx={{ mb: { xs: 1.5, sm: 3 } }}>
        <Grid item xs={12} md={8}>
          <Card sx={{ bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
            <CardContent sx={{ px: { xs: 1, sm: 2 }, py: { xs: 1.5, sm: 2 } }}>
              <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1, fontSize: { xs: '0.85rem', sm: '1rem' } }}>累積 PnL (30天)</Typography>
              <Box sx={{ height: { xs: 180, sm: 300 } }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={pnlData}>
                    <defs>
                      <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#00e5ff" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#00e5ff" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" tick={{ fontSize: { xs: 9, sm: 11 }, fill: '#9e9e9e' }} />
                    <YAxis tick={{ fontSize: { xs: 9, sm: 11 }, fill: '#9e9e9e' }} />
                    <ReTooltip
                      contentStyle={{ bgcolor: '#0d0d1a', border: '1px solid rgba(0,240,255,0.4)', borderRadius: 8, color: '#e0e0e0', boxShadow: '0 0 20px rgba(0,240,255,0.2)' }}
                      labelStyle={{ color: '#00f0ff', fontWeight: 700, fontSize: 13 }}
                      itemStyle={{ color: '#ffffff' }}
                    />
                    <Area type="monotone" dataKey="cumulative" stroke="#00e5ff" fill="url(#pnlGradient)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </Box>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card sx={{ bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
            <CardContent sx={{ px: { xs: 1, sm: 2 }, py: { xs: 1.5, sm: 2 } }}>
              <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1, fontSize: { xs: '0.85rem', sm: '1rem' } }}>
                BTC 價格走勢 (即時)
                {btcPrice && (
                  <Typography component="span" variant="caption" color={btcPrice.change_24h >= 0 ? 'success.main' : 'error.main'} sx={{ ml: 1 }}>
                    ${(btcPrice.price || 0).toLocaleString()} ({btcPrice.change_24h >= 0 ? '+' : ''}{btcPrice.change_24h?.toFixed(2)}%)
                  </Typography>
                )}
                <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1, fontSize: '0.65rem' }}>
                  即時·每30秒更新
                </Typography>
              </Typography>
              <Box sx={{ height: { xs: 180, sm: 300 } }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={btcChart}>
                    <defs>
                      <linearGradient id="btcGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f7931a" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#f7931a" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" tick={{ fontSize: { xs: 8, sm: 10 }, fill: '#9e9e9e' }} />
                    <YAxis domain={['dataMin - 500', 'dataMax + 500']} tick={{ fontSize: { xs: 8, sm: 10 }, fill: '#9e9e9e' }} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                    <ReTooltip
                      contentStyle={{ bgcolor: '#0d0d1a', border: '1px solid rgba(247,147,26,0.4)', borderRadius: 8, color: '#e0e0e0', boxShadow: '0 0 20px rgba(247,147,26,0.2)' }}
                      labelStyle={{ color: '#f7931a', fontWeight: 700, fontSize: 13 }}
                      itemStyle={{ color: '#ffffff' }}
                      formatter={(value) => [`$${value.toLocaleString()}`, 'BTC']}
                    />
                    <Area type="monotone" dataKey="price" stroke="#f7931a" fill="url(#btcGradient)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Positions Table - scrollable horizontally on mobile */}
      <Card sx={{ bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
        <CardContent sx={{ px: { xs: 1, sm: 2 }, py: { xs: 1.5, sm: 2 } }}>
          <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1, fontSize: { xs: '0.85rem', sm: '1rem' } }}>持倉列表</Typography>
          <TableContainer component={Paper} sx={{ bgcolor: 'transparent', boxShadow: 'none' }}>
            <Table size="small" sx={{ minWidth: { xs: 500, sm: 'auto' } }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: { xs: '0.7rem', sm: '0.8rem' }, px: { xs: 0.5, sm: 1 } }}>交易對</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: { xs: '0.7rem', sm: '0.8rem' }, px: { xs: 0.5, sm: 1 } }}>方向</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: { xs: '0.7rem', sm: '0.8rem' }, px: { xs: 0.5, sm: 1 } }} align="right">倉位</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: { xs: '0.7rem', sm: '0.8rem' }, px: { xs: 0.5, sm: 1 } }} align="right">開倉價</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: { xs: '0.7rem', sm: '0.8rem' }, px: { xs: 0.5, sm: 1 } }} align="right">標記價</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: { xs: '0.7rem', sm: '0.8rem' }, px: { xs: 0.5, sm: 1 } }} align="right">PnL</TableCell>
                  <TableCell sx={{ color: 'text.secondary', fontWeight: 600, fontSize: { xs: '0.7rem', sm: '0.8rem' }, px: { xs: 0.5, sm: 1 } }} align="right">PnL%</TableCell>
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
                  positions.map((pos, i) => (
                    <TableRow key={i} sx={{ '&:hover': { bgcolor: 'rgba(255,255,255,0.03)' } }}>
                      <TableCell sx={{ px: { xs: 0.5, sm: 1 }, fontSize: { xs: '0.7rem', sm: '0.8rem' } }}>
                        <Typography variant="body2" fontWeight={600} sx={{ fontSize: { xs: '0.7rem', sm: '0.8rem' } }}>{pos.symbol}</Typography>
                      </TableCell>
                      <TableCell sx={{ px: { xs: 0.5, sm: 1 } }}>
                        <Chip
                          label={pos.side === 'long' ? '做多' : '做空'}
                          size="small"
                          color={pos.side === 'long' ? 'success' : 'error'}
                          variant="outlined"
                          sx={{ fontWeight: 600, fontSize: { xs: 9, sm: 11 }, height: { xs: 20, sm: 24 } }}
                        />
                      </TableCell>
                      <TableCell sx={{ px: { xs: 0.5, sm: 1 }, fontSize: { xs: '0.7rem', sm: '0.8rem' } }} align="right">{pos.size}</TableCell>
                      <TableCell sx={{ px: { xs: 0.5, sm: 1 }, fontSize: { xs: '0.7rem', sm: '0.8rem' } }} align="right">${(pos.entry_price || 0).toLocaleString()}</TableCell>
                      <TableCell sx={{ px: { xs: 0.5, sm: 1 }, fontSize: { xs: '0.7rem', sm: '0.8rem' } }} align="right">${(pos.mark_price || 0).toLocaleString()}</TableCell>
                      <TableCell sx={{ px: { xs: 0.5, sm: 1 }, fontSize: { xs: '0.7rem', sm: '0.8rem' } }} align="right">
                        <Typography variant="body2" fontWeight={600} color={pos.pnl >= 0 ? 'success.main' : 'error.main'} sx={{ fontSize: { xs: '0.7rem', sm: '0.8rem' } }}>
                          {pos.pnl >= 0 ? '+' : ''}${(pos.pnl || 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ px: { xs: 0.5, sm: 1 }, fontSize: { xs: '0.7rem', sm: '0.8rem' } }} align="right">
                        <Typography variant="body2" fontWeight={600} color={pos.pnl_percent >= 0 ? 'success.main' : 'error.main'} sx={{ fontSize: { xs: '0.7rem', sm: '0.8rem' } }}>
                          {pos.pnl_percent >= 0 ? '+' : ''}{(pos.pnl_percent || 0).toFixed(2)}%
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    </Box>
  );
}
