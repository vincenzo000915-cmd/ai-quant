import React, { useEffect, useState, useCallback, memo } from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Tooltip, IconButton, Stack,
  Alert, LinearProgress, Grid, Button, CircularProgress,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';

const API = process.env.REACT_APP_API_URL || '';

const REGIME_META = {
  strong_trend: { label: '強趨勢', color: '#00d4aa', emoji: '📈' },
  weak_trend:   { label: '弱趨勢', color: '#84cc16', emoji: '↗️' },
  range:        { label: '盤整',   color: '#f59e0b', emoji: '🔄' },
  unknown:      { label: '未知',   color: '#64748b', emoji: '❓' },
};

const FIT_META = {
  good:    { label: '匹配',   color: '#00d4aa' },
  ok:      { label: '尚可',   color: '#84cc16' },
  bad:     { label: '不匹配', color: '#ff4757' },
  unknown: { label: '—',     color: '#64748b' },
};

// Phase 14k-98: 双维度 (理论 fit × 实际 EV) 综合判断
// 4 类典型 case + 边界 (weak/unknown) 全覆盖
function combinedFitMeta(fit, evHealth) {
  // === fit = bad ===
  if (fit === 'bad' && evHealth === 'healthy') {
    return { label: '数据胜理论', color: '#3b82f6', tip: '教科书说市场不匹配, 但实际 EV 健康 — 数据胜过理论, 让它跑' };
  }
  if (fit === 'bad' && evHealth === 'weak') {
    return { label: '理论差实微利', color: '#a855f7', tip: '理论不匹配但实际微利 — 观察就好, 别急着 pause' };
  }
  if (fit === 'bad' && evHealth === 'negative') {
    return { label: '都差', color: '#ef4444', tip: '理论 + 实际都差, 建议 pause 或先回测验证' };
  }
  if (fit === 'bad' && evHealth === 'unknown') {
    return { label: '理论差数据少', color: '#f59e0b', tip: '理论不匹配 + 实盘样本不足 — 先跑回测验证再决定' };
  }
  // === fit = good/ok ===
  if (fit === 'good' && evHealth === 'negative') {
    return { label: '理论好实亏', color: '#f59e0b', tip: '理论上匹配但实际 EV 负, 回测可能过时或样本不足' };
  }
  if ((fit === 'good' || fit === 'ok') && evHealth === 'healthy') {
    return { label: '匹配+盈利', color: '#00d4aa', tip: '理论匹配 + EV 健康' };
  }
  if ((fit === 'good' || fit === 'ok') && evHealth === 'weak') {
    return { label: '匹配+微利', color: '#84cc16', tip: '理论匹配但 EV 微利, 继续观察' };
  }
  // fallback: 旧 fit label (ok / unknown 等)
  return FIT_META[fit] || FIT_META.unknown;
}

const EV_HEALTH_META = {
  healthy:  { label: '盈利健康',  color: '#00d4aa' },
  weak:     { label: '微利',      color: '#84cc16' },
  negative: { label: '负 EV',     color: '#ef4444' },
  unknown:  { label: '数据少',    color: '#64748b' },
};

const AFFINITY_LABEL = {
  trend_follower: '趨勢跟蹤',
  mean_reverter:  '均值回歸',
  breakout:       '突破',
};

function RegimePanelInner() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [ai, setAi] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);

  const fetchAi = useCallback(async () => {
    setAiLoading(true);
    setAi(null);
    setAiError(null);
    try {
      const r = await fetch(`${API}/api/regime/ai-explain`, { method: 'POST' });
      const body = await r.json();
      if (!r.ok || !body.ok) setAiError(body.error || `HTTP ${r.status}`);
      else setAi(body);
    } catch (e) { setAiError(e.message); }
    finally { setAiLoading(false); }
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API}/api/regime/running`);
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
    const t = setInterval(fetchData, 120000);
    return () => clearInterval(t);
  }, [fetchData]);

  const regimes = Object.entries(data?.regimes || {});
  const perStrategy = data?.per_strategy || [];
  // Phase 14k-98: 双维度统计 — 真"都差"才算需 pause
  // 旧: mismatchCount = fit==bad (按教科书, 真在赚的也算)
  // 新: realProblemCount = fit==bad AND ev_health == negative (理论+实际都差)
  //     dataBeatsTheoryCount = fit==bad AND ev_health == healthy (蓝色, 别动)
  const mismatchCount = perStrategy.filter(p => p.fit === 'bad').length;
  const realProblemCount = perStrategy.filter(p => p.fit === 'bad' && p.ev_health === 'negative').length;
  const dataBeatsTheoryCount = perStrategy.filter(p => p.fit === 'bad' && p.ev_health === 'healthy').length;

  return (
    <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
      <CardContent sx={{ px: 2.5, py: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
          <Box>
            <Typography variant="h6" fontWeight={700}>🌡️ 市場狀態檢測</Typography>
            <Typography variant="caption" color="text.secondary">
              ADX 趨勢強度 + Hurst 指數 → 判斷當前市場是趨勢、盤整還是過渡，並標出策略類型是否匹配
            </Typography>
          </Box>
          <Stack direction="row" spacing={1}>
            <Tooltip title="AI 解读市场状态（Pro）">
              <Button
                size="small"
                variant="outlined"
                startIcon={aiLoading ? <CircularProgress size={14} /> : <AutoAwesomeIcon />}
                onClick={fetchAi}
                disabled={aiLoading || !data}
                sx={{ color: '#a78bfa', borderColor: '#a78bfa66', textTransform: 'none' }}
              >
                {aiLoading ? '思考中…' : 'AI 解讀'}
              </Button>
            </Tooltip>
            <Tooltip title="重新計算">
              <IconButton size="small" onClick={fetchData}><RefreshIcon /></IconButton>
            </Tooltip>
          </Stack>
        </Box>

        {(ai || aiError) && (
          <Alert
            severity={aiError ? 'error' : 'info'}
            sx={{ mb: 2, bgcolor: aiError ? undefined : 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}
            onClose={() => { setAi(null); setAiError(null); }}
          >
            {aiError ? (
              <Typography variant="body2">AI 失败：{aiError}</Typography>
            ) : (
              <Box>
                <Stack direction="row" spacing={1} sx={{ mb: 1, flexWrap: 'wrap' }}>
                  <Chip size="small" label={ai.provider_used} variant="outlined" />
                  <Chip size="small" label={ai.model_used} variant="outlined" />
                  {ai.cached && <Chip size="small" label="缓存命中" color="success" variant="outlined" />}
                  {ai.latency_ms != null && <Chip size="small" label={`${ai.latency_ms} ms`} variant="outlined" />}
                </Stack>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                  {ai.text}
                </Typography>
              </Box>
            )}
          </Alert>
        )}

        {loading && <LinearProgress sx={{ mb: 1 }} />}
        {error && <Alert severity="error" sx={{ mb: 1 }}>讀取失敗：{error}</Alert>}

        {data && regimes.length === 0 && (
          <Alert severity="info">目前沒有運行中的策略。</Alert>
        )}

        {data && regimes.length > 0 && (
          <>
            <Grid container spacing={1.5} sx={{ mb: 2 }}>
              {regimes.map(([key, r]) => {
                const meta = REGIME_META[r.regime] || REGIME_META.unknown;
                return (
                  <Grid item xs={12} sm={6} md={4} key={key}>
                    <Box sx={{
                      p: 1.5,
                      border: `1px solid ${meta.color}40`,
                      borderRadius: 1,
                      bgcolor: `${meta.color}10`,
                    }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                        <Typography variant="body2" fontWeight={700}>
                          {r.symbol} <span style={{ color: '#94a3b8', fontWeight: 400 }}>· {r.timeframe}</span>
                        </Typography>
                        <Chip
                          label={`${meta.emoji} ${meta.label}`}
                          size="small"
                          sx={{ bgcolor: meta.color, color: '#000', fontWeight: 700, fontSize: 11 }}
                        />
                      </Box>
                      <Box sx={{ display: 'flex', gap: 2, mt: 0.5 }}>
                        <Tooltip title="ADX > 25 通常代表強趨勢">
                          <Typography variant="caption" color="text.secondary">
                            ADX <strong style={{ color: '#fff' }}>{r.adx ?? '—'}</strong>
                          </Typography>
                        </Tooltip>
                        <Tooltip title="Hurst > 0.55 偏趨勢；< 0.45 偏均值回歸；≈ 0.5 隨機">
                          <Typography variant="caption" color="text.secondary">
                            Hurst <strong style={{ color: '#fff' }}>{r.hurst ?? '—'}</strong>
                          </Typography>
                        </Tooltip>
                      </Box>
                    </Box>
                  </Grid>
                );
              })}
            </Grid>

            {/* Phase 14k-98: 双维度 warning — 区分"真问题"vs"理论冲突但盈利" */}
            {realProblemCount > 0 && (
              <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
                有 <strong>{realProblemCount}</strong> 个策略 <strong>理论 + 实际都差</strong>（市场不匹配 AND EV 负）—
                这种才该考虑 pause 或先做回测验证。
              </Alert>
            )}
            {dataBeatsTheoryCount > 0 && (
              <Alert severity="info" sx={{ mb: 1, py: 0.5 }}>
                有 <strong>{dataBeatsTheoryCount}</strong> 个策略 <strong>「数据胜过理论」</strong>—
                教科书说市场不匹配, 但实际 EV 健康 (蓝色标签)。<strong>让它继续跑</strong>, 别被教科书理论误导。
              </Alert>
            )}

            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
              策略 × 當前市場匹配度 + 實際 EV (14k-98 雙維度)：
            </Typography>
            <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
              {perStrategy.map(p => {
                // Phase 14k-98: 用 combinedFitMeta 综合 fit + ev_health
                const fit = combinedFitMeta(p.fit, p.ev_health);
                const aff = AFFINITY_LABEL[p.affinity] || '—';
                const evNote = p.ev_pct != null
                  ? ` · 真實 EV ${p.ev_pct >= 0 ? '+' : ''}${p.ev_pct.toFixed(2)}%/單 (門檻 ${p.ev_threshold_pct}%)`
                  : ' · EV 數據不足';
                return (
                  <Tooltip
                    key={p.strategy_id}
                    title={`${p.name} — 類型：${aff} / 當前 ${p.symbol} ${p.timeframe} = ${REGIME_META[p.regime]?.label || '未知'}${evNote}\n${fit.tip || ''}`}
                  >
                    <Box sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 0.5,
                      px: 1,
                      py: 0.3,
                      border: `1px solid ${fit.color}60`,
                      bgcolor: `${fit.color}15`,
                      borderRadius: 1,
                      fontSize: 11,
                    }}>
                      <Typography variant="caption" sx={{ fontWeight: 600 }}>
                        #{p.strategy_id} {p.name.length > 8 ? p.name.slice(0, 8) + '…' : p.name}
                      </Typography>
                      <Chip
                        label={fit.label}
                        size="small"
                        sx={{
                          height: 16,
                          fontSize: 9,
                          bgcolor: fit.color,
                          color: '#000',
                          fontWeight: 700,
                          '& .MuiChip-label': { px: 0.5 },
                        }}
                      />
                    </Box>
                  </Tooltip>
                );
              })}
            </Stack>
          </>
        )}
      </CardContent>
    </Card>
  );
}

const RegimePanel = memo(RegimePanelInner);
export default RegimePanel;
