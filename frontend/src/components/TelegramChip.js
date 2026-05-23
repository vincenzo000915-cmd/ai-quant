// Phase 12.43: 复用 Telegram 频道引流 chip
//   用法: <TelegramChip />  /  <TelegramChip variant="cta" />  /  <TelegramChip variant="icon" />

import React from 'react';
import { Box, Chip, IconButton, Tooltip, Typography, Stack, Button } from '@mui/material';

const PURPLE = '#a78bfa';
const TG_CHANNEL_URL = 'https://t.me/vincenzo_svip';
const TG_CHANNEL_HANDLE = '@vincenzo_svip';

// 自定义 Telegram 纸飞机 SVG（无需依赖，brand 紫色）
export const TelegramIcon = ({ size = 18, color = PURPLE }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
  >
    <path
      d="M21.43 2.65L2.86 9.79c-1.27.51-1.26 1.21-.23 1.51l4.76 1.49 11.02-6.96c.52-.32.99-.15.6.2L9.97 14.24l-.34 5.13c.49 0 .71-.22 1-.5l2.4-2.34 4.97 3.67c.92.51 1.58.24 1.8-.85l3.26-15.36c.33-1.33-.49-1.94-1.63-1.34z"
      fill={color}
    />
  </svg>
);

/**
 * 三种 variants:
 *   - default: small chip with icon + handle
 *   - cta: large button with "加入官方频道" CTA
 *   - icon: just icon button (for compact areas like top bar)
 */
export default function TelegramChip({ variant = 'default', subscriberCount, sx = {} }) {
  const onClick = () => window.open(TG_CHANNEL_URL, '_blank', 'noopener,noreferrer');

  if (variant === 'icon') {
    return (
      <Tooltip title={`加入官方频道 ${TG_CHANNEL_HANDLE}`}>
        <IconButton
          onClick={onClick}
          size="small"
          sx={{
            color: PURPLE,
            '&:hover': { bgcolor: 'rgba(167,139,250,0.12)' },
            ...sx,
          }}
        >
          <TelegramIcon size={18} />
        </IconButton>
      </Tooltip>
    );
  }

  if (variant === 'cta') {
    return (
      <Button
        variant="contained"
        startIcon={<TelegramIcon size={18} color="#fff" />}
        onClick={onClick}
        sx={{
          bgcolor: PURPLE,
          color: '#fff',
          '&:hover': { bgcolor: '#9472eb' },
          textTransform: 'none',
          px: 2.5,
          py: 1,
          ...sx,
        }}
      >
        <Stack direction="column" alignItems="flex-start" spacing={0}>
          <Typography variant="body2" fontWeight={700} sx={{ lineHeight: 1.2 }}>
            加入官方 Telegram 频道
          </Typography>
          <Typography variant="caption" sx={{ lineHeight: 1.2, opacity: 0.9 }}>
            每日 AI 策略 · 市场分析 · 早期 feature 访问
          </Typography>
        </Stack>
      </Button>
    );
  }

  // default chip
  return (
    <Chip
      icon={<Box sx={{ display: 'flex', alignItems: 'center', pl: 0.5 }}><TelegramIcon size={14} /></Box>}
      label={
        <Stack direction="row" alignItems="center" spacing={0.5}>
          <Typography variant="caption" fontWeight={600}>{TG_CHANNEL_HANDLE}</Typography>
          {subscriberCount && (
            <Typography variant="caption" sx={{ opacity: 0.7 }}>
              · {subscriberCount}+ traders
            </Typography>
          )}
        </Stack>
      }
      onClick={onClick}
      clickable
      sx={{
        bgcolor: 'rgba(167,139,250,0.1)',
        color: PURPLE,
        borderColor: 'rgba(167,139,250,0.3)',
        cursor: 'pointer',
        '&:hover': { bgcolor: 'rgba(167,139,250,0.18)' },
        ...sx,
      }}
      variant="outlined"
    />
  );
}

export { TG_CHANNEL_URL, TG_CHANNEL_HANDLE };
