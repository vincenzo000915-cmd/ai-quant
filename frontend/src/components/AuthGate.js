import React, { useEffect, useState } from 'react';
import { Box, Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, Typography, Alert, Stack } from '@mui/material';
import LockIcon from '@mui/icons-material/Lock';
import { getToken, setToken, verifyToken, onUnauthorized } from '../auth';

/**
 * 包住整個 App 的鉴权閘門。
 * - 啟動先打 /api/auth/check 驗 token
 * - 401 / 未設定 → 彈框要求輸入
 * - 設定後存 localStorage、重新 verify
 */
export default function AuthGate({ children }) {
  const [state, setState] = useState('checking');  // checking / ok / locked
  const [input, setInput] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const doVerify = async () => {
    const r = await verifyToken();
    if (!r.enabled || r.ok) {
      setState('ok');
    } else {
      setState('locked');
      setInput(getToken() || '');
    }
  };

  useEffect(() => {
    doVerify();
    const unsub = onUnauthorized(() => setState('locked'));
    return unsub;
  }, []);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setToken(input.trim());
    const r = await verifyToken();
    if (r.ok) {
      setState('ok');
    } else {
      setError('token 無效，再試一次');
    }
    setBusy(false);
  };

  if (state === 'checking') {
    return (
      <Box sx={{ p: 8, textAlign: 'center', color: 'text.secondary' }}>
        <Typography>驗證 token…</Typography>
      </Box>
    );
  }

  return (
    <>
      {children}
      <Dialog open={state === 'locked'} maxWidth="xs" fullWidth disableEscapeKeyDown>
        <DialogTitle>
          <Stack direction="row" alignItems="center" spacing={1}>
            <LockIcon color="warning" />
            <span>API 鉴权</span>
          </Stack>
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Phase 8.1 起所有 mutating endpoint 要 Bearer token。
            從 <code>/opt/quant/.env</code> 拿 <code>API_AUTH_TOKEN</code> 值貼進來。
          </Typography>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <TextField
            autoFocus
            fullWidth
            label="API Token"
            type="password"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
            placeholder="Bearer token 內容"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={submit} disabled={busy || !input.trim()} variant="contained">
            {busy ? '驗證中…' : '解鎖'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
