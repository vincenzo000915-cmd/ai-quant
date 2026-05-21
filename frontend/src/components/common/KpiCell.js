// Phase 12.15.3: 統一 KPI 細胞 — SaaS 級簡潔，去掉 corner accent / radial glow / glow text
// 只保留：label / 主數字 / 副信息（趨勢箭頭可選）

import React from 'react';
import { Box, Stack, Typography } from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import RemoveIcon from '@mui/icons-material/Remove';
import { LineChart, Line, ResponsiveContainer, Area, AreaChart } from 'recharts';
import { palette, typo, pnlColor } from '../../theme';

// 內嵌 mini sparkline — 金融科技風關鍵元素
function MiniSparkline({ data, color, height = 28 }) {
  if (!data || data.length < 2) {
    return <Box sx={{ height, opacity: 0.2, color: palette.textFaint, fontFamily: typo.mono, fontSize: 9, display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>···</Box>;
  }
  const norm = data.map((v, i) => ({ i, v }));
  return (
    <Box sx={{ height, width: '100%', mt: 0.5 }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={norm} margin={{ top: 1, right: 0, bottom: 1, left: 0 }}>
          <defs>
            <linearGradient id={`spark-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey="v" stroke={color} fill={`url(#spark-${color.replace('#', '')})`} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </Box>
  );
}

export default function KpiCell({
  label,
  value,
  sub,
  trend = null,
  trendValue = null,
  accent = null,
  loading = false,
  size = 'sub',          // 'hero' | 'sub' | 'compact' — compact 是 trading top bar 緊湊風
  icon = null,
  sparkData = null,      // mini sparkline 數據 [v1, v2, v3 ...]
  badge = null,          // 右上角小徽章 (例如 24h chg "+2.4%")
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
  const isCompact = size === 'compact';
  const metricFontSize = isHero
    ? { xs: '2rem', sm: '2.4rem', md: '2.8rem' }
    : isCompact
    ? { xs: '1rem', md: '1.15rem' }
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
      p: isHero ? 2.5 : isCompact ? 1.5 : 2,
      bgcolor: isHero ? palette.surface2 : palette.surface,
      border: `1px solid ${palette.border}`,
      borderRadius: isCompact ? 1 : 1.5,
      height: '100%',
      // compact 统一 96px（有/无 sparkline 都同高，6 cell 底部对齐）
      minHeight: isHero ? 132 : isCompact ? 96 : 90,
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
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={0.5} sx={{ mb: isHero ? 1 : 0.25 }}>
        <Stack direction="row" alignItems="center" spacing={0.5}>
          {icon && <Box sx={{ fontSize: isHero ? 18 : 12, opacity: 0.85, filter: isHero ? 'drop-shadow(0 0 8px rgba(255,255,255,0.15))' : 'none' }}>{icon}</Box>}
          <Typography sx={{ ...typo.label, color: palette.textMuted, fontSize: isHero ? '0.78rem' : isCompact ? '0.65rem' : '0.6875rem' }}>
            {label}
          </Typography>
        </Stack>
        {badge && (
          <Typography sx={{
            fontSize: 10, fontWeight: 700, fontFamily: typo.mono,
            color: typeof badge === 'object' ? badge.color : palette.textMuted,
            bgcolor: typeof badge === 'object' && badge.bg ? badge.bg : 'transparent',
            px: 0.6, py: 0.15, borderRadius: 0.5, letterSpacing: 0.2,
            lineHeight: 1.4,
          }}>
            {typeof badge === 'object' ? badge.text : badge}
          </Typography>
        )}
      </Stack>
      <Box>
        <Typography sx={{
          ...typo.metric,
          color: valueColor,
          fontSize: metricFontSize,
          fontWeight: 700,
          lineHeight: 1.05,
          fontVariantNumeric: 'tabular-nums',
          letterSpacing: '-0.03em',
          ...(isHero && {
            textShadow: `0 0 28px ${accentColor}55, 0 2px 4px rgba(0,0,0,0.3)`,
          }),
        }}>
          {loading ? '—' : value}
        </Typography>
        {(sub || trendDir) && !isCompact && (
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
        {isCompact && sub && (
          <Typography sx={{
            fontSize: 10, fontFamily: typo.mono, mt: 0.25,
            color: trendDir ? trendColor : palette.textFaint, lineHeight: 1.2,
          }}>
            {sub}
          </Typography>
        )}
        {sparkData && (
          <MiniSparkline data={sparkData} color={accentColor} height={isHero ? 36 : isCompact ? 18 : 24} />
        )}
      </Box>
    </Box>
  );
}
