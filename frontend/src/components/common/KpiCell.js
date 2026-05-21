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

  return (
    <Box sx={{
      p: 2,
      bgcolor: palette.surface,
      border: `1px solid ${palette.border}`,
      borderRadius: 1.5,
      height: '100%',
      minHeight: 92,
      display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      transition: 'border-color 120ms ease',
      '&:hover': { borderColor: palette.borderHot },
    }}>
      <Typography sx={{ ...typo.label, color: palette.textMuted, mb: 0.5 }}>
        {label}
      </Typography>
      <Box>
        <Typography sx={{ ...typo.metric, color: valueColor, fontSize: { xs: '1.4rem', md: '1.75rem' } }}>
          {loading ? '—' : value}
        </Typography>
        {(sub || trendDir) && (
          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.5 }}>
            {trendDir && <TrendIcon sx={{ fontSize: 14, color: trendColor }} />}
            <Typography sx={{ ...typo.caption, color: trendDir ? trendColor : palette.textMuted, fontFamily: typo.mono }}>
              {sub}
            </Typography>
          </Stack>
        )}
      </Box>
    </Box>
  );
}
