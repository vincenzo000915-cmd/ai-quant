// Phase 11.5.1: BYO LLM API key 綁定（Anthropic / OpenAI / Gemini）— Settings 頁卡片

import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, CardContent, Typography, Stack, TextField, Button, Alert, Chip,
  Box, Switch, FormControlLabel, IconButton, InputAdornment, Tooltip,
  Accordion, AccordionSummary, AccordionDetails,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import VerifiedIcon from '@mui/icons-material/Verified';
import LinkOffIcon from '@mui/icons-material/LinkOff';
import ScienceIcon from '@mui/icons-material/Science';
import SaveIcon from '@mui/icons-material/Save';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

const PROVIDERS = [
  {
    id: 'anthropic',
    name: 'Anthropic Claude',
    desc: '推薦：質量穩、prompt 還原度高',
    keyHint: 'sk-ant-...',
    signupUrl: 'https://console.anthropic.com/settings/keys',
  },
  {
    id: 'openai',
    name: 'OpenAI GPT',
    desc: '快、便宜（gpt-4o-mini）',
    keyHint: 'sk-...',
    signupUrl: 'https://platform.openai.com/api-keys',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    desc: '免費 quota 大；質量參差',
    keyHint: 'AIzaSy...',
    signupUrl: 'https://aistudio.google.com/apikey',
  },
];

export default function LlmBindingCard() {
  const [bound, setBound] = useState({});

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/me/llm');
      const data = await r.json();
      setBound(data.bound || {});
    } catch (e) {
      console.error('载入 LLM 状态失败', e);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <AutoAwesomeIcon sx={{ color: 'primary.main' }} />
          <Typography variant="h6">AI Features · BYO LLM Key</Typography>
          <Chip label="PRO" size="small" color="warning" variant="outlined" />
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          綁定您自己的 LLM API key 解鎖 7 個 AI 功能（策略解釋 / 生成 / regime 解讀 / 復盤 / 個性化建議 / 故障診斷 / 策略翻譯）。
          Token 費用由您自己付給 provider — 我們不轉手。Key 用 AES-256 (Fernet) 加密存 DB。
        </Typography>

        {PROVIDERS.map((p) => (
          <ProviderRow key={p.id} provider={p} state={bound[p.id]} onChange={load} />
        ))}
      </CardContent>
    </Card>
  );
}

function ProviderRow({ provider, state, onChange }) {
  const [editing, setEditing] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [testResult, setTestResult] = useState(null);

  const handleSave = async () => {
    if (!apiKey.trim()) {
      setMsg({ type: 'error', text: 'API Key 必填' });
      return;
    }
    setBusy(true);
    try {
      const r = await fetch(`/api/me/llm/${provider.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey.trim() }),
      });
      const body = await r.json();
      if (!r.ok) {
        setMsg({ type: 'error', text: body.error || `HTTP ${r.status}` });
      } else {
        setMsg({ type: 'success', text: '已保存。建議點「測試」驗證 key 有效。' });
        setEditing(false);
        setApiKey('');
        await onChange();
      }
    } finally { setBusy(false); }
  };

  const handleTest = async () => {
    setBusy(true);
    setTestResult(null);
    try {
      const r = await fetch(`/api/me/llm/${provider.id}/test`, { method: 'POST' });
      const body = await r.json();
      setTestResult(body);
      if (body.ok) await onChange();
    } finally { setBusy(false); }
  };

  const handleToggle = async (is_active) => {
    setBusy(true);
    try {
      await fetch(`/api/me/llm/${provider.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active }),
      });
      await onChange();
    } finally { setBusy(false); }
  };

  const handleDelete = async () => {
    if (!window.confirm(`确定解绑 ${provider.name}？`)) return;
    setBusy(true);
    try {
      await fetch(`/api/me/llm/${provider.id}`, { method: 'DELETE' });
      setTestResult(null);
      await onChange();
    } finally { setBusy(false); }
  };

  const bound = !!state;
  const verified = bound && !!state.verified_at;

  return (
    <Accordion
      defaultExpanded={bound}
      sx={{
        mb: 1,
        bgcolor: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.06)',
        boxShadow: 'none',
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" alignItems="center" spacing={1.5} sx={{ width: '100%', flexWrap: 'wrap' }}>
          <Typography variant="subtitle1" fontWeight={600}>{provider.name}</Typography>
          {bound ? (
            <>
              <Chip
                size="small"
                label={state.is_active ? '已启用' : '已停用'}
                color={state.is_active ? 'success' : 'default'}
                variant="outlined"
              />
              {verified && (
                <Tooltip title={`已验证 ${state.verified_at}`}>
                  <VerifiedIcon sx={{ color: 'success.main', fontSize: 16 }} />
                </Tooltip>
              )}
              {!verified && bound && (
                <Chip size="small" label="未验证" color="warning" variant="outlined" />
              )}
            </>
          ) : (
            <Chip size="small" label="未綁定" variant="outlined" />
          )}
          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11 }}>
            {provider.desc}
          </Typography>
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        {msg && <Alert severity={msg.type} sx={{ mb: 2 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}

        {!bound && !editing && (
          <Stack spacing={1.5}>
            <Typography variant="caption" color="text.secondary">
              申請 API Key：<a href={provider.signupUrl} target="_blank" rel="noreferrer" style={{ color: '#06b6d4' }}>
                {provider.signupUrl}
              </a>
            </Typography>
            <Button variant="contained" size="small" onClick={() => setEditing(true)}>
              綁定 {provider.name} Key
            </Button>
          </Stack>
        )}

        {bound && !editing && (
          <Stack spacing={1.5}>
            <Box>
              <Typography variant="body2" sx={{ mb: 0.5 }}>
                API Key: <code>{state.api_key_masked}</code>
              </Typography>
              <Typography variant="caption" color="text.secondary">
                优先级 {state.priority} · 本月用量 {(state.monthly_input_tokens || 0).toLocaleString()} in /
                {(state.monthly_output_tokens || 0).toLocaleString()} out tokens
              </Typography>
              {state.last_error && (
                <Alert severity="warning" sx={{ mt: 1, fontSize: 12 }}>
                  上次错误：{state.last_error.substring(0, 150)}
                </Alert>
              )}
            </Box>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
              <Button size="small" variant="outlined" startIcon={<ScienceIcon />} onClick={handleTest} disabled={busy}>
                测试
              </Button>
              <Button size="small" variant="outlined" onClick={() => setEditing(true)} disabled={busy}>
                更新 Key
              </Button>
              <FormControlLabel
                control={<Switch checked={!!state.is_active} onChange={(e) => handleToggle(e.target.checked)} size="small" disabled={busy} />}
                label={<Typography variant="body2">启用</Typography>}
              />
              <Button size="small" variant="outlined" color="error" startIcon={<LinkOffIcon />} onClick={handleDelete} disabled={busy}>
                解绑
              </Button>
            </Stack>
          </Stack>
        )}

        {editing && (
          <Stack spacing={1.5}>
            <TextField
              fullWidth size="small"
              label="API Key"
              placeholder={provider.keyHint}
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton size="small" onClick={() => setShowKey(v => !v)}>
                      {showKey ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                    </IconButton>
                  </InputAdornment>
                ),
              }}
            />
            <Stack direction="row" spacing={1}>
              <Button variant="contained" size="small" startIcon={<SaveIcon />} onClick={handleSave} disabled={busy || !apiKey.trim()}>
                保存
              </Button>
              <Button variant="text" size="small" onClick={() => { setEditing(false); setApiKey(''); setMsg(null); }} disabled={busy}>
                取消
              </Button>
            </Stack>
          </Stack>
        )}

        {testResult && (
          <Alert severity={testResult.ok ? 'success' : 'error'} sx={{ mt: 2 }}>
            {testResult.ok
              ? `OK — ${testResult.model_pinged ? `model=${testResult.model_pinged}` : '验证通过'}`
              : `失败：${(testResult.error || '').substring(0, 200)}`}
          </Alert>
        )}
      </AccordionDetails>
    </Accordion>
  );
}
