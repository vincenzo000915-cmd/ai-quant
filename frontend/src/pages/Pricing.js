// Phase 12.23: 订阅定价页 — USDT 收款 / 紫色 AI 金融科技风
//
// 三档 + Trial 7d + 预付折扣
// 价格走 USDT，不接法币（不需 Stripe / KYC）

import React, { useState } from 'react';
import { Box, Container, Typography, Grid, Button, Chip, Switch, Link as MuiLink } from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import StarIcon from '@mui/icons-material/Star';
import BoltIcon from '@mui/icons-material/Bolt';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { palette, typo } from '../theme';
import TelegramChip from '../components/TelegramChip';
import { getUser } from '../auth';

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
      '✓ 全部 22 个内置策略 + 自动信号循环',
      '✓ LIVE 实盘模式（接你自己的 OKX API key）',
      '✓ 智能托管（auto retire / revive / apply / fan-out）',
      '✓ 候选池浏览 + 单个 candidate promote 上架',
      '✓ Walk-forward 回测 + per-TF gate 自动筛选',
      '✓ Telegram 通知（开平仓 + halt / kill switch）',
      '✓ 每日 08:00 UTC PnL 早报',
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
    description: 'AI 量化驾驶舱 — 半自动智能驾驶',
    features: [
      '✓ 包含 Basic 全部功能',
      '🚗 <b>半自动智能驾驶</b> — 高 Sharpe ≥2.5 策略 AI 自动上线 (中低走面板等审)',
      '🚀 AI 精选策略一键上架 (真 research + risk_params + 一键 apply)',
      '✨ AI 改进顾问 (多 symbol + 多 TF + 跨网 research)',
      '✨ AI 策略解释 (一键看「赚什么 / 怕什么」)',
      '✨ AI 自然语言生成策略',
      '✨ AI Regime 解读 + 周复盘报告',
      '✨ AI 个性化建议 + 故障诊断',
      '✨ AI 仓位/杠杆推荐',
      '🔑 BYO LLM key (Anthropic / OpenAI / Gemini)',
      '── 单交易所绑定 (OKX OR Hyperliquid)',
      '✗ 全自动 AI 自动托管 (需 Team)',
    ],
    cta: '选择 Pro',
    accent: true,
  },
  {
    id: 'team',
    name: 'Team',
    icon: StarIcon,
    price: 299,
    badge: '🚀 顶级',
    description: 'AI 自动托管 — AI 全权管理你的资金',
    features: [
      '✓ 包含 Pro 全部功能',
      '🤖 <b>AI 自动托管</b> (全自动 AI 量化经理):',
      '  · 设盈利目标 (例 +20% / 30 天)',
      '  · AI 自动跟踪进度, 落后主动 review 加策略',
      '  · 回撤保护 (DD ≥ 15% 自动 halt)',
      '  · 单日亏损止血 (5%/日上限)',
      '  · 资金跨档自动扩张策略 ($100 / $500 / $2000)',
      '  · 每周 AI 复盘: 淘汰亏损策略 + 补新',
      '  · 30 天无交易策略自动退役 (信号死循环检测)',
      '🌐 <b>多交易所同时支持</b> — OKX + Hyperliquid 同时绑定',
      '⚡ Per-strategy 指定交易所 (BTC 走 OKX, ETH 走 HL 这种)',
      '🎯 每个交易所独立 AI 推荐池 (AI 工作量 × 交易所数)',
      '📊 后台多账户汇总余额视图',
    ],
    cta: '选择 Team',
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
  { q: '注册免费可以看到什么？', a: '完整 UI（Dashboard / 策略 / 候选池 / Trades / Settings），demo 数据 + 系统架构展示。所有「动作」按钮禁用。订阅 Basic 立刻解锁交易动作，Pro 解锁半自动智能驾驶 + 所有 AI 工具，Team 解锁 AI 自动托管 + 多交易所。' },
  { q: 'Pro 和 Team 有什么本质区别？', a: 'Pro 是「半自动智能驾驶」— AI 推荐策略, 高 Sharpe 自动应用, 但需要你设定目标 / 管资金 / 监控回撤。Team 是「AI 自动托管」— 你设个目标 (例 +20%/30 天), AI 全权管理: 自动跟踪 / 回撤保护 / 策略轮换 / 跨档扩张策略, 还能同时跑 OKX + Hyperliquid 多账户。适合不想花时间盯盘的用户。' },
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
      return;
    }
    // Phase 12.48: 未登入 → 先注册（带 next 让注册完跳回 checkout，不掉单）
    const target = `/checkout?plan=${plan.id}&months=${discount.months}`;
    if (!getUser()) {
      navigate(`/login?tab=register&next=${encodeURIComponent(target)}`);
      return;
    }
    navigate(target);
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

      {/* === 4 plans (Phase 14k-117: md=3 让 4 张卡 Preview/Basic/Pro/Team 占满 12 grid 一排;
             之前 md=4 是 3-card 时代留下的, Preview tier 加入后 Team 掉到下排) === */}
      <Grid container spacing={2.5} sx={{ mb: 8 }} justifyContent="center">
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
                      <Typography
                        sx={{ color: palette.text, fontSize: 12.5, lineHeight: 1.5 }}
                        dangerouslySetInnerHTML={{ __html: f }}
                      />
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

      {/* Phase 12.43: TG CTA - 付费前社群兜底，建立信任 */}
      <Box sx={{
        textAlign: 'center', mb: 4, py: 3, px: 2,
        bgcolor: 'rgba(167,139,250,0.04)',
        border: `1px dashed ${palette.borderAccent}`,
        borderRadius: 2,
      }}>
        <Typography sx={{ color: palette.text, fontWeight: 700, mb: 0.5, fontSize: 15 }}>
          💬 加入官方频道先看再决定
        </Typography>
        <Typography sx={{ color: palette.textMuted, fontSize: 13, mb: 2 }}>
          AI 每日策略 · 市场行情 · 真实订阅者反馈 · 早期 feature 访问
        </Typography>
        <TelegramChip variant="cta" />
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
