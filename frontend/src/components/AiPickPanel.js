// Phase 12.42 v8: AI 精选策略面板 — 列出 qualified candidates (AI improve v8 输出)
//   每张卡片含 metrics + AI 推荐 risk_params + 一键 apply / adjust / reject

import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, CardContent, Typography, Stack, Button, Chip, Alert, Box,
  CircularProgress, Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, IconButton, Tooltip, Divider, Collapse,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import RefreshIcon from '@mui/icons-material/Refresh';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import TuneIcon from '@mui/icons-material/Tune';
import CloseIcon from '@mui/icons-material/Close';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import { prettifyType } from '../utils/strategyTypeLabels';

const PURPLE = '#a78bfa';

const fmtNum = (v, digits = 2) => {
  if (v == null || v === undefined) return '-';
  const n = Number(v);
  if (Number.isNaN(n)) return '-';
  return n.toFixed(digits);
};

// Phase 14k-94: AI 决策模式标签 (跟 AdvisorPanel 同步)
const MODE_LABELS = {
  manual:    { label: '手动', desc: '候选需手动点"上线启动"' },
  preview:   { label: '预览', desc: 'AI 只提议不执行' },
  semi_auto: { label: '半自动', desc: 'Sharpe≥2.5 候选自动上线' },
  full_auto: { label: '全自动', desc: '候选进 panel 时已尝试 auto-promote (cap 2/天)' },
};

export default function AiPickPanel() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [needsPro, setNeedsPro] = useState(false);    // Phase 12.44: 402 → 升级提示
  const [actioning, setActioning] = useState({});
  const [adjustDialog, setAdjustDialog] = useState(null);
  const [expandedIds, setExpandedIds] = useState({});
  // Phase 14h: per-item LLM 解释 (lazy-fetched after items load)
  const [explanations, setExplanations] = useState({});   // { [id]: { explanation, risk_warning, source, loading?, error? } }
  // Phase 14k-94: AI 决策模式
  const [config, setConfig] = useState(null);

  // Phase 14k-94: 拉 config (用于显示 mode banner)
  useEffect(() => {
    fetch('/api/config').then(r => r.ok ? r.json() : null).then(c => c && setConfig(c)).catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    setBusy(true);
    setErr(null);
    setNeedsPro(false);
    try {
      const r = await fetch('/api/candidates/ai-picks');
      if (r.status === 402) {
        setNeedsPro(true);
        setItems([]);
        return;
      }
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
      setItems(body.items || []);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Phase 14h: 每次 items 变化, 异步取每条的 LLM 解释 (catalog clone 才有意义)
  useEffect(() => {
    if (!items.length) return;
    items.filter(it => it.source === 'catalog_clone').forEach(it => {
      setExplanations(prev => {
        if (prev[it.id]) return prev;    // 已有 (loading/done/error) → skip
        // 启动 fetch (在 setState 内安全, 因为下方 promise 在 microtask 调度)
        fetch('/api/me/recommendation-explain', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ clone_id: it.id }),
        })
          .then(r => r.json())
          .then(data => {
            if (!data.ok) {
              setExplanations(s => ({ ...s, [it.id]: { error: data.error || 'failed', loading: false } }));
              return;
            }
            setExplanations(s => ({ ...s, [it.id]: {
              explanation: data.explanation, risk_warning: data.risk_warning,
              source: data.source, cached: data.cached, loading: false,
            }}));
          })
          .catch(e => setExplanations(s => ({ ...s, [it.id]: { error: e.message, loading: false } })));
        return { ...prev, [it.id]: { loading: true } };
      });
    });
  }, [items]);

  const handleApply = async (cid, customRisk = null) => {
    setActioning(s => ({ ...s, [cid]: 'apply' }));
    try {
      const body = customRisk ? { risk_params: customRisk } : {};
      const r = await fetch(`/api/candidates/${cid}/promote-and-start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok || !data.ok) throw new Error(data.error || `HTTP ${r.status}`);
      await refresh();
      setAdjustDialog(null);
    } catch (e) {
      setErr(`Apply 失败: ${e.message}`);
    } finally {
      setActioning(s => ({ ...s, [cid]: null }));
    }
  };

  const handleReject = async (cid) => {
    if (!window.confirm('确认忽略此 AI 推荐？')) return;
    setActioning(s => ({ ...s, [cid]: 'reject' }));
    try {
      const r = await fetch(`/api/candidates/${cid}/dismiss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'user dismissed via panel' }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await refresh();
    } catch (e) {
      setErr(`Reject 失败: ${e.message}`);
    } finally {
      setActioning(s => ({ ...s, [cid]: null }));
    }
  };

  const renderCard = (it) => {
    const m = it.metrics || {};
    const rp = it.risk_params || {};
    const est = it.self_estimate || {};
    const tp = it.trade_patterns || {};
    const isApplying = actioning[it.id] === 'apply';
    const isRejecting = actioning[it.id] === 'reject';
    const isExpanded = !!expandedIds[it.id];

    return (
      <Card key={it.id} sx={{
        bgcolor: 'rgba(167,139,250,0.04)',
        border: `1px solid rgba(167,139,250,0.25)`,
        mb: 1.5,
      }}>
        <CardContent sx={{ px: 2, py: 1.5, '&:last-child': { pb: 1.5 } }}>
          {/* Header */}
          <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 1 }}>
            <Box sx={{ flexGrow: 1 }}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Tooltip title={`原始 type: ${it.candidate_type || '—'}`} arrow>
                  <Typography variant="subtitle1" fontWeight={700} sx={{ color: PURPLE, cursor: 'help' }}>
                    {prettifyType(it.candidate_type).emoji} {prettifyType(it.candidate_type).label}
                  </Typography>
                </Tooltip>
                {prettifyType(it.candidate_type).tag && (
                  <Chip label={prettifyType(it.candidate_type).tag} size="small" sx={{ bgcolor: 'rgba(167,139,250,0.15)', color: PURPLE, fontSize: 10, height: 20 }} />
                )}
                <Chip label={it.symbol} size="small" variant="outlined" />
                <Chip label={`${it.timeframe} ${it.category || ''}`} size="small" />
              </Stack>
              <Typography variant="caption" color="text.secondary">
                {it.source_name} · {it.created_at ? new Date(it.created_at).toLocaleString() : ''}
              </Typography>
            </Box>
          </Stack>

          {/* Key metrics row */}
          <Stack direction="row" spacing={1} sx={{ mb: 1, flexWrap: 'wrap', gap: 0.5 }}>
            <Chip
              size="small"
              label={`Sharpe ${fmtNum(m.oos_sharpe)}`}
              color={(m.oos_sharpe || 0) >= 2 ? 'success' : 'default'}
              variant="outlined"
            />
            <Chip size="small" label={`PF ${fmtNum(m.oos_profit_factor)}`} variant="outlined" />
            {m.oos_total_trades != null && <Chip size="small" label={`${m.oos_total_trades} trades`} variant="outlined" />}
            {m.oos_annual_return_pct != null && <Chip size="small" label={`AR ${fmtNum(m.oos_annual_return_pct)}%`} variant="outlined" />}
            {m.oos_max_drawdown_pct != null && <Chip size="small" label={`MaxDD ${fmtNum(m.oos_max_drawdown_pct)}%`} variant="outlined" />}
            {m.decay_pct != null && (
              <Chip size="small" label={`decay ${fmtNum(m.decay_pct)}%`} variant="outlined" />
            )}
            {m.source_label && (
              <Chip size="small" label={m.source_label}
                color={m.metric_source === 'catalog_seed' ? 'warning' : 'info'}
                variant="outlined" />
            )}
          </Stack>
          {/* Phase 14k-15: 文献验证 (非本地回测) 警告 */}
          {m.metric_warning && (
            <Alert severity="warning" sx={{ mb: 1, py: 0.3, fontSize: 11 }}>
              ⚠️ {m.metric_warning}
            </Alert>
          )}

          {/* Risk params box (AI recommendation) */}
          <Box sx={{
            p: 1, mb: 1, borderRadius: 1,
            bgcolor: 'rgba(167,139,250,0.08)',
            border: '1px dashed rgba(167,139,250,0.3)',
          }}>
            <Typography variant="caption" sx={{ display: 'block', fontWeight: 700, color: PURPLE }}>
              💼 AI 推荐 risk params
            </Typography>
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              杠杆 <b>{rp.leverage ?? '—'}x</b>　·　仓位 <b>${rp.position_size_usdt ?? '自适应'}</b>　·
              SL <b>{(rp.stop_loss_pct ?? rp.sl_pct) ?? '—'}%</b>　·　TP <b>{(rp.take_profit_pct ?? rp.tp_pct) ?? '—'}%</b>
              {rp.order_type && (<span style={{ marginLeft: 8, opacity: 0.6, fontSize: 11 }}>({rp.order_type})</span>)}
            </Typography>
            {rp.reasoning && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.3 }}>
                {rp.reasoning}
              </Typography>
            )}
          </Box>

          {/* Phase 14h: LLM 个性化解释 (lazy-loaded) */}
          {(() => {
            const expl = explanations[it.id];
            if (!expl) return null;
            if (expl.loading) {
              return (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, color: 'text.secondary' }}>
                  <CircularProgress size={12} />
                  <Typography variant="caption">AI 正在分析为什么这条适合你…</Typography>
                </Box>
              );
            }
            if (expl.error) return null;   // 静默 fallback 到 rationale
            return (
              <Box sx={{
                mb: 1, p: 1, borderRadius: 1,
                bgcolor: 'rgba(96,165,250,0.06)',
                border: '1px solid rgba(96,165,250,0.18)',
              }}>
                <Typography variant="body2" sx={{ color: 'text.primary', lineHeight: 1.5 }}>
                  🤖 {expl.explanation}
                </Typography>
                {expl.risk_warning && (
                  <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: '#fbbf24' }}>
                    ⚠️ {expl.risk_warning}
                  </Typography>
                )}
                <Typography variant="caption" sx={{ display: 'block', mt: 0.3, color: 'text.disabled', fontSize: 9 }}>
                  {expl.source === 'llm' && '由 AI 实时生成'}
                  {expl.source === 'cache' && '由 AI 生成 (cached 12h)'}
                  {expl.source === 'rule_based' && 'rule-based 描述'}
                </Typography>
              </Box>
            );
          })()}

          {/* Rationale snippet */}
          {it.rationale && (
            <Typography variant="body2" sx={{
              mb: 1, color: 'text.secondary',
              display: '-webkit-box', WebkitLineClamp: isExpanded ? 'unset' : 2,
              WebkitBoxOrient: 'vertical', overflow: 'hidden',
            }}>
              💡 {it.rationale}
            </Typography>
          )}

          {/* Expandable details */}
          <Collapse in={isExpanded}>
            <Divider sx={{ my: 1 }} />
            {it.external_source && (
              <Typography variant="caption" sx={{ display: 'block', mb: 0.5 }}>
                📡 External: {it.external_source}
              </Typography>
            )}
            {it.internal_ref && (
              <Typography variant="caption" sx={{ display: 'block', mb: 0.5 }}>
                🔗 Internal ref: <code>{it.internal_ref}</code>
              </Typography>
            )}
            {Object.keys(est).length > 0 && (
              <Typography variant="caption" sx={{ display: 'block', mb: 0.5 }}>
                🎯 LLM 自估: Sharpe={fmtNum(est.expected_oos_sharpe)} PF={fmtNum(est.expected_oos_pf)} trades={est.expected_oos_trades}
              </Typography>
            )}
            {Object.keys(tp).length > 0 && (
              <Typography variant="caption" sx={{ display: 'block', mb: 0.5 }}>
                📈 trade pattern: SL hit {fmtNum(tp.sl_hit_pct, 0)}% / TP hit {fmtNum(tp.tp_hit_pct, 0)}% / W/L ratio {fmtNum(tp.win_loss_ratio)}
              </Typography>
            )}
            {it.external_research_summary && (
              <Typography variant="caption" sx={{
                display: 'block', mt: 1, color: 'text.secondary',
                whiteSpace: 'pre-wrap', fontStyle: 'italic',
              }}>
                {it.external_research_summary}
              </Typography>
            )}
          </Collapse>

          {/* Phase 14k-15: 没自动上架原因 (历史 source_meta) */}
          {it.auto_skip_reason && (
            <Box sx={{ mb: 1, p: 0.8, borderRadius: 1, bgcolor: 'rgba(251,191,36,0.08)', border: '1px dashed rgba(251,191,36,0.3)' }}>
              <Typography variant="caption" sx={{ color: '#fbbf24' }}>
                🛑 未自动上架原因: {it.auto_skip_reason}
              </Typography>
            </Box>
          )}

          {/* Phase 14k-96: 实时 gate 状态 — 此刻能不能上架 */}
          {it.gate_block && (
            <Box sx={{ mb: 1, p: 0.8, borderRadius: 1, bgcolor: 'rgba(239,68,68,0.08)', border: '1px dashed rgba(239,68,68,0.4)' }}>
              <Typography variant="caption" sx={{ color: '#ef4444' }}>
                ⛔ 当前不能上架: {it.gate_block.reason}
              </Typography>
            </Box>
          )}

          {/* Actions */}
          <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', gap: 1 }}>
            <Button
              variant="contained"
              size="small"
              startIcon={isApplying ? <CircularProgress size={14} /> : <RocketLaunchIcon />}
              onClick={() => handleApply(it.id)}
              disabled={isApplying || isRejecting}
              sx={{ bgcolor: PURPLE, '&:hover': { bgcolor: '#9472eb' } }}
            >
              直接应用 + 上架
            </Button>
            <Button
              variant="outlined"
              size="small"
              startIcon={<TuneIcon />}
              onClick={() => setAdjustDialog({ ...it, _customRisk: { ...rp } })}
              disabled={isApplying || isRejecting}
              sx={{ borderColor: PURPLE, color: PURPLE }}
            >
              调整后应用
            </Button>
            {/* Phase 14k-15: 一键回测 */}
            <Button
              variant="outlined"
              size="small"
              onClick={async () => {
                setActioning(s => ({ ...s, [it.id]: 'backtest' }));
                try {
                  const r = await fetch(`/api/candidates/${it.id}/run-backtest`, { method: 'POST' });
                  const body = await r.json();
                  if (body.ok) {
                    alert(`回测完成. ${body.message || ''}`);
                    await refresh();
                  } else {
                    alert(`回测失败: ${body.error || 'unknown'}`);
                  }
                } catch (e) { alert(`回测异常: ${e.message}`); }
                finally { setActioning(s => ({ ...s, [it.id]: null })); }
              }}
              disabled={actioning[it.id] === 'backtest' || isApplying || isRejecting}
              color="info"
            >
              {actioning[it.id] === 'backtest' ? '回测中…' : '🔬 跑回测'}
            </Button>
            <Box sx={{ flexGrow: 1 }} />
            <Button
              variant="text"
              size="small"
              startIcon={isRejecting ? <CircularProgress size={14} /> : <CloseIcon />}
              onClick={() => handleReject(it.id)}
              disabled={isApplying || isRejecting}
              color="inherit"
            >
              忽略
            </Button>
            <IconButton
              size="small"
              onClick={() => setExpandedIds(s => ({ ...s, [it.id]: !isExpanded }))}
            >
              {isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            </IconButton>
          </Stack>
        </CardContent>
      </Card>
    );
  };

  return (
    <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid rgba(167,139,250,0.3)' }}>
      <CardContent sx={{ px: 2.5, py: 2 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <AutoAwesomeIcon sx={{ color: PURPLE }} />
          <Typography variant="h6" fontWeight={700}>AI 精选策略</Typography>
          <Chip label="v8" size="small" variant="outlined" />
          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="caption" color="text.secondary">
            {items.length > 0 ? `${items.length} 个待审` : ''}
          </Typography>
          <Tooltip title="刷新">
            <IconButton size="small" onClick={refresh} disabled={busy}>
              {busy ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Stack>

        {/* Phase 14k-94: AI mode banner */}
        {config?.ai_decision_mode && (() => {
          const m = MODE_LABELS[config.ai_decision_mode] || { label: config.ai_decision_mode, desc: '' };
          const sev = config.ai_decision_mode === 'full_auto' ? 'info' :
                       config.ai_decision_mode === 'manual' ? 'warning' : 'success';
          return (
            <Alert severity={sev} sx={{ mb: 1.5, py: 0.3 }}>
              <Typography variant="caption">
                <strong>AI 决策模式: {m.label}</strong> · {m.desc}
                {config.ai_decision_mode === 'full_auto' && config.auto_promote_max_per_day != null && (
                  <span> · auto-promote cap {config.auto_promote_max_per_day}/天</span>
                )}
              </Typography>
            </Alert>
          );
        })()}

        {err && (
          <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setErr(null)}>
            {err}
          </Alert>
        )}

        {busy && items.length === 0 && (
          <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 2 }}>
            <CircularProgress size={20} />
            <Typography variant="body2" color="text.secondary">载入中…</Typography>
          </Stack>
        )}

        {/* Phase 12.44: 非 Pro user 升级提示 */}
        {needsPro && (
          <Box sx={{
            py: 3, textAlign: 'center',
            bgcolor: 'rgba(167,139,250,0.06)',
            border: '1px dashed rgba(167,139,250,0.3)', borderRadius: 1,
          }}>
            <Typography variant="body2" fontWeight={700} sx={{ mb: 1, color: PURPLE }}>
              ✨ AI 精选策略是 Pro 功能
            </Typography>
            <Typography variant="caption" sx={{ display: 'block', mb: 1.5, color: 'text.secondary' }}>
              AI 每日生成新策略 · 自带 risk_params 推荐 · 一键上架
            </Typography>
            <Button
              variant="contained"
              size="small"
              onClick={() => window.location.href = '/pricing'}
              sx={{ bgcolor: PURPLE, '&:hover': { bgcolor: '#9472eb' } }}
            >
              升级到 Pro 解锁
            </Button>
          </Box>
        )}

        {!needsPro && !busy && items.length === 0 && (
          <Box sx={{
            py: 2.5, textAlign: 'center', color: 'text.secondary',
            border: '1px dashed rgba(167,139,250,0.2)', borderRadius: 1,
          }}>
            <Typography variant="body2" sx={{ mb: 0.5 }}>
              ✨ 暂无 AI 推荐策略
            </Typography>
            <Typography variant="caption">
              Daily AI improve (07:00 UTC) 会自动生成；或调用 /api/strategies/ai-improve 手动触发
            </Typography>
          </Box>
        )}

        {items.map(renderCard)}
      </CardContent>

      {/* Adjust dialog */}
      <AdjustRiskDialog
        item={adjustDialog}
        onClose={() => setAdjustDialog(null)}
        onApply={handleApply}
      />
    </Card>
  );
}


function AdjustRiskDialog({ item, onClose, onApply }) {
  const [risk, setRisk] = useState({});
  useEffect(() => {
    if (item) {
      setRisk({
        leverage: item._customRisk?.leverage || item.risk_params?.leverage || 5,
        position_size_usdt: item._customRisk?.position_size_usdt || item.risk_params?.position_size_usdt || 6,
        stop_loss_pct: item._customRisk?.stop_loss_pct || item.risk_params?.stop_loss_pct || 5,
        take_profit_pct: item._customRisk?.take_profit_pct || item.risk_params?.take_profit_pct || 10,
        order_type: item._customRisk?.order_type || item.risk_params?.order_type || 'market',
      });
    }
  }, [item]);
  if (!item) return null;

  const setNum = (k, v) => setRisk(r => ({ ...r, [k]: Number(v) }));
  const setStr = (k, v) => setRisk(r => ({ ...r, [k]: v }));
  return (
    <Dialog open={!!item} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>
        调整 risk params — {prettifyType(item.candidate_type).emoji} {prettifyType(item.candidate_type).label}
        <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mt: 0.5 }}>
          {item.candidate_type}
        </Typography>
      </DialogTitle>
      <DialogContent>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
          AI 推荐: 杠杆 {item.risk_params?.leverage}x · SL {item.risk_params?.stop_loss_pct}% · TP {item.risk_params?.take_profit_pct}% · 仓位 ${item.risk_params?.position_size_usdt}
        </Typography>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="杠杆 (leverage)"
            type="number"
            value={risk.leverage || ''}
            onChange={(e) => setNum('leverage', e.target.value)}
            inputProps={{ min: 1, max: 15, step: 1 }}
            size="small"
            fullWidth
          />
          <TextField
            label="单笔仓位 (USDT)"
            type="number"
            value={risk.position_size_usdt || ''}
            onChange={(e) => setNum('position_size_usdt', e.target.value)}
            inputProps={{ min: 1, step: 0.5 }}
            size="small"
            fullWidth
          />
          <TextField
            label="止损 % (stop_loss_pct)"
            type="number"
            value={risk.stop_loss_pct || ''}
            onChange={(e) => setNum('stop_loss_pct', e.target.value)}
            inputProps={{ min: 1, max: 30, step: 0.5 }}
            size="small"
            fullWidth
          />
          <TextField
            label="止盈 % (take_profit_pct)"
            type="number"
            value={risk.take_profit_pct || ''}
            onChange={(e) => setNum('take_profit_pct', e.target.value)}
            inputProps={{ min: 1, max: 50, step: 0.5 }}
            size="small"
            fullWidth
          />
          <TextField
            select
            label="订单类型 (Phase 13)"
            value={risk.order_type || 'market'}
            onChange={(e) => setStr('order_type', e.target.value)}
            size="small"
            fullWidth
            SelectProps={{ native: true }}
            helperText="maker = post_only 限价 (fee 0.02%)；market = 市价 (fee 0.05%)"
          >
            <option value="market">市价 (taker 0.05%) - 立即成交</option>
            <option value="maker">挂单 (maker 0.02%) - 60s 超时 cancel</option>
            <option value="maker_with_fallback">挂单 + 超时改市价 (0.025%)</option>
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button
          variant="contained"
          onClick={() => onApply(item.id, risk)}
          sx={{ bgcolor: PURPLE, '&:hover': { bgcolor: '#9472eb' } }}
        >
          应用并上架
        </Button>
      </DialogActions>
    </Dialog>
  );
}
