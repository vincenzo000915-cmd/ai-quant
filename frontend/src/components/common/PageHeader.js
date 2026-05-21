// Phase 12.15.3: 統一頁頭 — 取代各頁面重複寫 Typography h5 + caption + Box flex

import React from 'react';
import { Box, Typography, Stack } from '@mui/material';
import { palette, typo } from '../../theme';

export default function PageHeader({ title, subtitle, actions = null }) {
  return (
    <Box sx={{
      display: 'flex', alignItems: 'flex-start',
      justifyContent: 'space-between',
      mb: 3, pb: 2,
      borderBottom: `1px solid ${palette.border}`,
      gap: 2, flexWrap: 'wrap',
    }}>
      <Box sx={{ minWidth: 0 }}>
        <Typography component="h1" sx={{
          ...typo.display,
          color: palette.text, mb: 0.5,
          fontSize: { xs: '1.5rem', md: '2rem' },
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
