// Phase 11.1.5: 把舊的 Bearer-token Dialog 換成完整 Login 頁（email/password + admin token fallback）

import React, { useEffect, useState } from 'react';
import { Box, Typography } from '@mui/material';
import { verifyToken, onUnauthorized } from '../auth';
import Login from '../pages/Login';

export default function AuthGate({ children }) {
  const [state, setState] = useState('checking');  // checking / ok / locked

  const doVerify = async () => {
    const r = await verifyToken();
    if (!r.enabled || r.ok) {
      setState('ok');
    } else {
      setState('locked');
    }
  };

  useEffect(() => {
    doVerify();
    const unsub = onUnauthorized(() => setState('locked'));
    return unsub;
  }, []);

  if (state === 'checking') {
    return (
      <Box sx={{ p: 8, textAlign: 'center', color: 'text.secondary' }}>
        <Typography>正在验证身份…</Typography>
      </Box>
    );
  }

  if (state === 'locked') {
    return <Login onLoggedIn={() => setState('ok')} />;
  }

  return children;
}
