import React, { useEffect, useRef, useState } from 'react';
import { Box, Typography } from '@mui/material';
import { createChart, CrosshairMode } from 'lightweight-charts';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera';
import { IconButton, Tooltip } from '@mui/material';
import { palette } from '../theme';

const TF_SECONDS = {
  '15m': 15 * 60, '30m': 30 * 60, '1h': 3600, '4h': 4 * 3600,
  '1d': 86400, '1w': 7 * 86400,
};

function useCandleCountdown(timeframe) {
  const [remaining, setRemaining] = useState(0);
  useEffect(() => {
    const sec = TF_SECONDS[timeframe] || 3600;
    const tick = () => {
      const now = Math.floor(Date.now() / 1000);
      const nextClose = Math.ceil(now / sec) * sec;
      setRemaining(nextClose - now);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [timeframe]);
  return remaining;
}

function fmtCountdown(sec) {
  if (sec <= 0) return '收盤中';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/**
 * Phase 7.4: BTC K 線（TradingView lightweight-charts）
 *
 * props:
 *   data       : [{ timestamp, open, high, low, close, volume }, ...]（ts in ms）
 *   trades     : [{ entry_time, entry_price, exit_time, exit_price, pnl, ... }]
 *   positions  : [{ id, strategy_id, side, entry_price, opened_at, unrealized_pnl, ... }]
 *   indicators : { sma20, ema50, bb, signals }
 *   timeframe  : '15m' | '30m' | '1h' | '4h' | '1d' | '1w'
 *   height     : number, default 360
 */
export default function BTCChart({ data, trades, positions, indicators, timeframe = '1h', height = 360 }) {
  const remaining = useCandleCountdown(timeframe);
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const sma20Ref = useRef(null);
  const ema50Ref = useRef(null);
  const bbUpperRef = useRef(null);
  const bbLowerRef = useRef(null);
  // Phase 12.16: hover OHLC 数据 + fullscreen
  const [hoverData, setHoverData] = useState(null);   // {o, h, l, c, vol, time}
  const [fullscreen, setFullscreen] = useState(false);
  const effectiveHeight = fullscreen ? 'calc(100vh - 200px)' : height;
  // 24h 变化（拿最近 + 最早算）
  const stat24h = (() => {
    if (!data || data.length < 2) return null;
    const last = data[data.length - 1];
    const dayAgo = data.find(d => d.timestamp >= last.timestamp - 86400_000) || data[0];
    if (!dayAgo || !last || !dayAgo.close || !last.close) return null;
    const change = last.close - dayAgo.close;
    const changePct = (change / dayAgo.close) * 100;
    const high24 = Math.max(...data.slice(-Math.min(24, data.length)).map(d => d.high || 0));
    const low24 = Math.min(...data.slice(-Math.min(24, data.length)).map(d => d.low || Infinity));
    return { change, changePct, high24, low24, last: last.close };
  })();

  // 初始化 chart（只跑一次）
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: 'transparent' },
        textColor: 'rgba(203,213,225,0.75)',
        fontFamily: 'JetBrains Mono, monospace',
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.03)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: 'rgba(251,191,36,0.4)', width: 1, style: 2 },
        horzLine: { color: 'rgba(251,191,36,0.4)', width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: 'rgba(255,255,255,0.06)',
        scaleMargins: { top: 0.1, bottom: 0.2 },   // 留下面 20% 給 volume
      },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.06)',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00d4aa',
      downColor: '#ff4757',
      borderUpColor: '#00d4aa',
      borderDownColor: '#ff4757',
      wickUpColor: '#00d4aa',
      wickDownColor: '#ff4757',
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',   // 獨立比例，不跟價格混
      color: 'rgba(6,182,212,0.4)',
      lastValueVisible: false,
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },     // 只佔底部 ~18%
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    // Phase 12.16: 监听 crosshair 移动更新 hover OHLC 数据
    chart.subscribeCrosshairMove(param => {
      if (!param || !param.time || !param.seriesData) {
        setHoverData(null);
        return;
      }
      const candleData = param.seriesData.get(candleSeries);
      const volData = param.seriesData.get(volumeSeries);
      if (candleData) {
        setHoverData({
          o: candleData.open, h: candleData.high, l: candleData.low, c: candleData.close,
          vol: volData?.value, time: param.time,
        });
      }
    });

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [height]);

  // Phase 12.16.1: 增量更新主 K 線 + volume — 5s polling 不重置 zoom / crosshair
  //   首次 / symbol/tf 切换 → setData() 全量
  //   后续：只对最后一根 candle 调用 update()
  const lastLastTsRef = useRef(0);
  const lastFirstTsRef = useRef(0);
  useEffect(() => {
    if (!candleSeriesRef.current || !data || !data.length) return;
    const candles = data
      .filter(d => d.open != null && d.high != null && d.low != null && d.close != null)
      .map(d => ({
        time: Math.floor(d.timestamp / 1000),
        open: d.open, high: d.high, low: d.low, close: d.close,
      }));
    const vols = data
      .filter(d => d.volume != null)
      .map(d => ({
        time: Math.floor(d.timestamp / 1000),
        value: d.volume,
        color: d.close >= d.open ? 'rgba(0,212,170,0.4)' : 'rgba(255,71,87,0.4)',
      }));
    if (candles.length === 0) return;

    const firstTs = candles[0].time;
    const lastTs = candles[candles.length - 1].time;
    // 全量重置触发条件：首次 / 切换 symbol/tf (firstTs 变) / 新数据 last 比之前还旧
    const isReset = lastFirstTsRef.current !== firstTs || lastTs < lastLastTsRef.current;
    lastFirstTsRef.current = firstTs;

    if (isReset) {
      candleSeriesRef.current.setData(candles);
      volumeSeriesRef.current.setData(vols);
      chartRef.current?.timeScale().fitContent();
      lastLastTsRef.current = lastTs;
    } else {
      // 增量：只对 ts > lastLastTsRef 或 ts == lastLastTsRef 的 candle 调用 update()
      // update() 自动处理 append (new candle) 或 update (same ts, new OHLC)
      for (const c of candles) {
        if (c.time >= lastLastTsRef.current) {
          candleSeriesRef.current.update(c);
        }
      }
      for (const v of vols) {
        if (v.time >= lastLastTsRef.current) {
          volumeSeriesRef.current.update(v);
        }
      }
      lastLastTsRef.current = lastTs;
    }
  }, [data]);

  // 指標：SMA20 / EMA50 / Bollinger
  useEffect(() => {
    if (!chartRef.current || !data || !data.length) return;
    const closes = data.map(d => d.close).filter(v => v != null);
    const times = data.map(d => Math.floor(d.timestamp / 1000));

    // 移除舊指標 line
    [sma20Ref, ema50Ref, bbUpperRef, bbLowerRef].forEach(ref => {
      if (ref.current) {
        try { chartRef.current.removeSeries(ref.current); } catch {/* */}
        ref.current = null;
      }
    });

    if (indicators?.sma20) {
      const sma = closes.map((_, i) => {
        if (i < 19) return null;
        const slice = closes.slice(i - 19, i + 1);
        return slice.reduce((s, v) => s + v, 0) / 20;
      });
      const s = chartRef.current.addLineSeries({
        color: 'rgba(6,182,212,0.85)',
        lineWidth: 1.5,
        priceLineVisible: false,
        lastValueVisible: false,
        title: 'SMA20',
      });
      s.setData(sma.map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean));
      sma20Ref.current = s;
    }

    if (indicators?.ema50) {
      const k = 2 / (50 + 1);
      let prev = closes[0];
      const ema = closes.map((p, i) => {
        if (i === 0) { prev = p; return null; }
        prev = p * k + prev * (1 - k);
        return i >= 49 ? prev : null;
      });
      const s = chartRef.current.addLineSeries({
        color: 'rgba(6,182,212,0.85)',
        lineWidth: 1.5,
        priceLineVisible: false,
        lastValueVisible: false,
        title: 'EMA50',
      });
      s.setData(ema.map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean));
      ema50Ref.current = s;
    }

    if (indicators?.bb) {
      const N = closes.length;
      const upper = []; const lower = [];
      for (let i = 0; i < N; i++) {
        if (i < 19) { upper.push(null); lower.push(null); continue; }
        const slice = closes.slice(i - 19, i + 1);
        const mean = slice.reduce((s, v) => s + v, 0) / 20;
        const variance = slice.reduce((s, v) => s + (v - mean) ** 2, 0) / 20;
        const std = Math.sqrt(variance);
        upper.push(mean + 2 * std);
        lower.push(mean - 2 * std);
      }
      const su = chartRef.current.addLineSeries({
        color: 'rgba(6,182,212,0.6)',
        lineWidth: 1,
        lineStyle: 2,   // dashed
        priceLineVisible: false,
        lastValueVisible: false,
        title: 'BB↑',
      });
      su.setData(upper.map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean));
      bbUpperRef.current = su;

      const sl = chartRef.current.addLineSeries({
        color: 'rgba(6,182,212,0.6)',
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        title: 'BB↓',
      });
      sl.setData(lower.map((v, i) => v != null ? { time: times[i], value: v } : null).filter(Boolean));
      bbLowerRef.current = sl;
    }
  }, [data, indicators]);

  // 信號 markers — 已完成 trades 的進出 + 未平倉 positions 的入場
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    if (!indicators?.signals) {
      candleSeriesRef.current.setMarkers([]);
      return;
    }
    const markers = [];

    // 已完成 trades
    (trades || []).forEach(t => {
      if (t.entry_time) {
        markers.push({
          time: Math.floor(new Date(t.entry_time).getTime() / 1000),
          position: 'belowBar',
          color: '#00d4aa',
          shape: 'arrowUp',
          text: `BUY $${t.entry_price?.toFixed(0) || ''}`,
        });
      }
      if (t.exit_time) {
        const pnlOk = (t.pnl || 0) >= 0;
        markers.push({
          time: Math.floor(new Date(t.exit_time).getTime() / 1000),
          position: 'aboveBar',
          color: pnlOk ? '#00d4aa' : '#ff4757',
          shape: 'arrowDown',
          text: `${pnlOk ? '+' : ''}${(t.pnl || 0).toFixed(2)}`,
        });
      }
    });

    // 持倉中（沒平的）— 用空心 circle 區別於已平
    (positions || []).filter(p => p.status === 'open').forEach(p => {
      if (p.opened_at) {
        markers.push({
          time: Math.floor(new Date(p.opened_at).getTime() / 1000),
          position: 'belowBar',
          color: '#f7a600',
          shape: 'circle',
          text: `HOLD ${p.unrealized_pnl >= 0 ? '+' : ''}${(p.unrealized_pnl || 0).toFixed(2)}`,
        });
      }
    });

    markers.sort((a, b) => a.time - b.time);
    candleSeriesRef.current.setMarkers(markers);
  }, [trades, positions, indicators?.signals]);

  // 显示 hover 时的 OHLC，否则显示最近一根
  const ohlc = hoverData || (data && data.length ? {
    o: data[data.length - 1].open, h: data[data.length - 1].high,
    l: data[data.length - 1].low, c: data[data.length - 1].close,
    vol: data[data.length - 1].volume,
  } : null);
  const ohlcChange = ohlc ? (ohlc.c - ohlc.o) : 0;
  const ohlcColor = ohlcChange >= 0 ? palette.success : palette.error;

  return (
    <Box sx={{
      position: 'relative',
      ...(fullscreen && {
        position: 'fixed', inset: 0, zIndex: 1300,
        bgcolor: palette.bg,
        p: 3,
        display: 'flex', flexDirection: 'column',
      }),
    }}>
      {/* Phase 12.16: 顶部 OHLC bar — TradingView 风 */}
      <Box sx={{
        display: 'flex', alignItems: 'center', gap: 2,
        px: 1, py: 0.85, mb: 0.5,
        flexWrap: 'wrap',
        fontFamily: '"JetBrains Mono", monospace',
        fontSize: 11,
      }}>
        {ohlc && (
          <>
            <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'baseline' }}>
              {[
                { k: 'O', v: ohlc.o },
                { k: 'H', v: ohlc.h },
                { k: 'L', v: ohlc.l },
                { k: 'C', v: ohlc.c },
              ].map(item => (
                <Box key={item.k} sx={{ display: 'flex', alignItems: 'baseline', gap: 0.4 }}>
                  <Typography component="span" sx={{ fontSize: 9, fontWeight: 700, color: palette.textMuted, letterSpacing: 0.3 }}>{item.k}</Typography>
                  <Typography component="span" sx={{ fontSize: 12, fontWeight: 600, color: palette.text, fontFamily: 'inherit' }}>
                    {item.v?.toFixed?.(item.v > 100 ? 1 : 4) ?? '—'}
                  </Typography>
                </Box>
              ))}
              <Typography component="span" sx={{
                fontSize: 11, fontWeight: 700, color: ohlcColor, fontFamily: 'inherit', ml: 0.5,
              }}>
                {ohlcChange >= 0 ? '+' : ''}{ohlcChange?.toFixed?.(1)}
              </Typography>
            </Box>
            {ohlc.vol && (
              <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.4 }}>
                <Typography component="span" sx={{ fontSize: 9, fontWeight: 700, color: palette.textMuted, letterSpacing: 0.3 }}>VOL</Typography>
                <Typography component="span" sx={{ fontSize: 11, color: palette.textMuted, fontFamily: 'inherit' }}>
                  {ohlc.vol > 1e6 ? `${(ohlc.vol / 1e6).toFixed(1)}M` : ohlc.vol > 1e3 ? `${(ohlc.vol / 1e3).toFixed(1)}K` : ohlc.vol?.toFixed(0)}
                </Typography>
              </Box>
            )}
          </>
        )}
        {stat24h && !hoverData && (
          <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1.5, ml: 'auto' }}>
            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.4 }}>
              <Typography component="span" sx={{ fontSize: 9, fontWeight: 700, color: palette.textMuted }}>24H</Typography>
              <Typography component="span" sx={{ fontSize: 11, color: stat24h.changePct >= 0 ? palette.success : palette.error, fontFamily: 'inherit', fontWeight: 700 }}>
                {stat24h.changePct >= 0 ? '+' : ''}{stat24h.changePct.toFixed(2)}%
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.4 }}>
              <Typography component="span" sx={{ fontSize: 9, fontWeight: 700, color: palette.textMuted }}>H</Typography>
              <Typography component="span" sx={{ fontSize: 11, color: palette.text, fontFamily: 'inherit' }}>{stat24h.high24?.toFixed(0)}</Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.4 }}>
              <Typography component="span" sx={{ fontSize: 9, fontWeight: 700, color: palette.textMuted }}>L</Typography>
              <Typography component="span" sx={{ fontSize: 11, color: palette.text, fontFamily: 'inherit' }}>{stat24h.low24?.toFixed(0)}</Typography>
            </Box>
          </Box>
        )}
        <Tooltip title="截图导出">
          <IconButton size="small" onClick={() => {
            // lightweight-charts takeScreenshot
            try {
              const canvas = chartRef.current?.takeScreenshot?.();
              if (!canvas) return;
              const link = document.createElement('a');
              link.download = `chart-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png`;
              link.href = canvas.toDataURL('image/png');
              link.click();
            } catch (e) { console.error('截图失败:', e); }
          }}
            sx={{ ml: stat24h ? 0 : 'auto', color: palette.textMuted, '&:hover': { color: palette.accent } }}>
            <PhotoCameraIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title={fullscreen ? '退出全屏' : '全屏'}>
          <IconButton size="small" onClick={() => setFullscreen(f => !f)}
            sx={{ color: palette.textMuted, '&:hover': { color: palette.accent } }}>
            {fullscreen ? <FullscreenExitIcon fontSize="small" /> : <FullscreenIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Box>

      <div ref={containerRef} style={{ width: '100%', height: effectiveHeight, flexGrow: fullscreen ? 1 : 0 }} />
      {/* 倒計時（LIVE 标识已上移到 chart 容器顶部，删本地重复）*/}
      <Box sx={{
        position: 'absolute', top: fullscreen ? 80 : 48, left: 12,
        display: 'flex', alignItems: 'center', gap: 1,
        fontFamily: 'JetBrains Mono, monospace',
        pointerEvents: 'none',
      }}>
        <Box sx={{
          px: 0.8, py: 0.2,
          bgcolor: 'rgba(8,10,24,0.7)',
          border: '1px solid rgba(251,191,36,0.3)',
          borderRadius: 0.5,
        }}>
          <Typography variant="caption" sx={{ color: 'rgba(148,163,184,0.7)', fontSize: '0.6rem', mr: 0.5 }}>
            下一根{timeframe}
          </Typography>
          <Typography component="span" sx={{ color: '#f7a600', fontWeight: 700, fontSize: '0.72rem', fontFamily: 'JetBrains Mono, monospace' }}>
            {fmtCountdown(remaining)}
          </Typography>
        </Box>
        {indicators?.signals && (
          <Box sx={{
            display: 'flex', gap: 1, alignItems: 'center',
            px: 0.8, py: 0.2,
            bgcolor: 'rgba(8,10,24,0.7)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 0.5,
          }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25 }}>
              <Box sx={{ width: 0, height: 0, borderLeft: '4px solid transparent', borderRight: '4px solid transparent', borderBottom: '6px solid #00d4aa' }} />
              <Typography variant="caption" sx={{ fontSize: '0.6rem', color: 'rgba(148,163,184,0.8)' }}>BUY</Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25 }}>
              <Box sx={{ width: 0, height: 0, borderLeft: '4px solid transparent', borderRight: '4px solid transparent', borderTop: '6px solid #ff4757' }} />
              <Typography variant="caption" sx={{ fontSize: '0.6rem', color: 'rgba(148,163,184,0.8)' }}>SELL</Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25 }}>
              <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#f7a600' }} />
              <Typography variant="caption" sx={{ fontSize: '0.6rem', color: 'rgba(148,163,184,0.8)' }}>HOLD</Typography>
            </Box>
          </Box>
        )}
      </Box>
    </Box>
  );
}
