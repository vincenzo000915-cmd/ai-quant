// Phase 15 UI: 交易视图 — K 线 + 守门员/AI经理真实操作标记 (开仓▲/平仓▼ + SL/TP台阶线) + 手动交易面板。
// 规格 project-ui-redesign-spec ③. 用 lightweight-charts (可控数据, 能叠标记/价格线 — TradingView iframe 不行)。
// 桌面: 图(主) + 手动面板(右); 移动: 图上 + 面板下 (响应式)。
import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  Box, Typography, Stack, Chip, TextField, Button, ToggleButton, ToggleButtonGroup, Divider,
} from '@mui/material';
import { createChart } from 'lightweight-charts';
import { palette } from '../theme';

const API = process.env.REACT_APP_API_URL || '';

const C = {
  up: '#26a69a', down: '#ef5350',
  sl: '#ef5350', tp: '#fbbf24', be: '#60a5fa',
  long: '#26a69a', short: '#ef5350',
};

// 交易所成交 reason → 中文 + 是否止损/止盈
const REASON_CN = {
  stop_loss: '止损', take_profit: '止盈', signal: '信号平',
  reconcile_orphan_hl: '对账平', manual_close_retired_strategy: '退役平',
  gk_tp1: '锁TP1', gk_tp2: '锁TP2', gk_tp3: '吃TP3', gk_be: '保本平',
};

export default function TradeView({ symbol = 'BTC/USDT', timeframe = '15m' }) {
  const wrapRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const priceLinesRef = useRef([]);
  const [tv, setTv] = useState({ open_positions: [], trades: [] });
  // 手动下单面板
  const [side, setSide] = useState('long');
  const [sizeUsdt, setSizeUsdt] = useState(10);
  const [leverage, setLeverage] = useState(5);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  // === 建图 (一次) ===
  useEffect(() => {
    if (!wrapRef.current) return;
    const chart = createChart(wrapRef.current, {
      autoSize: false,
      width: wrapRef.current.clientWidth,
      height: 480,
      layout: { background: { color: 'transparent' }, textColor: 'rgba(203,213,225,0.75)', fontFamily: 'Inter, system-ui' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    const series = chart.addCandlestickSeries({
      upColor: C.up, downColor: C.down, borderUpColor: C.up, borderDownColor: C.down,
      wickUpColor: C.up, wickDownColor: C.down,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver(() => {
      if (wrapRef.current) chart.applyOptions({ width: wrapRef.current.clientWidth });
    });
    ro.observe(wrapRef.current);
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, []);

  // === 拉 K 线 (symbol/tf 变) ===
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch(`${API}/api/market/${encodeURIComponent(symbol)}/chart?timeframe=${timeframe}`);
        const j = await r.json();
        if (cancelled || !seriesRef.current || !Array.isArray(j)) return;
        const candles = j
          .filter(c => c.timestamp && c.open != null)
          .map(c => ({ time: Math.floor(c.timestamp / 1000), open: c.open, high: c.high, low: c.low, close: c.close }));
        seriesRef.current.setData(candles);
        chartRef.current?.timeScale().fitContent();
      } catch {}
    };
    load();
    const t = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(t); };
  }, [symbol, timeframe]);

  // === 拉交易视图数据 (开仓/成交) ===
  const loadTv = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/trade-view/${encodeURIComponent(symbol)}`);
      if (r.ok) setTv(await r.json());
    } catch {}
  }, [symbol]);
  useEffect(() => { loadTv(); const t = setInterval(loadTv, 30000); return () => clearInterval(t); }, [loadTv]);

  // === 叠标记 + SL/TP 价格线 (tv 变) ===
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    // 标记: 成交进出场 + 开仓
    const markers = [];
    (tv.trades || []).forEach((t) => {
      const long = t.side === 'long';
      if (t.entry_time) markers.push({
        time: t.entry_time, position: long ? 'belowBar' : 'aboveBar',
        color: long ? C.long : C.short, shape: long ? 'arrowUp' : 'arrowDown',
        text: long ? '开多' : '开空',
      });
      if (t.exit_time) markers.push({
        time: t.exit_time, position: long ? 'aboveBar' : 'belowBar',
        color: (t.pnl || 0) >= 0 ? C.up : C.down, shape: long ? 'arrowDown' : 'arrowUp',
        text: `${REASON_CN[t.reason] || '平'} ${(t.pnl || 0) >= 0 ? '+' : ''}${(t.pnl || 0).toFixed(2)}`,
      });
    });
    (tv.open_positions || []).forEach((p) => {
      const long = p.side === 'long';
      if (p.opened_at) markers.push({
        time: p.opened_at, position: long ? 'belowBar' : 'aboveBar',
        color: palette.accent, shape: long ? 'arrowUp' : 'arrowDown',
        text: `${p.strategy} ${long ? '持多' : '持空'}`,
      });
    });
    markers.sort((a, b) => a.time - b.time);
    series.setMarkers(markers);

    // 价格线: 清旧 → 画当前开仓 SL/TP 台阶
    priceLinesRef.current.forEach((l) => { try { series.removePriceLine(l); } catch {} });
    priceLinesRef.current = [];
    (tv.open_positions || []).forEach((p) => {
      if (p.entry) priceLinesRef.current.push(series.createPriceLine({
        price: p.entry, color: 'rgba(203,213,225,0.5)', lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: `开仓 ${p.side === 'long' ? '多' : '空'}`,
      }));
      if (p.sl) priceLinesRef.current.push(series.createPriceLine({
        price: p.sl, color: C.sl, lineWidth: 1, lineStyle: 0,
        axisLabelVisible: true, title: 'SL 止损',
      }));
      (p.tp_levels || []).forEach((tp) => {
        if (!tp.price) return;
        priceLinesRef.current.push(series.createPriceLine({
          price: tp.price, color: tp.hit ? C.up : C.tp, lineWidth: 1, lineStyle: tp.hit ? 0 : 2,
          axisLabelVisible: true, title: `${tp.label}${tp.hit ? '✓已吃' : ''} ${tp.r ? tp.r + 'R' : ''}`,
        }));
      });
    });
  }, [tv]);

  const submitOrder = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await fetch(`${API}/api/manual-order`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, side, size_usdt: sizeUsdt, leverage }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        setMsg({ ok: true, text: `已下单 @ ${j.entry} · SL ${j.sl?.toFixed?.(2)} / TP ${j.tp?.toFixed?.(2)}${j.simulated ? ' [模拟]' : ''}` });
        loadTv();
      } else setMsg({ ok: false, text: j.error || '下单失败' });
    } catch (e) { setMsg({ ok: false, text: '网络错误' }); }
    finally { setBusy(false); }
  };

  const pos = (tv.open_positions || [])[0];

  return (
    <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="stretch">
      {/* 图 (主) */}
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Box ref={wrapRef} sx={{ width: '100%', height: 480 }} />
        {/* 图例 */}
        <Stack direction="row" spacing={1.5} flexWrap="wrap" sx={{ mt: 1 }}>
          <LegendDot color={C.up} label="开多/盈利平" />
          <LegendDot color={C.down} label="开空/亏损平" />
          <LegendDot color={C.sl} label="SL 止损线" />
          <LegendDot color={C.tp} label="TP 台阶 (✓=已吃)" />
        </Stack>
      </Box>

      {/* 手动交易面板 (右/下) */}
      <Box sx={{ width: { xs: '100%', md: 260 }, flexShrink: 0 }}>
        <Box sx={{ p: 1.75, borderRadius: 1, border: `1px solid ${palette.border}`, bgcolor: 'rgba(255,255,255,0.02)' }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>手动下单 · {symbol?.split('/')[0]}</Typography>
          <ToggleButtonGroup size="small" exclusive fullWidth value={side} onChange={(e, v) => v && setSide(v)} sx={{ mb: 1.5 }}>
            <ToggleButton value="long" sx={{ py: 0.5, ...(side === 'long' ? { color: '#fff', bgcolor: `${C.long} !important` } : {}) }}>做多 🔺</ToggleButton>
            <ToggleButton value="short" sx={{ py: 0.5, ...(side === 'short' ? { color: '#fff', bgcolor: `${C.short} !important` } : {}) }}>做空 🔻</ToggleButton>
          </ToggleButtonGroup>
          <TextField label="保证金 (USDT)" type="number" size="small" fullWidth value={sizeUsdt}
            onChange={(e) => setSizeUsdt(parseFloat(e.target.value) || 0)} sx={{ mb: 1.25 }} />
          <TextField label="杠杆" type="number" size="small" fullWidth value={leverage}
            onChange={(e) => setLeverage(parseFloat(e.target.value) || 1)} sx={{ mb: 0.5 }} />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
            名义 ≈ ${(sizeUsdt * leverage).toFixed(0)} · SL/TP 自动按 15m 业界标准
          </Typography>
          <Button fullWidth variant="contained" disabled={busy || sizeUsdt <= 0}
            onClick={submitOrder}
            sx={{ bgcolor: side === 'long' ? C.long : C.short, '&:hover': { bgcolor: side === 'long' ? C.long : C.short, filter: 'brightness(1.1)' } }}>
            {busy ? '下单中…' : (side === 'long' ? '买入做多' : '卖出做空')}
          </Button>
          {msg && <Typography variant="caption" sx={{ display: 'block', mt: 1, color: msg.ok ? palette.success : palette.error }}>{msg.text}</Typography>}
        </Box>

        {/* 当前持仓 (守门员/AI经理/手动 在图上做了什么) */}
        {pos && (
          <Box sx={{ mt: 1.5, p: 1.5, borderRadius: 1, border: `1px solid ${palette.accent}44`, bgcolor: `${palette.accent}0a` }}>
            <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: 0.75 }}>
              <Chip size="small" label={pos.source === 'gatekeeper' ? '守门员' : '手动'} sx={{ height: 18, fontSize: 10, bgcolor: `${palette.accent}22`, color: palette.accent }} />
              <Typography variant="caption" fontWeight={700}>{pos.strategy} · {pos.side === 'long' ? '多 🔺' : '空 🔻'}</Typography>
            </Stack>
            <Typography variant="caption" sx={{ display: 'block' }}>开仓 {pos.entry} · SL <span style={{ color: C.sl }}>{pos.sl?.toFixed?.(4)}</span></Typography>
            {(pos.tp_levels || []).map((tp) => (
              <Typography key={tp.label} variant="caption" sx={{ display: 'block', color: tp.hit ? palette.success : 'text.secondary' }}>
                {tp.label} {tp.r}R @ {tp.price} {tp.hit ? '✓已吃' : ''}
              </Typography>
            ))}
            <Divider sx={{ my: 0.75, borderColor: palette.border }} />
            <Typography variant="caption">浮盈 <b style={{ color: (pos.unrealized_pnl || 0) >= 0 ? palette.success : palette.error }}>
              {(pos.unrealized_pnl || 0) >= 0 ? '+' : ''}{(pos.unrealized_pnl || 0).toFixed(3)}</b></Typography>
          </Box>
        )}
      </Box>
    </Stack>
  );
}

function LegendDot({ color, label }) {
  return (
    <Stack direction="row" alignItems="center" spacing={0.5}>
      <Box sx={{ width: 8, height: 8, borderRadius: '2px', bgcolor: color }} />
      <Typography variant="caption" color="text.secondary" sx={{ fontSize: 10 }}>{label}</Typography>
    </Stack>
  );
}
