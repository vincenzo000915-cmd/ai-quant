// Phase 11.5.10: AI 看現有策略 + 表現 + regime → 主動建議補完性新策略

import React, { useEffect, useState } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, Box,
  Typography, CircularProgress, Alert, Chip, Stack, Link, Divider, List, ListItem,
  ListItemText, ListItemIcon,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import LightbulbIcon from '@mui/icons-material/Lightbulb';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import CloseIcon from '@mui/icons-material/Close';

export default function ImproveStrategiesDialog({ open, onClose, onCreated }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setResult(null);
    setError(null);
    (async () => {
      try {
        const r = await fetch('/api/me/improve-strategies', { method: 'POST' });
        const body = await r.json();
        if (!r.ok || !body.ok) setError({ status: r.status, body });
        else { setResult(body); onCreated?.(body); }
      } catch (e) { setError({ status: 0, body: { error: e.message } }); }
      finally { setLoading(false); }
    })();
  }, [open, onCreated]);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Stack direction="row" alignItems="center" spacing={1}>
          <LightbulbIcon sx={{ color: '#a78bfa' }} />
          <Typography variant="h6">AI 策略改进建议</Typography>
          <Chip label="PRO · 闭环" size="small" color="warning" variant="outlined" />
        </Stack>
        <Typography variant="caption" color="text.secondary">
          AI 看你現有策略 + 7 日表現 + 當前 regime → 主動建議補完性新策略 → 自動進候選池等回測 + auto promote
        </Typography>
      </DialogTitle>

      <DialogContent>
        {loading && (
          <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 4 }}>
            <CircularProgress size={20} />
            <Typography variant="body2" color="text.secondary">
              LLM 分析現有策略 + 生成 1-3 個補完性候選 + 沙箱驗證…（20-60 秒）
            </Typography>
          </Stack>
        )}

        {error && (
          <Alert severity={error.status === 402 ? 'warning' : 'error'}>
            <Typography variant="body2">{error.body.error || `HTTP ${error.status}`}</Typography>
            {error.body.upgrade_hint && (
              <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>
                {error.body.upgrade_hint}
              </Typography>
            )}
          </Alert>
        )}

        {result && (
          <Stack spacing={2.5}>
            <Box>
              <Typography variant="overline" color="text.secondary">分析</Typography>
              <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                {result.analysis}
              </Typography>
            </Box>

            {result.generated?.length > 0 && (
              <Box>
                <Typography variant="overline" color="text.secondary">
                  生成 {result.generated.length} 個新候選（沙箱驗證通過 ✓）
                </Typography>
                <List dense sx={{ mt: 0.5 }}>
                  {result.generated.map((g) => (
                    <ListItem
                      key={g.candidate_id}
                      sx={{
                        bgcolor: 'rgba(0,212,170,0.06)',
                        border: '1px solid rgba(0,212,170,0.2)',
                        borderRadius: 1, mb: 1, py: 1.5, alignItems: 'flex-start',
                      }}
                    >
                      <ListItemIcon sx={{ minWidth: 32, mt: 0.5 }}>
                        <CheckCircleIcon sx={{ color: 'success.main', fontSize: 18 }} />
                      </ListItemIcon>
                      <ListItemText
                        primary={
                          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', alignItems: 'center', mb: 0.5 }}>
                            <Typography variant="body2" fontWeight={600}>
                              #{g.candidate_id} {g.candidate_type}
                            </Typography>
                            <Chip size="small" label={g.category} variant="outlined" />
                            <Chip size="small" label={g.timeframe} variant="outlined" />
                          </Stack>
                        }
                        secondary={
                          <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                            {g.rationale}
                          </Typography>
                        }
                      />
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}

            {result.rejected?.length > 0 && (
              <Box>
                <Typography variant="overline" color="text.secondary">
                  被拒絕 {result.rejected.length} 個（沙箱失敗 / 重複類型）
                </Typography>
                <List dense>
                  {result.rejected.map((r, i) => (
                    <ListItem key={i} sx={{ py: 0.5 }}>
                      <ListItemIcon sx={{ minWidth: 28 }}>
                        <ErrorIcon sx={{ color: 'error.main', fontSize: 16 }} />
                      </ListItemIcon>
                      <ListItemText
                        primary={<Typography variant="caption">{r.candidate_type || '(no type)'}: {r.reason}</Typography>}
                      />
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}

            <Divider />

            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
              <Chip size="small" label={result.llm_meta?.provider_used} variant="outlined" />
              <Chip size="small" label={result.llm_meta?.model_used} variant="outlined" />
              {result.llm_meta?.latency_ms != null && (
                <Chip size="small" label={`${result.llm_meta.latency_ms} ms`} variant="outlined" />
              )}
            </Stack>

            {result.generated?.length > 0 && (
              <Alert severity="info" sx={{ fontSize: 12 }}>
                <Typography variant="caption" sx={{ display: 'block' }}>
                  <b>閉環下一步</b>（已自動接管）：
                </Typography>
                <Typography variant="caption" component="ol" sx={{ pl: 2, mt: 0.5 }}>
                  <li>候選池 cron 自動跑回測（walk-forward + OOS Sharpe）</li>
                  <li>OOS Sharpe ≥ 1.5 → status='qualified'</li>
                  <li>auto_promote cron 把 qualified 推上線 → strategies 表 status='stopped'</li>
                  <li>advisor auto_apply 篩 OOS Sharpe 最好的 → status='running'</li>
                  <li>Celery beat 拉信號 → LIVE 真實下單到 OKX</li>
                </Typography>
                <Link href="/candidates" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, mt: 1, fontSize: 12 }}>
                  去候選池看 → <OpenInNewIcon sx={{ fontSize: 12 }} />
                </Link>
              </Alert>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} startIcon={<CloseIcon />}>关闭</Button>
      </DialogActions>
    </Dialog>
  );
}
