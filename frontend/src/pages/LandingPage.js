// Phase 12.26: 营销 Landing Page — 未登录访客首页
//
// 结构：Hero → How → Features → Pricing teaser → Stats → FAQ → CTA → Footer

import React, { useEffect, useState, useRef } from 'react';
import { Box, Container, Typography, Button, Stack, Grid, Chip, Link as MuiLink } from '@mui/material';
import { useNavigate, Link as RouterLink } from 'react-router-dom';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import CurrencyExchangeIcon from '@mui/icons-material/CurrencyExchange';
import HubIcon from '@mui/icons-material/Hub';
import PsychologyIcon from '@mui/icons-material/Psychology';
import LockIcon from '@mui/icons-material/Lock';
import BoltIcon from '@mui/icons-material/Bolt';
import VerifiedIcon from '@mui/icons-material/Verified';
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight';
import LinkIcon from '@mui/icons-material/Link';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import MarketingNav from '../components/MarketingNav';
import NeuralBackdrop from '../components/NeuralBackdrop';
import { palette, typo } from '../theme';

// ============================================================
// 滚动淡入 hook
// ============================================================
function useReveal() {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!ref.current) { setVisible(true); return; }
    const io = new IntersectionObserver(
      ([entry]) => entry.isIntersecting && setVisible(true),
      { threshold: 0.12, rootMargin: '0px 0px -10% 0px' }
    );
    io.observe(ref.current);
    // fallback: 2s 后无条件显示（防 observer 跨 viewport 错过 / reduced-motion）
    const timer = setTimeout(() => setVisible(true), 2000);
    return () => { io.disconnect(); clearTimeout(timer); };
  }, []);
  return [ref, visible];
}

function Reveal({ children, delay = 0, sx }) {
  const [ref, visible] = useReveal();
  return (
    <Box ref={ref} sx={{
      opacity: visible ? 1 : 0,
      transform: visible ? 'translateY(0)' : 'translateY(20px)',
      transition: `opacity 700ms ${delay}ms ease, transform 700ms ${delay}ms ease`,
      ...sx,
    }}>
      {children}
    </Box>
  );
}

// 数字 counter 动画
function CountUp({ value, suffix = '', duration = 1500 }) {
  const [ref, visible] = useReveal();
  const [current, setCurrent] = useState(0);
  useEffect(() => {
    if (!visible) return;
    const start = Date.now();
    const tick = () => {
      const elapsed = Date.now() - start;
      const p = Math.min(1, elapsed / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setCurrent(Math.round(value * eased));
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, [visible, value, duration]);
  return <span ref={ref}>{current}{suffix}</span>;
}

// ============================================================
// 各 section
// ============================================================

function Hero() {
  const navigate = useNavigate();
  return (
    <Box sx={{ position: 'relative', overflow: 'hidden', pt: { xs: 6, md: 12 }, pb: { xs: 6, md: 14 } }}>
      <NeuralBackdrop enabled={true} />
      <Container maxWidth="lg" sx={{ position: 'relative', zIndex: 1, textAlign: 'center' }}>
        <Reveal>
          <Chip
            icon={<AutoAwesomeIcon sx={{ fontSize: '14px !important', color: `${palette.ai} !important` }} />}
            label="LIVE · 65 commits 跨 4 天 · OKX 实盘运行中"
            sx={{
              bgcolor: palette.aiBg, color: palette.ai,
              border: `1px solid ${palette.borderAccent}`,
              fontFamily: typo.mono, fontWeight: 700, letterSpacing: 0.6, mb: 4,
            }}
          />
        </Reveal>

        <Reveal delay={120}>
          <Typography sx={{
            fontSize: { xs: '2.4rem', sm: '3.2rem', md: '4rem' },
            fontWeight: 800, lineHeight: 1.05, letterSpacing: '-0.03em',
            color: palette.text, mb: 2,
          }}>
            AI 量化交易工具<br />
            <Box component="span" sx={{
              background: `linear-gradient(135deg, ${palette.ai} 0%, ${palette.accentBright} 100%)`,
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}>
              你自己的 OKX 驾驶舱
            </Box>
          </Typography>
        </Reveal>

        <Reveal delay={240}>
          <Typography sx={{
            fontSize: { xs: '1rem', md: '1.2rem' }, color: palette.textMuted,
            maxWidth: 680, mx: 'auto', mb: 5, lineHeight: 1.6,
          }}>
            软件工具租赁 · 不替你下单 · 不持有资金 · USDT 4 链订阅 · 链上自动结算
            <br />
            <Box component="span" sx={{ color: palette.text, fontWeight: 600 }}>
              22 个策略 · AI 改进顾问 · TradingView 专业 K 线 · 全自动智能托管
            </Box>
          </Typography>
        </Reveal>

        <Reveal delay={360}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} justifyContent="center">
            <Button
              onClick={() => navigate('/pricing')}
              variant="contained" size="large"
              endIcon={<KeyboardArrowRightIcon />}
              sx={{
                bgcolor: palette.ai, color: palette.bg, fontWeight: 700,
                fontSize: 15, px: 4, py: 1.4, letterSpacing: 0.5,
                boxShadow: `0 0 28px ${palette.accentGlow}`,
                '&:hover': { bgcolor: palette.accentBright, boxShadow: `0 0 40px ${palette.accentGlow}` },
              }}>
              查看订阅方案
            </Button>
            <Button
              onClick={() => navigate('/login')}
              variant="outlined" size="large"
              sx={{
                color: palette.ai, borderColor: palette.borderAccent, fontWeight: 700,
                fontSize: 15, px: 4, py: 1.4, letterSpacing: 0.5,
                '&:hover': { borderColor: palette.ai, bgcolor: 'rgba(167,139,250,0.06)' },
              }}>
              免费注册
            </Button>
          </Stack>
        </Reveal>

        <Reveal delay={480}>
          <Box sx={{ mt: 6, display: 'flex', justifyContent: 'center', gap: 1.5, flexWrap: 'wrap' }}>
            {[
              { label: 'USDT-TRC20', icon: '⚡' },
              { label: 'USDT-ERC20', icon: 'Ξ' },
              { label: 'USDT-BEP20', icon: '🟡' },
              { label: 'USDT-SPL', icon: '◎' },
              { label: '无 KYC', icon: '🔓' },
            ].map(b => (
              <Chip key={b.label} label={`${b.icon} ${b.label}`} size="small" sx={{
                bgcolor: 'rgba(167,139,250,0.06)',
                border: `1px solid ${palette.border}`,
                color: palette.textMuted, fontFamily: typo.mono, fontSize: 11,
              }} />
            ))}
          </Box>
        </Reveal>
      </Container>
    </Box>
  );
}

function Stats() {
  const stats = [
    { value: 22, label: '内置策略', suffix: '+' },
    { value: 4, label: 'USDT 链', suffix: '' },
    { value: 65, label: '迭代 commits', suffix: '+' },
    { value: 100, label: '自动化率', suffix: '%' },
  ];
  return (
    <Box sx={{ py: 5, borderTop: `1px solid ${palette.border}`, borderBottom: `1px solid ${palette.border}`, bgcolor: 'rgba(167,139,250,0.02)' }}>
      <Container maxWidth="lg">
        <Grid container spacing={2}>
          {stats.map((s, i) => (
            <Grid item xs={6} md={3} key={s.label}>
              <Reveal delay={i * 80} sx={{ textAlign: 'center' }}>
                <Typography sx={{
                  fontSize: { xs: '2rem', md: '2.6rem' }, fontWeight: 800,
                  fontFamily: typo.mono, color: palette.ai,
                  textShadow: `0 0 24px ${palette.accentGlow}`,
                }}>
                  <CountUp value={s.value} suffix={s.suffix} />
                </Typography>
                <Typography sx={{ color: palette.textMuted, fontSize: 12, letterSpacing: 0.5 }}>
                  {s.label}
                </Typography>
              </Reveal>
            </Grid>
          ))}
        </Grid>
      </Container>
    </Box>
  );
}

function HowItWorks() {
  const steps = [
    {
      icon: LinkIcon,
      title: '1 · 绑定你的 OKX API key',
      desc: 'AES-256 加密保存，仅 Celery worker 内存解密。你的资金始终在你自己的 OKX 账户，我们不持有、不挪用。',
    },
    {
      icon: AccountTreeIcon,
      title: '2 · AI 自动跑策略 + 改进闭环',
      desc: '7 个 hardcode 策略 + 候选池（爬虫 + LLM 翻译）+ AI 改进顾问每日生成新候选 + 智能托管 5 actions 自动 retire/revive/apply。',
    },
    {
      icon: RocketLaunchIcon,
      title: '3 · 看 Telegram 通知 / Dashboard 监控',
      desc: 'TradingView K 线 + 策略动作时间线 + 每日 PnL 报表 + 风控自动 halt。Pro 用户还可 AI 解读策略 / 周复盘 / 个性化建议。',
    },
  ];
  return (
    <Container id="how" maxWidth="lg" sx={{ py: { xs: 8, md: 12 } }}>
      <Reveal sx={{ textAlign: 'center', mb: 7 }}>
        <Typography sx={{ color: palette.ai, fontSize: 12, fontWeight: 700, letterSpacing: 2, mb: 1 }}>
          HOW IT WORKS · 三步开始
        </Typography>
        <Typography sx={{ fontSize: { xs: '1.7rem', md: '2.3rem' }, fontWeight: 700, color: palette.text }}>
          5 分钟从注册到 LIVE 实盘
        </Typography>
      </Reveal>
      <Grid container spacing={3}>
        {steps.map((s, i) => (
          <Grid item xs={12} md={4} key={i}>
            <Reveal delay={i * 140}>
              <Box sx={{
                position: 'relative', p: 3.5, height: '100%',
                bgcolor: palette.surface,
                border: `1px solid ${palette.border}`, borderRadius: 1.5,
                transition: 'all 240ms',
                '&:hover': {
                  borderColor: palette.borderAccent,
                  boxShadow: `0 4px 32px ${palette.accentGlow}`,
                  transform: 'translateY(-4px)',
                },
              }}>
                <Box sx={{
                  width: 48, height: 48, borderRadius: 1.25,
                  bgcolor: palette.aiBg,
                  border: `1px solid ${palette.borderAccent}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  mb: 2.5, color: palette.ai,
                }}>
                  <s.icon sx={{ fontSize: 24 }} />
                </Box>
                <Typography sx={{ color: palette.text, fontWeight: 700, fontSize: '1.05rem', mb: 1.2 }}>
                  {s.title}
                </Typography>
                <Typography sx={{ color: palette.textMuted, fontSize: 13.5, lineHeight: 1.65 }}>
                  {s.desc}
                </Typography>
              </Box>
            </Reveal>
          </Grid>
        ))}
      </Grid>
    </Container>
  );
}

function Features() {
  const items = [
    {
      icon: AutoAwesomeIcon,
      title: 'AI 改进顾问',
      desc: '看你现有策略 + regime 自动生成补完性新候选；4 重门槛过滤（Sharpe ≥1.5 + PF ≥1.5 + AR ≥8% + 30 trades）',
      tag: 'Pro',
    },
    {
      icon: ShowChartIcon,
      title: 'TradingView 专业 K 线',
      desc: '完整 TV widget · OKX 实时 WebSocket · MACD/RSI/BB 等几十指标 · 截图导出 · 全屏',
      tag: '通用',
    },
    {
      icon: CurrencyExchangeIcon,
      title: 'USDT 4 链订阅',
      desc: 'TRC20 + ERC20 + BEP20 + SOL · 链上自动验证 · 不需要 KYC · 不抽平台费',
      tag: '0%',
    },
    {
      icon: PsychologyIcon,
      title: '智能托管',
      desc: '5 actions 自动决策：retire / revive / apply_params / fan-out / promote。Sanity gates 防滥推',
      tag: '自动',
    },
    {
      icon: HubIcon,
      title: '全候选池',
      desc: 'GitHub 爬虫 + LLM 翻译 + 沙箱验证 + 自动回测 + auto-promote。策略池每日自动扩张',
      tag: '24/7',
    },
    {
      icon: LockIcon,
      title: '资金安全',
      desc: 'OKX/LLM key Fernet AES-256 加密；不持有资金；不替你下单；不需要 KYC',
      tag: '安全',
    },
  ];
  return (
    <Box id="features" sx={{ py: { xs: 8, md: 12 }, bgcolor: 'rgba(167,139,250,0.015)' }}>
      <Container maxWidth="lg">
        <Reveal sx={{ textAlign: 'center', mb: 7 }}>
          <Typography sx={{ color: palette.ai, fontSize: 12, fontWeight: 700, letterSpacing: 2, mb: 1 }}>
            FEATURES · 你能用什么
          </Typography>
          <Typography sx={{ fontSize: { xs: '1.7rem', md: '2.3rem' }, fontWeight: 700, color: palette.text }}>
            6 个核心能力 · 一个订阅全部解锁
          </Typography>
        </Reveal>
        <Grid container spacing={2.5}>
          {items.map((f, i) => (
            <Grid item xs={12} sm={6} md={4} key={i}>
              <Reveal delay={i * 70}>
                <Box sx={{
                  height: '100%', p: 3, position: 'relative',
                  bgcolor: palette.surface,
                  border: `1px solid ${palette.border}`, borderRadius: 1.5,
                  transition: 'all 240ms',
                  '&:hover': {
                    borderColor: palette.borderAccent,
                    boxShadow: `0 0 24px ${palette.accentGlow}`,
                    '& .feature-icon': {
                      color: palette.accentBright,
                      bgcolor: 'rgba(167,139,250,0.15)',
                    },
                  },
                }}>
                  <Chip label={f.tag} size="small" sx={{
                    position: 'absolute', top: 14, right: 14, height: 18,
                    fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
                    bgcolor: palette.aiBg, color: palette.ai,
                    border: `1px solid ${palette.borderAccent}`,
                  }} />
                  <Box className="feature-icon" sx={{
                    width: 40, height: 40, borderRadius: 1,
                    bgcolor: palette.aiBg, color: palette.ai,
                    display: 'flex', alignItems: 'center', justifyContent: 'center', mb: 2,
                    transition: 'all 220ms',
                  }}>
                    <f.icon sx={{ fontSize: 20 }} />
                  </Box>
                  <Typography sx={{ color: palette.text, fontWeight: 700, fontSize: 15, mb: 1 }}>
                    {f.title}
                  </Typography>
                  <Typography sx={{ color: palette.textMuted, fontSize: 13, lineHeight: 1.6 }}>
                    {f.desc}
                  </Typography>
                </Box>
              </Reveal>
            </Grid>
          ))}
        </Grid>
      </Container>
    </Box>
  );
}

function PricingTeaser() {
  const navigate = useNavigate();
  const plans = [
    { name: 'Basic', price: 50, desc: '工具基础包 + LIVE 实盘', best: false },
    { name: 'Pro', price: 125, desc: 'BYO LLM key + AI 全套', best: true },
    { name: 'Team', price: 250, desc: '多账户 + 优先客服', best: false, suffix: '+' },
  ];
  return (
    <Container maxWidth="lg" sx={{ py: { xs: 8, md: 12 } }}>
      <Reveal sx={{ textAlign: 'center', mb: 7 }}>
        <Typography sx={{ color: palette.ai, fontSize: 12, fontWeight: 700, letterSpacing: 2, mb: 1 }}>
          PRICING · USDT 月付
        </Typography>
        <Typography sx={{ fontSize: { xs: '1.7rem', md: '2.3rem' }, fontWeight: 700, color: palette.text, mb: 1 }}>
          注册免费浏览，使用最少订阅 1 月
        </Typography>
        <Typography sx={{ color: palette.textMuted, fontSize: 13.5 }}>
          预付折扣 · 3 月 -10% / 6 月 -20% / 1 年 -30%
        </Typography>
      </Reveal>
      <Grid container spacing={2.5} sx={{ mb: 4 }}>
        {plans.map((p, i) => (
          <Grid item xs={12} sm={4} key={p.name}>
            <Reveal delay={i * 100}>
              <Box sx={{
                p: 3, height: '100%', position: 'relative',
                bgcolor: p.best ? 'rgba(167,139,250,0.06)' : palette.surface,
                border: `1px solid ${p.best ? palette.borderAccent : palette.border}`,
                borderRadius: 1.5,
                boxShadow: p.best ? `0 0 28px ${palette.accentGlow}` : 'none',
                transition: 'all 220ms',
                '&:hover': { transform: 'translateY(-3px)', borderColor: palette.borderAccent },
              }}>
                {p.best && (
                  <Chip label="最热门" sx={{
                    position: 'absolute', top: -10, right: 16, height: 22,
                    bgcolor: palette.ai, color: palette.bg,
                    fontWeight: 700, fontSize: 10, letterSpacing: 0.5,
                  }} />
                )}
                <Typography sx={{ color: palette.text, fontWeight: 700, fontSize: '1.2rem', mb: 1 }}>
                  {p.name}
                </Typography>
                <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.5, mb: 2 }}>
                  <Typography sx={{ color: palette.ai, fontWeight: 800, fontSize: '2.2rem', fontFamily: typo.mono }}>
                    ${p.price}{p.suffix || ''}
                  </Typography>
                  <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>USDT / 月</Typography>
                </Box>
                <Typography sx={{ color: palette.textMuted, fontSize: 13, mb: 2.5, minHeight: 40 }}>
                  {p.desc}
                </Typography>
                <Button fullWidth
                  variant={p.best ? 'contained' : 'outlined'}
                  onClick={() => navigate(`/checkout?plan=${p.name.toLowerCase()}&months=1`)}
                  sx={p.best ? {
                    bgcolor: palette.ai, color: palette.bg, fontWeight: 700,
                    '&:hover': { bgcolor: palette.accentBright },
                  } : {
                    color: palette.ai, borderColor: palette.borderAccent, fontWeight: 700,
                    '&:hover': { borderColor: palette.ai, bgcolor: 'rgba(167,139,250,0.06)' },
                  }}>
                  选择 {p.name}
                </Button>
              </Box>
            </Reveal>
          </Grid>
        ))}
      </Grid>
      <Reveal sx={{ textAlign: 'center' }}>
        <Button
          onClick={() => navigate('/pricing')}
          variant="text" endIcon={<KeyboardArrowRightIcon />}
          sx={{ color: palette.ai, fontWeight: 700, '&:hover': { color: palette.accentBright } }}>
          查看完整定价 · 含 FAQ + 法律条款
        </Button>
      </Reveal>
    </Container>
  );
}

function FAQ() {
  const items = [
    { q: '会保证盈利吗？', a: '不会。我们是工具提供商，70% 量化散户首年亏损是行业基线。盈亏由策略 + 市场 + 你的参数决定。' },
    { q: '我的资金安全吗？', a: '资金始终在你自己的 OKX 账户。我们的角色仅是「调你的 API 下单」，AES-256 加密 key，不持有任何用户资金。' },
    { q: '为什么没有永久免费？', a: '量化工具维护成本高（candidate pipeline / AI 调用 / 服务器）。注册后可免费浏览 UI 验证产品，使用需订阅最少 1 月。' },
    { q: 'USDT 付款怎么验证？', a: '系统自动监听 4 链 admin 主地址 incoming USDT。按金额唯一 suffix 匹配你的订单，链上确认后自动开通（通常 1-3 分钟）。' },
    { q: '可以退款吗？', a: 'USDT 链上不可逆，订阅期内不退款。注册后免费 Preview 充分了解后再付费。详见退款政策。' },
  ];
  return (
    <Box sx={{ py: { xs: 8, md: 12 }, bgcolor: 'rgba(167,139,250,0.015)' }}>
      <Container maxWidth="md">
        <Reveal sx={{ textAlign: 'center', mb: 6 }}>
          <Typography sx={{ color: palette.ai, fontSize: 12, fontWeight: 700, letterSpacing: 2, mb: 1 }}>
            FAQ · 常见问题
          </Typography>
          <Typography sx={{ fontSize: { xs: '1.7rem', md: '2.3rem' }, fontWeight: 700, color: palette.text }}>
            付费前你想清楚的
          </Typography>
        </Reveal>
        <Stack spacing={1.5}>
          {items.map((item, i) => (
            <Reveal key={i} delay={i * 60}>
              <Box sx={{
                p: 2.5,
                bgcolor: palette.surface,
                border: `1px solid ${palette.border}`, borderRadius: 1.5,
                transition: 'border-color 220ms',
                '&:hover': { borderColor: palette.borderAccent },
              }}>
                <Typography sx={{ color: palette.ai, fontWeight: 700, fontSize: 14, mb: 0.5 }}>
                  Q · {item.q}
                </Typography>
                <Typography sx={{ color: palette.textMuted, fontSize: 13, lineHeight: 1.7 }}>
                  {item.a}
                </Typography>
              </Box>
            </Reveal>
          ))}
        </Stack>
      </Container>
    </Box>
  );
}

function FinalCTA() {
  const navigate = useNavigate();
  return (
    <Container maxWidth="md" sx={{ py: { xs: 10, md: 14 }, textAlign: 'center' }}>
      <Reveal>
        <Box sx={{
          p: { xs: 5, md: 8 },
          bgcolor: 'rgba(167,139,250,0.04)',
          border: `1px solid ${palette.borderAccent}`,
          borderRadius: 2,
          position: 'relative', overflow: 'hidden',
          '&::before': {
            content: '""',
            position: 'absolute', top: 0, left: 0, right: 0, height: 2,
            background: `linear-gradient(90deg, transparent, ${palette.ai}, transparent)`,
          },
        }}>
          <BoltIcon sx={{ fontSize: 40, color: palette.ai, mb: 2 }} />
          <Typography sx={{ fontSize: { xs: '1.7rem', md: '2.3rem' }, fontWeight: 700, color: palette.text, mb: 1.5, lineHeight: 1.2 }}>
            准备好让 AI 跑你的量化了？
          </Typography>
          <Typography sx={{ color: palette.textMuted, fontSize: 14, mb: 4 }}>
            5 分钟绑定 OKX · 立刻开始 LIVE · USDT 4 链 0 KYC 订阅
          </Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} justifyContent="center">
            <Button onClick={() => navigate('/login')}
              variant="outlined" size="large"
              sx={{
                color: palette.ai, borderColor: palette.borderAccent, fontWeight: 700,
                px: 4, py: 1.4, fontSize: 15,
                '&:hover': { borderColor: palette.ai, bgcolor: 'rgba(167,139,250,0.08)' },
              }}>
              免费注册浏览
            </Button>
            <Button onClick={() => navigate('/pricing')}
              variant="contained" size="large"
              endIcon={<KeyboardArrowRightIcon />}
              sx={{
                bgcolor: palette.ai, color: palette.bg, fontWeight: 700,
                px: 4, py: 1.4, fontSize: 15,
                boxShadow: `0 0 28px ${palette.accentGlow}`,
                '&:hover': { bgcolor: palette.accentBright, boxShadow: `0 0 40px ${palette.accentGlow}` },
              }}>
              查看订阅方案
            </Button>
          </Stack>
        </Box>
      </Reveal>
    </Container>
  );
}

function MarketingFooter() {
  return (
    <Box sx={{
      borderTop: `1px solid ${palette.border}`,
      py: 4, bgcolor: 'rgba(7,10,19,0.5)',
    }}>
      <Container maxWidth="lg">
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems="center" spacing={2}>
          <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>
            © 2026 Quant Pro · AI 量化交易工具 · 软件租赁服务（非投资顾问）
          </Typography>
          <Stack direction="row" spacing={2.5}>
            {[
              { label: '服务条款', path: '/terms' },
              { label: '退款政策', path: '/refund-policy' },
              { label: '隐私政策', path: '/privacy' },
              { label: '订阅', path: '/pricing' },
            ].map(l => (
              <MuiLink key={l.path} component={RouterLink} to={l.path}
                sx={{
                  color: palette.textMuted, fontSize: 12, textDecoration: 'none',
                  '&:hover': { color: palette.ai },
                }}>
                {l.label}
              </MuiLink>
            ))}
          </Stack>
        </Stack>
      </Container>
    </Box>
  );
}

// ============================================================
// 主导出
// ============================================================
export default function LandingPage() {
  return (
    <Box sx={{ bgcolor: palette.bg, minHeight: '100vh' }}>
      <MarketingNav />
      <Hero />
      <Stats />
      <HowItWorks />
      <Features />
      <PricingTeaser />
      <FAQ />
      <FinalCTA />
      <MarketingFooter />
    </Box>
  );
}
