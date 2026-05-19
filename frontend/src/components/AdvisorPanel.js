import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Tooltip, IconButton,
  Alert, LinearProgress, Stack, Collapse, Button, Snackbar,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CheckIcon from '@mui/icons-material/Check';

const API = process.env.REACT_APP_API_URL || '';

const SEVERITY_META = {
  critical: { color: '#ef4444', label: '緊急', bg: 'rgba(239,68,68,0.10)' },
  warn:     { color: '#f59e0b', label: '建議', bg: 'rgba(245,158,11,0.10)' },
  info:     { color: '#22d3ee', label: '機會', bg: 'rgba(34,211,238,0.08)' },
};

const ACTION_META = {
  retire:       { emoji: '🪦', label: '退役', actionable: true,  btn: '退役此策略' },
  pause:        { emoji: '⏸️',  label: '暫停', actionable: true,  btn: '暫停' },
  apply_params: { emoji: '🔧', label: '套用最佳參數', actionable: true, btn: '套用參數' },
  fan_out:      { emoji: '📡', label: '一鍵擴幣種',   actionable: true, btn: '擴到 ETH/SOL/AVAX' },
  mtf_caution:  { emoji: '⚠️',  label: '多 TF 衝突', actionable: false, btn: '' },
};

// fan_out 預設目標幣種（除 BTC 之外的 3 個流動性最好的）
const FAN_OUT_DEFAULTS = ['ETH/USDT', 'SOL/USDT', 'AVAX/USDT'];

export default function AdvisorPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(true);
  const [busyKey, setBusyKey] = useState(null);   // 'action-stratId'
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API}/api/advisor/recommendations`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setData(body);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, 300000);
    return () => clearInterval(t);
  }, [fetchData]);

  const applyAction = async (item) => {
    const sid = item.strategy_id;
    const key = `${item.action}-${sid}`;
    let confirmMsg = '';
    let req = null;     // {url, body, okMsg}

    if (item.action === 'retire') {
      confirmMsg = `確定退役 #${sid} ${item.strategy_name}？\n原因：${item.reason}`;
      req = {
        url: `${API}/api/strategies/${sid}/retire`,
        body: { reason: `advisor: ${item.reason.slice(0, 200)}` },
        okMsg: `已退役 #${sid}`,
      };
    } else if (item.action === 'pause') {
      confirmMsg = `確定暫停 #${sid} ${item.strategy_name}？`;
      req = {
        url: `${API}/api/strategies/${sid}/stop`,
        body: {},
        okMsg: `已暫停 #${sid}`,
      };
    } else if (item.action === 'apply_params') {
      const params = item.meta?.best_params;
      if (!params) {
        setSnackbar({ open: true, severity: 'error', message: '找不到 best_params' });
        return;
      }
      const paramsStr = Object.entries(params).map(([k, v]) => `${k}=${v}`).join(' ');
      confirmMsg = `套用以下參數到 #${sid} ${item.strategy_name}？\n${paramsStr}\nOOS Sharpe = ${item.meta.best_oos_sharpe?.toFixed?.(2)}`;
      req = {
        url: `${API}/api/strategies/${sid}/apply-params`,
        body: { params, optimization_id: item.meta?.optimization_id },
        okMsg: `已套用新參數到 #${sid}`,
      };
    } else if (item.action === 'fan_out') {
      confirmMsg = `把 #${sid} ${item.strategy_name} 一鍵複製到 ${FAN_OUT_DEFAULTS.join(' / ')}？\n（會以 status=stopped 建立，需手動啟動）`;
      req = {
        url: `${API}/api/strategies/${sid}/fan-out`,
        body: { symbols: FAN_OUT_DEFAULTS },
        okMsg: `已建立兄弟策略，請至策略頁啟動`,
      };
    } else {
      return;
    }

    if (!window.confirm(confirmMsg)) return;

    setBusyKey(key);
    try {
      const res = await fetch(req.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || body.detail || `HTTP ${res.status}`);
      setSnackbar({ open: true, severity: 'success', message: req.okMsg });
      await fetchData();
    } catch (e) {
      setSnackbar({ open: true, severity: 'error', message: `失敗：${e.message}` });
    } finally {
      setBusyKey(null);
    }
  };

  const items = data?.items || [];
  const summary = data?.summary || {};

  return (
    <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid rgba(34,211,238,0.20)' }}>
      <CardContent sx={{ px: 2.5, py: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Typography variant="h6" fontWeight={700}>🎯 操作建議</Typography>
            {summary.total > 0 && (
              <Stack direction="row" spacing={0.5}>
                {summary.critical > 0 && <Chip size="small" label={`緊急 ${summary.critical}`} sx={{ bgcolor: '#ef4444', color: '#fff', fontWeight: 700 }} />}
                {summary.warn > 0 && <Chip size="small" label={`建議 ${summary.warn}`} sx={{ bgcolor: '#f59e0b', color: '#000', fontWeight: 700 }} />}
                {summary.info > 0 && <Chip size="small" label={`機會 ${summary.info}`} variant="outlined" sx={{ borderColor: '#22d3ee', color: '#22d3ee' }} />}
              </Stack>
            )}
          </Box>
          <Box>
            <IconButton size="small" onClick={() => setExpanded(!expanded)}>
              {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            </IconButton>
            <IconButton size="small" onClick={fetchData}>
              <RefreshIcon />
            </IconButton>
          </Box>
        </Box>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
          綜合相關性 / 市場狀態 / 多 TF 訊號 / 最近回測與參數優化 — 全自動生成。所有建議都由你決定是否執行。
        </Typography>

        {loading && <LinearProgress sx={{ mb: 1 }} />}
        {error && <Alert severity="error" sx={{ mb: 1 }}>讀取失敗：{error}</Alert>}

        {data && items.length === 0 && (
          <Alert severity="success" sx={{ py: 0.5 }}>目前沒有任何建議 — 系統狀態看起來不錯。</Alert>
        )}

        <Collapse in={expanded}>
          <Stack spacing={1}>
            {items.map((item, idx) => {
              const sev = SEVERITY_META[item.severity] || SEVERITY_META.info;
              const act = ACTION_META[item.action] || { emoji: '•', label: item.action, tip: '' };
              return (
                <Box
                  key={idx}
                  sx={{
                    p: 1.5,
                    borderLeft: `3px solid ${sev.color}`,
                    bgcolor: sev.bg,
                    borderRadius: '0 4px 4px 0',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 1.5,
                  }}
                >
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, flexWrap: 'wrap' }}>
                      <Chip
                        label={sev.label}
                        size="small"
                        sx={{ bgcolor: sev.color, color: sev.color === '#22d3ee' ? '#000' : '#fff', fontWeight: 700, height: 20 }}
                      />
                      <Typography variant="body2" fontWeight={700}>
                        {act.emoji} {act.label}
                      </Typography>
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>·</Typography>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        #{item.strategy_id} {item.strategy_name}
                      </Typography>
                    </Box>
                    <Typography variant="caption" sx={{ display: 'block', color: 'text.primary', lineHeight: 1.5 }}>
                      {item.reason}
                    </Typography>
                  </Box>
                  {act.actionable && (
                    <Button
                      size="small"
                      variant="contained"
                      disabled={busyKey === `${item.action}-${item.strategy_id}`}
                      onClick={() => applyAction(item)}
                      startIcon={<CheckIcon fontSize="small" />}
                      sx={{
                        flexShrink: 0,
                        bgcolor: sev.color,
                        color: sev.color === '#22d3ee' ? '#000' : '#fff',
                        fontWeight: 700,
                        fontSize: 11,
                        whiteSpace: 'nowrap',
                        '&:hover': { bgcolor: sev.color, opacity: 0.85 },
                      }}
                    >
                      {busyKey === `${item.action}-${item.strategy_id}` ? '處理中…' : act.btn}
                    </Button>
                  )}
                </Box>
              );
            })}
          </Stack>
        </Collapse>

        <Snackbar
          open={snackbar.open}
          autoHideDuration={3500}
          onClose={() => setSnackbar(s => ({ ...s, open: false }))}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        >
          <Alert severity={snackbar.severity} variant="filled">{snackbar.message}</Alert>
        </Snackbar>
      </CardContent>
    </Card>
  );
}
