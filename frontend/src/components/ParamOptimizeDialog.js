import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Box, Typography, LinearProgress, Alert, Table, TableHead, TableBody,
  TableRow, TableCell, Chip, IconButton, Tooltip,
} from '@mui/material';
import TuneIcon from '@mui/icons-material/Tune';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';

const API = process.env.REACT_APP_API_URL || '';

function fmtNum(v, d = 2) {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(d);
}

function paramsToStr(p) {
  if (!p) return '—';
  return Object.entries(p).map(([k, v]) => `${k}=${v}`).join(' ');
}

/**
 * Phase 10.2 参数优化 Modal。
 * Props:
 *   open, onClose, strategy, onApplied(newParams)
 */
export default function ParamOptimizeDialog({ open, onClose, strategy, onApplied }) {
  const [latest, setLatest] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const [applying, setApplying] = useState(null);  // params 字串当 key
  const pollRef = useRef(null);

  const fetchLatest = useCallback(async () => {
    if (!strategy) return;
    try {
      const r = await fetch(`${API}/api/strategies/${strategy.id}/optimize/latest`);
      if (r.status === 404) {
        setLatest(null);
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setLatest(body);
    } catch (e) {
      setError(e.message);
    }
  }, [strategy]);

  // 打开时拉一次，并在 running 时启动轮询
  useEffect(() => {
    if (!open) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    setError(null);
    fetchLatest();
  }, [open, fetchLatest]);

  useEffect(() => {
    if (!open) return;
    const isRunning = latest && (latest.status === 'pending' || latest.status === 'running');
    if (isRunning && !pollRef.current) {
      pollRef.current = setInterval(fetchLatest, 4000);
    } else if (!isRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [open, latest, fetchLatest]);

  const startOptimize = async () => {
    setStarting(true);
    setError(null);
    try {
      const r = await fetch(`${API}/api/strategies/${strategy.id}/optimize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_combos: 24 }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
      await fetchLatest();
    } catch (e) {
      setError(e.message);
    } finally {
      setStarting(false);
    }
  };

  const applyParams = async (params, optimizationId) => {
    if (!window.confirm(`套用此參數到「${strategy.name}」？\n${paramsToStr(params)}\n\n建議套用後重新跑健康檢查。`)) return;
    setApplying(JSON.stringify(params));
    try {
      const r = await fetch(`${API}/api/strategies/${strategy.id}/apply-params`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params, optimization_id: optimizationId }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
      onApplied && onApplied(params);
    } catch (e) {
      setError(`套用失敗：${e.message}`);
    } finally {
      setApplying(null);
    }
  };

  const isRunning = latest && (latest.status === 'pending' || latest.status === 'running');
  const isCompleted = latest && latest.status === 'completed';
  const results = (latest?.candidate_results || []).filter(r => !r.error);
  const baselineKey = latest ? JSON.stringify(latest.baseline_params || {}) : '';

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <TuneIcon sx={{ color: '#22d3ee' }} />
        參數網格搜尋
        {strategy && (
          <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
            {strategy.name} · {strategy.symbol} · {strategy.timeframe}
          </Typography>
        )}
      </DialogTitle>
      <DialogContent dividers>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <Alert severity="info" sx={{ mb: 2, py: 0.5 }}>
          每組參數跑一次 walk-forward（IS 70% / OOS 30%）。按 <strong>OOS Sharpe</strong> 排序 —
          那才是真正的樣本外表現。IS Sharpe 大但 OOS 衰減 {'>'} 50% 通常是過擬合。
        </Alert>

        {!latest && !loading && (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              尚未跑過優化。點下方按鈕開始。
            </Typography>
            <Button
              variant="contained"
              startIcon={<PlayArrowIcon />}
              onClick={startOptimize}
              disabled={starting}
              sx={{ bgcolor: '#22d3ee', '&:hover': { bgcolor: '#0891b2' } }}
            >
              {starting ? '啟動中…' : '開始優化（背景跑數分鐘）'}
            </Button>
          </Box>
        )}

        {latest && (
          <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                <Chip
                  label={
                    latest.status === 'completed' ? '已完成' :
                    latest.status === 'running' ? '執行中' :
                    latest.status === 'error' ? '錯誤' : latest.status
                  }
                  color={
                    latest.status === 'completed' ? 'success' :
                    latest.status === 'error' ? 'error' : 'info'
                  }
                  size="small"
                />
                <Typography variant="caption" color="text.secondary">
                  進度 {latest.combos_done}/{latest.combos_total}
                </Typography>
                {latest.baseline_oos_sharpe !== null && latest.baseline_oos_sharpe !== undefined && (
                  <Typography variant="caption" color="text.secondary">
                    · 基線 OOS Sharpe = <strong>{fmtNum(latest.baseline_oos_sharpe)}</strong>
                  </Typography>
                )}
                {latest.best_oos_sharpe !== null && latest.best_oos_sharpe !== undefined && (
                  <Typography variant="caption" sx={{ color: '#22d3ee' }}>
                    · 最佳 OOS Sharpe = <strong>{fmtNum(latest.best_oos_sharpe)}</strong>
                  </Typography>
                )}
              </Box>
              {(latest.status === 'completed' || latest.status === 'error') && (
                <Button size="small" variant="outlined" startIcon={<PlayArrowIcon />} onClick={startOptimize} disabled={starting}>
                  重跑
                </Button>
              )}
            </Box>

            {isRunning && (
              <LinearProgress
                variant={latest.combos_total > 0 ? 'determinate' : 'indeterminate'}
                value={latest.combos_total > 0 ? (latest.combos_done / latest.combos_total) * 100 : 0}
                sx={{ mb: 2 }}
              />
            )}

            {latest.error_message && (
              <Alert severity="error" sx={{ mb: 2 }}>{latest.error_message}</Alert>
            )}

            {isCompleted && results.length === 0 && (
              <Alert severity="warning">所有組合的 OOS Sharpe 都無效（樣本太少或行情無波動）。</Alert>
            )}

            {results.length > 0 && (
              <Table size="small" sx={{ mt: 1, '& td, & th': { fontSize: 12, py: 0.5 } }}>
                <TableHead>
                  <TableRow>
                    <TableCell>排名</TableCell>
                    <TableCell>參數</TableCell>
                    <TableCell align="right">OOS Sharpe</TableCell>
                    <TableCell align="right">IS Sharpe</TableCell>
                    <TableCell align="right">衰減</TableCell>
                    <TableCell align="right">OOS 交易</TableCell>
                    <TableCell align="right">OOS 年化%</TableCell>
                    <TableCell align="right">OOS MaxDD%</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {results.slice(0, 15).map((r, idx) => {
                    const isBaseline = JSON.stringify(r.params) === baselineKey;
                    const oos = r.oos_sharpe;
                    const decay = r.decay_pct;
                    const overfit = decay !== null && decay !== undefined && decay > 50;
                    return (
                      <TableRow key={idx} sx={{ bgcolor: idx === 0 ? 'rgba(34,211,238,0.08)' : 'transparent' }}>
                        <TableCell>
                          {idx === 0 ? <CheckCircleIcon sx={{ color: '#22d3ee', fontSize: 16, verticalAlign: 'middle' }} /> : (idx + 1)}
                        </TableCell>
                        <TableCell>
                          <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                            {paramsToStr(r.params)}
                          </Typography>
                          {isBaseline && <Chip label="目前" size="small" sx={{ ml: 0.5, height: 16, fontSize: 9 }} />}
                        </TableCell>
                        <TableCell align="right" sx={{ fontWeight: 600, color: oos > 1 ? '#22c55e' : oos < 0 ? '#ef4444' : 'text.primary' }}>
                          {fmtNum(oos)}
                        </TableCell>
                        <TableCell align="right">{fmtNum(r.is_sharpe)}</TableCell>
                        <TableCell align="right" sx={{ color: overfit ? '#f59e0b' : 'text.secondary' }}>
                          {decay === null || decay === undefined ? '—' : `${decay}%`}
                          {overfit && <Tooltip title="OOS 衰減 > 50%，疑似過擬合"><span> ⚠️</span></Tooltip>}
                        </TableCell>
                        <TableCell align="right">{r.oos_trades ?? '—'}</TableCell>
                        <TableCell align="right">{fmtNum(r.oos_ar)}</TableCell>
                        <TableCell align="right">{fmtNum(r.oos_maxdd)}</TableCell>
                        <TableCell align="right">
                          {!isBaseline && oos !== null && oos !== undefined && (
                            <Button
                              size="small"
                              variant="outlined"
                              disabled={!!applying}
                              onClick={() => applyParams(r.params, latest.id)}
                              sx={{ fontSize: 10, minWidth: 60 }}
                            >
                              {applying === JSON.stringify(r.params) ? '套用…' : '套用'}
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>關閉</Button>
      </DialogActions>
    </Dialog>
  );
}
