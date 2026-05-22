// Phase 12.23: 订阅定价页 — USDT 收款 / 紫色 AI 金融科技风
//
// 三档 + Trial 7d + 预付折扣
// 价格走 USDT，不接法币（不需 Stripe / KYC）

import React, { useState } from 'react';
import { Box, Container, Typography, Grid, Button, Chip, Switch, Link as MuiLink } from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import StarIcon from '@mui/icons-material/Star';
import BoltIcon from '@mui/icons-material/Bolt';
import GroupsIcon from '@mui/icons-material/Groups';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { palette, typo } from '../theme';

const PLANS = [
  {
    id: 'preview',
    name: 'Preview',
    icon: BoltIcon,
    price: 0,
    badge: '注册即可',
    description: '注册后浏览 UI，不能实际使用',
    features: [
      '✓ 可浏览 dashboard / 策略 / 候选池',
      '✓ 看 demo 数据 + 系统架构',
      '✗ 无法新增 / 修改策略',
      '✗ 无法 LIVE 实盘 / 跑回测',
      '✗ 无法使用 AI features',
      '→ 想使用功能至少订阅 Basic 1 个月',
    ],
    cta: '免费注册',
    accent: false,
  },
  {
    id: 'basic',
    name: 'Basic',
    icon: BoltIcon,
    price: 50,
    description: '量化交易工具基础包',
    features: [
      '✓ 全部 22 个 hardcode 策略',
      '✓ 智能托管 5 actions（auto retire/revive/apply/fan-out/promote）',
      '✓ 全候选池（爬虫 + 翻译 + 沙箱 + 回测 pipeline）',
      '✓ LIVE 实盘模式（接你自己的 OKX API key）',
      '✓ Telegram 通知',
      '✓ 日报 + 周报 + 审计日志',
    ],
    cta: '选择 Basic',
    accent: false,
  },
  {
    id: 'pro',
    name: 'Pro',
    icon: StarIcon,
    price: 125,
    badge: '最受欢迎',
    description: 'AI 量化驾驶舱 — BYO LLM key',
    features: [
      '✓ 包含 Basic 全部功能',
      '✨ AI 策略解释（一键看「赚什么 / 怕什么」）',
      '✨ AI 自然语言生成策略',
      '✨ AI Regime 解读 + 周复盘报告',
      '✨ AI 个性化建议 + 故障诊断 agent',
      '✨ AI 改进顾问（自动看你策略缺口 + 生成新候选）',
      '✨ AI 仓位/杠杆推荐',
      '🔑 BYO key — 你自己付 Anthropic/OpenAI/Gemini token',
    ],
    cta: '选择 Pro',
    accent: true,
  },
  {
    id: 'team',
    name: 'Team',
    icon: GroupsIcon,
    price: 250,
    priceSuffix: '+',
    description: '团队 / 多账户 / 优先客服',
    features: [
      '✓ 包含 Pro 全部功能',
      '✓ 多账户子用户管理',
      '✓ 团队权限分级（admin / trader / viewer）',
      '✓ 多 OKX key 隔离运行',
      '✓ 优先 Telegram 客服（24h 内回复）',
      '✓ 定制策略需求支持',
    ],
    cta: '联系销售',
    accent: false,
  },
];

const DISCOUNT_TIERS = [
  { months: 1, discount: 0,  label: '月付' },
  { months: 3, discount: 10, label: '季付 -10%' },
  { months: 6, discount: 20, label: '半年 -20%' },
  { months: 12, discount: 30, label: '年付 -30%' },
];

const FAQ = [
  { q: '为什么没有永久免费方案？', a: '量化工具维护成本高（candidate pipeline / AI 调用 / OKX WS / 服务器），免费会被无限注册滥用拖垮服务。注册后可免费浏览 UI 验证产品，但实际使用需订阅最少 1 个月。' },
  { q: '注册免费可以看到什么？', a: '完整 UI（Dashboard / 策略 / 候选池 / Trades / 审计 / Settings），demo 数据 + 系统架构展示。但所有「动作」按钮禁用 — 不能新增策略 / 不能跑回测 / 不能 LIVE / 不能用 AI features。订阅后立刻全部解锁。' },
  { q: '怎么付款？', a: '点击 CTA 跳转到我们网页内的支付页面，显示对应订阅 USDT 金额 + 二维码 + 链上地址（支持 TRC20 / ERC20）。从你自己钱包扫码或复制地址转账即可。系统监听链上自动确认（通常 1-3 分钟）后立即开通订阅。全程不离开 Quant Pro 网页，无需 Telegram 或第三方 App。' },
  { q: '可以退款吗？', a: '订阅期内不退款（USDT 链上不可逆 + 防滥用）。建议注册免费浏览 + 看 demo 充分了解后再订阅。详见 退款政策。' },
  { q: '你们能保证盈利吗？', a: '不能。70% 散户量化首年亏损是行业基线。我们提供的是工具（策略池 / 回测 / 风控 / AI），盈亏由策略 + 市场 + 你的参数决定。' },
  { q: '我的 OKX API key 安全吗？', a: 'AES-256-GCM (Fernet) 加密存进 DB，解密 key 只在 Celery worker 内存。我们不持有你的资金，所有下单都通过你自己的 OKX key 调用 OKX。' },
  { q: '可以中途升级 / 降级吗？', a: '可以。升级按比例补差价（USDT 链上付款）。降级在当前订阅周期结束后生效。' },
];


export default function Pricing() {
  const [discountIdx, setDiscountIdx] = useState(0);
  const discount = DISCOUNT_TIERS[discountIdx];
  const navigate = useNavigate();

  const handleCta = (plan) => {
    if (plan.id === 'preview') {
      navigate('/login?tab=register');
    } else if (plan.id === 'team') {
      window.location.href = 'mailto:vincenzo000915@gmail.com?subject=Quant Pro Team Plan 询价';
    } else {
      navigate(`/checkout?plan=${plan.id}&months=${discount.months}`);
    }
  };

  const calcPrice = (basePrice) => {
    if (!basePrice) return 0;
    const total = basePrice * discount.months;
    return Math.round(total * (1 - discount.discount / 100));
  };

  return (
    <Container maxWidth="lg" sx={{ py: 6, position: 'relative', zIndex: 1 }}>
      {/* === Hero === */}
      <Box sx={{ textAlign: 'center', mb: 6 }}>
        <Chip
          label="USDT 网页直付 · 无需 KYC · 链上结算"
          sx={{
            bgcolor: palette.aiBg, color: palette.ai,
            border: `1px solid ${palette.borderAccent}`,
            fontFamily: typo.mono, fontSize: 11, fontWeight: 700,
            letterSpacing: 0.6, mb: 2,
          }}
        />
        <Typography sx={{ ...typo.display, color: palette.text, mb: 1.5 }}>
          AI 量化交易工具 · 订阅定价
        </Typography>
        <Typography sx={{ color: palette.textMuted, fontSize: '1rem', maxWidth: 720, mx: 'auto', mb: 3 }}>
          软件工具租赁模式（非投资顾问）。USDT 收款 · 链上结算 · 不持有用户资金 · 不替用户下单。
          <br />
          <Box component="span" sx={{ color: palette.text, fontWeight: 600, fontSize: '0.9rem' }}>
            注册免费浏览，使用功能最少订阅 1 个月
          </Box>
        </Typography>

        {/* 周期切换 */}
        <Box sx={{
          display: 'inline-flex', gap: 0.5, p: 0.4,
          bgcolor: palette.surface, border: `1px solid ${palette.border}`,
          borderRadius: 1.5,
        }}>
          {DISCOUNT_TIERS.map((d, i) => (
            <Box
              key={d.months}
              component="button"
              onClick={() => setDiscountIdx(i)}
              sx={{
                cursor: 'pointer', border: 0,
                px: 1.6, py: 0.8, borderRadius: 1,
                fontFamily: typo.mono, fontSize: 12, fontWeight: 700,
                color: discountIdx === i ? palette.bg : palette.textMuted,
                bgcolor: discountIdx === i ? palette.ai : 'transparent',
                transition: 'all 180ms',
                '&:hover': { color: discountIdx === i ? palette.bg : palette.text },
              }}
            >
              {d.label}
            </Box>
          ))}
        </Box>
      </Box>

      {/* === 4 plans === */}
      <Grid container spacing={2.5} sx={{ mb: 8 }}>
        {PLANS.map((plan) => {
          const Icon = plan.icon;
          const isAccent = plan.accent;
          const price = calcPrice(plan.price);
          return (
            <Grid key={plan.id} item xs={12} sm={6} md={3}>
              <Box sx={{
                position: 'relative', height: '100%',
                p: 3,
                bgcolor: isAccent ? 'rgba(167,139,250,0.06)' : palette.surface,
                border: `1px solid ${isAccent ? palette.borderAccent : palette.border}`,
                borderRadius: 1.5,
                boxShadow: isAccent ? `0 0 24px ${palette.accentGlow}` : 'none',
                display: 'flex', flexDirection: 'column',
                transition: 'border-color 200ms, transform 200ms',
                '&:hover': { borderColor: palette.borderHot, transform: 'translateY(-2px)' },
                '&::before': isAccent ? {
                  content: '""',
                  position: 'absolute', top: 0, left: 0, right: 0,
                  height: 2,
                  background: `linear-gradient(90deg, transparent, ${palette.ai}, transparent)`,
                } : {},
              }}>
                {plan.badge && (
                  <Chip
                    label={plan.badge}
                    size="small"
                    sx={{
                      position: 'absolute', top: -10, right: 16,
                      bgcolor: palette.ai, color: palette.bg,
                      fontWeight: 700, fontSize: 10, letterSpacing: 0.5,
                      height: 20,
                    }}
                  />
                )}
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                  <Box sx={{
                    width: 32, height: 32, borderRadius: 1,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    bgcolor: `${palette.ai}1a`, color: palette.ai,
                  }}>
                    <Icon sx={{ fontSize: 18 }} />
                  </Box>
                  <Typography sx={{ ...typo.h2, color: palette.text }}>{plan.name}</Typography>
                </Box>

                <Typography sx={{ color: palette.textMuted, fontSize: 13, mb: 2, minHeight: 36 }}>
                  {plan.description}
                </Typography>

                <Box sx={{ mb: 2.5 }}>
                  {plan.price === 0 ? (
                    <Typography sx={{ ...typo.metric, color: palette.ai, fontSize: '2rem' }}>
                      免费
                    </Typography>
                  ) : (
                    <>
                      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.5 }}>
                        <Typography sx={{ ...typo.metric, color: palette.text, fontSize: '2rem' }}>
                          ${price}{plan.priceSuffix || ''}
                        </Typography>
                        <Typography sx={{ color: palette.textMuted, fontSize: 13 }}>
                          USDT / {discount.months} 月
                        </Typography>
                      </Box>
                      {discount.discount > 0 && (
                        <Typography sx={{ color: palette.success, fontSize: 11, fontFamily: typo.mono, mt: 0.3 }}>
                          省 ${plan.price * discount.months - price} USDT（-{discount.discount}%）
                        </Typography>
                      )}
                    </>
                  )}
                </Box>

                <Box sx={{ flexGrow: 1, mb: 2 }}>
                  {plan.features.map((f, i) => (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.8, mb: 0.6 }}>
                      <Typography sx={{ color: palette.text, fontSize: 12.5, lineHeight: 1.5 }}>
                        {f}
                      </Typography>
                    </Box>
                  ))}
                </Box>

                <Button
                  variant={isAccent ? 'contained' : 'outlined'}
                  fullWidth
                  onClick={() => handleCta(plan)}
                  sx={{
                    bgcolor: isAccent ? palette.ai : 'transparent',
                    borderColor: palette.borderAccent,
                    color: isAccent ? palette.bg : palette.ai,
                    fontWeight: 700, letterSpacing: 0.5,
                    py: 1.1,
                    '&:hover': {
                      bgcolor: isAccent ? palette.accentBright : palette.aiBg,
                      borderColor: palette.ai,
                    },
                  }}
                >
                  {plan.cta}
                </Button>
              </Box>
            </Grid>
          );
        })}
      </Grid>

      {/* === Risk disclaimer === */}
      <Box sx={{
        p: 2.5, mb: 6,
        bgcolor: 'rgba(255,71,87,0.04)',
        border: `1px solid rgba(255,71,87,0.18)`,
        borderRadius: 1.5,
      }}>
        <Typography sx={{ color: palette.error, fontWeight: 700, fontSize: 13, mb: 1 }}>
          ⚠️ 风险声明
        </Typography>
        <Typography sx={{ color: palette.textMuted, fontSize: 12.5, lineHeight: 1.7 }}>
          量化交易工具 ≠ 盈利保证。70% 散户量化首年亏损是行业基线。我们提供策略池 / 回测引擎 /
          风控 / AI 等软件工具，但<strong style={{ color: palette.text }}>不构成投资建议</strong>，
          不持有你的资金，不替你下单。策略执行、参数选择、风险管理由用户负责。
          建议先用 7 天 Trial 充分验证后再付费订阅。详见{' '}
          <MuiLink component={RouterLink} to="/terms" sx={{ color: palette.ai }}>服务条款</MuiLink>。
        </Typography>
      </Box>

      {/* === FAQ === */}
      <Box sx={{ mb: 6 }}>
        <Typography sx={{ ...typo.h1, color: palette.text, mb: 3, textAlign: 'center' }}>
          常见问题
        </Typography>
        <Grid container spacing={2}>
          {FAQ.map((item, i) => (
            <Grid key={i} item xs={12} md={6}>
              <Box sx={{
                p: 2,
                bgcolor: palette.surface,
                border: `1px solid ${palette.border}`,
                borderRadius: 1,
                height: '100%',
              }}>
                <Typography sx={{ color: palette.ai, fontWeight: 700, fontSize: 13, mb: 0.8 }}>
                  Q: {item.q}
                </Typography>
                <Typography sx={{ color: palette.textMuted, fontSize: 12.5, lineHeight: 1.7 }}>
                  {item.a}
                </Typography>
              </Box>
            </Grid>
          ))}
        </Grid>
      </Box>

      {/* === Footer links === */}
      <Box sx={{ textAlign: 'center', color: palette.textMuted, fontSize: 12 }}>
        <MuiLink component={RouterLink} to="/terms" sx={{ color: palette.textMuted, mx: 1.2, '&:hover': { color: palette.ai } }}>服务条款</MuiLink>
        ·
        <MuiLink component={RouterLink} to="/refund-policy" sx={{ color: palette.textMuted, mx: 1.2, '&:hover': { color: palette.ai } }}>退款政策</MuiLink>
        ·
        <MuiLink component={RouterLink} to="/privacy" sx={{ color: palette.textMuted, mx: 1.2, '&:hover': { color: palette.ai } }}>隐私政策</MuiLink>
      </Box>
    </Container>
  );
}
