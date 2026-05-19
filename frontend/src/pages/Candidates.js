import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Chip, Button, IconButton,
  Dialog, DialogTitle, DialogContent, DialogActions, Tabs, Tab,
  LinearProgress, Tooltip, Alert, Snackbar, Grid, MenuItem, Select,
  FormControl, InputLabel, TextField, Stack,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import TranslateIcon from '@mui/icons-material/Translate';
import ScienceIcon from '@mui/icons-material/Science';
import CloudDownloadIcon from '@mui/icons-material/CloudDownload';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import BlockIcon from '@mui/icons-material/Block';
import DeleteIcon from '@mui/icons-material/Delete';
import VisibilityIcon from '@mui/icons-material/Visibility';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import GitHubIcon from '@mui/icons-material/GitHub';
import ShowChartIcon from '@mui/icons-material/ShowChart';

const API = process.env.REACT_APP_API_URL || '';

const STATUS_LABELS = {
  pending: { label: '待翻譯', color: 'default' },
  translating: { label: '翻譯中', color: 'info' },
  translated: { label: '已翻譯', color: 'primary' },
  backtesting: { label: '回測中', color: 'info' },
  qualified: { label: '✅ 合格', color: 'success' },
  rejected: { label: '已拒絕', color: 'error' },
  promoted: { label: '🚀 已上線', color: 'success' },
  error: { label: '❌ 錯誤', color: 'warning' },
};

const SOURCE_LABELS = {
  github: { label: 'GitHub', icon: <GitHubIcon fontSize="small" /> },
  tradingview: { label: 'TradingView', icon: <ShowChartIcon fontSize="small" /> },
  manual: { label: '手動', icon: null },
};

const STATUS_FILTERS = ['all', 'pending', 'translated', 'qualified', 'rejected', 'error'];

function fmtNum(v, digits = 2, suffix = '') {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(digits) + suffix;
}

export default function Candidates() {
  const [candidates, setCandidates] = useState([]);
  const [stats, setStats] = useState({ total: 0, by_status: {}, by_source: {} });
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('all');
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [tabIdx, setTabIdx] = useState(0);
  const [busy, setBusy] = useState(null);   // candidate id being processed
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });

  const showMsg = (message, severity = 'success') => setSnackbar({ open: true, message, severity });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (statusFilter !== 'all') params.set('status', statusFilter);
      const [r1, r2] = await Promise.all([
        fetch(`${API}/api/candidates?${params.toString()}`),
        fetch(`${API}/api/candidates/stats`),
      ]);
      setCandidates(await r1.json());
      setStats(await r2.json());
    } catch (e) {
      showMsg(`載入失敗：${e.message}`, 'error');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const openDetail = async (cid) => {
    try {
      const res = await fetch(`${API}/api/candidates/${cid}`);
      if (!res.ok) throw new Error(await res.text());
      setDetail(await res.json());
      setTabIdx(0);
      setDetailOpen(true);
    } catch (e) {
      showMsg(`載入詳情失敗：${e.message}`, 'error');
    }
  };

  const callAction = async (cid, action, method = 'POST', confirmMsg = null) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    setBusy(cid);
    try {
      const res = await fetch(`${API}/api/candidates/${cid}/${action}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || JSON.stringify(body));
      showMsg(`${action} 完成`, 'success');
      await load();
      if (detailOpen && detail && detail.id === cid) await openDetail(cid);
    } catch (e) {
      showMsg(`${action} 失敗：${e.message}`, 'error');
    } finally {
      setBusy(null);
    }
  };

  const deleteCandidate = async (cid) => {
    if (!window.confirm('確認刪除候選？此操作無法復原。')) return;
    setBusy(cid);
    try {
      await fetch(`${API}/api/candidates/${cid}`, { method: 'DELETE' });
      showMsg('已刪除');
      await load();
    } catch (e) {
      showMsg(`刪除失敗：${e.message}`, 'error');
    } finally {
      setBusy(null);
    }
  };

  const crawlGithub = async () => {
    if (!window.confirm('觸發 GitHub 爬蟲？可能需要 1-3 分鐘（首次 clone）。')) return;
    setBusy('crawl');
    try {
      const res = await fetch(`${API}/api/candidates/crawl/github`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || JSON.stringify(body));
      showMsg(`爬蟲完成：新增 ${body.totals.inserted}，跳過 ${body.totals.skipped}`);
      await load();
    } catch (e) {
      showMsg(`爬蟲失敗：${e.message}`, 'error');
    } finally {
      setBusy(null);
    }
  };

  const backtestPending = async () => {
    if (!window.confirm('批次回測所有已翻譯候選？視數量可能 5-30 分鐘。')) return;
    setBusy('bt-pending');
    try {
      const res = await fetch(`${API}/api/candidates/backtest-pending`, {
        method: 'POST',
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || JSON.stringify(body));
      showMsg(`批次回測：共 ${body.count} 個，${body.qualified} 個合格`);
      await load();
    } catch (e) {
      showMsg(`回測失敗：${e.message}`, 'error');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Box>
      {/* Header */}
      <Box sx={{ mb: 3, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Typography variant="h4" fontWeight={800} sx={{ letterSpacing: -0.5 }}>
            候選策略池
          </Typography>
          <Typography variant="body2" color="text.secondary">
            爬蟲 → LLM 翻譯 → 沙箱驗證 → 真實回測 → Promote 上線
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap">
          <Button
            startIcon={<RefreshIcon />}
            onClick={load}
            variant="outlined"
            size="small"
          >
            刷新
          </Button>
          <Button
            startIcon={<CloudDownloadIcon />}
            onClick={crawlGithub}
            variant="outlined"
            color="primary"
            size="small"
            disabled={busy === 'crawl'}
          >
            爬 GitHub
          </Button>
          <Button
            startIcon={<ScienceIcon />}
            onClick={backtestPending}
            variant="contained"
            color="secondary"
            size="small"
            disabled={busy === 'bt-pending' || !(stats.by_status?.translated)}
          >
            批次回測 ({stats.by_status?.translated || 0})
          </Button>
        </Stack>
      </Box>

      {/* Stats */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} sm={3}>
          <StatCard label="總候選" value={stats.total} color="primary" />
        </Grid>
        <Grid item xs={6} sm={3}>
          <StatCard label="待翻譯" value={stats.by_status?.pending || 0} color="default" />
        </Grid>
        <Grid item xs={6} sm={3}>
          <StatCard label="已翻譯" value={stats.by_status?.translated || 0} color="info" />
        </Grid>
        <Grid item xs={6} sm={3}>
          <StatCard label="合格" value={stats.by_status?.qualified || 0} color="success" />
        </Grid>
      </Grid>

      {/* Status filter */}
      <Box sx={{ mb: 2, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        {STATUS_FILTERS.map(s => (
          <Chip
            key={s}
            label={s === 'all' ? `全部 (${stats.total})` : `${STATUS_LABELS[s]?.label || s} (${stats.by_status?.[s] || 0})`}
            color={statusFilter === s ? 'primary' : 'default'}
            variant={statusFilter === s ? 'filled' : 'outlined'}
            onClick={() => setStatusFilter(s)}
            size="small"
          />
        ))}
      </Box>

      {/* Table */}
      <Card>
        {loading && <LinearProgress />}
        <TableContainer component={Paper} sx={{ backgroundColor: 'transparent', boxShadow: 'none' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>ID</TableCell>
                <TableCell>來源</TableCell>
                <TableCell>原策略名稱</TableCell>
                <TableCell>狀態</TableCell>
                <TableCell>類型/TF</TableCell>
                <TableCell align="right">Sharpe</TableCell>
                <TableCell align="right">AR%</TableCell>
                <TableCell align="right">MaxDD%</TableCell>
                <TableCell align="right">交易數</TableCell>
                <TableCell align="right">操作</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {candidates.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={10} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                    候選池為空 — 按 "爬 GitHub" 開始
                  </TableCell>
                </TableRow>
              )}
              {candidates.map(c => {
                const stLabel = STATUS_LABELS[c.status] || { label: c.status, color: 'default' };
                const srcLabel = SOURCE_LABELS[c.source] || { label: c.source };
                const bt = c.backtest;
                return (
                  <TableRow key={c.id} hover>
                    <TableCell>{c.id}</TableCell>
                    <TableCell>
                      <Chip
                        icon={srcLabel.icon}
                        label={srcLabel.label}
                        size="small"
                        variant="outlined"
                        component={c.source_url ? 'a' : 'div'}
                        href={c.source_url || undefined}
                        target={c.source_url ? '_blank' : undefined}
                        clickable={!!c.source_url}
                      />
                    </TableCell>
                    <TableCell>
                      <Tooltip title={c.source_url || ''}>
                        <Typography variant="body2" sx={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {c.source_name || '—'}
                        </Typography>
                      </Tooltip>
                      {c.source_author && (
                        <Typography variant="caption" color="text.secondary">@{c.source_author}</Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip label={stLabel.label} color={stLabel.color} size="small" />
                      {c.error_log && (
                        <Tooltip title={c.error_log}>
                          <Typography variant="caption" color="warning.main" sx={{ display: 'block', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {c.error_log.slice(0, 32)}…
                          </Typography>
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">
                        {c.candidate_type || '—'}
                      </Typography>
                      <Typography variant="caption" sx={{ display: 'block' }}>
                        {c.timeframe || '—'} · {c.category || '—'}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">{fmtNum(bt?.sharpe_ratio, 2)}</TableCell>
                    <TableCell align="right">{fmtNum(bt?.annual_return_pct, 1, '%')}</TableCell>
                    <TableCell align="right">{fmtNum(bt?.max_drawdown_pct, 1, '%')}</TableCell>
                    <TableCell align="right">{bt?.total_trades ?? '—'}</TableCell>
                    <TableCell align="right">
                      <Tooltip title="檢視">
                        <IconButton size="small" onClick={() => openDetail(c.id)}>
                          <VisibilityIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      {c.status === 'pending' && (
                        <Tooltip title="LLM 翻譯">
                          <span>
                            <IconButton
                              size="small"
                              onClick={() => callAction(c.id, 'translate')}
                              disabled={busy === c.id}
                            >
                              <TranslateIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      )}
                      {['translated', 'qualified', 'error'].includes(c.status) && c.signal_fn_name && (
                        <Tooltip title="跑回測">
                          <span>
                            <IconButton
                              size="small"
                              onClick={() => callAction(c.id, 'backtest')}
                              disabled={busy === c.id}
                            >
                              <ScienceIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      )}
                      {c.status === 'qualified' && (
                        <Tooltip title="Promote 上線（Phase 4.6）">
                          <span>
                            <IconButton
                              size="small"
                              color="success"
                              onClick={() => callAction(c.id, 'promote')}
                              disabled={busy === c.id}
                            >
                              <RocketLaunchIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      )}
                      {c.status !== 'rejected' && c.status !== 'promoted' && (
                        <Tooltip title="拒絕">
                          <span>
                            <IconButton
                              size="small"
                              onClick={() => callAction(c.id, 'reject')}
                              disabled={busy === c.id}
                            >
                              <BlockIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      )}
                      <Tooltip title="刪除">
                        <IconButton size="small" onClick={() => deleteCandidate(c.id)} disabled={busy === c.id}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Card>

      {/* Detail Dialog */}
      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} maxWidth="lg" fullWidth>
        {detail && (
          <>
            <DialogTitle>
              <Stack direction="row" spacing={1} alignItems="center">
                <Chip
                  label={SOURCE_LABELS[detail.source]?.label || detail.source}
                  icon={SOURCE_LABELS[detail.source]?.icon}
                  size="small"
                />
                <Typography variant="h6">#{detail.id} · {detail.source_name || '無名'}</Typography>
                <Chip label={STATUS_LABELS[detail.status]?.label || detail.status} color={STATUS_LABELS[detail.status]?.color || 'default'} size="small" />
              </Stack>
              {detail.source_url && (
                <Typography variant="caption" component="a" href={detail.source_url} target="_blank" sx={{ color: 'primary.main', textDecoration: 'none' }}>
                  {detail.source_url}
                </Typography>
              )}
            </DialogTitle>
            <DialogContent dividers>
              <Tabs value={tabIdx} onChange={(_, v) => setTabIdx(v)} sx={{ mb: 2 }}>
                <Tab label="概覽" />
                <Tab label="原始碼" />
                <Tab label="翻譯產物" disabled={!detail.parsed_signal} />
                <Tab label="回測" disabled={!detail.backtest} />
              </Tabs>

              {tabIdx === 0 && (
                <Box>
                  <Grid container spacing={2}>
                    <InfoRow label="ID" value={detail.id} />
                    <InfoRow label="來源 URL" value={detail.source_url || '—'} />
                    <InfoRow label="原作者" value={detail.source_author || '—'} />
                    <InfoRow label="原語言" value={detail.raw_lang || '—'} />
                    <InfoRow label="signal_fn_name" value={detail.signal_fn_name || '—'} />
                    <InfoRow label="candidate_type" value={detail.candidate_type || '—'} />
                    <InfoRow label="分類" value={detail.category || '—'} />
                    <InfoRow label="Timeframe" value={detail.timeframe || '—'} />
                    <InfoRow label="LLM model" value={detail.llm_model || '—'} />
                    <InfoRow label="預設參數" value={JSON.stringify(detail.default_params || {})} />
                    <InfoRow label="建立時間" value={detail.created_at} />
                    <InfoRow label="最後更新" value={detail.updated_at} />
                  </Grid>
                  {detail.llm_notes && (
                    <Box sx={{ mt: 2 }}>
                      <Typography variant="subtitle2" color="text.secondary">LLM 註解</Typography>
                      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mt: 1 }}>{detail.llm_notes}</Typography>
                    </Box>
                  )}
                  {detail.error_log && (
                    <Alert severity="error" sx={{ mt: 2 }}>
                      <Typography variant="caption" sx={{ whiteSpace: 'pre-wrap' }}>{detail.error_log}</Typography>
                    </Alert>
                  )}
                </Box>
              )}

              {tabIdx === 1 && (
                <Paper sx={{ p: 2, bgcolor: 'rgba(0,0,0,0.3)', maxHeight: 500, overflow: 'auto' }}>
                  <pre style={{ margin: 0, fontSize: 12, fontFamily: 'JetBrains Mono, monospace', whiteSpace: 'pre-wrap' }}>
                    {detail.raw_code || '(無原始碼)'}
                  </pre>
                </Paper>
              )}

              {tabIdx === 2 && (
                <Paper sx={{ p: 2, bgcolor: 'rgba(0,0,0,0.3)', maxHeight: 500, overflow: 'auto' }}>
                  <pre style={{ margin: 0, fontSize: 12, fontFamily: 'JetBrains Mono, monospace', whiteSpace: 'pre-wrap' }}>
                    {detail.parsed_signal || '(尚未翻譯)'}
                  </pre>
                </Paper>
              )}

              {tabIdx === 3 && detail.backtest && (
                <Box>
                  <Grid container spacing={2}>
                    <KPICard label="Sharpe" value={fmtNum(detail.backtest.sharpe_ratio, 2)} />
                    <KPICard label="年化報酬" value={fmtNum(detail.backtest.annual_return_pct, 1, '%')} />
                    <KPICard label="最大回撤" value={fmtNum(detail.backtest.max_drawdown_pct, 1, '%')} />
                    <KPICard label="盈虧比" value={fmtNum(detail.backtest.profit_factor, 2)} />
                    <KPICard label="總交易" value={detail.backtest.total_trades} />
                    <KPICard label="勝率" value={fmtNum(detail.backtest.win_rate, 1, '%')} />
                    <KPICard label="總 PnL" value={fmtNum(detail.backtest.total_pnl, 2)} />
                    <KPICard label="最終淨值" value={fmtNum(detail.backtest.final_equity, 2)} />
                  </Grid>
                </Box>
              )}
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setDetailOpen(false)}>關閉</Button>
            </DialogActions>
          </>
        )}
      </Dialog>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity={snackbar.severity}>{snackbar.message}</Alert>
      </Snackbar>
    </Box>
  );
}

function StatCard({ label, value, color }) {
  return (
    <Card>
      <CardContent sx={{ py: 1.5 }}>
        <Typography variant="caption" color="text.secondary">{label}</Typography>
        <Typography variant="h5" fontWeight={700} color={color === 'default' ? 'text.primary' : `${color}.main`}>
          {value}
        </Typography>
      </CardContent>
    </Card>
  );
}

function InfoRow({ label, value }) {
  return (
    <>
      <Grid item xs={4}>
        <Typography variant="caption" color="text.secondary">{label}</Typography>
      </Grid>
      <Grid item xs={8}>
        <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>{value}</Typography>
      </Grid>
    </>
  );
}

function KPICard({ label, value }) {
  return (
    <Grid item xs={6} sm={3}>
      <Card variant="outlined">
        <CardContent sx={{ py: 1.5 }}>
          <Typography variant="caption" color="text.secondary">{label}</Typography>
          <Typography variant="h6" fontWeight={700}>{value}</Typography>
        </CardContent>
      </Card>
    </Grid>
  );
}
