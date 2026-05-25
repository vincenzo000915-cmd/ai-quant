// Phase 11.2.3: OKX 綁定卡片 — Settings 頁掛載

import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, CardContent, Typography, Stack, TextField, Button, Alert, Chip,
  Box, Switch, FormControlLabel, IconButton, InputAdornment, Divider, Tooltip,
} from '@mui/material';
import KeyIcon from '@mui/icons-material/Key';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import VerifiedIcon from '@mui/icons-material/Verified';
import LinkOffIcon from '@mui/icons-material/LinkOff';
import ScienceIcon from '@mui/icons-material/Science';
import SaveIcon from '@mui/icons-material/Save';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { getUser } from '../auth';
import ExchangeRiskDialog from './ExchangeRiskDialog';

export default function OkxBindingCard({ onSaved }) {
  const [riskOpen, setRiskOpen] = useState(false);
  const [state, setState] = useState(null);   // server 状态：{bound, source, ...}
  const [editing, setEditing] = useState(false);
  const [api_key, setApiKey] = useState('');
  const [secret, setSecret] = useState('');
  const [passphrase, setPassphrase] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);   // {type, text}
  const [testResult, setTestResult] = useState(null);

  const user = getUser();
  const isAdmin = user?.role === 'admin' || user?._is_system;

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/me/okx');
      const data = await r.json();
      setState(data);
    } catch (e) {
      setMsg({ type: 'error', text: `载入失败：${e.message}` });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSave = async () => {
    if (!api_key || !secret || !passphrase) {
      setMsg({ type: 'error', text: 'API Key / Secret / Passphrase 都必填' });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const r = await fetch('/api/me/okx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key, secret, passphrase }),
      });
      const body = await r.json();
      if (!r.ok) {
        setMsg({ type: 'error', text: body.error || `HTTP ${r.status}` });
      } else {
        // Phase 14k-7: 切换 atomic 响应 → 显切换 toast (父组件管理)
        const switchInfo = body?.switch;
        const successMsg = switchInfo?.message || '已保存。点「测试」验证 key 是否有效。';
        setMsg({ type: 'success', text: successMsg });
        setEditing(false);
        setApiKey(''); setSecret(''); setPassphrase('');
        setState(body);
        if (onSaved) onSaved(body);
      }
    } finally { setBusy(false); }
  };

  const handleTest = async () => {
    setBusy(true);
    setTestResult(null);
    try {
      const r = await fetch('/api/me/okx/test', { method: 'POST' });
      const body = await r.json();
      setTestResult(body);
      if (body.ok) {
        await load();   // 刷新 verified_at
      }
    } finally { setBusy(false); }
  };

  const handleToggle = async (is_active) => {
    setBusy(true);
    try {
      await fetch('/api/me/okx', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active }),
      });
      await load();
    } finally { setBusy(false); }
  };

  const handleDelete = async () => {
    if (!window.confirm('确定解绑 OKX？已绑定策略 LIVE 模式会自动转 paper。')) return;
    setBusy(true);
    try {
      await fetch('/api/me/okx', { method: 'DELETE' });
      setTestResult(null);
      await load();
    } finally { setBusy(false); }
  };

  if (!state) return null;

  // Admin path — env-managed, read only display
  if (state.source === 'env') {
    return (
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
            <KeyIcon sx={{ color: 'warning.main' }} />
            <Typography variant="h6">OKX API 绑定</Typography>
            <Chip label="ADMIN · .env" size="small" color="warning" variant="outlined" />
          </Stack>
          <Alert severity="info" sx={{ mb: 2 }}>
            您是 admin，OKX key 走 <code>/opt/quant/.env</code>（EXCHANGE_API_KEY 等三个变量）。如需更换请直接改 .env 后重启容器，不在 UI 操作。
          </Alert>
          <Button variant="outlined" size="small" startIcon={<ScienceIcon />} onClick={handleTest} disabled={busy}>
            测试 env key 拉余额
          </Button>
          {testResult && (
            <Alert severity={testResult.ok ? 'success' : 'error'} sx={{ mt: 2 }}>
              {testResult.ok
                ? `OK — 余额 ≈ $${testResult.total_equity_usd?.toFixed?.(2) || testResult.total_equity_usd}`
                : `失败：${testResult.error}`}
            </Alert>
          )}
        </CardContent>
      </Card>
    );
  }

  // Regular user path
  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <KeyIcon sx={{ color: state.bound ? 'success.main' : 'text.secondary' }} />
          <Typography variant="h6">OKX API 绑定</Typography>
          {state.bound && (
            <Chip
              label={state.is_active ? '已启用' : '已停用'}
              size="small"
              color={state.is_active ? 'success' : 'default'}
              variant="outlined"
            />
          )}
          {state.bound && state.verified_at && (
            <Tooltip title={`最后验证 ${state.verified_at}`}>
              <VerifiedIcon sx={{ color: 'success.main', fontSize: 18 }} />
            </Tooltip>
          )}
        </Stack>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          绑定后 LIVE 模式才能下到您的 OKX 账户。Key 用 AES-256 (Fernet) 加密存 DB，前端不缓存明文。
        </Typography>

        {msg && <Alert severity={msg.type} sx={{ mb: 2 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}

        {!state.bound && !editing && (
          <Button variant="contained" startIcon={<KeyIcon />} onClick={() => setEditing(true)}>
            绑定 OKX Key
          </Button>
        )}

        {state.bound && !editing && (
          <Box>
            <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2, flexWrap: 'wrap', gap: 1 }}>
              <Typography variant="body2">
                API Key: <code>{state.api_key_masked}</code>
              </Typography>
              {state.last_error && (
                <Chip label="上次验证失败" size="small" color="error" variant="outlined" />
              )}
              {!state.verified_at && (
                <Chip label="未验证" size="small" color="warning" variant="outlined" />
              )}
            </Stack>
            {state.last_error && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                上次错误：{state.last_error}
              </Alert>
            )}
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
              <Button size="small" variant="outlined" startIcon={<ScienceIcon />} onClick={handleTest} disabled={busy}>
                测试连接
              </Button>
              <Button size="small" variant="outlined" onClick={() => setEditing(true)} disabled={busy}>
                更新 Key
              </Button>
              <FormControlLabel
                control={<Switch checked={!!state.is_active} onChange={(e) => handleToggle(e.target.checked)} disabled={busy} size="small" />}
                label={<Typography variant="body2">启用</Typography>}
              />
              <Button size="small" variant="outlined" color="error" startIcon={<LinkOffIcon />} onClick={handleDelete} disabled={busy}>
                解绑
              </Button>
            </Stack>
          </Box>
        )}

        {editing && (
          <Box>
            <Stack spacing={2}>
              <Alert severity="warning" sx={{ fontSize: 13 }}>
                只接受 OKX **永续合约 Trade** 权限的 API key。请确保账户 posMode=long_short_mode 才能用现有策略。
              </Alert>
              <TextField
                fullWidth size="small" label="API Key"
                value={api_key} onChange={(e) => setApiKey(e.target.value)}
              />
              <TextField
                fullWidth size="small" label="Secret"
                type={showSecret ? 'text' : 'password'}
                value={secret} onChange={(e) => setSecret(e.target.value)}
                InputProps={{
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton size="small" onClick={() => setShowSecret(v => !v)}>
                        {showSecret ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
              />
              <TextField
                fullWidth size="small" label="Passphrase"
                type={showSecret ? 'text' : 'password'}
                value={passphrase} onChange={(e) => setPassphrase(e.target.value)}
              />
              <Stack direction="row" spacing={1}>
                <Button variant="contained" startIcon={<SaveIcon />} onClick={handleSave} disabled={busy}>
                  保存
                </Button>
                <Button variant="text" onClick={() => { setEditing(false); setApiKey(''); setSecret(''); setPassphrase(''); }} disabled={busy}>
                  取消
                </Button>
              </Stack>
            </Stack>
          </Box>
        )}

        {testResult && (
          <>
            <Divider sx={{ my: 2 }} />
            <Alert severity={testResult.ok ? 'success' : 'error'}>
              {testResult.ok ? (
                <Box>
                  <Typography variant="body2">
                    OK — 总权益 ≈ ${testResult.total_equity_usd?.toFixed?.(4) || testResult.total_equity_usd}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    posMode={testResult.posMode || '?'} · acctLv={testResult.acctLv || '?'}
                  </Typography>
                </Box>
              ) : (
                <Typography variant="body2">失败：{testResult.error}</Typography>
              )}
            </Alert>
          </>
        )}

        {/* Phase 14k-6: 风险声明小字 */}
        <Box sx={{ mt: 2, pt: 1, borderTop: '1px dashed rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <WarningAmberIcon sx={{ fontSize: 12, color: 'text.disabled' }} />
          <Typography variant="caption" color="text.disabled">
            OKX 是中心化交易所 ·{' '}
            <Typography component="span" variant="caption" sx={{ color: '#60a5fa', cursor: 'pointer', textDecoration: 'underline' }} onClick={() => setRiskOpen(true)}>
              点这里了解平台风险
            </Typography>
          </Typography>
        </Box>
        <ExchangeRiskDialog open={riskOpen} onClose={() => setRiskOpen(false)} exchange="okx" />
      </CardContent>
    </Card>
  );
}
