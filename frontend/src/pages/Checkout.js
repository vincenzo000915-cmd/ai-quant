// Phase 12.24: USDT 自建付款 — 4 链选择 + QR + 准确金额 suffix + 倒计时
//
// 流程：
//   1. 进页面拿 ?plan=pro&months=3
//   2. 列 4 链 chips（fetch /api/billing/chains），用户选一条
//   3. 点「生成订单」→ POST /api/billing/invoice → 拿 invoice
//   4. 展示：QR + 地址 + 准确金额（含 .xxxxxx suffix）+ 30min 倒计时
//   5. 每 10s 轮询 GET /api/billing/invoice/<id>，status='confirmed' → 跳转 Settings
//   6. 5min 后启用 tx hash 备用通道

import React, { useState, useEffect, useCallback } from 'react';
import { Box, Container, Typography, Button, Chip, Stack, Alert, IconButton, TextField, Snackbar } from '@mui/material';
import { useSearchParams, useNavigate } from 'react-router-dom';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { QRCodeSVG } from 'qrcode.react';
import { palette, typo } from '../theme';

const API = process.env.REACT_APP_API_URL || '';

function fmtTimeLeft(ms) {
  if (ms <= 0) return '00:00';
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default function Checkout() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const plan = params.get('plan') || 'basic';
  const months = parseInt(params.get('months') || '1', 10);

  const [chainsConfig, setChainsConfig] = useState({});
  const [selectedChain, setSelectedChain] = useState(null);
  const [invoice, setInvoice] = useState(null);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(Date.now());
  const [copied, setCopied] = useState(false);
  const [showTxHashForm, setShowTxHashForm] = useState(false);
  const [txHashInput, setTxHashInput] = useState('');

  // 拉 chain 配置
  useEffect(() => {
    fetch(`${API}/api/billing/chains`)
      .then(r => r.json())
      .then(data => {
        setChainsConfig(data.chains || {});
        // 默认选 TRC20
        if (data.chains?.trc20) setSelectedChain('trc20');
      })
      .catch(() => setError('无法加载链配置'));
  }, []);

  // 倒计时 tick
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // 轮询 invoice status (10s)
  const pollInvoice = useCallback(async () => {
    if (!invoice || invoice.status !== 'pending') return;
    try {
      const r = await fetch(`${API}/api/billing/invoice/${invoice.id}`);
      if (!r.ok) return;
      const data = await r.json();
      setInvoice(data);
      if (data.status === 'confirmed') {
        setTimeout(() => navigate('/settings?tab=subscription&just_activated=1'), 3000);
      }
    } catch (e) { /* */ }
  }, [invoice, navigate]);

  useEffect(() => {
    if (!invoice || invoice.status !== 'pending') return;
    const id = setInterval(pollInvoice, 10000);
    return () => clearInterval(id);
  }, [invoice, pollInvoice]);

  const createInvoice = async () => {
    if (!selectedChain) { setError('请选择付款链'); return; }
    setError(null);
    try {
      const r = await fetch(`${API}/api/billing/invoice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan, months, chain: selectedChain }),
      });
      const data = await r.json();
      if (!r.ok) { setError(data.error || '创建订单失败'); return; }
      setInvoice(data);
    } catch (e) {
      setError('网络错误，请重试');
    }
  };

  const copyAddress = () => {
    navigator.clipboard.writeText(invoice.address);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const copyAmount = () => {
    navigator.clipboard.writeText(invoice.amount_due.toString());
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const submitTxHash = async () => {
    if (!txHashInput.trim()) return;
    try {
      const r = await fetch(`${API}/api/billing/invoice/${invoice.id}/submit-tx`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tx_hash: txHashInput.trim() }),
      });
      const data = await r.json();
      if (!r.ok) { setError(data.error || '提交失败'); return; }
      setInvoice(data);
      setShowTxHashForm(false);
    } catch (e) { setError('网络错误'); }
  };

  // 计算预览金额 (生成 invoice 前展示)
  const PLAN_PRICES = { basic: 50, pro: 125, team: 250 };
  const DISCOUNT_MAP = { 1: 0, 3: 10, 6: 20, 12: 30 };
  const previewAmount = Math.round(
    PLAN_PRICES[plan] * months * (1 - (DISCOUNT_MAP[months] || 0) / 100) * 100
  ) / 100;

  // 倒计时
  const timeLeft = invoice ? new Date(invoice.expires_at).getTime() - now : 0;
  const showTxOption = invoice && invoice.status === 'pending'
    && (now - new Date(invoice.created_at).getTime()) > 5 * 60 * 1000;

  return (
    <Container maxWidth="sm" sx={{ py: 6, position: 'relative', zIndex: 1 }}>
      <Button onClick={() => navigate('/pricing')} startIcon={<ArrowBackIcon />}
        sx={{ color: palette.textMuted, mb: 2, '&:hover': { color: palette.ai } }}>
        返回定价
      </Button>

      <Box sx={{
        p: 4, bgcolor: palette.surface,
        border: `1px solid ${palette.borderAccent}`, borderRadius: 1.5,
        boxShadow: `0 0 32px ${palette.accentGlow}`, position: 'relative',
        '&::before': {
          content: '""', position: 'absolute', top: 0, left: 0, right: 0, height: 2,
          background: `linear-gradient(90deg, transparent, ${palette.ai}, transparent)`,
        },
      }}>
        <Typography sx={{ color: palette.ai, fontWeight: 700, fontSize: 11, letterSpacing: 1.5, mb: 1 }}>
          QUANT PRO · USDT CHECKOUT
        </Typography>
        <Typography sx={{ ...typo.h1, color: palette.text, mb: 2.5 }}>
          {invoice ? (invoice.status === 'confirmed' ? '订阅已开通' : '等待付款') : '确认订单'}
        </Typography>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {/* === 订单摘要 === */}
        <Box sx={{
          p: 2.5, mb: 3, bgcolor: 'rgba(167,139,250,0.06)',
          border: `1px solid ${palette.border}`, borderRadius: 1,
        }}>
          <Stack direction="row" justifyContent="space-between" sx={{ mb: 1 }}>
            <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>订阅</Typography>
            <Chip label={plan.toUpperCase()} size="small"
              sx={{ bgcolor: palette.aiBg, color: palette.ai, fontWeight: 700 }} />
          </Stack>
          <Stack direction="row" justifyContent="space-between" sx={{ mb: 1 }}>
            <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>周期</Typography>
            <Typography sx={{ color: palette.text, fontFamily: typo.mono, fontSize: 13 }}>{months} 个月</Typography>
          </Stack>
          {DISCOUNT_MAP[months] > 0 && (
            <Stack direction="row" justifyContent="space-between" sx={{ mb: 1 }}>
              <Typography sx={{ color: palette.textMuted, fontSize: 12 }}>预付折扣</Typography>
              <Typography sx={{ color: palette.success, fontFamily: typo.mono, fontSize: 13 }}>-{DISCOUNT_MAP[months]}%</Typography>
            </Stack>
          )}
          <Box sx={{ borderTop: `1px solid ${palette.border}`, pt: 1.5, mt: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="baseline">
              <Typography sx={{ color: palette.text, fontWeight: 600 }}>
                {invoice ? '准确金额' : '基础价'}
              </Typography>
              <Typography sx={{ ...typo.metric, color: palette.ai, fontSize: '1.6rem' }}>
                ${invoice ? invoice.amount_due.toFixed(6) : previewAmount}
                <Box component="span" sx={{ fontSize: 12, color: palette.textMuted, fontFamily: typo.mono, ml: 0.5 }}>
                  USDT
                </Box>
              </Typography>
            </Stack>
            {invoice && (
              <Typography sx={{ color: palette.warning, fontSize: 11, mt: 0.5, fontFamily: typo.mono }}>
                ⚠️ 末尾 6 位 ({invoice.suffix}) 用于识别你的订单，请精确转账
              </Typography>
            )}
          </Box>
        </Box>

        {/* === 没生成 invoice 时：选链 === */}
        {!invoice && (
          <>
            <Typography sx={{ color: palette.text, fontWeight: 600, fontSize: 13, mb: 1.5 }}>
              选择付款链
            </Typography>
            <Stack spacing={1} sx={{ mb: 3 }}>
              {Object.entries(chainsConfig).map(([key, c]) => (
                <Box key={key}
                  onClick={() => setSelectedChain(key)}
                  sx={{
                    cursor: 'pointer', p: 1.5,
                    border: `1px solid ${selectedChain === key ? palette.ai : palette.border}`,
                    bgcolor: selectedChain === key ? 'rgba(167,139,250,0.08)' : 'transparent',
                    borderRadius: 1,
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    transition: 'all 180ms',
                    '&:hover': { borderColor: palette.borderHot },
                  }}>
                  <Box>
                    <Typography sx={{ color: palette.text, fontWeight: 700, fontSize: 14 }}>
                      {c.label}
                    </Typography>
                    <Typography sx={{ color: palette.textMuted, fontSize: 11 }}>
                      {c.network} · 手续费 {c.fee_estimate} · 确认 {c.confirm_time}
                    </Typography>
                  </Box>
                  {selectedChain === key && <CheckCircleIcon sx={{ color: palette.ai, fontSize: 20 }} />}
                </Box>
              ))}
            </Stack>
            <Button variant="contained" fullWidth onClick={createInvoice}
              disabled={!selectedChain}
              sx={{
                bgcolor: palette.ai, color: palette.bg,
                fontWeight: 700, py: 1.3, letterSpacing: 0.6,
                '&:hover': { bgcolor: palette.accentBright },
                '&.Mui-disabled': { bgcolor: 'rgba(167,139,250,0.3)', color: 'rgba(255,255,255,0.5)' },
              }}>
              生成付款订单
            </Button>
          </>
        )}

        {/* === Invoice pending 状态：显示 QR + 地址 === */}
        {invoice && invoice.status === 'pending' && (
          <>
            <Box sx={{
              p: 3, mb: 2,
              border: `1px solid ${palette.border}`, borderRadius: 1,
              bgcolor: 'rgba(0,0,0,0.2)',
              textAlign: 'center',
            }}>
              <Box sx={{
                p: 2, bgcolor: '#fff', borderRadius: 1, display: 'inline-block', mb: 2,
              }}>
                <QRCodeSVG
                  value={invoice.address}
                  size={180}
                  level="M"
                  includeMargin={false}
                />
              </Box>
              <Typography sx={{ color: palette.textMuted, fontSize: 11, mb: 0.5 }}>
                {chainsConfig[invoice.chain]?.label} 收款地址
              </Typography>
              <Stack direction="row" alignItems="center" justifyContent="center" spacing={0.5}>
                <Typography sx={{
                  color: palette.text, fontFamily: typo.mono, fontSize: 11,
                  wordBreak: 'break-all', maxWidth: '100%', textAlign: 'center',
                  bgcolor: 'rgba(167,139,250,0.06)',
                  px: 1, py: 0.5, borderRadius: 0.5,
                }}>
                  {invoice.address}
                </Typography>
                <IconButton size="small" onClick={copyAddress}
                  sx={{ color: palette.ai, '&:hover': { color: palette.accentBright } }}>
                  <ContentCopyIcon sx={{ fontSize: 14 }} />
                </IconButton>
              </Stack>
            </Box>

            {/* 精确金额 */}
            <Box sx={{
              p: 2, mb: 2,
              border: `1px solid ${palette.warning}40`,
              bgcolor: 'rgba(247,166,0,0.06)',
              borderRadius: 1,
            }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Box>
                  <Typography sx={{ color: palette.warning, fontSize: 10, fontWeight: 700, letterSpacing: 0.6, mb: 0.3 }}>
                    精确转账金额
                  </Typography>
                  <Typography sx={{
                    color: palette.text, fontFamily: typo.mono, fontSize: '1.2rem', fontWeight: 700,
                  }}>
                    {invoice.amount_due.toFixed(6)} <Box component="span" sx={{ fontSize: 12, color: palette.textMuted }}>USDT</Box>
                  </Typography>
                </Box>
                <IconButton onClick={copyAmount} sx={{ color: palette.warning }}>
                  <ContentCopyIcon sx={{ fontSize: 18 }} />
                </IconButton>
              </Stack>
            </Box>

            {/* 倒计时 */}
            <Box sx={{
              p: 1.5, mb: 2, textAlign: 'center',
              border: `1px solid ${timeLeft < 5 * 60 * 1000 ? palette.error : palette.border}`,
              borderRadius: 1,
            }}>
              <Typography sx={{ color: palette.textMuted, fontSize: 10, letterSpacing: 0.6, mb: 0.3 }}>
                订单有效期
              </Typography>
              <Typography sx={{
                color: timeLeft < 5 * 60 * 1000 ? palette.error : palette.text,
                fontFamily: typo.mono, fontSize: '1.5rem', fontWeight: 700,
              }}>
                {fmtTimeLeft(timeLeft)}
              </Typography>
              <Typography sx={{ color: palette.textMuted, fontSize: 10, mt: 0.3 }}>
                付款后 1-3 分钟系统自动识别开通订阅
              </Typography>
            </Box>

            {/* 备用通道 */}
            {showTxOption && !showTxHashForm && (
              <Button variant="outlined" fullWidth onClick={() => setShowTxHashForm(true)}
                sx={{
                  borderColor: palette.border, color: palette.textMuted,
                  '&:hover': { borderColor: palette.ai, color: palette.ai },
                }}>
                已付款但 5 分钟未确认？上传 tx hash
              </Button>
            )}
            {showTxHashForm && (
              <Box sx={{ p: 2, border: `1px solid ${palette.border}`, borderRadius: 1, mb: 1 }}>
                <Typography sx={{ color: palette.textMuted, fontSize: 11, mb: 1 }}>
                  你的链上 tx hash（admin 1-2 工作日内审核）
                </Typography>
                <TextField fullWidth size="small" value={txHashInput}
                  onChange={e => setTxHashInput(e.target.value)}
                  placeholder="0x... 或 ..."
                  sx={{ mb: 1, '& .MuiInputBase-input': { fontFamily: typo.mono, fontSize: 11 } }} />
                <Button onClick={submitTxHash} variant="contained" disabled={!txHashInput.trim()}
                  sx={{ bgcolor: palette.ai, color: palette.bg, fontWeight: 700 }}>
                  提交审核
                </Button>
              </Box>
            )}

            <Typography sx={{ color: palette.textFaint, fontSize: 10, textAlign: 'center', mt: 2 }}>
              点击付款即表示同意 <a href="/terms" style={{ color: palette.ai }}>服务条款</a>
              {' · '}
              <a href="/refund-policy" style={{ color: palette.ai }}>退款政策</a>
            </Typography>
          </>
        )}

        {/* === Confirmed 状态 === */}
        {invoice && invoice.status === 'confirmed' && (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <CheckCircleIcon sx={{ fontSize: 64, color: palette.success, mb: 2 }} />
            <Typography sx={{ color: palette.success, fontSize: '1.5rem', fontWeight: 700, mb: 1 }}>
              付款成功，订阅已开通
            </Typography>
            <Typography sx={{ color: palette.textMuted, fontSize: 13, mb: 2 }}>
              即将跳转 Settings 页查看订阅...
            </Typography>
            <Button onClick={() => navigate('/dashboard')} variant="contained"
              sx={{ bgcolor: palette.ai, color: palette.bg, fontWeight: 700 }}>
              前往 Dashboard
            </Button>
          </Box>
        )}

        {/* === 过期 === */}
        {invoice && (invoice.status === 'expired' || invoice.status === 'cancelled') && (
          <Box sx={{ textAlign: 'center', py: 3 }}>
            <Typography sx={{ color: palette.error, fontSize: '1.2rem', fontWeight: 700, mb: 1 }}>
              订单已{invoice.status === 'expired' ? '过期' : '取消'}
            </Typography>
            <Button onClick={() => { setInvoice(null); setSelectedChain('trc20'); }} variant="contained"
              sx={{ bgcolor: palette.ai, color: palette.bg, fontWeight: 700, mt: 2 }}>
              重新下单
            </Button>
          </Box>
        )}

        {/* === Pending review === */}
        {invoice && invoice.status === 'pending_review' && (
          <Alert severity="info" sx={{ mt: 2 }}>
            tx hash 已提交，admin 将在 1-2 工作日内审核。审核通过后自动开通。
          </Alert>
        )}
      </Box>

      <Snackbar open={copied} message="已复制" autoHideDuration={1500}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }} />
    </Container>
  );
}
