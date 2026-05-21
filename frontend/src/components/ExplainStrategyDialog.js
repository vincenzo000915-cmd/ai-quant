// Phase 11.5.3: AI 策略解釋 Dialog

import React, { useEffect, useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, Box,
  Typography, CircularProgress, Alert, Chip, Stack, Link,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import CloseIcon from '@mui/icons-material/Close';

export default function ExplainStrategyDialog({ open, strategy, onClose }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open || !strategy) return;
    setLoading(true);
    setResult(null);
    setError(null);
    (async () => {
      try {
        const r = await fetch(`/api/strategies/${strategy.id}/explain`, { method: 'POST' });
        const body = await r.json();
        if (!r.ok) {
          setError({ status: r.status, body });
        } else {
          setResult(body);
        }
      } catch (e) {
        setError({ status: 0, body: { error: e.message } });
      } finally { setLoading(false); }
    })();
  }, [open, strategy]);

  // 渲染 markdown-ish 文本（簡單版：**粗體** → <b>，換行保留）
  const renderText = (text) => {
    if (!text) return null;
    // 切 **bold** 區段
    const parts = text.split(/(\*\*[^*]+\*\*)/g);
    return parts.map((p, i) => {
      if (p.startsWith('**') && p.endsWith('**')) {
        return <b key={i}>{p.slice(2, -2)}</b>;
      }
      return <span key={i}>{p}</span>;
    });
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Stack direction="row" alignItems="center" spacing={1}>
          <AutoAwesomeIcon sx={{ color: 'primary.main' }} />
          <Typography variant="h6">AI 解读 · {strategy?.name || ''}</Typography>
        </Stack>
        <Typography variant="caption" color="text.secondary">
          {strategy?.symbol} · {strategy?.timeframe} · {strategy?.type}
        </Typography>
      </DialogTitle>
      <DialogContent>
        {loading && (
          <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 4 }}>
            <CircularProgress size={20} />
            <Typography variant="body2" color="text.secondary">
              LLM 思考中…（首次约 5-10 秒，缓存命中即时返回）
            </Typography>
          </Stack>
        )}

        {error && (
          <Box>
            {error.status === 402 ? (
              <Alert severity="warning">
                <Typography variant="body2">{error.body.error}</Typography>
                {error.body.upgrade_hint && (
                  <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>
                    {error.body.upgrade_hint}
                  </Typography>
                )}
              </Alert>
            ) : (
              <Alert severity="error">
                <Typography variant="body2">
                  {error.body.error || `HTTP ${error.status}`}
                </Typography>
                {!error.body.text && error.body.error?.includes('未綁定') && (
                  <Link href="/settings" sx={{ display: 'block', mt: 1, fontSize: 13 }}>
                    → 去设置页绑定 LLM Key
                  </Link>
                )}
              </Alert>
            )}
          </Box>
        )}

        {result && result.ok && (
          <Box>
            <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', gap: 0.5 }}>
              <Chip size="small" label={`provider: ${result.provider_used}`} variant="outlined" />
              <Chip size="small" label={`model: ${result.model_used}`} variant="outlined" />
              {result.cached && <Chip size="small" label="缓存命中" color="success" variant="outlined" />}
              {!result.cached && result.usage && (
                <Chip
                  size="small"
                  label={`${result.usage.input_tokens} in / ${result.usage.output_tokens} out tokens`}
                  variant="outlined"
                />
              )}
              {result.latency_ms != null && (
                <Chip size="small" label={`${result.latency_ms} ms`} variant="outlined" />
              )}
            </Stack>
            <Typography
              variant="body2"
              component="div"
              sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, color: 'text.primary' }}
            >
              {renderText(result.text)}
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} startIcon={<CloseIcon />}>关闭</Button>
      </DialogActions>
    </Dialog>
  );
}
