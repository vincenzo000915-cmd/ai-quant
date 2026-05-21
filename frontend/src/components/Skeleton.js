// Phase 12.15.1: 統一骨架屏 — 取代各頁面的 CircularProgress / LinearProgress
// SaaS 級別「立刻看到結構」感而不是 spinner 等

import React from 'react';
import { Box, Skeleton as MuiSkeleton, Card, CardContent, Stack, Grid } from '@mui/material';

// KPI 顶 bar 4 块
export function KpiBarSkeleton() {
  return (
    <Grid container spacing={1.5} sx={{ mb: 2 }}>
      {[0, 1, 2, 3].map(i => (
        <Grid item xs={6} md={3} key={i}>
          <Box sx={{
            p: 1.5, border: '1px solid rgba(6,182,212,0.1)',
            borderRadius: 1.5, bgcolor: 'rgba(8,10,24,0.4)',
            position: 'relative', overflow: 'hidden',
          }}>
            <MuiSkeleton variant="text" width="55%" height={14} sx={{ bgcolor: 'rgba(255,255,255,0.04)' }} />
            <MuiSkeleton variant="text" width="80%" height={30} sx={{ bgcolor: 'rgba(255,255,255,0.06)' }} />
          </Box>
        </Grid>
      ))}
    </Grid>
  );
}

// 通用 panel/card 骨架
export function CardSkeleton({ height = 200, headerWidth = '40%', rows = 3 }) {
  return (
    <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
      <CardContent sx={{ px: 2.5, py: 2 }}>
        <MuiSkeleton variant="text" width={headerWidth} height={28} sx={{ mb: 1, bgcolor: 'rgba(255,255,255,0.06)' }} />
        <MuiSkeleton variant="text" width="70%" height={14} sx={{ mb: 2, bgcolor: 'rgba(255,255,255,0.04)' }} />
        <Stack spacing={1}>
          {Array.from({ length: rows }).map((_, i) => (
            <MuiSkeleton key={i} variant="rectangular" height={(height - 80) / rows} sx={{ bgcolor: 'rgba(255,255,255,0.03)', borderRadius: 0.5 }} />
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}

// K 線骨架
export function ChartSkeleton({ height = 320 }) {
  return (
    <Box sx={{
      width: '100%', height, position: 'relative',
      border: '1px solid rgba(6,182,212,0.12)',
      borderRadius: 1, bgcolor: 'rgba(8,10,24,0.4)',
      overflow: 'hidden',
    }}>
      {/* 模拟 K 线 bar 高低 */}
      <Stack direction="row" spacing={0.5} sx={{ position: 'absolute', inset: 16, alignItems: 'flex-end' }}>
        {Array.from({ length: 28 }).map((_, i) => {
          const h = 20 + Math.abs(Math.sin(i * 0.7) * 60) + (i % 3 === 0 ? 30 : 0);
          return (
            <MuiSkeleton
              key={i} variant="rectangular"
              sx={{
                flexGrow: 1, height: `${h}%`,
                bgcolor: i % 2 === 0 ? 'rgba(0,212,170,0.08)' : 'rgba(255,71,87,0.08)',
                borderRadius: 0.5, opacity: 0.6,
              }}
            />
          );
        })}
      </Stack>
    </Box>
  );
}

// table row 骨架（strategies 表用）
export function TableRowSkeleton({ rows = 5, cols = 6 }) {
  return (
    <Stack spacing={1.2}>
      {Array.from({ length: rows }).map((_, r) => (
        <Stack key={r} direction="row" spacing={1.5} alignItems="center">
          {Array.from({ length: cols }).map((_, c) => (
            <MuiSkeleton
              key={c} variant="text" height={18}
              sx={{
                flex: c === 0 ? 2 : 1,
                bgcolor: 'rgba(255,255,255,0.04)',
              }}
            />
          ))}
        </Stack>
      ))}
    </Stack>
  );
}

// page-level 骨架（顶 + KPI + 2 card + chart）
export function PageSkeleton() {
  return (
    <Box>
      <MuiSkeleton variant="text" width={200} height={36} sx={{ mb: 0.5, bgcolor: 'rgba(255,255,255,0.06)' }} />
      <MuiSkeleton variant="text" width={320} height={14} sx={{ mb: 2.5, bgcolor: 'rgba(255,255,255,0.04)' }} />
      <KpiBarSkeleton />
      <CardSkeleton height={280} rows={5} />
      <ChartSkeleton />
    </Box>
  );
}
