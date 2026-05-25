// Phase 14k-3: Hyperliquid agent wallet 绑定卡片
// HL agent 设计: user 在 hyperliquid 网站派生 sub-wallet, 只能 trade
// (无法 transfer/withdraw), 主钱包永远不暴露给系统

import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, CardContent, Typography, Stack, TextField, Button, Alert, Chip,
  Box, Switch, FormControlLabel, IconButton, InputAdornment, Divider, Tooltip,
  Select, MenuItem, FormControl, InputLabel, Link,
} from '@mui/material';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import VerifiedIcon from '@mui/icons-material/Verified';
import LinkOffIcon from '@mui/icons-material/LinkOff';
import ScienceIcon from '@mui/icons-material/Science';
import SaveIcon from '@mui/icons-material/Save';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import ExchangeRiskDialog from './ExchangeRiskDialog';

const PURPLE = '#a78bfa';

export default function HyperliquidBindingCard({ onSaved }) {
  const [riskOpen, setRiskOpen] = useState(false);
  const [state, setState] = useState(null);
  const [editing, setEditing] = useState(false);
  const [agent_address, setAgent] = useState('');
  const [main_address, setMain] = useState('');
  const [agent_private_key, setPK] = useState('');
  const [network, setNetwork] = useState('mainnet');
  const [showPK, setShowPK] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [testResult, setTestResult] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/me/hyperliquid');
      setState(await r.json());
    } catch (e) {
      setMsg({ type: 'error', text: `载入失败: ${e.message}` });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSave = async () => {
    if (!agent_address || !main_address || !agent_private_key) {
      setMsg({ type: 'error', text: '三个字段都必填' });
      return;
    }
    setBusy(true); setMsg(null);
    try {
      const r = await fetch('/api/me/hyperliquid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_address, main_address, agent_private_key, network }),
      });
      const body = await r.json();
      if (!r.ok) {
        setMsg({ type: 'error', text: body.error || `HTTP ${r.status}` });
      } else {
        // Phase 14k-7: 切换 atomic 响应
        const switchInfo = body?.switch;
        const successMsg = switchInfo?.message || '已保存。点「测试」拉余额验证。';
        setMsg({ type: 'success', text: successMsg });
        setEditing(false);
        setAgent(''); setMain(''); setPK('');
        setState(body);
        if (onSaved) onSaved(body);
      }
    } finally { setBusy(false); }
  };

  const handleTest = async () => {
    setBusy(true); setTestResult(null);
    try {
      const r = await fetch('/api/me/hyperliquid/test', { method: 'POST' });
      const body = await r.json();
      setTestResult(body);
      if (body.ok) await load();
    } finally { setBusy(false); }
  };

  const handleToggle = async (is_active) => {
    setBusy(true);
    try {
      await fetch('/api/me/hyperliquid', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active }),
      });
      await load();
    } finally { setBusy(false); }
  };

  const handleDelete = async () => {
    if (!window.confirm('确定解绑 Hyperliquid agent? 已绑定策略 LIVE 模式会自动转 paper。')) return;
    setBusy(true);
    try {
      await fetch('/api/me/hyperliquid', { method: 'DELETE' });
      setTestResult(null);
      await load();
    } finally { setBusy(false); }
  };

  if (!state) return null;

  return (
    <Card sx={{ mb: 3, border: `1px solid ${PURPLE}33` }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <AccountBalanceWalletIcon sx={{ color: state.bound ? 'success.main' : PURPLE }} />
          <Typography variant="h6">Hyperliquid Agent</Typography>
          <Chip label="DEX · 永续合约" size="small" sx={{ bgcolor: `${PURPLE}22`, color: PURPLE, fontSize: 10 }} />
          {state.bound && (
            <Chip
              label={state.is_active ? '已启用' : '已停用'}
              size="small"
              color={state.is_active ? 'success' : 'default'}
              variant="outlined"
            />
          )}
          {state.bound && state.network && (
            <Chip
              label={state.network}
              size="small"
              color={state.network === 'mainnet' ? 'warning' : 'info'}
              variant="outlined"
            />
          )}
          {state.bound && state.verified_at && (
            <Tooltip title={`最后验证 ${state.verified_at}`}>
              <VerifiedIcon sx={{ color: 'success.main', fontSize: 18 }} />
            </Tooltip>
          )}
        </Stack>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          HL 是链上结算的非托管交易所，费率 ~0.035% taker 比 OKX 低 30%+，自托管不被冻结。
          需在 Hyperliquid 网站派生 <strong>agent wallet</strong> (只能 trade，无法 transfer)。
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 2 }}>
          <HelpOutlineIcon sx={{ fontSize: 14, color: 'text.secondary' }} />
          <Typography variant="caption" color="text.secondary">
            操作步骤: <Link href="https://app.hyperliquid.xyz/API" target="_blank" rel="noopener">app.hyperliquid.xyz/API</Link>
            {' '}→ Generate API Wallet → 复制 agent address + private key 贴这里
          </Typography>
        </Box>

        {msg && <Alert severity={msg.type} sx={{ mb: 2 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}

        {!state.bound && !editing && (
          <Button variant="contained" sx={{ bgcolor: PURPLE, '&:hover': { bgcolor: '#9472eb' } }}
                  startIcon={<AccountBalanceWalletIcon />} onClick={() => setEditing(true)}>
            绑定 Hyperliquid Agent
          </Button>
        )}

        {state.bound && !editing && (
          <Box>
            {/* Phase 14k-6: 180 天授权倒计时 */}
            {state.expired ? (
              <Alert severity="error" sx={{ mb: 2 }}>
                ⛔ Agent 已过期 ({state.agent_expires_at?.slice(0, 10)}). 所有 LIVE 策略已转 paper.
                点「更新」重新派生 agent + 贴新 private key.
              </Alert>
            ) : state.expiring_soon ? (
              <Alert severity="warning" sx={{ mb: 2 }}>
                ⚠️ Agent <strong>{state.days_remaining} 天</strong>后过期 ({state.agent_expires_at?.slice(0, 10)}).
                提前去 <Link href="https://app.hyperliquid.xyz/API" target="_blank" rel="noopener">hyperliquid.xyz/API</Link> 重新派生.
              </Alert>
            ) : state.days_remaining != null && (
              <Box sx={{ mb: 2, p: 1, borderRadius: 1, bgcolor: 'rgba(96,165,250,0.06)', display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="caption" color="text.secondary">授权倒计时:</Typography>
                <Chip label={`${state.days_remaining} 天`} size="small" color="info" sx={{ fontSize: 10, fontWeight: 700 }} />
                <Typography variant="caption" color="text.disabled">到期 {state.agent_expires_at?.slice(0, 10)} · HL 平台限制 180 天</Typography>
              </Box>
            )}
            <Stack spacing={0.5} sx={{ mb: 2 }}>
              <Typography variant="caption">
                <strong>Main wallet:</strong> <code>{state.main_address}</code>
              </Typography>
              <Typography variant="caption">
                <strong>Agent wallet:</strong> <code>{state.agent_address}</code>
              </Typography>
              {state.last_error && (
                <Alert severity="warning" sx={{ mt: 1 }}>上次错误: {state.last_error}</Alert>
              )}
              {!state.verified_at && (
                <Chip label="未验证" size="small" color="warning" variant="outlined" sx={{ width: 'fit-content' }} />
              )}
            </Stack>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
              <Button size="small" variant="outlined" startIcon={<ScienceIcon />} onClick={handleTest} disabled={busy}>
                测试连接 + 拉余额
              </Button>
              <Button size="small" variant="outlined" onClick={() => setEditing(true)} disabled={busy}>
                更新
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
                <strong>千万别贴你主钱包私钥！</strong> 只贴 HL 网站派生的 agent wallet 私钥。
                Agent 只能下单, 无法转账, 即使泄漏最多影响你 HL 账户内 USDC 仓位 (无法被提走)。
              </Alert>
              <FormControl size="small">
                <InputLabel>Network</InputLabel>
                <Select value={network} label="Network" onChange={(e) => setNetwork(e.target.value)}>
                  <MenuItem value="mainnet">Mainnet (真金)</MenuItem>
                  <MenuItem value="testnet">Testnet (测试)</MenuItem>
                </Select>
              </FormControl>
              <TextField
                fullWidth size="small" label="Main wallet address (0x...)"
                value={main_address} onChange={(e) => setMain(e.target.value)}
                placeholder="你存 USDC 的主钱包"
                helperText="HL 网站登录用的那个钱包地址"
              />
              <TextField
                fullWidth size="small" label="Agent wallet address (0x...)"
                value={agent_address} onChange={(e) => setAgent(e.target.value)}
                placeholder="HL 派生的 agent 地址"
              />
              <TextField
                fullWidth size="small" label="Agent private key"
                type={showPK ? 'text' : 'password'}
                value={agent_private_key} onChange={(e) => setPK(e.target.value)}
                placeholder="0x... 64 hex"
                InputProps={{
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton size="small" onClick={() => setShowPK(v => !v)}>
                        {showPK ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
              />
              <Stack direction="row" spacing={1}>
                <Button variant="contained" startIcon={<SaveIcon />} onClick={handleSave} disabled={busy}
                        sx={{ bgcolor: PURPLE, '&:hover': { bgcolor: '#9472eb' } }}>
                  保存 (Fernet 加密)
                </Button>
                <Button variant="text" onClick={() => { setEditing(false); setAgent(''); setMain(''); setPK(''); }} disabled={busy}>
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
                    OK — 账户余额 ≈ ${testResult.balance?.USDT?.total?.toFixed?.(2) || 0} USDC
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    free ${testResult.balance?.USDT?.free?.toFixed?.(2) || 0} ·
                    used ${testResult.balance?.USDT?.used?.toFixed?.(2) || 0}
                  </Typography>
                </Box>
              ) : (
                <Typography variant="body2">失败: {testResult.error}</Typography>
              )}
            </Alert>
          </>
        )}

        {/* Phase 14k-6: 风险声明小字 */}
        <Box sx={{ mt: 2, pt: 1, borderTop: '1px dashed rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <WarningAmberIcon sx={{ fontSize: 12, color: 'text.disabled' }} />
          <Typography variant="caption" color="text.disabled">
            HL 链上结算 + agent 180 天到期 ·{' '}
            <Typography component="span" variant="caption" sx={{ color: PURPLE, cursor: 'pointer', textDecoration: 'underline' }} onClick={() => setRiskOpen(true)}>
              点这里了解平台风险
            </Typography>
          </Typography>
        </Box>
        <ExchangeRiskDialog open={riskOpen} onClose={() => setRiskOpen(false)} exchange="hyperliquid" />
      </CardContent>
    </Card>
  );
}
