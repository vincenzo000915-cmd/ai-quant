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

  // 對應 accent color 給 hero 加 subtle radial glow 在右上角
  const accentColor = valueColor === palette.text ? palette.accent : valueColor;
  const glowRgba = accent === 'success' ? 'rgba(16,185,129,0.18)'
    : accent === 'error' ? 'rgba(244,63,94,0.18)'
    : accent === 'accent' ? 'rgba(6,182,212,0.16)'
    : 'rgba(255,255,255,0.04)';

  return (
    <Box sx={{
      position: 'relative',
      p: isHero ? 2.5 : 2,
      // hero 用更亮 surface 浮起來；sub 用標準 surface
      bgcolor: isHero ? palette.surface2 : palette.surface,
      border: `1px solid ${palette.border}`,
      borderRadius: 1.5,
      height: '100%',
      minHeight: isHero ? 132 : 90,
      display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      overflow: 'hidden',
      cursor: 'default',
      // 多層 shadow 給 elevation 而不是扁平
      boxShadow: isHero
        ? `0 1px 0 rgba(255,255,255,0.04) inset, 0 12px 32px -16px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.02)`
        : `0 1px 0 rgba(255,255,255,0.03) inset, 0 4px 12px -8px rgba(0,0,0,0.5)`,
      transition: 'all 180ms cubic-bezier(0.4, 0, 0.2, 1)',
      // hero 加渐变 + 右上角 radial glow
      ...(isHero && {
        background: `
          radial-gradient(circle at top right, ${glowRgba} 0%, transparent 60%),
          linear-gradient(135deg, ${palette.surface2} 0%, ${palette.surface} 100%)
        `,
        '&::before': {
          content: '""',
          position: 'absolute',
          left: 0, top: 0, bottom: 0,
          width: 3,
          background: accentColor,
          opacity: 0.95,
          boxShadow: `0 0 12px ${accentColor}`,
        },
      }),
      // micro hover lift — SaaS 級 polish
      '&:hover': {
        transform: 'translateY(-2px)',
        borderColor: palette.borderHot,
        boxShadow: isHero
          ? `0 1px 0 rgba(255,255,255,0.06) inset, 0 20px 40px -16px rgba(0,0,0,0.7), 0 0 0 1px ${accentColor}33`
          : `0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 20px -10px rgba(0,0,0,0.6)`,
      },
    }}>
      <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: isHero ? 1 : 0.5 }}>
        {icon && <Box sx={{ fontSize: isHero ? 18 : 13, opacity: 0.85, filter: isHero ? 'drop-shadow(0 0 8px rgba(255,255,255,0.15))' : 'none' }}>{icon}</Box>}
        <Typography sx={{ ...typo.label, color: palette.textMuted, fontSize: isHero ? '0.78rem' : '0.6875rem' }}>
          {label}
        </Typography>
      </Stack>
      <Box>
        <Typography sx={{
          ...typo.metric,
          color: valueColor,
          fontSize: metricFontSize,
          fontWeight: 700,
          lineHeight: 1.05,
          // hero 數字加微 text-shadow 給「重量 + 發光」感
          ...(isHero && {
            textShadow: `0 0 24px ${accentColor}44, 0 2px 4px rgba(0,0,0,0.3)`,
          }),
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
