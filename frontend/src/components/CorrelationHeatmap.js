import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Tooltip, IconButton,
  Alert, LinearProgress, Stack,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';

const API = process.env.REACT_APP_API_URL || '';

// 红 (高正相关) → 灰 (无关) → 绿 (高负相关，等同分散效益)
function corrColor(c) {
  if (c === null || c === undefined) return '#1e293b';
  const v = Math.max(-1, Math.min(1, c));
  if (v >= 0) {
    const r = Math.round(40 + v * 200);
    const g = Math.round(40 + (1 - v) * 80);
    const b = Math.round(60 + (1 - v) * 60);
    return `rgb(${r},${g},${b})`;
  }
  const t = -v;
  const r = Math.round(40 + (1 - t) * 80);
  const g = Math.round(80 + t * 160);
  const b = Math.round(60 + (1 - t) * 60);
  return `rgb(${r},${g},${b})`;
}

function fmt(c) {
  if (c === null || c === undefined) return '—';
  return c.toFixed(2);
}

export default function CorrelationHeatmap() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API}/api/strategies/correlation`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setData(body);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const strategies = data?.strategies || [];
  const matrix = data?.matrix || [];
  const flagged = data?.flagged || [];
  const n = strategies.length;
  const cell = n > 8 ? 44 : 60;

  return (
    <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
      <CardContent sx={{ px: 2.5, py: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
          <Box>
            <Typography variant="h6" fontWeight={700}>
              🔗 策略相关性矩阵
            </Typography>
            <Typography variant="caption" color="text.secondary">
              每日 PnL 序列两两 Pearson 相关系数 ({'>'} 0.7 视为高度同质，分散效益差)
            </Typography>
          </Box>
          <Tooltip title="重新计算">
            <IconButton size="small" onClick={fetchData}><RefreshIcon /></IconButton>
          </Tooltip>
        </Box>

        {loading && <LinearProgress sx={{ mb: 1 }} />}
        {error && <Alert severity="error" sx={{ mb: 1 }}>读取失败：{error}</Alert>}

        {data && n === 0 && (
          <Alert severity="info">没有运行中的策略可用于计算相关性。</Alert>
        )}

        {data && n > 0 && (
          <>
            <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: 'wrap', gap: 0.5 }}>
              <Chip
                size="small"
                label={`实盘成交：${data.sources_used?.live ?? 0}`}
                color={data.sources_used?.live > 0 ? 'success' : 'default'}
                variant="outlined"
              />
              <Chip
                size="small"
                label={`回测代理：${data.sources_used?.backtest ?? 0}`}
                color="info"
                variant="outlined"
              />
              {data.sources_used?.none > 0 && (
                <Chip size="small" label={`无数据：${data.sources_used.none}`} color="warning" variant="outlined" />
              )}
              <Chip
                size="small"
                label={`高相关警告：${flagged.length}`}
                color={flagged.length > 0 ? 'error' : 'success'}
                variant="outlined"
              />
            </Stack>

            {data.sources_used?.live === 0 && (
              <Alert severity="info" sx={{ mb: 1.5, py: 0.3 }}>
                目前实盘还没有平仓交易，矩阵以最近一次回测的 trades 计算。等实盘累积成交后会自动切换。
              </Alert>
            )}

            <Box sx={{ overflowX: 'auto', pb: 1 }}>
              <Box sx={{ display: 'inline-block', minWidth: 'fit-content' }}>
                {/* 上表头 */}
                <Box sx={{ display: 'flex', alignItems: 'flex-end' }}>
                  <Box sx={{ width: 140 }} />
                  {strategies.map(s => (
                    <Box
                      key={`h-${s.id}`}
                      sx={{
                        width: cell,
                        height: 90,
                        display: 'flex',
                        alignItems: 'flex-end',
                        justifyContent: 'center',
                        pb: 0.5,
                      }}
                    >
                      <Typography
                        variant="caption"
                        sx={{
                          transform: 'rotate(-55deg)',
                          transformOrigin: 'bottom center',
                          whiteSpace: 'nowrap',
                          fontSize: 11,
                          color: 'text.secondary',
                        }}
                      >
                        #{s.id} {s.name.length > 10 ? s.name.slice(0, 10) + '…' : s.name}
                      </Typography>
                    </Box>
                  ))}
                </Box>

                {/* 矩阵行 */}
                {strategies.map((rowS, i) => (
                  <Box key={`r-${rowS.id}`} sx={{ display: 'flex', alignItems: 'center' }}>
                    <Box sx={{ width: 140, pr: 1, textAlign: 'right' }}>
                      <Typography variant="caption" sx={{ fontSize: 11 }}>
                        #{rowS.id} {rowS.name.length > 12 ? rowS.name.slice(0, 12) + '…' : rowS.name}
                      </Typography>
                      <Typography variant="caption" sx={{ display: 'block', fontSize: 9, color: 'text.secondary' }}>
                        {rowS.source === 'live' ? '实盘' : rowS.source === 'backtest' ? '回测' : '无'} · {rowS.n_obs}d
                      </Typography>
                    </Box>
                    {matrix[i].map((c, j) => {
                      const isDiag = i === j;
                      const isFlagged = !isDiag && c !== null && Math.abs(c) > (data.threshold || 0.7);
                      return (
                        <Tooltip
                          key={`c-${i}-${j}`}
                          title={
                            c === null
                              ? `${rowS.name} ↔ ${strategies[j].name}：样本不足（需至少 ${data.min_obs || 5} 个重叠日）`
                              : `${rowS.name} ↔ ${strategies[j].name}：相关系数 ${c.toFixed(3)}`
                          }
                        >
                          <Box
                            sx={{
                              width: cell,
                              height: cell,
                              bgcolor: corrColor(c),
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              border: isFlagged ? '2px solid #f59e0b' : '1px solid rgba(255,255,255,0.05)',
                              cursor: 'pointer',
                              transition: 'transform 0.1s',
                              '&:hover': { transform: 'scale(1.08)', zIndex: 2, position: 'relative' },
                            }}
                          >
                            <Typography
                              variant="caption"
                              sx={{
                                fontSize: 11,
                                fontWeight: isDiag || isFlagged ? 700 : 500,
                                color: c === null ? '#64748b' : '#fff',
                              }}
                            >
                              {fmt(c)}
                            </Typography>
                          </Box>
                        </Tooltip>
                      );
                    })}
                  </Box>
                ))}

                {/* 色阶图例 */}
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1.5, ml: 17.5 }}>
                  <Typography variant="caption" color="text.secondary">-1 反向</Typography>
                  <Box sx={{ display: 'flex' }}>
                    {[-1, -0.5, 0, 0.5, 1].map(v => (
                      <Box key={v} sx={{ width: 28, height: 16, bgcolor: corrColor(v) }} />
                    ))}
                  </Box>
                  <Typography variant="caption" color="text.secondary">+1 同向</Typography>
                </Box>
              </Box>
            </Box>

            {flagged.length > 0 && (
              <Alert
                severity="warning"
                icon={<WarningAmberIcon />}
                sx={{ mt: 2 }}
              >
                <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>
                  发现 {flagged.length} 对高度相关策略（|ρ| {'>'} {data.threshold}）：
                </Typography>
                <Box component="ul" sx={{ m: 0, pl: 2 }}>
                  {flagged.slice(0, 5).map(f => (
                    <li key={`${f.a_id}-${f.b_id}`}>
                      <Typography variant="caption">
                        <strong>#{f.a_id} {f.a_name}</strong> ↔ <strong>#{f.b_id} {f.b_name}</strong>
                        {'  '}相关系数 <strong>{f.corr.toFixed(3)}</strong>
                        {'  '}({f.n_obs} 个共同交易日)
                      </Typography>
                    </li>
                  ))}
                </Box>
                <Typography variant="caption" sx={{ display: 'block', mt: 0.5, opacity: 0.8 }}>
                  建议：保留 Sharpe 较高的一支、退役另一支，或换成不同时框 / 不同币种，提升组合分散效益。
                </Typography>
              </Alert>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
