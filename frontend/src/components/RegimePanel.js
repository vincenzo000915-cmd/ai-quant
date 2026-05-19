import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Tooltip, IconButton, Stack,
  Alert, LinearProgress, Grid,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';

const API = process.env.REACT_APP_API_URL || '';

const REGIME_META = {
  strong_trend: { label: '強趨勢', color: '#22c55e', emoji: '📈' },
  weak_trend:   { label: '弱趨勢', color: '#84cc16', emoji: '↗️' },
  range:        { label: '盤整',   color: '#f59e0b', emoji: '🔄' },
  unknown:      { label: '未知',   color: '#64748b', emoji: '❓' },
};

const FIT_META = {
  good:    { label: '匹配',   color: '#22c55e' },
  ok:      { label: '尚可',   color: '#84cc16' },
  bad:     { label: '不匹配', color: '#ef4444' },
  unknown: { label: '—',     color: '#64748b' },
};

const AFFINITY_LABEL = {
  trend_follower: '趨勢跟蹤',
  mean_reverter:  '均值回歸',
  breakout:       '突破',
};

export default function RegimePanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

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
  const mismatchCount = perStrategy.filter(p => p.fit === 'bad').length;

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
          <Tooltip title="重新計算">
            <IconButton size="small" onClick={fetchData}><RefreshIcon /></IconButton>
          </Tooltip>
        </Box>

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

            {mismatchCount > 0 && (
              <Alert severity="warning" sx={{ mb: 2, py: 0.5 }}>
                有 <strong>{mismatchCount}</strong> 個策略類型與當前市場狀態不匹配 — 紅色「不匹配」標籤代表
                在這種環境下歷史表現通常較差，可考慮暫停或先做回測驗證。
              </Alert>
            )}

            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
              策略 × 當前市場匹配度：
            </Typography>
            <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
              {perStrategy.map(p => {
                const fit = FIT_META[p.fit] || FIT_META.unknown;
                const aff = AFFINITY_LABEL[p.affinity] || '—';
                return (
                  <Tooltip
                    key={p.strategy_id}
                    title={`${p.name} — 類型：${aff} / 當前 ${p.symbol} ${p.timeframe} = ${REGIME_META[p.regime]?.label || '未知'}`}
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
