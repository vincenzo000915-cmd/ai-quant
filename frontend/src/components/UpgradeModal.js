// Phase 12.24.5: 全局 upgrade modal — 当 API 返回 402 时弹出引导订阅
import React, { useState, useEffect } from 'react';
import { Dialog, DialogContent, Box, Typography, Button, Chip } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium';
import { onUpgradeRequired } from '../auth';
import { palette, typo } from '../theme';

const TIER_LABELS = { basic: 'Basic ($50/月)', pro: 'Pro ($125/月)', team: 'Team ($250+/月)' };

export default function UpgradeModal() {
  const [info, setInfo] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const off = onUpgradeRequired((body) => setInfo(body || {}));
    return off;
  }, []);

  if (!info) return null;

  const required = (info.tier_required || 'basic').toLowerCase();
  const label = TIER_LABELS[required] || required.toUpperCase();

  return (
    <Dialog open={!!info} onClose={() => setInfo(null)} maxWidth="xs" fullWidth
      PaperProps={{
        sx: {
          bgcolor: palette.surface,
          border: `1px solid ${palette.borderAccent}`,
          borderRadius: 1.5,
          boxShadow: `0 0 32px ${palette.accentGlow}`,
          position: 'relative',
          overflow: 'hidden',
          '&::before': {
            content: '""', position: 'absolute', top: 0, left: 0, right: 0, height: 2,
            background: `linear-gradient(90deg, transparent, ${palette.ai}, transparent)`,
          },
        },
      }}>
      <DialogContent sx={{ p: 3.5, textAlign: 'center' }}>
        <Box sx={{
          width: 48, height: 48, borderRadius: '50%',
          bgcolor: palette.aiBg, color: palette.ai,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          mx: 'auto', mb: 2,
        }}>
          <WorkspacePremiumIcon sx={{ fontSize: 26 }} />
        </Box>

        <Typography sx={{ ...typo.h2, color: palette.text, mb: 1 }}>
          此功能需 {label}
        </Typography>

        <Typography sx={{ color: palette.textMuted, fontSize: 13, lineHeight: 1.7, mb: 2.5 }}>
          {info.error || '当前订阅 tier 不足以使用此功能'}
        </Typography>

        <Chip label={`需要：${required.toUpperCase()} 及以上`} sx={{
          bgcolor: palette.aiBg, color: palette.ai,
          border: `1px solid ${palette.borderAccent}`,
          fontWeight: 700, fontSize: 11, mb: 3,
        }} />

        <Box sx={{ display: 'flex', gap: 1.5, justifyContent: 'center' }}>
          <Button onClick={() => setInfo(null)} variant="outlined"
            sx={{ borderColor: palette.border, color: palette.textMuted,
                  '&:hover': { borderColor: palette.ai, color: palette.ai } }}>
            取消
          </Button>
          <Button onClick={() => { setInfo(null); navigate('/pricing'); }} variant="contained"
            sx={{ bgcolor: palette.ai, color: palette.bg, fontWeight: 700,
                  '&:hover': { bgcolor: palette.accentBright } }}>
            查看订阅方案
          </Button>
        </Box>
      </DialogContent>
    </Dialog>
  );
}
