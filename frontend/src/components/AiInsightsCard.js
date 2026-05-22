// Phase 11.5.6-8: 整合三個 AI insights — 週復盤 / 個性化建議 / 故障診斷

import React, { useState } from 'react';
import {
  Card, CardContent, Typography, Stack, Button, Chip, Alert, Box,
  CircularProgress, Tabs, Tab,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import ReplayIcon from '@mui/icons-material/Replay';

const FEATURES = [
  { id: 'weekly-review',   label: '週復盤',     icon: '📊', endpoint: '/api/me/weekly-review',   hint: '過去 7 日表現摘要 + 風控異常' },
  { id: 'personal-advice', label: '個性化建議', icon: '🎯', endpoint: '/api/me/personal-advice', hint: '基於你的帳戶/持倉/策略給建議' },
  { id: 'diagnose',        label: '故障診斷',   icon: '🔍', endpoint: '/api/me/diagnose',        hint: '系統怪怪的 / 0 trades 太久時用' },
];

export default function AiInsightsCard() {
  const [tab, setTab] = useState(0);
  const [results, setResults] = useState({});   // { [id]: {ok, text, ...} }
  const [busy, setBusy] = useState({});
  const [errors, setErrors] = useState({});

  const fetchFor = async (idx) => {
    const f = FEATURES[idx];
    setBusy(b => ({ ...b, [f.id]: true }));
    setErrors(e => ({ ...e, [f.id]: null }));
    try {
      const r = await fetch(f.endpoint, { method: 'POST' });
      const body = await r.json();
      if (!r.ok || !body.ok) {
        setErrors(e => ({ ...e, [f.id]: body.error || `HTTP ${r.status}` }));
      } else {
        setResults(s => ({ ...s, [f.id]: body }));
      }
    } catch (e) {
      setErrors(er => ({ ...er, [f.id]: e.message }));
    } finally {
      setBusy(b => ({ ...b, [f.id]: false }));
    }
  };

  const current = FEATURES[tab];
  const result = results[current.id];
  const error = errors[current.id];
  const isBusy = busy[current.id];

  return (
    <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid rgba(167,139,250,0.2)' }}>
      <CardContent sx={{ px: 2.5, py: 2 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <AutoAwesomeIcon sx={{ color: '#a78bfa' }} />
          <Typography variant="h6" fontWeight={700}>AI 洞察</Typography>
          <Chip label="PRO" size="small" color="primary" variant="outlined" />
        </Stack>

        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="fullWidth" sx={{ mb: 2, minHeight: 36 }}>
          {FEATURES.map((f, i) => (
            <Tab key={f.id} value={i} label={<span>{f.icon} {f.label}</span>} sx={{ minHeight: 36, py: 0.5, textTransform: 'none' }} />
          ))}
        </Tabs>

        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
          {current.hint}
        </Typography>

        {!result && !error && !isBusy && (
          <Button
            variant="outlined"
            startIcon={<AutoAwesomeIcon />}
            onClick={() => fetchFor(tab)}
            sx={{ color: '#a78bfa', borderColor: '#a78bfa', textTransform: 'none' }}
          >
            ✨ 生成 {current.label}
          </Button>
        )}

        {isBusy && (
          <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 2 }}>
            <CircularProgress size={20} />
            <Typography variant="body2" color="text.secondary">
              LLM 思考中…（10-30 秒；首次跑較慢，後續同類 cache 命中即時）
            </Typography>
          </Stack>
        )}

        {error && !isBusy && (
          <Alert severity="error" onClose={() => setErrors(e => ({ ...e, [current.id]: null }))}
            action={
              <Button size="small" onClick={() => fetchFor(tab)} startIcon={<ReplayIcon fontSize="small" />}>
                重試
              </Button>
            }>
            {error}
          </Alert>
        )}

        {result && !isBusy && (
          <Box>
            <Stack direction="row" spacing={1} sx={{ mb: 1, flexWrap: 'wrap', gap: 0.5 }}>
              <Chip size="small" label={result.provider_used} variant="outlined" />
              <Chip size="small" label={result.model_used} variant="outlined" />
              {result.cached && <Chip size="small" label="缓存命中" color="success" variant="outlined" />}
              {result.latency_ms != null && <Chip size="small" label={`${result.latency_ms} ms`} variant="outlined" />}
              <Box sx={{ flexGrow: 1 }} />
              <Button size="small" onClick={() => fetchFor(tab)} startIcon={<ReplayIcon fontSize="small" />} sx={{ textTransform: 'none' }}>
                重新生成
              </Button>
            </Stack>
            <Box sx={{
              p: 2, borderRadius: 1, bgcolor: 'rgba(251,191,36,0.04)',
              border: '1px solid rgba(251,191,36,0.15)',
            }}>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.75 }}>
                {result.text}
              </Typography>
            </Box>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
