import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Tooltip, IconButton,
  Alert, LinearProgress, Table, TableHead, TableBody, TableRow, TableCell,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';

const API = process.env.REACT_APP_API_URL || '';

const SIGNAL_META = {
  buy:          { label: '買',  color: '#22c55e' },
  sell:         { label: '賣',  color: '#ef4444' },
  hold:         { label: '觀望', color: '#64748b' },
  insufficient: { label: '不足', color: '#475569' },
  error:        { label: '錯',  color: '#f59e0b' },
};

const CONSENSUS_META = {
  strong_buy:   { label: '一致買入',  color: '#22c55e', emoji: '🟢' },
  lean_buy:     { label: '偏多',      color: '#86efac', emoji: '↗️' },
  strong_sell:  { label: '一致賣出',  color: '#ef4444', emoji: '🔴' },
  lean_sell:    { label: '偏空',      color: '#fca5a5', emoji: '↘️' },
  mixed:        { label: '衝突',      color: '#f59e0b', emoji: '⚠️' },
  hold_all:     { label: '全部觀望',  color: '#64748b', emoji: '⏸️' },
  insufficient: { label: '資料不足',  color: '#475569', emoji: '❓' },
};

export default function MTFConsensusPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API}/api/mtf/running`);
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
    const t = setInterval(fetchData, 180000);
    return () => clearInterval(t);
  }, [fetchData]);

  const strategies = data?.strategies || [];
  const conflictCount = strategies.filter(s => s.consensus?.label === 'mixed').length;

  // 收集所有 TF（保证表头顺序）
  const allTfs = Array.from(new Set(strategies.flatMap(s => (s.per_tf || []).map(p => p.tf))));

  return (
    <Card sx={{ mb: 2.5, bgcolor: 'background.paper', border: '1px solid rgba(255,255,255,0.06)' }}>
      <CardContent sx={{ px: 2.5, py: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
          <Box>
            <Typography variant="h6" fontWeight={700}>🎯 多時框一致性檢查</Typography>
            <Typography variant="caption" color="text.secondary">
              每個策略同時跑 15m / 1h / 4h / 1d 看當前訊號，TF 之間衝突（buy + sell 並存）通常代表轉折，建議謹慎入場
            </Typography>
          </Box>
          <Tooltip title="重新計算">
            <IconButton size="small" onClick={fetchData}><RefreshIcon /></IconButton>
          </Tooltip>
        </Box>

        {loading && <LinearProgress sx={{ mb: 1 }} />}
        {error && <Alert severity="error" sx={{ mb: 1 }}>讀取失敗：{error}</Alert>}

        {data && strategies.length === 0 && (
          <Alert severity="info">目前沒有運行中的策略。</Alert>
        )}

        {data && strategies.length > 0 && (
          <>
            {conflictCount > 0 && (
              <Alert severity="warning" sx={{ mb: 1.5, py: 0.5 }}>
                {conflictCount} 個策略存在 TF 衝突訊號（同時有 buy 跟 sell）— 行情可能正在轉折
              </Alert>
            )}
            <Box sx={{ overflowX: 'auto' }}>
              <Table size="small" sx={{ '& td, & th': { fontSize: 12, py: 0.5 } }}>
                <TableHead>
                  <TableRow>
                    <TableCell>策略</TableCell>
                    <TableCell>幣種</TableCell>
                    {allTfs.map(tf => (
                      <TableCell key={tf} align="center">{tf}</TableCell>
                    ))}
                    <TableCell align="center">一致性</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {strategies.map(s => {
                    const cons = CONSENSUS_META[s.consensus?.label] || CONSENSUS_META.insufficient;
                    const byTf = Object.fromEntries((s.per_tf || []).map(p => [p.tf, p]));
                    return (
                      <TableRow key={s.strategy_id}>
                        <TableCell>
                          <Typography variant="caption" fontWeight={600}>
                            #{s.strategy_id} {s.name}
                          </Typography>
                          {s.base_tf && (
                            <Typography variant="caption" sx={{ ml: 0.5, color: 'text.secondary', fontSize: 10 }}>
                              ({s.base_tf})
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell>{s.symbol}</TableCell>
                        {allTfs.map(tf => {
                          const r = byTf[tf];
                          const sig = r?.signal || '—';
                          const meta = SIGNAL_META[sig] || SIGNAL_META.insufficient;
                          const isBase = tf === s.base_tf;
                          return (
                            <TableCell key={tf} align="center">
                              <Tooltip title={r?.error || `${sig} @ ${tf}${isBase ? '（基準 TF）' : ''}`}>
                                <Chip
                                  label={meta.label}
                                  size="small"
                                  sx={{
                                    bgcolor: meta.color,
                                    color: sig === 'hold' || sig === 'insufficient' ? '#cbd5e1' : '#000',
                                    fontWeight: 700,
                                    fontSize: 10,
                                    height: 20,
                                    minWidth: 36,
                                    border: isBase ? '1.5px solid #fff' : 'none',
                                  }}
                                />
                              </Tooltip>
                            </TableCell>
                          );
                        })}
                        <TableCell align="center">
                          <Chip
                            label={`${cons.emoji} ${cons.label}`}
                            size="small"
                            sx={{
                              bgcolor: cons.color,
                              color: '#000',
                              fontWeight: 700,
                              fontSize: 10,
                            }}
                          />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, fontSize: 10 }}>
              基準 TF 用白色外框標示。本面板僅作參考診斷，不直接影響實盤下單。
            </Typography>
          </>
        )}
      </CardContent>
    </Card>
  );
}
