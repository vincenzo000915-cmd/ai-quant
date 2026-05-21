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
        <Typography component="h1" sx={{ ...typo.h1, color: palette.text, mb: 0.5 }}>
          {title}
        </Typography>
        {subtitle && (
          <Typography sx={{ ...typo.caption, color: palette.textMuted }}>
            {subtitle}
          </Typography>
        )}
      </Box>
      {actions && (
        <Stack direction="row" spacing={1} sx={{ flexShrink: 0, flexWrap: 'wrap' }}>
          {actions}
        </Stack>
      )}
    </Box>
  );
}
