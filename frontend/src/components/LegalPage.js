// Phase 12.23: 通用法律页面 layout — 给 Terms / RefundPolicy / Privacy 复用
import React from 'react';
import { Container, Box, Typography } from '@mui/material';
import { palette, typo } from '../theme';

export default function LegalPage({ title, subtitle, lastUpdated, sections }) {
  return (
    <Container maxWidth="md" sx={{ py: 6, position: 'relative', zIndex: 1 }}>
      <Box sx={{ mb: 4 }}>
        <Typography sx={{ ...typo.display, color: palette.text, mb: 1, fontSize: '1.75rem' }}>
          {title}
        </Typography>
        {subtitle && (
          <Typography sx={{ color: palette.textMuted, fontSize: 14, mb: 1 }}>
            {subtitle}
          </Typography>
        )}
        {lastUpdated && (
          <Typography sx={{ color: palette.textFaint, fontSize: 12, fontFamily: typo.mono }}>
            Last updated: {lastUpdated}
          </Typography>
        )}
      </Box>

      <Box sx={{
        p: 4,
        bgcolor: palette.surface,
        border: `1px solid ${palette.border}`,
        borderRadius: 1.5,
      }}>
        {sections.map((sec, i) => (
          <Box key={i} sx={{ mb: i === sections.length - 1 ? 0 : 4 }}>
            <Typography sx={{
              ...typo.h2,
              color: palette.ai,
              fontSize: '1.1rem',
              mb: 1.5,
              pb: 1,
              borderBottom: `1px solid ${palette.border}`,
            }}>
              {i + 1}. {sec.heading}
            </Typography>
            {sec.paragraphs.map((p, j) => (
              <Typography key={j} sx={{
                color: palette.text,
                fontSize: 13.5,
                lineHeight: 1.8,
                mb: 1.5,
                '& strong': { color: palette.ai, fontWeight: 700 },
                '& code': {
                  fontFamily: typo.mono, fontSize: 12,
                  bgcolor: 'rgba(167,139,250,0.08)', px: 0.6, py: 0.1, borderRadius: 0.3,
                  color: palette.accentBright,
                },
              }}
              dangerouslySetInnerHTML={{ __html: p }}
              />
            ))}
            {sec.list && (
              <Box component="ul" sx={{ pl: 2.5, mb: 1.5 }}>
                {sec.list.map((item, k) => (
                  <Box key={k} component="li" sx={{
                    color: palette.text, fontSize: 13, lineHeight: 1.8, mb: 0.5,
                  }}>
                    <span dangerouslySetInnerHTML={{ __html: item }} />
                  </Box>
                ))}
              </Box>
            )}
          </Box>
        ))}
      </Box>
    </Container>
  );
}
