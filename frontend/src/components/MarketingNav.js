// Phase 12.26: 营销 nav 顶栏 — 给 Landing / Pricing / 法律页用（不带 sidebar）
import React, { useState, useEffect } from 'react';
import { Box, Button, Container, Stack, Typography } from '@mui/material';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import { palette, typo } from '../theme';

const NAV_LINKS = [
  { label: 'Features', path: '/#features' },
  { label: '订阅', path: '/pricing' },
  { label: '服务条款', path: '/terms' },
];

export default function MarketingNav() {
  const navigate = useNavigate();
  const location = useLocation();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 30);
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const handleNav = (path) => {
    if (path.startsWith('/#')) {
      const id = path.slice(2);
      if (location.pathname === '/') {
        const el = document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: 'smooth' });
      } else {
        navigate('/' + path.slice(1));
      }
    } else {
      navigate(path);
    }
  };

  return (
    <Box sx={{
      position: 'sticky', top: 0, zIndex: 100,
      bgcolor: scrolled ? 'rgba(10,14,26,0.85)' : 'rgba(10,14,26,0.4)',
      backdropFilter: 'blur(16px)',
      borderBottom: `1px solid ${scrolled ? palette.border : 'transparent'}`,
      transition: 'all 220ms',
    }}>
      <Container maxWidth="lg" sx={{ py: 1.5 }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
          {/* Logo */}
          <Stack component={Link} to="/" direction="row" alignItems="center" spacing={1}
            sx={{ textDecoration: 'none', '&:hover .logo-icon': { color: palette.accentBright } }}>
            <Box className="logo-icon" sx={{
              width: 32, height: 32, borderRadius: 1,
              bgcolor: palette.aiBg,
              border: `1px solid ${palette.borderAccent}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: palette.ai,
              boxShadow: `0 0 14px ${palette.accentGlow}`,
              transition: 'color 180ms',
            }}>
              <TrendingUpIcon sx={{ fontSize: 18 }} />
            </Box>
            <Box>
              <Typography sx={{
                color: palette.text, fontWeight: 700,
                fontSize: '1rem', lineHeight: 1, letterSpacing: '-0.01em',
              }}>
                Quant Pro
              </Typography>
              <Typography sx={{
                color: palette.textMuted, fontSize: 9,
                fontFamily: typo.mono, letterSpacing: 0.5, lineHeight: 1.2,
              }}>
                AI · QUANT · USDT
              </Typography>
            </Box>
          </Stack>

          {/* Nav links — 中桌面以上才显示 */}
          <Stack direction="row" spacing={0.5} sx={{ display: { xs: 'none', md: 'flex' } }}>
            {NAV_LINKS.map(l => (
              <Box key={l.label} component="button"
                onClick={() => handleNav(l.path)}
                sx={{
                  cursor: 'pointer', background: 'none', border: 0,
                  px: 1.5, py: 0.75,
                  color: palette.textMuted, fontSize: 13, fontWeight: 500,
                  fontFamily: typo.sans, borderRadius: 1,
                  transition: 'color 180ms, background-color 180ms',
                  '&:hover': { color: palette.text, bgcolor: 'rgba(167,139,250,0.06)' },
                }}>
                {l.label}
              </Box>
            ))}
          </Stack>

          {/* Right side CTA */}
          <Stack direction="row" spacing={1}>
            <Button
              onClick={() => navigate('/login')}
              variant="text"
              sx={{
                color: palette.textMuted, fontWeight: 600, fontSize: 13,
                px: 1.5, '&:hover': { color: palette.ai, bgcolor: 'rgba(167,139,250,0.06)' },
              }}>
              登入
            </Button>
            <Button
              onClick={() => navigate('/pricing')}
              variant="contained"
              sx={{
                bgcolor: palette.ai, color: palette.bg, fontWeight: 700, fontSize: 13,
                px: 2, py: 0.75, letterSpacing: 0.3,
                boxShadow: `0 0 14px ${palette.accentGlow}`,
                '&:hover': { bgcolor: palette.accentBright, boxShadow: `0 0 22px ${palette.accentGlow}` },
              }}>
              立即订阅
            </Button>
          </Stack>
        </Stack>
      </Container>
    </Box>
  );
}
