// Phase 12.15.3: 統一狀態 chip — 取代各頁面散落的 chip 顏色

import React from 'react';
import { Box, Typography } from '@mui/material';
import { palette, statusColors } from '../../theme';

export default function StatusChip({ status, label = null, size = 'sm', solid = false }) {
  const s = statusColors[status] || { bg: 'rgba(148,163,184,0.1)', fg: palette.textMuted, label: status };
  const display = label || s.label || status;

  const heights = { sm: 20, md: 24, lg: 28 };
  const fontSizes = { sm: 11, md: 12, lg: 13 };
  const paddings = { sm: 1, md: 1.25, lg: 1.5 };

  return (
    <Box
      component="span"
      sx={{
        display: 'inline-flex', alignItems: 'center',
        height: heights[size], px: paddings[size],
        bgcolor: solid ? s.fg : s.bg,
        color: solid ? palette.bg : s.fg,
        border: solid ? 'none' : `1px solid ${s.fg}33`,
        borderRadius: 0.75,
        fontWeight: 600, fontSize: fontSizes[size],
        lineHeight: 1,
        letterSpacing: 0.2,
        whiteSpace: 'nowrap',
      }}
    >
      {display}
    </Box>
  );
}
