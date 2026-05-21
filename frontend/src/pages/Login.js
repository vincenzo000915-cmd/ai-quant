// Phase 11.1.5: 登入 / 註冊 / 系統 token 三模式

import React, { useState } from 'react';
import {
  Box, Card, CardContent, Tabs, Tab, TextField, Button, Typography,
  Alert, Stack, Collapse, IconButton, InputAdornment, Divider,
} from '@mui/material';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import LockIcon from '@mui/icons-material/Lock';
import { loginWithPassword, registerWithPassword, setToken, verifyToken } from '../auth';

const TAB_LOGIN = 0;
const TAB_REGISTER = 1;

export default function Login({ onLoggedIn }) {
  const [tab, setTab] = useState(TAB_LOGIN);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const [adminMode, setAdminMode] = useState(false);
  const [adminToken, setAdminToken] = useState('');
  const [adminError, setAdminError] = useState(null);
  const [adminBusy, setAdminBusy] = useState(false);

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    if (!email || !password) {
      setError('请填写邮箱和密码');
      return;
    }
    setBusy(true);
    setError(null);
    const fn = tab === TAB_LOGIN ? loginWithPassword : registerWithPassword;
    const r = await fn(email.trim(), password);
    setBusy(false);
    if (!r.ok) {
      setError(r.error || (tab === TAB_LOGIN ? '登入失败' : '注册失败'));
      return;
    }
    onLoggedIn?.(r.user);
  };

  const submitAdminToken = async () => {
    if (!adminToken.trim()) return;
    setAdminBusy(true);
    setAdminError(null);
    setToken(adminToken.trim());
    const r = await verifyToken();
    setAdminBusy(false);
    if (r.ok) {
      onLoggedIn?.(null);
    } else {
      setToken('');
      setAdminError('Token 无效，请确认 .env 里的 API_AUTH_TOKEN');
    }
  };

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        p: 2,
      }}
    >
      <Card
        elevation={0}
        sx={{
          width: '100%',
          maxWidth: 420,
          bgcolor: 'background.paper',
          border: '1px solid rgba(6,182,212,0.2)',
          boxShadow: '0 0 40px rgba(6,182,212,0.08)',
        }}
      >
        <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
          {/* Logo / Brand */}
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="center" sx={{ mb: 1 }}>
            <ShowChartIcon sx={{ color: 'primary.main', fontSize: 28 }} />
            <Typography variant="h5" fontWeight={700} color="text.primary">
              量化交易系统
            </Typography>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', textAlign: 'center', mb: 3 }}>
            SaaS 模式 · 第一次使用请先注册
          </Typography>

          <Tabs
            value={tab}
            onChange={(_, v) => { setTab(v); setError(null); }}
            variant="fullWidth"
            sx={{ mb: 2 }}
          >
            <Tab label="登入" />
            <Tab label="注册" />
          </Tabs>

          <form onSubmit={handleSubmit}>
            <Stack spacing={2}>
              {error && <Alert severity="error" sx={{ fontSize: 13 }}>{error}</Alert>}

              <TextField
                fullWidth
                label="邮箱"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                autoFocus
                size="small"
              />
              <TextField
                fullWidth
                label="密码"
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={tab === TAB_LOGIN ? 'current-password' : 'new-password'}
                size="small"
                helperText={tab === TAB_REGISTER ? '至少 8 字符' : ' '}
                InputProps={{
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton size="small" onClick={() => setShowPw((v) => !v)} edge="end">
                        {showPw ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
              />

              <Button
                type="submit"
                variant="contained"
                disabled={busy || !email || !password}
                size="large"
                sx={{ textTransform: 'none', fontWeight: 600 }}
              >
                {busy ? '处理中…' : (tab === TAB_LOGIN ? '登入' : '注册并登入')}
              </Button>
            </Stack>
          </form>

          <Divider sx={{ my: 3, borderColor: 'rgba(255,255,255,0.06)' }} />

          {/* Admin / API token backdoor */}
          <Box>
            <Button
              variant="text"
              size="small"
              startIcon={<LockIcon />}
              onClick={() => setAdminMode((v) => !v)}
              sx={{ color: 'text.secondary', textTransform: 'none', fontSize: 12 }}
            >
              {adminMode ? '收起' : '用 API Token 登入（管理员后门）'}
            </Button>
            <Collapse in={adminMode}>
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                <Typography variant="caption" color="text.secondary">
                  贴 <code>/opt/quant/.env</code> 里的 <code>API_AUTH_TOKEN</code> 值；
                  用于 admin 紧急 debug，不走 user 登入。
                </Typography>
                {adminError && <Alert severity="error" sx={{ fontSize: 13 }}>{adminError}</Alert>}
                <TextField
                  fullWidth
                  type="password"
                  size="small"
                  placeholder="Bearer token 内容"
                  value={adminToken}
                  onChange={(e) => setAdminToken(e.target.value)}
                />
                <Button
                  variant="outlined"
                  size="small"
                  onClick={submitAdminToken}
                  disabled={adminBusy || !adminToken.trim()}
                  sx={{ textTransform: 'none' }}
                >
                  {adminBusy ? '验证中…' : '解锁 admin'}
                </Button>
              </Stack>
            </Collapse>
          </Box>

          <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', color: 'text.disabled', mt: 3, fontSize: 11 }}>
            Phase 11.1 SaaS 基建 · 仅 admin 可走 LIVE 模式
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}
