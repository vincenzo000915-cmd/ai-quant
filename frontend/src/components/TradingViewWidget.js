// Phase 12.19: TradingView Advanced Chart Widget（免费 iframe 嵌入）
//
// 替代原 BTCChart (lightweight-charts) — TV widget 自带：
//   - K 棒倒计时 / 多 TF 切换 / 自动 scale (永远不压扁)
//   - 全部专业指标（MACD/RSI/BB/EMA/...）+ drawings
//   - hover crosshair / fullscreen / 截图导出
//   - WebSocket 实时推送
//   - 多 symbol（BINANCE:BTCUSDT 等）
//
// 注：BUY/SELL/HOLD markers 改放 Dashboard 下方独立的 TradesTimeline 卡片
//
// Widget 文档：https://www.tradingview.com/widget/advanced-chart/

import React, { useEffect, useRef, memo } from 'react';
import { Box } from '@mui/material';
import { palette } from '../theme';

// OKX 现货 symbol → TV 的 OKX exchange code
// 注：TV 上 OKX 的合约用 "OKX:BTCUSDT.P" (perpetual)，spot 是 "OKX:BTCUSDT"
// 我们 backend 跑的是 USDT-SWAP，所以 perpetual 最合适
function toTvSymbol(symbol) {
  // "BTC/USDT" → "OKX:BTCUSDT.P"
  const clean = (symbol || 'BTC/USDT').replace('/', '');
  return `OKX:${clean}.P`;
}

// 我们的 timeframe → TV interval
const TF_TO_INTERVAL = {
  '15m': '15',
  '30m': '30',
  '1h':  '60',
  '4h':  '240',
  '1d':  'D',
  '1w':  'W',
};

function TradingViewWidgetInner({ symbol = 'BTC/USDT', timeframe = '1h', height = 520 }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;
    // 清空之前的 iframe（symbol/tf 切换时重建）
    containerRef.current.innerHTML = '';

    const scriptEl = document.createElement('script');
    scriptEl.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    scriptEl.async = true;
    scriptEl.type = 'text/javascript';
    scriptEl.innerHTML = JSON.stringify({
      autosize: true,
      symbol: toTvSymbol(symbol),
      interval: TF_TO_INTERVAL[timeframe] || '60',
      timezone: 'Etc/UTC',
      theme: 'dark',
      style: '1',                       // 1 = candles
      locale: 'zh_CN',
      enable_publishing: false,
      hide_side_toolbar: false,
      allow_symbol_change: false,        // 我们自己控制 symbol
      save_image: true,                  // 截图按钮
      details: true,                     // 显示 symbol 详情
      hotlist: false,
      calendar: false,
      backgroundColor: 'rgba(8,10,24,0.6)',
      gridColor: 'rgba(255,255,255,0.04)',
      withdateranges: true,              // 顶部时间段快捷
      hide_volume: false,                // 显示成交量
      studies: [
        'MACD@tv-basicstudies',
        'RSI@tv-basicstudies',
      ],                                  // 默认加 MACD + RSI 副图
      support_host: 'https://www.tradingview.com',
    });
    containerRef.current.appendChild(scriptEl);
  }, [symbol, timeframe]);

  return (
    <Box sx={{
      position: 'relative',
      width: '100%',
      height,
      borderRadius: 1,
      overflow: 'hidden',
      border: `1px solid ${palette.border || 'rgba(255,255,255,0.06)'}`,
      bgcolor: 'rgba(8,10,24,0.4)',
    }}>
      <div
        ref={containerRef}
        className="tradingview-widget-container"
        style={{ width: '100%', height: '100%' }}
      />
    </Box>
  );
}

export default memo(TradingViewWidgetInner);
