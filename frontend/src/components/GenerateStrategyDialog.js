// Phase 11.5.4: AI 自然語言 → 策略生成 Dialog

import React, { useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField,
  Typography, CircularProgress, Alert, Chip, Stack, Box, Link,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';

const EXAMPLES = [
  '結合 RSI 反向 + 布林帶擠壓的短線多策略',
  '用 200 MA 趨勢過濾 + ADX > 25 的波段跟隨',
  'VWAP 跌破 1.5%（hot zone）做空，反彈 0.5% 平倉',
];

export default function GenerateStrategyDialog({ open, onClose, onCreated }) {
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!description.trim()) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const r = await fetch('/api/strategies/ai-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: description.trim() }),
      });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setError({ status: r.status, body });
      } else {
        setResult(body);
        onCreated?.(body);
      }
    } catch (e) {
      setError({ status: 0, body: { error: e.message } });
    } finally { setBusy(false); }
  };

  const reset = () => {
    setDescription('');
    setResult(null);
    setError(null);
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Stack direction="row" alignItems="center" spacing={1}>
          <AutoAwesomeIcon sx={{ color: '#fbbf24' }} />
          <Typography variant="h6">AI 生成策略</Typography>
          <Chip label="PRO" size="small" color="warning" variant="outlined" />
        </Stack>
        <Typography variant="caption" color="text.secondary">
          用自然語言描述你想要的策略邏輯，LLM 會生成 signal function 並沙箱驗證
        </Typography>
      </DialogTitle>

      <DialogContent>
        {!result && !error && (
          <Stack spacing={2}>
            <TextField
              fullWidth
              multiline
              minRows={3}
              maxRows={8}
              label="策略描述"
              placeholder="例：用 RSI 反向 + 布林帶擠壓的短線多策略，4H 框架，RSI<30 + 帶寬<5% 觸發 buy，>70 觸發 sell"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={busy}
              helperText={`${description.length} / 2000 字符`}
            />
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                範例（點擊填入）：
              </Typography>
              <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
                {EXAMPLES.map((ex, i) => (
                  <Chip
                    key={i}
                    size="small"
                    label={ex.length > 30 ? ex.substring(0, 30) + '…' : ex}
                    onClick={() => setDescription(ex)}
                    disabled={busy}
                    clickable
                    sx={{ fontSize: 11 }}
                  />
                ))}
              </Stack>
            </Box>
            {busy && (
              <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 2 }}>
                <CircularProgress size={20} />
                <Typography variant="body2" color="text.secondary">
                  LLM 思考 + 沙箱驗證中…（10-30 秒）
                </Typography>
              </Stack>
            )}
          </Stack>
        )}

        {error && (
          <Stack spacing={2}>
            <Alert severity={error.status === 402 ? 'warning' : 'error'}>
              <Typography variant="body2">
                {error.body.error || `HTTP ${error.status}`}
              </Typography>
              {error.body.upgrade_hint && (
                <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>
                  {error.body.upgrade_hint}
                </Typography>
              )}
              {error.body.verify?.error && (
                <Typography variant="caption" sx={{ display: 'block', mt: 1, fontFamily: 'monospace' }}>
                  sandbox: {error.body.verify.error}
                </Typography>
              )}
            </Alert>
            {error.body.raw_output && (
              <Box>
                <Typography variant="caption" color="text.secondary">LLM 原始輸出（截斷）：</Typography>
                <Box sx={{
                  mt: 1, p: 1, bgcolor: 'rgba(0,0,0,0.4)', borderRadius: 1,
                  fontFamily: 'monospace', fontSize: 11, maxHeight: 200, overflow: 'auto',
                }}>
                  {error.body.raw_output}
                </Box>
              </Box>
            )}
            <Button onClick={reset} variant="outlined" size="small">重試</Button>
          </Stack>
        )}

        {result && (
          <Stack spacing={2}>
            <Alert severity="success">
              <Typography variant="body2">
                <b>✅ 策略已生成並寫入候選池</b>
              </Typography>
              <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                candidate_id = {result.candidate_id} · {result.candidate?.candidate_type}
              </Typography>
            </Alert>

            <Box>
              <Typography variant="overline" color="text.secondary">LLM Notes</Typography>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                {result.candidate?.llm_notes}
              </Typography>
            </Box>

            <Box>
              <Typography variant="overline" color="text.secondary">配置</Typography>
              <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
                <Chip size="small" label={`category: ${result.candidate?.category}`} />
                <Chip size="small" label={`timeframe: ${result.candidate?.timeframe}`} />
                <Chip size="small" label={`fn: ${result.candidate?.signal_fn_name}`} />
              </Stack>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                default_params: <code>{JSON.stringify(result.candidate?.default_params)}</code>
              </Typography>
            </Box>

            <Stack direction="row" spacing={1}>
              <Chip size="small" label={`${result.llm_meta?.provider_used}`} variant="outlined" />
              <Chip size="small" label={`${result.llm_meta?.model_used}`} variant="outlined" />
              {result.llm_meta?.latency_ms != null && (
                <Chip size="small" label={`${result.llm_meta.latency_ms} ms`} variant="outlined" />
              )}
            </Stack>

            <Alert severity="info" sx={{ fontSize: 12 }}>
              下一步：到 <Link href="/candidates" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                候選池頁 <OpenInNewIcon sx={{ fontSize: 14 }} />
              </Link> 給這個 candidate 跑回測，OOS Sharpe 夠就 promote 到策略表。
            </Alert>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        {!result && !error && (
          <>
            <Button onClick={onClose} disabled={busy}>取消</Button>
            <Button onClick={submit} variant="contained" disabled={busy || !description.trim()}
              startIcon={busy ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}>
              {busy ? '生成中…' : '生成'}
            </Button>
          </>
        )}
        {(result || error) && (
          <Button onClick={() => { reset(); onClose(); }} variant="contained">关闭</Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
