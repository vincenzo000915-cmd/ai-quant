import React, { useState, useEffect, useCallback, useMemo, useRef, lazy, Suspense } from 'react';
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
  AreaChart, Area, LineChart, Line, ComposedChart, XAxis, YAxis,
  CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer, ReferenceDot,
  ReferenceLine,
} from 'recharts';
// Phase 12.19: TradingView Widget 替代 lightweight-charts (BTCChart)
//   + TradesTimeline 替代 K 线 markers (策略动作独立面板)
import TradingViewWidget from '../components/TradingViewWidget';
// Phase 15 UI: 交易视图 (lightweight-charts + AI操作标记 + 手动面板)
import TradeView from '../components/TradeView';
import TradesTimeline from '../components/TradesTimeline';
// Phase 12.15.2: secondary panel lazy load — 減小 main bundle，首屏加快
const RegimePanel = lazy(() => import('../components/RegimePanel'));
const MTFConsensusPanel = lazy(() => import('../components/MTFConsensusPanel'));
// Phase 15 UI 重构: 守门员驾驶舱 (信号预告+守门员台+AI经理台+策略库+飞轮) 取代散落的 AI 面板
const GatekeeperCockpit = lazy(() => import('../components/GatekeeperCockpit'));
import { PageSkeleton, KpiBarSkeleton, CardSkeleton } from '../components/Skeleton';
// Phase 12.15.3: 新 design system
import { palette, typo, pnlColor } from '../theme';
import PageHeader from '../components/common/PageHeader';
import KpiCell from '../components/common/KpiCell';
import StatusChip from '../components/common/StatusChip';
import { prettifyType } from '../utils/strategyTypeLabels';
import ProfitTargetCard from '../components/ProfitTargetCard';
import { tierRank } from '../auth';
// Phase 12.20: NeuralBackdrop 已下架（装饰过头）

const API = process.env.REACT_APP_API_URL || '';

// Phase 12.20: 紫主调 (Hyperliquid / Phantom 风) — AI 量化身份
const C = {
  primary: '#a78bfa',
  primaryGlow: 'rgba(167, 139, 250, 0.55)',
  accent: '#a78bfa',
  accentGlow: 'rgba(167, 139, 250, 0.45)',
  // Phase 12.25: pink 已删（unused）
  purple: '#a78bfa',
  gold: '#f7a600',
  goldDeep: '#f59e0b',
  warnYellow: '#f7a600',
  success: '#00d4aa',
  error: '#ff4757',
  errorBright: '#ff3355',
  warning: '#f59e0b',
  text: '#e2e8f0',
  textDim: '#94a3b8',
  textFaint: '#475569',
  border: 'rgba(167, 139, 250, 0.22)',
};

const CATEGORY_META = {
  ultra: { label: '◢ ULTRA',  color: C.purple, bg: 'rgba(167, 139, 250, 0.15)' },
  short: { label: '◤ SHORT',  color: C.error,  bg: 'rgba(255, 71, 87, 0.15)' },
  swing: { label: '◇ SWING',  color: C.gold,   bg: 'rgba(251, 191, 36, 0.15)' },
  long:  { label: '◆ LONG',   color: C.success,bg: 'rgba(0, 212, 170, 0.15)' },
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
    pnlSummary && pnlSummary.total_trades > 0 && `TRADES ${pnlSummary.total_trades} · EV $${(pnlSummary.total_pnl / pnlSummary.total_trades).toFixed(2)}/单`,
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
// useSystemStats / formatUptime 已移除 — 那是 Hermes 留下的 Math.random 假數據
// 真實狀態走 /api/account + /api/pnl/summary + /api/config，渲染在 SysStatBlock row

export default function Dashboard() {
  const [account, setAccount] = useState(null);
  const [btcPrice, setBtcPrice] = useState(null);
  const [btcChart, setBtcChart] = useState([]);
  const [positions, setPositions] = useState([]);
  const [pnlData, setPnlData] = useState([]);
  const [pnlSummary, setPnlSummary] = useState(null);
  const [perfList, setPerfList] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [trades, setTrades] = useState([]);
  const [tfBtc, setTfBtc] = useState('1h');
  const [chartSymbol, setChartSymbol] = useState('BTC/USDT');
  const [supportedSymbols, setSupportedSymbols] = useState([]);
  // Phase 15 UI: 图表视图切换 — 'trade'=交易视图(AI操作标记+手动面板) / 'pro'=专业指标图(TV widget)
  const [chartView, setChartView] = useState('trade');
  // Phase 12.19: indicators state 已删除（TV widget 自带指标 dropdown，前端不再控制）
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchData = useCallback(async (silent = false) => {
    // Phase 12.15.1: stale-while-revalidate — 已有資料時不 setLoading（避免閃 skeleton）
    if (!silent && !account) setLoading(true);
    try {
      const [acctRes, priceRes, posRes, pnlHistRes, pnlSumRes, perfRes, cfgRes] = await Promise.allSettled([
        fetch(`${API}/api/account`),
        fetch(`${API}/api/market/btc-price`),
        fetch(`${API}/api/positions`),
        fetch(`${API}/api/pnl/history?days=30`),
        fetch(`${API}/api/pnl/summary`),
        fetch(`${API}/api/strategies/performance`),
        fetch(`${API}/api/config`),
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
      if (cfgRes.status === 'fulfilled' && cfgRes.value.ok) {
        setCfg(await cfgRes.value.json());
      }

      // chart 用獨立 fetch（依 tfBtc 重拉）— 見下方 useEffect

      try {
        const tradesRes = await fetch(`${API}/api/trades?limit=200`);
        if (tradesRes.ok) {
          const tj = await tradesRes.json();
          setTrades(Array.isArray(tj) ? tj : []);
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

  // 載入支援的交易對清單一次
  useEffect(() => {
    fetch(`${API}/api/symbols`).then(r => r.json()).then(d => setSupportedSymbols(Array.isArray(d) ? d : [])).catch(() => {});
  }, []);

  // Phase 12.18: K 線 — 历史用 REST 一次性拉，实时 update 走 OKX WebSocket 推送
  //   - 切 symbol/tf 时拉一次历史 + subscribe 新 channel
  //   - WS 推送 < 100ms 接收最新 candle，直接 merge 进 btcChart state
  //   - REST 兜底 60s 一次（防 WS 断线漏数据）
  useEffect(() => {
    let cancelled = false;
    const loadChart = async () => {
      try {
        const r = await fetch(`${API}/api/market/${chartSymbol}/chart?timeframe=${tfBtc}`);
        if (!r.ok || cancelled) return;
        const j = await r.json();
        if (!cancelled) setBtcChart(Array.isArray(j) ? j : []);
      } catch {/* */}
    };
    loadChart();
    const restFallback = setInterval(loadChart, 60000);   // 60s REST 兜底

    // 订阅 OKX WS 实时推送
    let unsubscribe = null;
    (async () => {
      try {
        const okxWs = (await import('../services/okxWebSocket')).default;
        unsubscribe = okxWs.subscribe(chartSymbol, tfBtc, (candle) => {
          if (cancelled) return;
          // merge 进 btcChart：找同 timestamp 的 candle 更新；否则 append
          setBtcChart(prev => {
            if (!prev.length) return prev;
            const idx = prev.findIndex(d => d.timestamp === candle.timestamp);
            if (idx >= 0) {
              const next = [...prev];
              next[idx] = { ...next[idx], ...candle, price: candle.close };
              return next;
            }
            // 新 candle — append
            return [...prev, { ...candle, price: candle.close }];
          });
        });
      } catch (e) { console.error('[BTCChart] WS subscribe failed:', e); }
    })();

    return () => {
      cancelled = true;
      clearInterval(restFallback);
      if (unsubscribe) unsubscribe();
    };
  }, [tfBtc, chartSymbol]);

  // Phase 12.19: btcChartEnriched 已删除（TV widget 自带指标，不再需要前端计算）

  // Phase 12.18.1: ticker 价格从 btcChart 最后一根 close 派生（同步 WebSocket 推送）
  //   不再独立 polling /api/market/<sym>/price，消除 5s 延迟
  //   24h change/high/low 仍用 REST 拉一次（OKX ticker WS 频率太高，浪费）
  useEffect(() => {
    let cancelled = false;
    const load24h = async () => {
      try {
        const r = await fetch(`${API}/api/market/${chartSymbol}/price`);
        if (!r.ok || cancelled) return;
        const json = await r.json();
        if (!cancelled) setBtcPrice(json);
      } catch { /* */ }
    };
    load24h();
    const id = setInterval(load24h, 30000);   // 24h 数据 30s 刷一次足够
    return () => { cancelled = true; clearInterval(id); };
  }, [chartSymbol]);

  // 实时 price 从 btcChart 最后一根 close 取（WebSocket 推送同步）
  const livePrice = useMemo(() => {
    if (btcChart.length && btcChart[btcChart.length - 1].close != null) {
      return btcChart[btcChart.length - 1].close;
    }
    return btcPrice?.price;
  }, [btcChart, btcPrice]);

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

  // Phase 12.20: KPI Card — 去 sparkline / 去 corner / 去 radial glow，紫色边框 + 鲜明数据
  const KPICard = ({ label, value, sublabel, icon, accent = 'primary', highlight = false }) => {
    const accentMap = {
      primary: { color: C.primary },
      success: { color: C.success },
      error:   { color: C.error },
      warning: { color: C.warning },
      accent:  { color: C.accent },
      gold:    { color: C.gold },
    };
    const a = accentMap[accent] || accentMap.primary;
    return (
      <Box sx={{
        p: 2, height: '100%', position: 'relative', overflow: 'hidden',
        bgcolor: 'rgba(16, 23, 43, 0.6)',
        border: `1px solid ${highlight ? a.color : 'rgba(167, 139, 250, 0.18)'}`,
        borderRadius: 1.25,
        boxShadow: highlight ? `0 0 16px ${a.color}30, inset 0 1px 0 ${a.color}20` : 'inset 0 1px 0 rgba(255,255,255,0.03)',
        transition: 'border-color 0.18s, box-shadow 0.18s',
        '&:hover': { borderColor: a.color, boxShadow: `0 0 14px ${a.color}25` },
      }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 0.85 }}>
          <Typography variant="overline" sx={{ color: 'text.secondary', lineHeight: 1, fontSize: '0.65rem', letterSpacing: 0.6 }}>
            {label}
          </Typography>
          <Box sx={{
            width: 26, height: 26, borderRadius: 1,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            bgcolor: `${a.color}14`, color: a.color,
          }}>
            {React.cloneElement(icon, { sx: { fontSize: 15 } })}
          </Box>
        </Box>
        <Typography className="num-mono" sx={{
          fontSize: { xs: '1.35rem', sm: '1.7rem' },
          fontWeight: 700, color: a.color, lineHeight: 1.05, mb: 0.4,
          letterSpacing: '-0.02em',
        }}>
          {value}
        </Typography>
        {sublabel && (
          <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', display: 'block' }}>
            {sublabel}
          </Typography>
        )}
      </Box>
    );
  };

  // Phase 12.15.3: 新 hero — 刪 Ticker + 刪 SysStatBlock strip + 刪 cyberpunk title
  // 統一 5 個 KPI cell（左到右）+ 主標 + 副標 + 風險灯
  const liveMode = cfg?.trading_mode === 'live';
  const halted = cfg?.halted;
  const todayPnl = pnlSummary?.today_pnl ?? 0;
  const todayTrades = pnlSummary?.today_trades ?? 0;
  const openPositions = pnlSummary?.open_positions ?? 0;
  const runningStrats = pnlSummary?.running_strategies ?? 0;

  return (
    <Box sx={{ position: 'relative', zIndex: 1 }}>
      {/* Phase 12.20: 删 NeuralBackdrop — cyberpunk 装饰过重，主精力放紫色 accent + 数据密度 */}

      {/* === 統一頁頭 — 緊湊版 + KILL SWITCH 收進 actions === */}
      <PageHeader
        title="儀表板"
        subtitle={`OKX · ${liveMode ? 'LIVE 实盘' : 'PAPER 模拟'} · 杠杆 ${cfg?.leverage || 15}x · 每笔 $${cfg?.trade_size_usdt || 4} · ${utcTime}`}
        actions={[
          <StatusChip key="mode" status={liveMode ? 'error' : 'success'} label={liveMode ? 'LIVE' : 'PAPER'} solid />,
          halted && <StatusChip key="halt" status="error" label="HALTED" solid />,
          <Tooltip key="refresh" title="立即刷新">
            <IconButton onClick={() => fetchData(false)} size="small" sx={{ border: `1px solid ${palette.border}`, color: palette.textMuted, '&:hover': { borderColor: palette.borderHot } }}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>,
          <Tooltip key="kill" title="🆘 KILL SWITCH — 停所有策略 + 强平所有持仓">
            <Box
              key="kill-btn"
              component="button"
              onClick={async () => {
                const yes1 = window.confirm('🆘 KILL SWITCH 會：\n• 停所有 running 策略\n• 強平所有 open positions（市價）\n• 設 halt 阻止新開倉\n\n確定？');
                if (!yes1) return;
                const txt = window.prompt('再次確認：請輸入大寫 KILL 才會執行');
                if (txt !== 'KILL') { alert('未輸入 KILL，已取消'); return; }
                const r = await fetch(`${API}/api/killswitch`, {
                  method: 'POST', headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ confirm: 'KILL', reason: 'dashboard manual' }),
                });
                const body = await r.json();
                alert(r.ok ? `已執行：stop ${body.stopped_strategies?.length} 策略，平 ${body.closed_positions?.length} 持倉` : `失敗：${body.error}`);
                fetchData();
              }}
              sx={{
                cursor: 'pointer',
                border: `1px solid ${palette.error}66`,
                bgcolor: `${palette.error}11`,
                color: palette.error,
                px: 1.25, py: 0.55, borderRadius: 0.75,
                fontFamily: 'inherit', fontSize: 11, fontWeight: 700, letterSpacing: 0.5,
                lineHeight: 1, height: 28,
                '&:hover': { bgcolor: `${palette.error}22`, borderColor: palette.error, boxShadow: `0 0 12px ${palette.errorGlow}` },
              }}
            >
              🆘 KILL
            </Box>
          </Tooltip>,
        ].filter(Boolean)}
      />

      {/* === HALTED banner（cfg.halted 才顯示） === */}
      {cfg?.halted && (
        <Box
          onClick={async () => {
            if (!window.confirm(`系統 HALTED:\n${cfg.halt_reason}\n\n確定要解除？`)) return;
            await fetch(`${API}/api/unhalt`, { method: 'POST' });
            fetchData();
          }}
          sx={{
            mb: 1.5, p: 1.25, cursor: 'pointer',
            bgcolor: `${palette.error}14`,
            border: `1px solid ${palette.error}55`,
            borderRadius: 1,
            display: 'flex', alignItems: 'center', gap: 1,
            '&:hover': { bgcolor: `${palette.error}1f` },
          }}>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: palette.error, boxShadow: `0 0 8px ${palette.error}`, animation: 'pulse-dot 1s infinite' }} />
          <Typography sx={{ color: palette.error, fontWeight: 600, fontSize: 13, flex: 1 }}>
            系统已 HALTED · {cfg.halt_reason} · <span style={{ textDecoration: 'underline' }}>点击解除</span>
          </Typography>
        </Box>
      )}

      {/* Phase 15: 目标驱动 = AI 经理控制台 (设目标/暂停/启动/改目标 都是 AI 经理功能) → Team 专属.
          否则 Pro 看到这张就等于在用 AI 经理 (user 查出). Pro 用守门员台, 无目标托管. */}
      {tierRank() >= 3 && <ProfitTargetCard />}

      {/* === KPI bar — 6 cells，无 emoji 无 sparkline 高度统一（专业 trader 风）=== */}
      <Grid container spacing={1} sx={{ mb: 2.5 }}>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCell size="compact" label="账户余额"
            value={account?.balance != null ? `$${account.balance.toFixed(2)}` : '—'}
            sub={
              (account?.accounts && account.accounts.length > 1)
                ? account.accounts.map(a => `${a.label}:$${(a.equity || 0).toFixed(0)}`).join(' · ')
                : (account ? `$${(account.free_margin || 0).toFixed(2)} 可用` : '')
            }
            accent="accent" loading={!account} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCell size="compact" label="今日 PnL"
            value={`${todayPnl >= 0 ? '+' : ''}$${todayPnl.toFixed(2)}`}
            sub={todayTrades ? `${pnlSummary.today_wins}W / ${pnlSummary.today_losses}L` : '0 trades'}
            accent={todayPnl > 0 ? 'success' : todayPnl < 0 ? 'error' : null}
            trendValue={todayPnl} loading={!pnlSummary}
            badge={todayTrades > 0 ? { text: `${todayTrades}笔`, color: '#94a3b8' } : null} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCell size="compact" label="累计 PnL"
            value={pnlSummary ? `${pnlSummary.total_pnl >= 0 ? '+' : ''}$${pnlSummary.total_pnl?.toFixed(2)}` : '—'}
            sub={pnlSummary && pnlSummary.total_trades > 0
                  ? `EV ${((pnlSummary.total_pnl / pnlSummary.total_trades) >= 0 ? '+' : '')}${(pnlSummary.total_pnl / pnlSummary.total_trades).toFixed(2)}$/单`
                  : '—'}
            accent={pnlSummary?.total_pnl > 0 ? 'success' : pnlSummary?.total_pnl < 0 ? 'error' : null}
            trendValue={pnlSummary?.total_pnl} loading={!pnlSummary}
            badge={pnlSummary ? { text: `${pnlSummary.total_trades}笔`, color: '#94a3b8' } : null} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCell size="compact" label="持仓 / 运行"
            value={`${openPositions} / ${runningStrats}`}
            sub={openPositions > 0 ? `${openPositions} 开仓中` : '无开仓'}
            accent={openPositions > 0 ? 'accent' : null} loading={!pnlSummary}
            badge={openPositions > 0 ? { text: 'LIVE', color: '#00d4aa', bg: 'rgba(0,212,170,0.15)' } : null} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCell size="compact" label="未实现"
            value={pnlSummary ? `${pnlSummary.unrealized_pnl >= 0 ? '+' : ''}$${pnlSummary.unrealized_pnl?.toFixed(2)}` : '$0.00'}
            sub={openPositions > 0 ? `${openPositions} 持仓` : '无浮动'}
            accent={pnlSummary?.unrealized_pnl > 0 ? 'success' : pnlSummary?.unrealized_pnl < 0 ? 'error' : null}
            trendValue={pnlSummary?.unrealized_pnl} loading={!pnlSummary} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCell size="compact" label="最大回撤"
            value={pnlSummary?.max_drawdown != null ? `-$${Math.abs(pnlSummary.max_drawdown).toFixed(2)}` : '—'}
            sub={pnlSummary?.max_drawdown_pct ? `-${pnlSummary.max_drawdown_pct.toFixed(1)}%` : '90 天'}
            accent={(pnlSummary?.max_drawdown_pct || 0) > 30 ? 'error' : (pnlSummary?.max_drawdown_pct || 0) > 10 ? 'warning' : null}
            loading={!pnlSummary} badge={{ text: '90D', color: '#94a3b8' }} />
        </Grid>
      </Grid>

      {/* refresh 時頂部 2px 細條 */}
      {loading && account && <LinearProgress sx={{ mb: 2, height: 2, borderRadius: 1, bgcolor: palette.border, '& .MuiLinearProgress-bar': { bgcolor: palette.accent } }} />}

      {/* Phase 15 UI 重构: 守门员驾驶舱 (信号预告+守门员台Pro+AI经理台Team+策略库+飞轮, tier分层) */}
      <Suspense fallback={<CardSkeleton height={300} headerWidth="40%" rows={5} />}>
        <GatekeeperCockpit />
      </Suspense>

      {/* === Phase 12.20: 走势图全宽（删 Row 1 右侧重复 OPEN POSITIONS）=== */}
      <Grid container spacing={2} sx={{ mb: 2.5 }}>
        <Grid item xs={12}>
          <Box className="glass-card" sx={{ p: 2.25, position: 'relative', overflow: 'hidden' }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1.5, flexWrap: 'wrap', gap: 1 }}>
              <Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                  <Box sx={{
                    width: 6, height: 6, borderRadius: '50%',
                    bgcolor: palette.success,
                    boxShadow: `0 0 6px ${palette.success}`,
                    animation: 'live-pulse-tk 1.2s ease-in-out infinite',
                    '@keyframes live-pulse-tk': {
                      '0%, 100%': { opacity: 1, transform: 'scale(1)' },
                      '50%': { opacity: 0.5, transform: 'scale(1.4)' },
                    },
                  }} />
                  <Typography variant="overline" sx={{ color: palette.success, fontWeight: 700, letterSpacing: 0.5 }}>
                    {chartSymbol} · LIVE · OKX WS
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1.5, flexWrap: 'wrap' }}>
                  <Typography
                    className="num-mono"
                    variant="h5"
                    sx={{ fontWeight: 700, color: C.gold, fontSize: '1.6rem' }}
                  >
                    ${(livePrice || 0).toLocaleString()}
                  </Typography>
                  {/* 币种切换 */}
                  <Box sx={{ display: 'flex', gap: 0.4, flexWrap: 'wrap' }}>
                    {(supportedSymbols.length ? supportedSymbols : [{ symbol: 'BTC/USDT' }]).map(s => (
                      <Box
                        key={s.symbol}
                        component="button"
                        onClick={() => setChartSymbol(s.symbol)}
                        sx={{
                          cursor: 'pointer',
                          px: 0.7, py: 0.15,
                          border: '1px solid',
                          borderColor: chartSymbol === s.symbol ? C.gold : 'rgba(255,255,255,0.08)',
                          color: chartSymbol === s.symbol ? C.gold : 'rgba(148,163,184,0.7)',
                          bgcolor: chartSymbol === s.symbol ? 'rgba(251,191,36,0.08)' : 'transparent',
                          fontFamily: 'JetBrains Mono, monospace',
                          fontSize: '0.58rem', fontWeight: 700, letterSpacing: 0.5,
                          borderRadius: 0.4,
                        }}
                      >
                        {s.symbol.split('/')[0]}
                      </Box>
                    ))}
                  </Box>
                </Box>
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

            {/* === Timeframe 切換器 + 视图切换 === */}
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mb: 1, alignItems: 'center' }}>
              <Typography variant="caption" sx={{ color: 'text.secondary', mr: 0.5, fontSize: '0.65rem' }}>TF:</Typography>
              {['15m', '30m', '1h', '4h', '1d', '1w'].map(tf => (
                <Box
                  key={tf}
                  component="button"
                  onClick={() => setTfBtc(tf)}
                  sx={{
                    cursor: 'pointer',
                    px: 0.8, py: 0.2,
                    border: '1px solid',
                    borderColor: tfBtc === tf ? C.gold : 'rgba(255,255,255,0.12)',
                    color: tfBtc === tf ? C.gold : C.textDim,
                    bgcolor: tfBtc === tf ? 'rgba(251,191,36,0.1)' : 'transparent',
                    fontFamily: 'JetBrains Mono, monospace',
                    fontSize: '0.65rem', fontWeight: 700,
                    borderRadius: 0.5,
                  }}
                >
                  {tf}
                </Box>
              ))}
              {/* Phase 15 UI: 交易视图(AI标记+手动) / 专业指标图 切换 */}
              <Box sx={{ ml: 'auto', display: 'flex', gap: 0.5 }}>
                {[['trade', '交易视图'], ['pro', '专业图']].map(([v, label]) => (
                  <Box
                    key={v}
                    component="button"
                    onClick={() => setChartView(v)}
                    sx={{
                      cursor: 'pointer', px: 1, py: 0.2,
                      border: '1px solid',
                      borderColor: chartView === v ? C.gold : 'rgba(255,255,255,0.12)',
                      color: chartView === v ? C.gold : C.textDim,
                      bgcolor: chartView === v ? 'rgba(251,191,36,0.1)' : 'transparent',
                      fontSize: '0.65rem', fontWeight: 700, borderRadius: 0.5,
                    }}
                  >
                    {label}
                  </Box>
                ))}
              </Box>
            </Box>

            {chartView === 'trade' ? (
              /* Phase 15 UI: 交易视图 — K线 + 守门员/AI经理操作标记(开仓▲平仓▼/SL/TP台阶) + 手动交易面板 */
              <TradeView symbol={chartSymbol} timeframe={tfBtc} />
            ) : (
              /* Phase 12.19: TradingView Widget — 专业指标 (MACD/RSI) + auto-scale + 倒计时 */
              <TradingViewWidget
                symbol={chartSymbol}
                timeframe={tfBtc}
                height={720}
              />
            )}

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

      {/* === Phase 12.19: 策略动作时间线 (取代 K 线上的 BUY/SELL markers) === */}
      <Grid container spacing={2} sx={{ mb: 2.5 }}>
        <Grid item xs={12}>
          <Box className="glass-card" sx={{ p: 2.25, position: 'relative', overflow: 'hidden' }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 1.5 }}>
              <Box>
                <Typography variant="overline" sx={{ color: 'text.secondary' }}>策略动作时间线 · STRATEGY TIMELINE</Typography>
                <Typography variant="subtitle1" sx={{ fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>
                  [{trades.length}] CLOSED · [{positions.filter(p => p.status === 'open').length}] HOLDING
                </Typography>
              </Box>
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>
                最近 30 条 · 倒序
              </Typography>
            </Box>
            <TradesTimeline
              trades={trades}
              positions={positions}
              strategyNameMap={Object.fromEntries((perfList || []).map(p => [p.id, p.name]))}
              maxRows={30}
              height={380}
            />
          </Box>
        </Grid>
      </Grid>

      {/* === PnL Row（從 Charts Row 移下來） === */}
      <Grid container spacing={2} sx={{ mb: 2.5 }}>
        <Grid item xs={12}>
          <Box className="glass-card" sx={{ p: 2.25, position: 'relative', overflow: 'hidden' }}>
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
                      ? `0 0 28px ${pnlSummary?.total_pnl >= 0 ? 'rgba(0,212,170,0.5)' : 'rgba(255,71,87,0.5)'}`
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
                  <CartesianGrid strokeDasharray="2 8" stroke="rgba(167,139,250,0.1)" />
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
      </Grid>

      {/* Phase 15 UI 重构: AiPickPanel/AiInsightsCard/AdvisorPanel/AiActivityLogCard 已并入
          GatekeeperCockpit (信号预告/守门员/AI经理/库/飞轮), 旧自主范式碎片砍掉. */}

      {/* === Phase 10.3: 市場狀態 + 策略匹配度 === */}
      <Suspense fallback={<CardSkeleton height={240} headerWidth="40%" rows={3} />}>
        <RegimePanel />
      </Suspense>

      {/* === Phase 10.4: 多時框一致性檢查 === */}
      <Suspense fallback={<CardSkeleton height={200} headerWidth="40%" rows={3} />}>
        <MTFConsensusPanel />
      </Suspense>

      {/* === Phase 7.2: STRATEGY LIVE STATE — 每策略指標卡 === */}
      <StrategyLiveStateGrid C={C} />

      {/* === Strategy Matrix（密集模式）=== */}
      <Box className="glass-card" sx={{ p: 2.25, mb: 2.5, position: 'relative', overflow: 'hidden' }}>
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
                  excellent:  { label: '⭐ EXCEL', color: '#f7a600' },
                  good:       { label: '✅ GOOD',  color: '#00d4aa' },
                  marginal:   { label: '⚠ MARG',  color: '#94a3b8' },
                  negative:   { label: '❌ NEG',   color: '#ff4757' },
                  liquidated: { label: '💀 LIQD',  color: '#f87171' },
                }[s.rating] || null;
                return (
                  <TableRow
                    key={s.id}
                    hover
                    sx={{
                      '&:hover': { background: 'rgba(167,139,250,0.05)' },
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
                          color: bt.sharpe_ratio >= 3 ? '#f7a600' : bt.sharpe_ratio >= 1.5 ? C.success : bt.sharpe_ratio >= 0 ? C.textDim : C.error,
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
                    <TableRow key={pos.id} hover sx={{ '&:hover': { background: 'rgba(167,139,250,0.04)' } }}>
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
                          bgcolor: pos.side === 'long' ? 'rgba(0,212,170,0.15)' : 'rgba(255,71,87,0.15)',
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
                          ? `0 0 12px ${(pos.unrealized_pnl || 0) >= 0 ? 'rgba(0,212,170,0.5)' : 'rgba(255,71,87,0.5)'}`
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


function CustomChartTooltip({ active, payload, label, C }) {
  if (!active || !payload?.length) return null;
  // 過濾掉 null / undefined，去重（同 key 重複時取第一個）
  const seen = new Set();
  const rows = payload.filter(p => {
    if (p.value == null) return false;
    if (seen.has(p.dataKey)) return false;
    seen.add(p.dataKey);
    return true;
  });
  if (!rows.length) return null;
  const labelFor = (k) => ({
    price: 'BTC',
    sma20: 'SMA20',
    ema50: 'EMA50',
    bbU: 'BB↑',
    bbL: 'BB↓',
    buy: '🟢 開倉',
    sell: '🔴 平倉',
  }[k] || k);
  return (
    <Box sx={{
      bgcolor: 'rgba(8,10,24,0.94)',
      border: '1px solid rgba(167,139,250,0.35)',
      borderRadius: 1,
      px: 1.25, py: 1,
      fontFamily: 'JetBrains Mono, monospace',
      minWidth: 130,
    }}>
      <Box sx={{ fontSize: '0.65rem', color: 'rgba(148,163,184,0.8)', mb: 0.5 }}>{label}</Box>
      {rows.map(r => (
        <Box key={r.dataKey} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1, fontSize: '0.7rem' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: r.color || r.stroke }} />
            <span style={{ color: 'rgba(203,213,225,0.85)' }}>{labelFor(r.dataKey)}</span>
          </Box>
          <span style={{ color: '#fff', fontWeight: 700 }}>
            ${Number(r.value).toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </span>
        </Box>
      ))}
    </Box>
  );
}


function StrategyLiveStateGrid({ C }) {
  const [states, setStates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch(`${API}/api/strategies/live-state`);
        if (!r.ok || cancelled) return;
        const j = await r.json();
        if (!cancelled) {
          setStates(Array.isArray(j) ? j : []);
          setUpdatedAt(new Date());
        }
      } catch {/* */}
      finally { if (!cancelled) setLoading(false); }
    };
    load();
    const id = setInterval(load, 30000);  // 30s 刷新（指標不會每秒變）
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (loading && !states.length) return null;
  if (!states.length) return null;

  const fmtAge = (iso) => {
    if (!iso) return '尚無';
    const ms = Date.now() - new Date(iso).getTime();
    const min = Math.floor(ms / 60000);
    if (min < 60) return `${min}m 前`;
    const h = Math.floor(min / 60);
    if (h < 24) return `${h}h 前`;
    return `${Math.floor(h / 24)}d 前`;
  };

  return (
    <Box className="glass-card" sx={{ p: 2.25, mb: 2.5, position: 'relative', overflow: 'hidden' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
        <Box>
          <Typography variant="overline" sx={{ color: 'text.secondary' }}>STRATEGY LIVE STATE</Typography>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1 }}>
            [{states.length}] STREAMING · 距觸發即時讀數
          </Typography>
        </Box>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontFamily: 'JetBrains Mono, monospace' }}>
          {updatedAt ? `UPDATED ${updatedAt.toTimeString().slice(0, 8)}` : ''}
        </Typography>
      </Box>

      <Box sx={{
        display: 'grid',
        // 14k-21: 手机 < 480px 强制 1 列, 防止 280 minmax 撑出滚动条
        gridTemplateColumns: { xs: '1fr', sm: 'repeat(auto-fill, minmax(280px, 1fr))' },
        gap: 1.5,
      }}>
        {states.map((s) => (
          <Box key={s.id} sx={{
            p: 1.25,
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 1,
            bgcolor: 'rgba(255,255,255,0.02)',
            display: 'flex', flexDirection: 'column', gap: 0.5,
          }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <Typography variant="body2" fontWeight={700} sx={{ fontSize: '0.82rem' }}>
                {s.name}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem', fontFamily: 'JetBrains Mono' }}>
                {s.timeframe} · {s.category}
              </Typography>
            </Box>

            {s.error ? (
              <Typography variant="caption" sx={{ color: C.warning, fontSize: '0.7rem' }}>
                ⚠ {s.error}
              </Typography>
            ) : (
              <>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {(s.indicators || []).map((ind, i) => (
                    <Box key={i} sx={{
                      px: 0.6, py: 0.15, borderRadius: 0.5,
                      bgcolor: 'rgba(167,139,250,0.08)',
                      border: '1px solid rgba(167,139,250,0.18)',
                      fontFamily: 'JetBrains Mono, monospace',
                      fontSize: '0.68rem',
                    }}>
                      <Typography component="span" variant="caption" sx={{ color: 'text.secondary', fontSize: '0.6rem' }}>
                        {ind.label}
                      </Typography>
                      <Typography component="span" sx={{ ml: 0.5, color: 'text.primary', fontWeight: 700, fontSize: '0.7rem' }}>
                        {ind.value}
                      </Typography>
                    </Box>
                  ))}
                </Box>
                {s.hint && (
                  <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.66rem', lineHeight: 1.4, mt: 0.3 }}>
                    {s.hint}
                  </Typography>
                )}
              </>
            )}

            <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 0.3, pt: 0.4, borderTop: '1px dashed rgba(255,255,255,0.06)', gap: 1 }}>
              <Tooltip title={`类型: ${s.type || '—'}`} arrow>
                <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.6rem', cursor: 'help', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {prettifyType(s.type).emoji} {prettifyType(s.type).label}
                </Typography>
              </Tooltip>
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.6rem', whiteSpace: 'nowrap' }}>
                上次成交: {fmtAge(s.last_trade)}
              </Typography>
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
