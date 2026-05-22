// Phase 12.15.3: 統一頁頭 — 取代各頁面重複寫 Typography h5 + caption + Box flex

import React from 'react';
import { Box, Typography, Stack } from '@mui/material';
import { palette, typo } from '../../theme';

export default function PageHeader({ title, subtitle, actions = null }) {
  return (
    <Box sx={{
      display: 'flex', alignItems: 'center',
      justifyContent: 'space-between',
      mb: 2, pb: 1.5,
      borderBottom: `1px solid ${palette.border}`,
      gap: 2, flexWrap: 'wrap',
      position: 'relative',
      // 底部短 accent 线段
      '&::after': {
        content: '""',
        position: 'absolute',
        left: 0, bottom: -1, height: 2, width: 32,
        background: palette.accent,
        boxShadow: `0 0 8px ${palette.accent}`,
      },
    }}>
      <Box sx={{ minWidth: 0, position: 'relative', pl: 1.5,
        // 左侧 cyan accent bar
        '&::before': {
          content: '""',
          position: 'absolute',
          left: 0, top: 4, bottom: 4, width: 3,
          background: palette.accent,
          borderRadius: 1,
          boxShadow: `0 0 6px ${palette.accent}`,
        },
      }}>
        <Typography component="h1" sx={{
          ...typo.h1,
          color: palette.text, mb: 0.25,
          fontSize: { xs: '1.25rem', md: '1.5rem' },
        }}>
          {title}
        </Typography>
        {subtitle && (
          <Typography sx={{
            ...typo.caption,
            color: palette.textMuted,
            fontFamily: typo.mono,
            fontSize: '0.75rem',
            letterSpacing: 0.3,
          }}>
            {subtitle}
          </Typography>
        )}
      </Box>
      {actions && (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ flexShrink: 0, flexWrap: 'wrap', pt: 0.5 }}>
          {actions}
        </Stack>
      )}
    </Box>
  );
}
