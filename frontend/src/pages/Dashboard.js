import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Box, Grid, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, LinearProgress,
  IconButton, Tooltip,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import BoltIcon from '@mui/icons-material/Bolt';
import EmojiEventsIcon from '@mui/icons-material/EmojiEvents';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import MemoryIcon from '@mui/icons-material/Memory';
import SpeedIcon from '@mui/icons-material/Speed';
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer,
} from 'recharts';

const API = process.env.REACT_APP_API_URL || '';

const C = {
  primary: '#6366f1',
  primaryGlow: 'rgba(99, 102, 241, 0.6)',
  accent: '#06b6d4',
  accentGlow: 'rgba(6, 182, 212, 0.55)',
  pink: '#ec4899',
  purple: '#a855f7',
  gold: '#fbbf24',
  goldDeep: '#f59e0b',
  warnYellow: '#facc15',
  success: '#22c55e',
  error: '#ef4444',
  errorBright: '#ff3355',
  warning: '#f59e0b',
  text: '#e2e8f0',
  textDim: '#94a3b8',
  textFaint: '#475569',
  border: 'rgba(99, 102, 241, 0.2)',
};

const CATEGORY_META = {
  ultra: { label: '◢ ULTRA',  color: C.purple, bg: 'rgba(168, 85, 247, 0.15)' },
  short: { label: '◤ SHORT',  color: C.error,  bg: 'rgba(239, 68, 68, 0.15)' },
  swing: { label: '◇ SWING',  color: C.gold,   bg: 'rgba(251, 191, 36, 0.15)' },
  long:  { label: '◆ LONG',   color: C.success,bg: 'rgba(34, 197, 94, 0.15)' },
};

// 戰術角裝飾
const CornerDecor = ({ position = 'tl', color = C.primary, size = 14 }) => {
  const styles = {
    tl: { top: -1, left: -1, borderTop: `2px solid ${color}`, borderLeft: `2px solid ${color}` },
    tr: { top: -1, right: -1, borderTop: `2px solid ${color}`, borderRight: `2px solid ${color}` },
    bl: { bottom: -1, left: -1, borderBottom: `2px solid ${color}`, borderLeft: `2px solid ${color}` },
    br: { bottom: -1, right: -1, borderBottom: `2px solid ${color}`, borderRight: `2px solid ${color}` },
  };
  return (
    <Box sx={{
      position: 'absolute', width: size, height: size,
      filter: `drop-shadow(0 0 6px ${color}88)`,
      ...styles[position],
      pointerEvents: 'none',
    }} />
  );
};

const PulseDot = ({ color = C.success, size = 8 }) => (
  <Box sx={{ position: 'relative', width: size, height: size, display: 'inline-block', flexShrink: 0 }}>
    <Box className="pulse-dot" sx={{
      width: size, height: size, borderRadius: '50%',
      bgcolor: color, position: 'absolute',
      color,
    }} />
  </Box>
);

// 雷達脈衝（活躍狀態用）
const RadarPulse = ({ color = C.success }) => (
  <Box className="radar-pulse-container">
    <Box className="radar-pulse-ring" sx={{ borderColor: color }} />
    <Box className="radar-pulse-ring" sx={{ borderColor: color }} />
    <Box className="radar-pulse-dot" sx={{ bgcolor: color, boxShadow: `0 0 8px ${color}` }} />
  </Box>
);

// 跑馬燈
const Ticker = ({ btcPrice, account, pnlSummary }) => {
  const items = [
    btcPrice && `BTC/USDT $${btcPrice.price?.toLocaleString()} ${btcPrice.change_24h >= 0 ? '+' : ''}${btcPrice.change_24h?.toFixed(2)}%`,
    btcPrice && `24H HIGH $${btcPrice.high_24h?.toLocaleString()}`,
    btcPrice && `24H LOW $${btcPrice.low_24h?.toLocaleString()}`,
    `SIMULATION MODE · LEV 15×`,
    account && `BAL $${account.balance?.toFixed(2)} USDT`,
    pnlSummary && `TRADES ${pnlSummary.total_trades} · WIN ${pnlSummary.win_rate}%`,
    pnlSummary && `OPEN POS ${pnlSummary.open_positions}`,
    `OKX · BTC-USDT-SWAP`,
    `RISK PROFILE: HIGH`,
    `ENGINE v0.1.0-alpha`,
  ].filter(Boolean);
  const text = items.join('   ◆   ');
  return (
    <Box sx={{
      overflow: 'hidden',
      whiteSpace: 'nowrap',
      bgcolor: 'rgba(8, 10, 24, 0.6)',
      backdropFilter: 'blur(12px)',
      border: `1px solid ${C.border}`,
      borderRadius: 1,
      py: 0.75, px: 0,
      mb: 2,
      position: 'relative',
    }}>
      <Box className="ticker-content" sx={{
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: '0.72rem',
        color: C.textDim,
        letterSpacing: 0.3,
      }}>
        <span style={{ marginRight: 24 }}>{text}</span>
        <span>{text}</span>
      </Box>
      {/* 漸層遮罩兩端 */}
      <Box sx={{
        position: 'absolute', left: 0, top: 0, bottom: 0, width: 60,
        background: 'linear-gradient(90deg, rgba(8,10,24,0.95), transparent)',
        pointerEvents: 'none',
      }} />
      <Box sx={{
        position: 'absolute', right: 0, top: 0, bottom: 0, width: 60,
        background: 'linear-gradient(-90deg, rgba(8,10,24,0.95), transparent)',
        pointerEvents: 'none',
      }} />
    </Box>
  );
};

// 系統狀態小指標
const SysStatBlock = ({ label, value, suffix = '', accent = C.primary, icon }) => (
  <Box sx={{
    display: 'flex', alignItems: 'center', gap: 1,
    px: 1.25, py: 0.75,
    borderLeft: `2px solid ${accent}`,
    background: 'rgba(8, 10, 24, 0.4)',
    backdropFilter: 'blur(8px)',
    minWidth: 0,
  }}>
    {icon && React.cloneElement(icon, { sx: { fontSize: 14, color: accent } })}
    <Box sx={{ minWidth: 0 }}>
      <Typography sx={{ fontSize: '0.6rem', color: C.textFaint, lineHeight: 1, letterSpacing: 0.8, textTransform: 'uppercase', fontWeight: 600 }}>
        {label}
      </Typography>
      <Typography className="num-mono" sx={{ fontSize: '0.85rem', color: accent, fontWeight: 700, lineHeight: 1.2 }}>
        {value}{suffix}
      </Typography>
    </Box>
  </Box>
);

// Mini sparkline（策略表格用）
const Sparkline = ({ data, color, width = 60, height = 20 }) => {
  if (!data || data.length < 2) return <Box sx={{ width, height, opacity: 0.3, color: C.textFaint, fontFamily: 'JetBrains Mono', fontSize: 10, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>— — —</Box>;
  return (
    <Box className="spark-cell" sx={{ width, height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </Box>
  );
};

// 假的系統指標（之後接真的）
function useSystemStats() {
  const [stats, setStats] = useState({ uptime: 0, latency: 0, cpu: 0, ram: 0, signalQ: 0, net: 0 });
  useEffect(() => {
    const start = Date.now();
    const tick = () => {
      setStats({
        uptime: Math.floor((Date.now() - start) / 1000),
        latency: 18 + Math.floor(Math.random() * 30),
        cpu: 22 + Math.floor(Math.random() * 15),
        ram: 41 + Math.floor(Math.random() * 8),
        signalQ: Math.floor(Math.random() * 4),
        net: 1.2 + Math.random() * 0.8,
      });
    };
    tick();
    const interval = setInterval(tick, 2500);
    return () => clearInterval(interval);
  }, []);
  return stats;
}

function formatUptime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

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
  const sysStats = useSystemStats();

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
      } catch {/* */}

      setLastUpdate(new Date());
    } catch { /* */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const sortedPerf = useMemo(() => {
    return [...perfList].sort((a, b) => {
      // 1. 持倉中 > 沒持倉
      if (a.has_open_position !== b.has_open_position) return a.has_open_position ? -1 : 1;
      // 2. 運行中 > 停止
      if ((a.status === 'running') !== (b.status === 'running')) return a.status === 'running' ? -1 : 1;
      // 3. Backtest Sharpe 高 > 低
      const sa = a.backtest?.sharpe_ratio ?? -999;
      const sb = b.backtest?.sharpe_ratio ?? -999;
      return sb - sa;
    });
  }, [perfList]);

  // BTC sparkline data（從 btcChart 拿最後 30 點）
  const btcSpark = useMemo(() => {
    return (btcChart || []).slice(-30).map(d => ({ v: d.price }));
  }, [btcChart]);

  const utcTime = lastUpdate
    ? lastUpdate.toISOString().slice(11, 19) + ' UTC'
    : '——:——:—— UTC';

  // KPI Card
  const KPICard = ({ label, value, sublabel, icon, accent = 'primary', glow = false, highlight = false, sparkData, sparkColor }) => {
    const accentMap = {
      primary: { color: C.primary, glow: C.primaryGlow, glowClass: 'glow-text-primary' },
      success: { color: C.success, glow: 'rgba(34,197,94,0.55)', glowClass: 'glow-text-success' },
      error:   { color: C.error,   glow: 'rgba(239,68,68,0.55)', glowClass: 'glow-text-error' },
      warning: { color: C.warning, glow: 'rgba(245,158,11,0.55)', glowClass: 'glow-text-gold' },
      accent:  { color: C.accent,  glow: C.accentGlow, glowClass: 'glow-text-accent' },
      gold:    { color: C.gold,    glow: 'rgba(251,191,36,0.55)', glowClass: 'glow-text-gold' },
    };
    const a = accentMap[accent] || accentMap.primary;
    return (
      <Box
        className={highlight ? 'glow-border glass-card' : 'glass-card'}
        sx={{ p: 2, height: '100%', position: 'relative', overflow: 'hidden' }}
      >
        <CornerDecor position="tl" color={a.color} />
        <CornerDecor position="br" color={a.color} />

        <Box sx={{
          position: 'absolute', top: -30, right: -30, width: 140, height: 140,
          background: `radial-gradient(circle, ${a.glow} 0%, transparent 70%)`,
          opacity: 0.3, pointerEvents: 'none',
        }} />

        <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 1, position: 'relative' }}>
          <Typography variant="overline" sx={{ color: 'text.secondary', lineHeight: 1 }}>
            {label}
          </Typography>
          <Box sx={{
            width: 30, height: 30, borderRadius: 1.25,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            bgcolor: `${a.color}1a`, color: a.color,
            border: `1px solid ${a.color}40`,
            boxShadow: `0 0 12px ${a.color}30`,
          }}>
            {React.cloneElement(icon, { sx: { fontSize: 16 } })}
          </Box>
        </Box>

        <Typography
          className={`num-mono ${glow ? a.glowClass : ''}`}
          sx={{
            fontSize: { xs: '1.3rem', sm: '1.65rem' },
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
          <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.7rem', position: 'relative', display: 'block' }}>
            {sublabel}
          </Typography>
        )}

        {sparkData && sparkData.length > 1 && (
          <Box sx={{ mt: 1, height: 28, opacity: 0.7 }}>
            <Sparkline data={sparkData} color={sparkColor || a.color} width="100%" height="100%" />
          </Box>
        )}
      </Box>
    );
  };

  return (
    <Box sx={{ position: 'relative', zIndex: 1 }}>
      {/* === Live Ticker === */}
      <Ticker btcPrice={btcPrice} account={account} pnlSummary={pnlSummary} />

      {/* === System Status Strip === */}
      <Box sx={{
        display: 'grid',
        gridTemplateColumns: { xs: 'repeat(3, 1fr)', sm: 'repeat(6, 1fr)' },
        gap: 1,
        mb: 2.5,
        border: `1px solid ${C.border}`,
        borderRadius: 1.5,
        overflow: 'hidden',
        background: 'rgba(8, 10, 24, 0.3)',
        backdropFilter: 'blur(12px)',
      }}>
        <SysStatBlock label="UPTIME"    value={formatUptime(sysStats.uptime)} accent={C.success}  icon={<SpeedIcon />} />
        <SysStatBlock label="LATENCY"   value={sysStats.latency}  suffix="ms" accent={C.accent}   icon={<BoltIcon />} />
        <SysStatBlock label="CPU"       value={sysStats.cpu}      suffix="%"  accent={sysStats.cpu > 70 ? C.error : C.primary} icon={<MemoryIcon />} />
        <SysStatBlock label="RAM"       value={sysStats.ram}      suffix="%"  accent={C.primary} icon={<MemoryIcon />} />
        <SysStatBlock label="SIGNAL Q"  value={sysStats.signalQ}             accent={C.gold}    icon={<BoltIcon />} />
        <SysStatBlock label="NET"       value={sysStats.net.toFixed(1)} suffix="MB/s" accent={C.purple} icon={<SpeedIcon />} />
      </Box>

      {/* === Tactical Header === */}
      <Box sx={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        mb: 2.5, pb: 2, borderBottom: `1px solid ${C.border}`,
        position: 'relative',
      }}>
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 0.5 }}>
            <PulseDot color={C.success} />
            <Typography variant="overline" sx={{ color: C.success }}>
              LIVE · SIMULATION ACTIVE
            </Typography>
            <Box sx={{
              ml: 1, px: 1, py: 0.25, borderRadius: 0.5,
              fontSize: '0.6rem', fontWeight: 700, letterSpacing: 1,
              color: '#000',
              background: 'linear-gradient(135deg, #facc15, #f59e0b)',
              boxShadow: '0 0 12px rgba(250, 204, 21, 0.5)',
            }}>
              ⚠ HIGH RISK · 15× LEV
            </Box>
          </Box>
          <Typography
            variant="h4"
            sx={{
              fontWeight: 800,
              background: `linear-gradient(135deg, ${C.primary} 0%, ${C.accent} 50%, ${C.purple} 100%)`,
              backgroundClip: 'text',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              fontSize: { xs: '1.4rem', sm: '2rem' },
              letterSpacing: -0.5,
              display: 'inline-flex',
              alignItems: 'baseline',
            }}
          >
            QUANT_TERMINAL
            <Box component="span" className="caret" sx={{ height: '0.85em' }} />
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontFamily: 'JetBrains Mono, monospace', fontSize: '0.7rem' }}>
            OKX · BTC/USDT · ENGINE v0.1.0 · {utcTime}
          </Typography>
        </Box>
        <Tooltip title="立即刷新">
          <IconButton
            onClick={fetchData}
            sx={{
              border: `1px solid ${C.border}`,
              color: C.primary,
              boxShadow: '0 0 16px rgba(99,102,241,0.2)',
              '&:hover': { background: 'rgba(99,102,241,0.15)', borderColor: 'rgba(99,102,241,0.6)' },
            }}
          >
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      {loading && <LinearProgress sx={{ mb: 2, height: 2, borderRadius: 1 }} />}

      {/* === KPI Cards === */}
      <Grid container spacing={2} sx={{ mb: 2.5 }}>
        <Grid item xs={6} md={3}>
          <KPICard
            label="帳戶餘額"
            value={account ? `$${(account.balance || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '———'}
            sublabel={pnlSummary != null
              ? `${pnlSummary.unrealized_pnl >= 0 ? '+' : ''}$${pnlSummary.unrealized_pnl.toFixed(2)} 未實現`
              : 'USDT'}
            icon={<AccountBalanceWalletIcon />}
            accent="primary"
            glow
            sparkData={pnlData.slice(-15).map(d => ({ v: d.cumulative }))}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <KPICard
            label="累積 PnL"
            value={pnlSummary
              ? `${pnlSummary.total_pnl >= 0 ? '+' : ''}$${pnlSummary.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
              : '———'}
            sublabel={pnlSummary
              ? `${pnlSummary.total_trades} 筆 · DD -$${pnlSummary.max_drawdown}`
              : '尚未交易'}
            icon={pnlSummary?.total_pnl >= 0 ? <TrendingUpIcon /> : <TrendingDownIcon />}
            accent={pnlSummary?.total_pnl > 0 ? 'success' : pnlSummary?.total_pnl < 0 ? 'error' : 'primary'}
            glow
            highlight
            sparkData={pnlData.slice(-15).map(d => ({ v: d.cumulative }))}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <KPICard
            label="勝率"
            value={pnlSummary ? `${pnlSummary.win_rate.toFixed(1)}%` : '———'}
            sublabel={pnlSummary
              ? `${pnlSummary.winning_trades}W · ${pnlSummary.losing_trades}L`
              : '尚無交易'}
            icon={<EmojiEventsIcon />}
            accent={pnlSummary?.win_rate >= 50 ? 'success' : pnlSummary?.win_rate >= 40 ? 'gold' : 'error'}
            glow
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <KPICard
            label="活躍策略"
            value={pnlSummary ? `${pnlSummary.running_strategies}` : '———'}
            sublabel={pnlSummary ? `${pnlSummary.open_positions} 持倉中 · ${perfList.length} 總數` : ''}
            icon={<BoltIcon />}
            accent="accent"
            glow
          />
        </Grid>
      </Grid>

      {/* === 警告斜紋條 === */}
      <Box className="warning-stripes" sx={{
        py: 0.75, px: 2, mb: 2.5,
        borderRadius: 1,
        display: 'flex', alignItems: 'center', gap: 1.5,
        border: `1px solid rgba(250, 204, 21, 0.3)`,
      }}>
        <WarningAmberIcon sx={{ fontSize: 18, color: C.warnYellow, filter: `drop-shadow(0 0 6px ${C.warnYellow})` }} />
        <Typography variant="caption" sx={{ color: '#fff', fontWeight: 700, letterSpacing: 1, flexGrow: 1, fontFamily: 'JetBrains Mono, monospace', fontSize: '0.72rem' }}>
          ⚠ HIGH LEVERAGE ZONE · 15× · POSITION SIZE $50 · MAX LOSS PER TRADE 5% · MAX GAIN 8% · NOT FINANCIAL ADVICE
        </Typography>
      </Box>

      {/* === Charts Row === */}
      <Grid container spacing={2} sx={{ mb: 2.5 }}>
        <Grid item xs={12} md={8}>
          <Box className="glass-card glow-border" sx={{ p: 2.25, position: 'relative', overflow: 'hidden' }}>
            <CornerDecor position="tl" color={C.primary} />
            <CornerDecor position="tr" color={C.accent} />

            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1.5 }}>
              <Box>
                <Typography variant="overline" sx={{ color: 'text.secondary' }}>累積 PNL · TIMESERIES 30D</Typography>
                <Typography
                  className="num-mono"
                  variant="h5"
                  sx={{
                    fontWeight: 700,
                    color: pnlSummary?.total_pnl >= 0 ? C.success : C.error,
                    textShadow: pnlSummary?.total_pnl !== 0
                      ? `0 0 28px ${pnlSummary?.total_pnl >= 0 ? 'rgba(34,197,94,0.5)' : 'rgba(239,68,68,0.5)'}`
                      : 'none',
                    fontSize: '1.6rem',
                  }}
                >
                  {pnlSummary ? `${pnlSummary.total_pnl >= 0 ? '+' : ''}$${pnlSummary.total_pnl.toFixed(2)}` : '$0.00'}
                </Typography>
              </Box>
              <Box sx={{ textAlign: 'right' }}>
                <Typography variant="overline" sx={{ color: 'text.secondary' }}>MAX DRAWDOWN</Typography>
                <Typography className="num-mono" sx={{ fontSize: '1.05rem', fontWeight: 700, color: C.warning }}>
                  -${(pnlSummary?.max_drawdown || 0).toFixed(2)}
                </Typography>
              </Box>
            </Box>

            <Box sx={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={pnlData}>
                  <defs>
                    <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={C.primary} stopOpacity={0.5} />
                      <stop offset="50%" stopColor={C.accent} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={C.accent} stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="pnlStroke" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor={C.primary} />
                      <stop offset="100%" stopColor={C.accent} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="2 8" stroke="rgba(99,102,241,0.1)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: C.textDim }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: C.textDim }} axisLine={false} tickLine={false} />
                  <ReTooltip />
                  <Area
                    type="monotone" dataKey="cumulative" name="累積 PnL"
                    stroke="url(#pnlStroke)" fill="url(#pnlGradient)"
                    strokeWidth={2.5}
                    activeDot={{ r: 5, fill: C.accent, stroke: '#fff', strokeWidth: 2 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Box>
          </Box>
        </Grid>

        <Grid item xs={12} md={4}>
          <Box className="glass-card" sx={{ p: 2.25, position: 'relative', overflow: 'hidden', height: '100%' }}>
            <CornerDecor position="tl" color={C.gold} />
            <CornerDecor position="tr" color={C.gold} />

            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1.5 }}>
              <Box>
                <Typography variant="overline" sx={{ color: 'text.secondary' }}>BTC · LIVE</Typography>
                <Typography
                  className="num-mono glow-text-gold"
                  variant="h5"
                  sx={{ fontWeight: 700, color: C.gold, fontSize: '1.6rem' }}
                >
                  ${(btcPrice?.price || 0).toLocaleString()}
                </Typography>
              </Box>
              {btcPrice && (
                <Box sx={{ textAlign: 'right' }}>
                  <Typography variant="overline" sx={{ color: 'text.secondary' }}>24H</Typography>
                  <Typography
                    className="num-mono"
                    sx={{
                      fontSize: '1rem', fontWeight: 700,
                      color: btcPrice.change_24h >= 0 ? C.success : C.error,
                    }}
                  >
                    {btcPrice.change_24h >= 0 ? '+' : ''}{(btcPrice.change_24h || 0).toFixed(2)}%
                  </Typography>
                </Box>
              )}
            </Box>

            <Box sx={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={btcChart}>
                  <defs>
                    <linearGradient id="btcGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={C.gold} stopOpacity={0.4} />
                      <stop offset="100%" stopColor={C.gold} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="2 8" stroke="rgba(99,102,241,0.08)" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: C.textDim }} axisLine={false} tickLine={false} />
                  <YAxis
                    domain={['dataMin - 500', 'dataMax + 500']}
                    tick={{ fontSize: 9, fill: C.textDim }}
                    axisLine={false} tickLine={false}
                    tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
                  />
                  <ReTooltip formatter={(value) => [`$${value.toLocaleString()}`, 'BTC']} />
                  <Area
                    type="monotone" dataKey="price"
                    stroke={C.gold}
                    fill="url(#btcGradient)"
                    strokeWidth={2}
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Box>

            {btcPrice && (
              <Box sx={{
                mt: 1.5, pt: 1.5, borderTop: `1px solid ${C.border}`,
                display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 1,
              }}>
                <Box>
                  <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>24H HIGH</Typography>
                  <Typography className="num-mono" sx={{ fontSize: '0.85rem', fontWeight: 600, color: C.success }}>
                    ${btcPrice.high_24h?.toLocaleString()}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>24H LOW</Typography>
                  <Typography className="num-mono" sx={{ fontSize: '0.85rem', fontWeight: 600, color: C.error }}>
                    ${btcPrice.low_24h?.toLocaleString()}
                  </Typography>
                </Box>
              </Box>
            )}
          </Box>
        </Grid>
      </Grid>

      {/* === Strategy Matrix（密集模式）=== */}
      <Box className="glass-card" sx={{ p: 2.25, mb: 2.5, position: 'relative', overflow: 'hidden' }}>
        <CornerDecor position="tl" color={C.primary} />
        <CornerDecor position="tr" color={C.accent} />
        <CornerDecor position="bl" color={C.purple} />
        <CornerDecor position="br" color={C.primary} />

        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
          <Box>
            <Typography variant="overline" sx={{ color: 'text.secondary' }}>STRATEGY MATRIX</Typography>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1 }}>
              [{perfList.length}] ACTIVE MODULES
              <Box component="span" sx={{ color: C.success, ml: 1, fontSize: '0.75rem' }}>
                · {pnlSummary?.running_strategies || 0} RUNNING
              </Box>
              <Box component="span" sx={{ color: C.gold, ml: 1, fontSize: '0.75rem' }}>
                · {pnlSummary?.open_positions || 0} POS
              </Box>
            </Typography>
          </Box>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontFamily: 'JetBrains Mono, monospace' }}>
            SORTED BY: POSITION → PNL → COUNT
          </Typography>
        </Box>

        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 30 }}>#</TableCell>
                <TableCell>策略</TableCell>
                <TableCell>類型</TableCell>
                <TableCell>TF</TableCell>
                <TableCell>狀態</TableCell>
                <TableCell>評級</TableCell>
                <TableCell align="right">BT Sharpe</TableCell>
                <TableCell align="right">BT 年化</TableCell>
                <TableCell align="right">BT MaxDD</TableCell>
                <TableCell align="right">交易</TableCell>
                <TableCell align="right">PnL</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sortedPerf.map((s, i) => {
                const cat = CATEGORY_META[s.category] || { label: s.category, color: C.textDim, bg: 'transparent' };
                const bt = s.backtest;
                const ratingMeta = {
                  excellent:  { label: '⭐ EXCEL', color: '#fbbf24' },
                  good:       { label: '✅ GOOD',  color: '#22c55e' },
                  marginal:   { label: '⚠ MARG',  color: '#94a3b8' },
                  negative:   { label: '❌ NEG',   color: '#ef4444' },
                  liquidated: { label: '💀 LIQD',  color: '#f87171' },
                }[s.rating] || null;
                return (
                  <TableRow
                    key={s.id}
                    hover
                    sx={{
                      '&:hover': { background: 'rgba(99,102,241,0.05)' },
                      borderLeft: s.has_open_position ? `3px solid ${C.success}` : '3px solid transparent',
                      transition: 'all 200ms',
                    }}
                  >
                    <TableCell sx={{ color: C.textFaint, fontFamily: 'JetBrains Mono', fontSize: '0.7rem' }}>
                      {String(i + 1).padStart(2, '0')}
                    </TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                        {s.has_open_position && <PulseDot color={C.success} size={6} />}
                        <Typography variant="body2" sx={{ fontWeight: 500, fontSize: '0.78rem' }}>{s.name}</Typography>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Box sx={{
                        display: 'inline-flex', alignItems: 'center',
                        px: 0.75, py: 0.15, borderRadius: 0.75,
                        bgcolor: cat.bg, color: cat.color,
                        fontSize: 9, fontWeight: 700,
                        letterSpacing: 0.6,
                        border: `1px solid ${cat.color}40`,
                        boxShadow: `0 0 6px ${cat.color}20`,
                      }}>
                        {cat.label}
                      </Box>
                    </TableCell>
                    <TableCell sx={{ fontFamily: 'JetBrains Mono', fontSize: '0.7rem', color: C.textDim }}>
                      {s.timeframe}
                    </TableCell>
                    <TableCell>
                      {s.status === 'running' ? (
                        <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                          <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: C.success, boxShadow: `0 0 6px ${C.success}` }} />
                          <Typography variant="caption" sx={{ color: C.success, fontWeight: 700, fontSize: '0.65rem' }}>ACTIVE</Typography>
                        </Box>
                      ) : (
                        <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>STOPPED</Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      {ratingMeta ? (
                        <Box sx={{
                          display: 'inline-flex',
                          px: 0.75, py: 0.15, borderRadius: 0.75,
                          bgcolor: `${ratingMeta.color}22`,
                          color: ratingMeta.color,
                          fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
                          border: `1px solid ${ratingMeta.color}40`,
                          fontFamily: 'JetBrains Mono, monospace',
                        }}>{ratingMeta.label}</Box>
                      ) : (
                        <Typography variant="caption" sx={{ color: C.textFaint, fontSize: '0.65rem' }}>—</Typography>
                      )}
                    </TableCell>
                    <TableCell align="right" className="num-mono" sx={{ fontSize: '0.78rem' }}>
                      {bt && bt.sharpe_ratio != null ? (
                        <span style={{
                          color: bt.sharpe_ratio >= 3 ? '#fbbf24' : bt.sharpe_ratio >= 1.5 ? C.success : bt.sharpe_ratio >= 0 ? C.textDim : C.error,
                          fontWeight: 600,
                        }}>{bt.sharpe_ratio.toFixed(2)}</span>
                      ) : <span style={{ color: C.textFaint }}>—</span>}
                    </TableCell>
                    <TableCell align="right" className="num-mono" sx={{ fontSize: '0.78rem' }}>
                      {bt && bt.annual_return_pct != null ? (
                        <span style={{
                          color: bt.annual_return_pct >= 50 ? C.success : bt.annual_return_pct >= 0 ? C.textDim : C.error,
                        }}>{bt.annual_return_pct >= 0 ? '+' : ''}{bt.annual_return_pct.toFixed(0)}%</span>
                      ) : <span style={{ color: C.textFaint }}>—</span>}
                    </TableCell>
                    <TableCell align="right" className="num-mono" sx={{ fontSize: '0.78rem' }}>
                      {bt && bt.max_drawdown_pct != null ? (
                        <span style={{
                          color: bt.max_drawdown_pct < 30 ? C.success : bt.max_drawdown_pct < 60 ? C.warning : C.error,
                        }}>-{bt.max_drawdown_pct.toFixed(0)}%</span>
                      ) : <span style={{ color: C.textFaint }}>—</span>}
                    </TableCell>
                    <TableCell align="right" className="num-mono" sx={{ color: 'text.secondary', fontSize: '0.78rem' }}>
                      {s.total_trades || <span style={{ color: C.textFaint }}>—</span>}
                    </TableCell>
                    <TableCell align="right" className="num-mono">
                      {s.total_pnl !== 0 ? (
                        <span style={{
                          color: s.total_pnl > 0 ? C.success : C.error,
                          fontWeight: 600, fontSize: '0.78rem',
                        }}>
                          {s.total_pnl > 0 ? '+' : ''}${s.total_pnl.toFixed(2)}
                        </span>
                      ) : <span style={{ color: C.textFaint }}>—</span>}
                    </TableCell>
                  </TableRow>
                );
              })}
              {sortedPerf.length === 0 && (
                <TableRow>
                  <TableCell colSpan={11} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                    尚無策略
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>

      {/* === Open Positions === */}
      <Box className="glass-card" sx={{ p: 2.25, position: 'relative', overflow: 'hidden' }}>
        <CornerDecor position="tl" color={C.gold} />
        <CornerDecor position="br" color={C.gold} />

        <Box sx={{ mb: 1.5 }}>
          <Typography variant="overline" sx={{ color: 'text.secondary' }}>OPEN POSITIONS</Typography>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1 }}>
            [{positions.length}] LIVE EXPOSURE
          </Typography>
        </Box>

        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>策略</TableCell>
                <TableCell>標的</TableCell>
                <TableCell>方向</TableCell>
                <TableCell align="right">SIZE</TableCell>
                <TableCell align="right">ENTRY</TableCell>
                <TableCell align="right">MARK</TableCell>
                <TableCell align="right">SPREAD</TableCell>
                <TableCell align="right">UNREALIZED</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {positions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} align="center" sx={{ py: 5, color: 'text.secondary' }}>
                    <Typography variant="body2">無持倉</Typography>
                    <Typography variant="caption" sx={{ fontFamily: 'JetBrains Mono', fontSize: '0.7rem' }}>
                      AWAITING SIGNAL<Box component="span" className="caret" sx={{ height: '0.8em', display: 'inline-block', width: 6 }} />
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                positions.map((pos) => {
                  const stratName = sortedPerf.find((p) => p.id === pos.strategy_id)?.name || `#${pos.strategy_id}`;
                  const spread = pos.current_price && pos.entry_price
                    ? ((pos.current_price - pos.entry_price) / pos.entry_price * 100)
                    : 0;
                  return (
                    <TableRow key={pos.id} hover sx={{ '&:hover': { background: 'rgba(99,102,241,0.04)' } }}>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                          <PulseDot color={pos.side === 'long' ? C.success : C.error} size={6} />
                          <Typography variant="body2" sx={{ fontWeight: 500, fontSize: '0.78rem' }}>{stratName}</Typography>
                        </Box>
                      </TableCell>
                      <TableCell className="num-mono" sx={{ fontSize: '0.78rem' }}>{pos.symbol}</TableCell>
                      <TableCell>
                        <Box sx={{
                          display: 'inline-flex',
                          px: 0.75, py: 0.15, borderRadius: 0.75,
                          bgcolor: pos.side === 'long' ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                          color: pos.side === 'long' ? C.success : C.error,
                          fontSize: 9, fontWeight: 700, letterSpacing: 0.8,
                          border: `1px solid ${pos.side === 'long' ? C.success : C.error}40`,
                          boxShadow: `0 0 6px ${pos.side === 'long' ? C.success : C.error}30`,
                        }}>
                          {pos.side === 'long' ? '◤ LONG' : '◣ SHORT'}
                        </Box>
                      </TableCell>
                      <TableCell align="right" className="num-mono" sx={{ fontSize: '0.78rem' }}>{pos.size}</TableCell>
                      <TableCell align="right" className="num-mono" sx={{ fontSize: '0.78rem' }}>${(pos.entry_price || 0).toLocaleString()}</TableCell>
                      <TableCell align="right" className="num-mono" sx={{ fontSize: '0.78rem' }}>${(pos.current_price || 0).toLocaleString()}</TableCell>
                      <TableCell align="right" className="num-mono" sx={{ fontSize: '0.75rem', color: spread >= 0 ? C.success : C.error }}>
                        {spread >= 0 ? '+' : ''}{spread.toFixed(3)}%
                      </TableCell>
                      <TableCell align="right" className="num-mono" sx={{
                        color: (pos.unrealized_pnl || 0) >= 0 ? C.success : C.error,
                        fontWeight: 700,
                        fontSize: '0.85rem',
                        textShadow: Math.abs(pos.unrealized_pnl || 0) > 0.5
                          ? `0 0 12px ${(pos.unrealized_pnl || 0) >= 0 ? 'rgba(34,197,94,0.5)' : 'rgba(239,68,68,0.5)'}`
                          : 'none',
                      }}>
                        {(pos.unrealized_pnl || 0) >= 0 ? '+' : ''}${(pos.unrealized_pnl || 0).toFixed(2)}
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
