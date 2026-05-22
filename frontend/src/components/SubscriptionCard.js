// Phase 12.24.3: 「我的订阅」卡 — Settings 页用
//
// 显示当前 tier / 到期 / 续费 / 取消 / 历史订单链接

import React, { useState, useEffect } from 'react';
import { Box, Typography, Button, Chip, Stack, LinearProgress, Alert } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium';
import { palette, typo } from '../theme';

const API = process.env.REACT_APP_API_URL || '';

const TIER_META = {
  preview: { label: 'Preview', color: palette.textMuted, desc: '注册免费，仅可浏览功能' },
  basic:   { label: 'Basic',   color: palette.success,   desc: '工具基础包，含 LIVE 实盘' },
  pro:     { label: 'Pro',     color: palette.ai,        desc: 'AI 量化驾驶舱，BYO LLM key' },
  team:    { label: 'Team',    color: palette.warmAccent,desc: '团队/多账户/优先客服' },
  admin:   { label: 'Admin',   color: palette.warmAccent,desc: '系统管理员，全功能' },
};

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function daysBetween(iso) {
  if (!iso) return 0;
  return Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000));
}

export default function SubscriptionCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetch(`${API}/api/me/subscription`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Box sx={{ p: 2.25, bgcolor: palette.surface, border: `1px solid ${palette.border}`, borderRadius: 1.5 }}>
        <LinearProgress sx={{ bgcolor: 'transparent', '& .MuiLinearProgress-bar': { bgcolor: palette.ai } }} />
      </Box>
    );
  }

  const tier = data?.tier || 'preview';
  const sub = data?.subscription;
  const meta = TIER_META[tier] || TIER_META.preview;
  const daysLeft = sub ? daysBetween(sub.expires_at) : 0;
  const expiringSoon = daysLeft > 0 && daysLeft <= 7;

  return (
    <Box className="glass-card" sx={{
      p: 2.5, mb: 2.5, position: 'relative', overflow: 'hidden',
      '&::before': {
        content: '""', position: 'absolute', top: 0, left: 0, right: 0, height: 2,
        background: `linear-gradient(90deg, transparent, ${meta.color}, transparent)`,
      },
    }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 2 }}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <WorkspacePremiumIcon sx={{ color: meta.color, fontSize: 20 }} />
          <Box>
            <Typography sx={{ ...typo.h3, color: palette.text, fontSize: '1rem' }}>
              我的订阅
            </Typography>
            <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>
              {meta.desc}
            </Typography>
          </Box>
        </Stack>
        <Chip
          label={meta.label}
          sx={{
            bgcolor: `${meta.color}1a`, color: meta.color,
            border: `1px solid ${meta.color}40`,
            fontWeight: 700, letterSpacing: 0.5,
          }}
        />
      </Stack>

      {/* 已订阅 — 显示到期 + 进度 */}
      {sub && tier !== 'preview' && tier !== 'admin' && (
        <Box sx={{ mb: 2 }}>
          <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
            <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>
              到期日 · {fmtDate(sub.expires_at)}
            </Typography>
            <Typography sx={{
              color: expiringSoon ? palette.warning : palette.text,
              fontFamily: typo.mono, fontSize: 12, fontWeight: 700,
            }}>
              剩 {daysLeft} 天
            </Typography>
          </Stack>
          <LinearProgress
            variant="determinate"
            value={Math.min(100, (daysLeft / 30) * 100)}
            sx={{
              height: 4, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.06)',
              '& .MuiLinearProgress-bar': {
                bgcolor: expiringSoon ? palette.warning : palette.ai,
              },
            }}
          />
          {expiringSoon && (
            <Alert severity="warning" sx={{ mt: 1.5, fontSize: 12 }}>
              订阅即将到期，建议提前续费避免功能锁住
            </Alert>
          )}
        </Box>
      )}

      {/* preview tier — 提示订阅 */}
      {tier === 'preview' && (
        <Alert severity="info" sx={{ mb: 2, fontSize: 12 }}>
          你正在使用免费 <strong>Preview</strong> 模式，可浏览 UI 但功能锁住。
          订阅 Basic ($50/月) 起立刻解锁完整工具。
        </Alert>
      )}

      {/* admin — 特殊提示 */}
      {tier === 'admin' && (
        <Alert severity="success" sx={{ mb: 2, fontSize: 12 }}>
          系统管理员账号，所有功能全部可用，不需要订阅。
        </Alert>
      )}

      {/* Actions */}
      <Stack direction="row" spacing={1}>
        {tier === 'preview' && (
          <Button variant="contained" onClick={() => navigate('/pricing')}
            sx={{ bgcolor: palette.ai, color: palette.bg, fontWeight: 700,
                  '&:hover': { bgcolor: palette.accentBright } }}>
            查看订阅方案
          </Button>
        )}
        {sub && (
          <>
            <Button variant="contained" onClick={() => navigate('/pricing')}
              sx={{ bgcolor: palette.ai, color: palette.bg, fontWeight: 700 }}>
              {expiringSoon ? '立即续费' : '续费 / 升级'}
            </Button>
            <Button variant="outlined" onClick={() => navigate('/pricing')}
              sx={{ borderColor: palette.border, color: palette.textMuted,
                    '&:hover': { borderColor: palette.ai, color: palette.ai } }}>
              切换方案
            </Button>
          </>
        )}
      </Stack>
    </Box>
  );
}
