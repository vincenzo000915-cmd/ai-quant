import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Tooltip, IconButton,
  Alert, LinearProgress, Stack, Collapse, Button, Snackbar,
  Switch, FormControlLabel, FormGroup, Checkbox, TextField,
  Dialog, DialogTitle, DialogContent, DialogActions, Divider,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CheckIcon from '@mui/icons-material/Check';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import SettingsIcon from '@mui/icons-material/Settings';
import PlayCircleIcon from '@mui/icons-material/PlayCircle';

const API = process.env.REACT_APP_API_URL || '';

const SEVERITY_META = {
  critical: { color: '#ef4444', label: '緊急', bg: 'rgba(239,68,68,0.10)' },
  warn:     { color: '#f59e0b', label: '建議', bg: 'rgba(245,158,11,0.10)' },
  info:     { color: '#22d3ee', label: '機會', bg: 'rgba(34,211,238,0.08)' },
};

const ACTION_META = {
  retire:            { emoji: '🪦', label: '退役', actionable: true,  btn: '退役此策略' },
  pause:             { emoji: '⏸️',  label: '暫停', actionable: true,  btn: '暫停' },
  apply_params:      { emoji: '🔧', label: '套用最佳參數', actionable: true, btn: '套用參數' },
  fan_out:           { emoji: '📡', label: '一鍵擴幣種',   actionable: true, btn: '擴到 ETH/SOL/AVAX' },
  promote_candidate: { emoji: '🚀', label: '上線新候選',  actionable: true, btn: '上線並啟動' },
  mtf_caution:       { emoji: '⚠️',  label: '多 TF 衝突', actionable: false, btn: '' },
};

// fan_out 預設目標幣種（除 BTC 之外的 3 個流動性最好的）
const FAN_OUT_DEFAULTS = ['ETH/USDT', 'SOL/USDT', 'AVAX/USDT'];

export default function AdvisorPanel() {
  const [data, setData] = useState(null);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(true);
  const [busyKey, setBusyKey] = useState(null);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });
  const [autoSettingsOpen, setAutoSettingsOpen] = useState(false);
  const [autoRunning, setAutoRunning] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [advRes, cfgRes] = await Promise.all([
        fetch(`${API}/api/advisor/recommendations`),
        fetch(`${API}/api/config`),
      ]);
      if (!advRes.ok) throw new Error(`advisor HTTP ${advRes.status}`);
      setData(await advRes.json());
      if (cfgRes.ok) setConfig(await cfgRes.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const t = setInterval(fetchAll, 300000);
    return () => clearInterval(t);
  }, [fetchAll]);

  const saveAutoConfig = async (patch) => {
    try {
      const r = await fetch(`${API}/api/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || body.detail || `HTTP ${r.status}`);
      setConfig(body);
      setSnackbar({ open: true, severity: 'success', message: '托管設定已更新' });
    } catch (e) {
      setSnackbar({ open: true, severity: 'error', message: `失敗：${e.message}` });
    }
  };

  const runAutoNow = async () => {
    if (!window.confirm('立即跑一次智能托管掃描？\n會根據目前授權的 action 立刻自動執行符合的建議。')) return;
    setAutoRunning(true);
    try {
      const r = await fetch(`${API}/api/advisor/auto-apply/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || body.detail || `HTTP ${r.status}`);
      if (body.skipped) {
        setSnackbar({ open: true, severity: 'warning', message: `已跳過：${body.reason}` });
      } else {
        setSnackbar({
          open: true,
          severity: body.applied_count > 0 ? 'success' : 'info',
          message: `掃描完成：套用 ${body.applied_count} 項，今日 ${body.today_count_after}/${body.daily_cap}`,
        });
        await fetchAll();
      }
    } catch (e) {
      setSnackbar({ open: true, severity: 'error', message: `失敗：${e.message}` });
    } finally {
      setAutoRunning(false);
    }
  };

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
    } else if (item.action === 'promote_candidate') {
      const cid = item.meta?.candidate_id;
      const oos = item.meta?.oos_sharpe;
      if (!cid) {
        setSnackbar({ open: true, severity: 'error', message: '找不到 candidate_id' });
        return;
      }
      confirmMsg = `上線候選 #${cid}（OOS Sharpe ${oos?.toFixed?.(2)}）？\n會建立新 strategy 並 status=running，立刻納入信號循環。`;
      req = {
        url: `${API}/api/candidates/${cid}/promote`,
        body: { symbol: item.meta?.symbol || 'BTC/USDT' },
        okMsg: `已上線候選 #${cid}（需手動到策略表啟動，或開啟智能托管自動）`,
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
      await fetchAll();
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
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1, flexWrap: 'wrap', gap: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
            <Typography variant="h6" fontWeight={700}>🎯 操作建議</Typography>
            {summary.total > 0 && (
              <Stack direction="row" spacing={0.5}>
                {summary.critical > 0 && <Chip size="small" label={`緊急 ${summary.critical}`} sx={{ bgcolor: '#ef4444', color: '#fff', fontWeight: 700 }} />}
                {summary.warn > 0 && <Chip size="small" label={`建議 ${summary.warn}`} sx={{ bgcolor: '#f59e0b', color: '#000', fontWeight: 700 }} />}
                {summary.info > 0 && <Chip size="small" label={`機會 ${summary.info}`} variant="outlined" sx={{ borderColor: '#22d3ee', color: '#22d3ee' }} />}
              </Stack>
            )}
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
            {/* 智能托管 master toggle */}
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={!!config?.auto_apply_enabled}
                  onChange={(e) => saveAutoConfig({ auto_apply_enabled: e.target.checked })}
                  sx={{
                    '& .MuiSwitch-thumb': { bgcolor: config?.auto_apply_enabled ? '#22c55e' : undefined },
                    '& .MuiSwitch-track': { bgcolor: config?.auto_apply_enabled ? '#22c55e !important' : undefined },
                  }}
                />
              }
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <SmartToyIcon fontSize="small" sx={{ color: config?.auto_apply_enabled ? '#22c55e' : 'text.secondary' }} />
                  <Typography variant="caption" sx={{ fontWeight: 700 }}>
                    智能托管
                  </Typography>
                  {config?.auto_apply_enabled && (config?.auto_apply_actions?.length || 0) > 0 && (
                    <Chip
                      size="small"
                      label={`${config.auto_apply_actions.length} 項`}
                      sx={{ height: 16, fontSize: 9, bgcolor: '#22c55e', color: '#000', ml: 0.5 }}
                    />
                  )}
                </Box>
              }
              sx={{ mr: 0 }}
            />
            <Tooltip title="托管設定（哪些 action 允許自動執行 / 每日上限）">
              <IconButton size="small" onClick={() => setAutoSettingsOpen(true)}>
                <SettingsIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="立即跑一次托管掃描">
              <span>
                <IconButton
                  size="small"
                  onClick={runAutoNow}
                  disabled={autoRunning || !config?.auto_apply_enabled}
                >
                  <PlayCircleIcon fontSize="small" sx={{ color: config?.auto_apply_enabled ? '#22c55e' : undefined }} />
                </IconButton>
              </span>
            </Tooltip>
            <IconButton size="small" onClick={() => setExpanded(!expanded)}>
              {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            </IconButton>
            <IconButton size="small" onClick={fetchAll}>
              <RefreshIcon />
            </IconButton>
          </Box>
        </Box>

        {config?.auto_apply_enabled && (config?.auto_apply_actions?.length || 0) > 0 ? (
          <Alert severity="success" icon={<SmartToyIcon />} sx={{ mb: 1.5, py: 0.3 }}>
            智能托管已啟用：自動執行 <strong>{config.auto_apply_actions.join(' / ')}</strong>，每日上限 {config.auto_apply_max_per_day} 次，每 4 小時掃描一次（+ 5min 偏移）。
            {config.trading_mode === 'live' && (config.auto_apply_actions.includes('retire')) && (
              <Typography component="span" variant="caption" sx={{ display: 'block', mt: 0.5, opacity: 0.85 }}>
                ⓘ LIVE 模式下 retire 會被內部安全網跳過 — 改用 pause 代替。
              </Typography>
            )}
          </Alert>
        ) : (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
            綜合相關性 / 市場狀態 / 多 TF 訊號 / 最近回測與參數優化 — 全自動生成。
            {!config?.auto_apply_enabled && '開啟「智能托管」可讓系統按你授權自動執行；目前所有動作仍須手動點。'}
          </Typography>
        )}

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

        {/* 智能托管設定 Dialog */}
        <Dialog open={autoSettingsOpen} onClose={() => setAutoSettingsOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <SmartToyIcon sx={{ color: '#22c55e' }} />
            智能托管設定
          </DialogTitle>
          <DialogContent dividers>
            <Alert severity="warning" sx={{ mb: 2, py: 0.5 }}>
              智能托管會在背景每 4 小時自動執行你勾選的 action。請按風險由低到高逐個開啟，並隨時可以關掉總開關。
              <br />所有自動執行都會寫進 audit log + 推 Telegram。
            </Alert>

            <FormControlLabel
              control={
                <Switch
                  checked={!!config?.auto_apply_enabled}
                  onChange={(e) => saveAutoConfig({ auto_apply_enabled: e.target.checked })}
                />
              }
              label={<Typography fontWeight={700}>主開關 — 啟用智能托管</Typography>}
              sx={{ mb: 1 }}
            />

            <Divider sx={{ my: 2 }} />

            <Typography variant="subtitle2" sx={{ mb: 1 }}>授權的自動 action（按風險排序）：</Typography>
            <FormGroup>
              {[
                { val: 'apply_params',      label: '🔧 套用最佳參數（最安全）', desc: '把參數優化跑出的最佳組合直接套用到策略' },
                { val: 'pause',             label: '⏸️ 暫停策略（中等）',       desc: '當 regime 不匹配時把策略改為 stopped' },
                { val: 'fan_out',           label: '📡 一鍵擴幣種（中等）',     desc: '為高 Sharpe 策略建立 ETH/SOL/AVAX 兄弟（回測過門檻才自動啟動）' },
                { val: 'promote_candidate', label: '🚀 上線新候選（積極）',     desc: '候選池 qualified（已過 walk-forward）→ 自動建 strategy 並 status=running' },
                { val: 'retire',            label: '🪦 退役策略（最積極）',      desc: 'LIVE 模式會自動跳過 retire，只在 paper 生效' },
              ].map(opt => {
                const checked = (config?.auto_apply_actions || []).includes(opt.val);
                return (
                  <Box key={opt.val} sx={{ mb: 1 }}>
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={checked}
                          disabled={!config?.auto_apply_enabled}
                          onChange={(e) => {
                            const cur = config?.auto_apply_actions || [];
                            const next = e.target.checked ? [...cur, opt.val] : cur.filter(x => x !== opt.val);
                            saveAutoConfig({ auto_apply_actions: next });
                          }}
                        />
                      }
                      label={<Typography variant="body2" fontWeight={600}>{opt.label}</Typography>}
                    />
                    <Typography variant="caption" sx={{ display: 'block', ml: 4, color: 'text.secondary' }}>
                      {opt.desc}
                    </Typography>
                  </Box>
                );
              })}
            </FormGroup>

            <Divider sx={{ my: 2 }} />

            <TextField
              label="每日上限"
              type="number"
              size="small"
              fullWidth
              value={config?.auto_apply_max_per_day ?? 5}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10);
                if (!Number.isNaN(n) && n >= 0 && n <= 100) {
                  saveAutoConfig({ auto_apply_max_per_day: n });
                }
              }}
              helperText="每天最多執行幾次自動 action（保險絲）。0 = 完全不執行（等效關閉）。"
              inputProps={{ min: 0, max: 100 }}
            />

            <Divider sx={{ my: 2 }} />

            <Typography variant="subtitle2" sx={{ mb: 1 }}>📡 fan_out 兄弟自動啟動策略</Typography>
            <FormControlLabel
              control={
                <Switch
                  checked={!!config?.fan_out_auto_start}
                  onChange={(e) => saveAutoConfig({ fan_out_auto_start: e.target.checked })}
                />
              }
              label={
                <Typography variant="body2" fontWeight={600}>
                  允許 fan_out 兄弟回測過門檻後自動 start
                </Typography>
              }
            />
            <Typography variant="caption" sx={{ display: 'block', ml: 4, color: 'text.secondary', mb: 1.5 }}>
              關閉時：fan_out 兄弟永遠 stopped，要手動 ▶ 啟動<br />
              開啟時：每個新兄弟立刻排 walk-forward 回測，OOS Sharpe ≥ 下方阈值才自動啟動，失敗推 Telegram
            </Typography>
            <TextField
              label="兄弟啟動門檻（OOS Sharpe ≥）"
              type="number"
              size="small"
              fullWidth
              value={config?.fan_out_min_oos_sharpe ?? 1.0}
              disabled={!config?.fan_out_auto_start}
              onChange={(e) => {
                const n = parseFloat(e.target.value);
                if (!Number.isNaN(n) && n >= -5 && n <= 10) {
                  saveAutoConfig({ fan_out_min_oos_sharpe: n });
                }
              }}
              helperText="保守建議 1.0（不錯）；積極可降到 0.5；嚴格可拉到 1.5"
              inputProps={{ min: -5, max: 10, step: 0.1 }}
            />

            <Divider sx={{ my: 2 }} />

            <Typography variant="subtitle2" sx={{ mb: 1 }}>🚀 候選自動 promote 上線設定</Typography>
            <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mb: 1 }}>
              候選池跑出 qualified（walk-forward 過）後，達到下方門檻就自動建 strategy 並 status=running。
              <br />需在上方勾選「🚀 上線新候選」action 才生效。
            </Typography>
            <Stack direction="row" spacing={2} sx={{ mb: 1 }}>
              <TextField
                label="OOS Sharpe 門檻"
                type="number"
                size="small"
                fullWidth
                value={config?.auto_promote_min_oos_sharpe ?? 1.5}
                onChange={(e) => {
                  const n = parseFloat(e.target.value);
                  if (!Number.isNaN(n) && n >= -5 && n <= 10) {
                    saveAutoConfig({ auto_promote_min_oos_sharpe: n });
                  }
                }}
                helperText="建議 1.5（比 fan_out 嚴格，因為是全新策略）"
                inputProps={{ min: -5, max: 10, step: 0.1 }}
              />
              <TextField
                label="每日 promote 上限"
                type="number"
                size="small"
                fullWidth
                value={config?.auto_promote_max_per_day ?? 2}
                onChange={(e) => {
                  const n = parseInt(e.target.value, 10);
                  if (!Number.isNaN(n) && n >= 0 && n <= 20) {
                    saveAutoConfig({ auto_promote_max_per_day: n });
                  }
                }}
                helperText="2-3 比較合理，避免一天爆出 10 個新策略"
                inputProps={{ min: 0, max: 20 }}
              />
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setAutoSettingsOpen(false)}>關閉</Button>
          </DialogActions>
        </Dialog>

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
