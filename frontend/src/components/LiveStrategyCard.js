// Phase 14i: running 策略卖点 mini-card
// 显示 30 天累计 pnl sparkline + 当前持仓距 SL/TP + 浮盈 + 上次信号时间
//
// Props:
//   strategyId — id (fallback: 自己 fetch)
//   data       — 父组件已 fetch 的 perf row (优先用, 省 N+1)

import React, { useState, useEffect, useCallback } from 'react';
import { Box, Typography, Stack, Chip, LinearProgress, Tooltip } from '@mui/material';
import { AreaChart, Area, ResponsiveContainer, YAxis, Tooltip as ReTooltip } from 'recharts';

const API = process.env.REACT_APP_API_URL || '';

function fmtPct(v, suffix = '%') {
  if (v == null || Number.isNaN(v)) return '—';
  const n = Number(v);
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}${suffix}`;
}

function fmtUsd(v) {
  if (v == null || Number.isNaN(v)) return '—';
  const n = Number(v);
  return `${n >= 0 ? '+' : ''}$${n.toFixed(2)}`;
}

function relativeTime(iso) {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return '刚刚';
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s 前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  return `${day} 天前`;
}

export default function LiveStrategyCard({ strategyId, data: dataProp }) {
  const [innerData, setInnerData] = useState(null);
  const [loading, setLoading] = useState(!dataProp);

  const refresh = useCallback(async () => {
    if (dataProp) return;     // 父组件管理 data, 不自己 fetch
    try {
      const r = await fetch(`${API}/api/strategies/performance?include=live_card`);
      if (!r.ok) return;
      const arr = await r.json();
      const row = (arr || []).find(x => x.id === strategyId);
      if (row) setInnerData(row);
    } catch {} finally {
      setLoading(false);
    }
  }, [strategyId, dataProp]);

  useEffect(() => {
    if (dataProp) return;
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh, dataProp]);

  const data = dataProp || innerData;
  if (loading && !data) return (
    <Box sx={{ py: 1 }}>
      <LinearProgress sx={{ height: 2, opacity: 0.4 }} />
    </Box>
  );
  if (!data) return null;

  const curve = data.equity_curve_30d || [];
  const pos = data.open_position_detail;
  const lastTrade = data.last_trade_at;
  const totalPnl = data.total_pnl || 0;
  const trades30d = data.trades_30d || 0;
  const isPnlPositive = totalPnl >= 0;
  const sparkColor = isPnlPositive ? '#34d399' : '#f87171';

  return (
    <Box sx={{
      p: 1.5,
      borderRadius: 1,
      bgcolor: 'rgba(167,139,250,0.04)',
      border: '1px dashed rgba(167,139,250,0.18)',
    }}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="stretch">

        {/* ─── 1. 30 天 PnL sparkline ─── */}
        <Box sx={{ flex: 1, minWidth: 180, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 0.5 }}>
            <Typography variant="caption" color="text.secondary">30 天累计 PnL · {trades30d} 笔</Typography>
            <Typography variant="caption" sx={{ color: sparkColor, fontWeight: 700, fontSize: 12 }}>
              {fmtUsd(totalPnl)}
            </Typography>
          </Box>
          <Box sx={{ height: 42 }}>
            {curve.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={curve} margin={{ top: 1, right: 1, bottom: 1, left: 1 }}>
                  <defs>
                    <linearGradient id={`spark-${strategyId}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={sparkColor} stopOpacity={0.5} />
                      <stop offset="100%" stopColor={sparkColor} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <YAxis hide domain={['dataMin', 'dataMax']} />
                  <ReTooltip
                    contentStyle={{ background: 'rgba(20,20,25,0.95)', border: '1px solid #333', borderRadius: 4, fontSize: 11 }}
                    formatter={(v) => [`${Number(v).toFixed(2)} USDT`, '累计 PnL']}
                    labelFormatter={(idx) => curve[idx] ? new Date(curve[idx].ts).toLocaleString() : ''}
                  />
                  <Area
                    type="monotone"
                    dataKey="cum_pnl"
                    stroke={sparkColor}
                    strokeWidth={1.5}
                    fill={`url(#spark-${strategyId})`}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Typography variant="caption" color="text.disabled">{trades30d === 0 ? '30 天内尚无成交' : '数据点不足'}</Typography>
              </Box>
            )}
          </Box>
        </Box>

        {/* ─── 2. 持仓详情 / SL TP 距离 ─── */}
        <Box sx={{ flex: 1.2, minWidth: 200 }}>
          {pos ? (
            <Box>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                <Chip
                  label={pos.side === 'long' ? '多 LONG' : '空 SHORT'}
                  size="small"
                  sx={{ bgcolor: pos.side === 'long' ? 'rgba(52,211,153,0.15)' : 'rgba(248,113,113,0.15)', color: pos.side === 'long' ? '#34d399' : '#f87171', fontWeight: 700, fontSize: 10, height: 18 }}
                />
                <Typography variant="caption" color="text.secondary">
                  开仓 {fmtUsd(pos.entry_price)} → 现 {fmtUsd(pos.current_price)}
                </Typography>
                <Box sx={{ flex: 1 }} />
                <Typography variant="body2" sx={{ fontWeight: 700, color: (pos.unrealized_pnl_usd || 0) >= 0 ? '#34d399' : '#f87171' }}>
                  {fmtUsd(pos.unrealized_pnl_usd)} ({fmtPct(pos.unrealized_pnl_pct)})
                </Typography>
              </Stack>

              {/* SL/TP 距离 bar — 简单 horizontal layout */}
              <Box sx={{ display: 'grid', gridTemplateColumns: '40px 1fr 50px', gap: 0.5, alignItems: 'center', mb: 0.3 }}>
                <Typography variant="caption" sx={{ color: '#f87171', fontSize: 10 }}>SL</Typography>
                <Tooltip title={pos.sl_price ? `止损 ${pos.sl_price}` : '未设止损'} arrow>
                  <Box sx={{ position: 'relative', height: 6, bgcolor: 'rgba(248,113,113,0.12)', borderRadius: 1, overflow: 'hidden' }}>
                    {pos.dist_to_sl_pct != null && pos.dist_to_sl_pct > 0 && (
                      <Box sx={{
                        position: 'absolute', left: 0, top: 0, bottom: 0,
                        width: `${Math.min(100, Math.abs(pos.dist_to_sl_pct) * 10)}%`,
                        bgcolor: pos.dist_to_sl_pct < 2 ? '#f87171' : '#fbbf24',
                      }} />
                    )}
                  </Box>
                </Tooltip>
                <Typography variant="caption" sx={{ fontSize: 10, textAlign: 'right', color: pos.dist_to_sl_pct != null && pos.dist_to_sl_pct < 2 ? '#f87171' : 'text.secondary' }}>
                  {pos.dist_to_sl_pct != null ? `${pos.dist_to_sl_pct.toFixed(1)}%` : '—'}
                </Typography>
              </Box>
              <Box sx={{ display: 'grid', gridTemplateColumns: '40px 1fr 50px', gap: 0.5, alignItems: 'center' }}>
                <Typography variant="caption" sx={{ color: '#34d399', fontSize: 10 }}>TP</Typography>
                <Tooltip title={pos.tp_price ? `止盈 ${pos.tp_price}` : '未设止盈'} arrow>
                  <Box sx={{ position: 'relative', height: 6, bgcolor: 'rgba(52,211,153,0.12)', borderRadius: 1, overflow: 'hidden' }}>
                    {pos.dist_to_tp_pct != null && pos.dist_to_tp_pct > 0 && (
                      <Box sx={{
                        position: 'absolute', left: 0, top: 0, bottom: 0,
                        width: `${Math.min(100, Math.abs(pos.dist_to_tp_pct) * 10)}%`,
                        bgcolor: '#34d399',
                      }} />
                    )}
                  </Box>
                </Tooltip>
                <Typography variant="caption" sx={{ fontSize: 10, textAlign: 'right', color: 'text.secondary' }}>
                  {pos.dist_to_tp_pct != null ? `${pos.dist_to_tp_pct.toFixed(1)}%` : '—'}
                </Typography>
              </Box>
              <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mt: 0.3, fontSize: 9 }}>
                持仓 {pos.size} · 开仓时间 {relativeTime(pos.opened_at)}
              </Typography>
            </Box>
          ) : (
            <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', color: 'text.disabled' }}>
              <Typography variant="caption">⚪️ 当前无持仓 — 等待信号</Typography>
              {lastTrade && (
                <Typography variant="caption" sx={{ fontSize: 10, mt: 0.3 }}>
                  上次成交 {relativeTime(lastTrade)}
                </Typography>
              )}
            </Box>
          )}
        </Box>
      </Stack>
    </Box>
  );
}
