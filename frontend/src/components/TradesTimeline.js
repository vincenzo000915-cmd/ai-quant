// Phase 12.19: Trades Timeline — 替代 K 线 markers 显示「策略动作时间线」
//
// 跟 TV Widget 分工：
//   - TV Widget = 看行情
//   - TradesTimeline = 看「我们策略干了什么」
//
// 每行显示：时间 / strategy / symbol / 动作 (BUY/SELL/HOLD) / 价格 / PnL / 持仓时长 / 原因

import React, { useMemo } from 'react';
import { Box, Typography, Chip } from '@mui/material';
import { palette } from '../theme';

function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${mm}-${dd} ${hh}:${mi}`;
}

function fmtDuration(startIso, endIso) {
  if (!startIso) return '';
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const sec = Math.floor((end - start) / 1000);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h${Math.floor((sec % 3600) / 60)}m`;
  return `${Math.floor(sec / 86400)}d${Math.floor((sec % 86400) / 3600)}h`;
}

function fmtPrice(p) {
  if (p == null) return '—';
  if (p >= 100) return p.toFixed(1);
  if (p >= 1) return p.toFixed(3);
  return p.toFixed(4);
}

const REASON_LABEL = {
  stop_loss: '止损',
  take_profit: '止盈',
  signal: '信号',
  reconcile_orphan: '对账孤儿',
  manual: '手动',
};

export default function TradesTimeline({ trades = [], positions = [], strategyNameMap = {}, maxRows = 30, height = 520 }) {
  const events = useMemo(() => {
    const arr = [];

    // Open positions → HOLD 事件
    (positions || []).filter(p => p.status === 'open').forEach(p => {
      arr.push({
        kind: 'hold',
        time: p.opened_at,
        strategy_id: p.strategy_id,
        symbol: p.symbol,
        side: p.side,
        entry_price: p.entry_price,
        unrealized_pnl: p.unrealized_pnl,
        duration: fmtDuration(p.opened_at, null),
        key: `pos-${p.id}`,
      });
    });

    // Trades → 已完成的 BUY+SELL pair（用 exit_time 作为主时间排序，但显示「持仓 X → 退出」一行）
    (trades || []).forEach(t => {
      arr.push({
        kind: t.pnl >= 0 ? 'win' : 'loss',
        time: t.exit_time || t.entry_time,
        entry_time: t.entry_time,
        exit_time: t.exit_time,
        strategy_id: t.strategy_id,
        symbol: t.symbol,
        side: t.side,
        entry_price: t.entry_price,
        exit_price: t.exit_price,
        pnl: t.pnl,
        pnl_percent: t.pnl_percent,
        reason: t.reason,
        duration: fmtDuration(t.entry_time, t.exit_time),
        key: `trade-${t.id}`,
      });
    });

    arr.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());
    return arr.slice(0, maxRows);
  }, [trades, positions, maxRows]);

  if (events.length === 0) {
    return (
      <Box sx={{
        height, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: palette.textMuted,
        border: `1px solid ${palette.border || 'rgba(255,255,255,0.06)'}`,
        borderRadius: 1, bgcolor: 'rgba(8,10,24,0.4)',
      }}>
        <Typography variant="caption">暂无策略动作</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{
      height,
      overflowY: 'auto',
      border: `1px solid ${palette.border || 'rgba(255,255,255,0.06)'}`,
      borderRadius: 1,
      bgcolor: 'rgba(8,10,24,0.4)',
      fontFamily: '"JetBrains Mono", monospace',
    }}>
      {events.map(ev => {
        const stratName = strategyNameMap[ev.strategy_id] || `#${ev.strategy_id}`;
        const isHold = ev.kind === 'hold';
        const isWin = ev.kind === 'win';
        const actionColor = isHold ? palette.warning : (isWin ? palette.success : palette.error);
        const actionLabel = isHold ? 'HOLD' : (ev.side === 'long' ? 'LONG' : 'SHORT');

        return (
          <Box key={ev.key} sx={{
            display: 'grid',
            gridTemplateColumns: '88px 56px 1fr 90px 80px 90px 70px',
            alignItems: 'center',
            gap: 1,
            px: 1.25, py: 0.85,
            borderBottom: '1px solid rgba(255,255,255,0.04)',
            fontSize: 12,
            transition: 'background 0.15s',
            '&:hover': { bgcolor: 'rgba(255,255,255,0.02)' },
          }}>
            {/* 时间 */}
            <Typography component="span" sx={{
              fontSize: 11, fontFamily: 'inherit',
              color: palette.textMuted, whiteSpace: 'nowrap',
            }}>
              {fmtTime(ev.time)}
            </Typography>

            {/* 动作 chip */}
            <Box sx={{
              px: 0.6, py: 0.1,
              borderRadius: 0.4,
              border: `1px solid ${actionColor}`,
              color: actionColor,
              fontSize: 10, fontWeight: 700,
              textAlign: 'center',
              fontFamily: 'inherit',
              lineHeight: 1.4,
            }}>
              {actionLabel}
            </Box>

            {/* strategy + symbol */}
            <Box sx={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <Typography component="span" sx={{
                fontSize: 12, fontWeight: 600, color: palette.text,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>
                {stratName}
              </Typography>
              <Typography component="span" sx={{ fontSize: 10, color: palette.textMuted, fontFamily: 'inherit' }}>
                {ev.symbol}
              </Typography>
            </Box>

            {/* 价格 entry → exit (或 entry 进行中) */}
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
              <Typography component="span" sx={{ fontSize: 11, color: palette.text, fontFamily: 'inherit' }}>
                {isHold ? `@$${fmtPrice(ev.entry_price)}` : `$${fmtPrice(ev.entry_price)}→$${fmtPrice(ev.exit_price)}`}
              </Typography>
            </Box>

            {/* PnL（HOLD 显示未实现，已完成显示实现） */}
            <Box sx={{ textAlign: 'right' }}>
              {isHold ? (
                <Typography component="span" sx={{
                  fontSize: 12, fontWeight: 700, fontFamily: 'inherit',
                  color: (ev.unrealized_pnl ?? 0) >= 0 ? palette.success : palette.error,
                }}>
                  {(ev.unrealized_pnl ?? 0) >= 0 ? '+' : ''}{(ev.unrealized_pnl ?? 0).toFixed(2)}
                </Typography>
              ) : (
                <Box>
                  <Typography component="span" sx={{
                    fontSize: 12, fontWeight: 700, fontFamily: 'inherit',
                    color: ev.pnl >= 0 ? palette.success : palette.error,
                  }}>
                    {ev.pnl >= 0 ? '+' : ''}${(ev.pnl || 0).toFixed(2)}
                  </Typography>
                  <Typography component="span" sx={{
                    display: 'block',
                    fontSize: 9, fontFamily: 'inherit',
                    color: ev.pnl >= 0 ? palette.success : palette.error,
                    opacity: 0.7,
                  }}>
                    {ev.pnl_percent >= 0 ? '+' : ''}{(ev.pnl_percent || 0).toFixed(2)}%
                  </Typography>
                </Box>
              )}
            </Box>

            {/* 持仓时长 */}
            <Typography component="span" sx={{
              fontSize: 10, fontFamily: 'inherit',
              color: palette.textMuted, textAlign: 'right',
            }}>
              {ev.duration}
            </Typography>

            {/* 退出原因 */}
            <Typography component="span" sx={{
              fontSize: 10, fontFamily: 'inherit',
              color: palette.textMuted, textAlign: 'right',
            }}>
              {isHold ? '进行中' : (REASON_LABEL[ev.reason] || ev.reason || '—')}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
}
