// Phase 12.15.3: 統一 KPI 細胞 — SaaS 級簡潔，去掉 corner accent / radial glow / glow text
// 只保留：label / 主數字 / 副信息（趨勢箭頭可選）

import React from 'react';
import { Box, Stack, Typography } from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import RemoveIcon from '@mui/icons-material/Remove';
import { palette, typo, pnlColor } from '../../theme';

export default function KpiCell({
  label,
  value,
  sub,
  trend = null,          // 'up' | 'down' | 'flat' | null
  trendValue = null,     // 數字，自動上下 — 跟 trend 二選一
  accent = null,         // 強調色 ('success' | 'error' | 'accent' | null)
  loading = false,
  size = 'sub',          // 'hero' | 'sub' — hero 是主 KPI，大字 + accent border
  icon = null,           // 可選 emoji 或圖標
}) {
  // 自動推 trend
  let trendDir = trend;
  if (trendDir === null && trendValue !== null) {
    trendDir = trendValue > 0 ? 'up' : trendValue < 0 ? 'down' : 'flat';
  }
  const trendColor = trendDir === 'up' ? palette.success
    : trendDir === 'down' ? palette.error
    : palette.textMuted;
  const TrendIcon = trendDir === 'up' ? TrendingUpIcon
    : trendDir === 'down' ? TrendingDownIcon
    : RemoveIcon;

  const valueColor = accent === 'success' ? palette.success
    : accent === 'error' ? palette.error
    : accent === 'accent' ? palette.accent
    : palette.text;

  const isHero = size === 'hero';
  const metricFontSize = isHero
    ? { xs: '2rem', sm: '2.4rem', md: '2.8rem' }
    : { xs: '1.25rem', md: '1.5rem' };

  // hero variant：左側 accent bar + 渐变暖底
  return (
    <Box sx={{
      position: 'relative',
      p: isHero ? 2.5 : 2,
      bgcolor: palette.surface,
      border: `1px solid ${palette.border}`,
      borderRadius: 1.5,
      height: '100%',
      minHeight: isHero ? 132 : 90,
      display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      overflow: 'hidden',
      transition: 'border-color 120ms ease, background 120ms ease',
      // hero 加一道左側 accent bar + 微微暖渐层
      ...(isHero && {
        background: `linear-gradient(135deg, ${palette.surface} 0%, ${palette.surface2} 100%)`,
        '&::before': {
          content: '""',
          position: 'absolute',
          left: 0, top: 0, bottom: 0,
          width: 3,
          background: valueColor === palette.text ? palette.accent : valueColor,
          opacity: 0.9,
        },
      }),
      '&:hover': { borderColor: palette.borderHot },
    }}>
      <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: isHero ? 1 : 0.5 }}>
        {icon && <Box sx={{ fontSize: isHero ? 16 : 13, opacity: 0.7 }}>{icon}</Box>}
        <Typography sx={{ ...typo.label, color: palette.textMuted, fontSize: isHero ? '0.78rem' : '0.6875rem' }}>
          {label}
        </Typography>
      </Stack>
      <Box>
        <Typography sx={{
          ...typo.metric,
          color: valueColor,
          fontSize: metricFontSize,
          fontWeight: isHero ? 700 : 700,
          lineHeight: 1.05,
        }}>
          {loading ? '—' : value}
        </Typography>
        {(sub || trendDir) && (
          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: isHero ? 1 : 0.5 }}>
            {trendDir && <TrendIcon sx={{ fontSize: isHero ? 16 : 13, color: trendColor }} />}
            <Typography sx={{
              ...typo.caption,
              color: trendDir ? trendColor : palette.textMuted,
              fontFamily: typo.mono,
              fontSize: isHero ? '0.82rem' : '0.72rem',
            }}>
              {sub}
            </Typography>
          </Stack>
        )}
      </Box>
    </Box>
  );
}
