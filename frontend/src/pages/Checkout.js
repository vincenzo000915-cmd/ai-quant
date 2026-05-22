// Phase 12.23: 结算页 placeholder — Web 端 USDT 付款流程
//
// TODO Phase 12.24+: 接 NowPayments / Coinbase Commerce / 自建 on-chain monitor
//   现在先展示流程预览，让 user 看到 Web 端付款方向（不引导 Telegram）

import React from 'react';
import { Box, Container, Typography, Button, Chip, Stack } from '@mui/material';
import { useSearchParams, useNavigate } from 'react-router-dom';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { palette, typo } from '../theme';

const PLAN_PRICES = {
  basic: 50,
  pro: 125,
  team: 250,
};

const DISCOUNT_MAP = {
  1: 0,
  3: 10,
  6: 20,
  12: 30,
};

export default function Checkout() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const plan = params.get('plan') || 'basic';
  const months = parseInt(params.get('months') || '1', 10);
  const basePrice = PLAN_PRICES[plan] || 50;
  const discount = DISCOUNT_MAP[months] || 0;
  const total = Math.round(basePrice * months * (1 - discount / 100));

  return (
    <Container maxWidth="sm" sx={{ py: 6, position: 'relative', zIndex: 1 }}>
      <Button
        onClick={() => navigate('/pricing')}
        startIcon={<ArrowBackIcon />}
        sx={{ color: palette.textMuted, mb: 2, '&:hover': { color: palette.ai } }}
      >
        返回定价
      </Button>

      <Box sx={{
        p: 4,
        bgcolor: palette.surface,
        border: `1px solid ${palette.borderAccent}`,
        borderRadius: 1.5,
        boxShadow: `0 0 32px ${palette.accentGlow}`,
        position: 'relative',
        '&::before': {
          content: '""',
          position: 'absolute', top: 0, left: 0, right: 0,
          height: 2,
          background: `linear-gradient(90deg, transparent, ${palette.ai}, transparent)`,
        },
      }}>
        <Typography sx={{ color: palette.ai, fontWeight: 700, fontSize: 11, letterSpacing: 1.5, mb: 1 }}>
          QUANT PRO · CHECKOUT
        </Typography>
        <Typography sx={{ ...typo.h1, color: palette.text, mb: 2.5 }}>
          确认订单
        </Typography>

        <Box sx={{
          p: 2.5, mb: 3,
          bgcolor: 'rgba(167,139,250,0.06)',
          border: `1px solid ${palette.border}`,
          borderRadius: 1,
        }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
            <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>订阅</Typography>
            <Chip label={plan.toUpperCase()} size="small" sx={{ bgcolor: palette.aiBg, color: palette.ai, fontWeight: 700 }} />
          </Stack>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
            <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>周期</Typography>
            <Typography sx={{ color: palette.text, fontFamily: typo.mono, fontSize: 14 }}>{months} 个月</Typography>
          </Stack>
          {discount > 0 && (
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
              <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>预付折扣</Typography>
              <Typography sx={{ color: palette.success, fontFamily: typo.mono, fontSize: 14 }}>-{discount}%</Typography>
            </Stack>
          )}
          <Box sx={{ borderTop: `1px solid ${palette.border}`, pt: 1.5, mt: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="baseline">
              <Typography sx={{ color: palette.text, fontWeight: 600 }}>合计</Typography>
              <Typography sx={{ ...typo.metric, color: palette.ai, fontSize: '1.8rem' }}>
                ${total} <Box component="span" sx={{ fontSize: 14, color: palette.textMuted, fontFamily: typo.mono }}>USDT</Box>
              </Typography>
            </Stack>
          </Box>
        </Box>

        {/* 付款方式 — Web 端 USDT 直付 */}
        <Box sx={{
          p: 2.5, mb: 2,
          border: `1px dashed ${palette.borderHot}`,
          borderRadius: 1,
        }}>
          <Typography sx={{ color: palette.ai, fontWeight: 700, fontSize: 12, mb: 1, letterSpacing: 0.6 }}>
            USDT 网页支付 · COMING SOON
          </Typography>
          <Typography sx={{ color: palette.textMuted, fontSize: 13, lineHeight: 1.7, mb: 2 }}>
            网页内直接显示 <strong style={{ color: palette.text }}>付款地址 + 二维码</strong>，从你自己钱包扫描转账。
            支持 USDT-TRC20 / USDT-ERC20。系统监听链上 1-3 分钟自动确认后立即开通订阅。
            <br /><br />
            <Box component="span" sx={{ color: palette.warning }}>
              ⚠️ 支付集成开发中（Phase 12.24+）
            </Box>
            。如需立即订阅，请邮件 <code style={{
              fontFamily: typo.mono, color: palette.accentBright,
              background: 'rgba(167,139,250,0.08)', padding: '2px 6px', borderRadius: 3,
            }}>vincenzo000915@gmail.com</code> 联系。
          </Typography>
          <Stack direction="row" spacing={1.5} sx={{ flexWrap: 'wrap', gap: 1 }}>
            <Chip label="USDT-TRC20" size="small" sx={{ bgcolor: palette.aiBg, color: palette.ai, fontWeight: 700 }} />
            <Chip label="USDT-ERC20" size="small" sx={{ bgcolor: palette.aiBg, color: palette.ai, fontWeight: 700 }} />
            <Chip label="不需 KYC" size="small" sx={{ bgcolor: 'rgba(0,212,170,0.1)', color: palette.success, fontWeight: 700 }} />
            <Chip label="链上结算" size="small" sx={{ bgcolor: 'rgba(0,212,170,0.1)', color: palette.success, fontWeight: 700 }} />
          </Stack>
        </Box>

        <Button
          variant="contained"
          fullWidth
          disabled
          sx={{
            bgcolor: palette.ai, color: palette.bg,
            fontWeight: 700, py: 1.3, letterSpacing: 0.6,
            '&:hover': { bgcolor: palette.accentBright },
            '&.Mui-disabled': { bgcolor: 'rgba(167,139,250,0.3)', color: 'rgba(255,255,255,0.5)' },
          }}
        >
          支付 ${total} USDT （集成中）
        </Button>

        <Typography sx={{ color: palette.textFaint, fontSize: 11, textAlign: 'center', mt: 2 }}>
          点击支付即表示同意 <a href="/terms" style={{ color: palette.ai }}>服务条款</a>
          {' · '}
          <a href="/refund-policy" style={{ color: palette.ai }}>退款政策</a>
        </Typography>
      </Box>
    </Container>
  );
}
