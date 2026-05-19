import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Card, CardContent, Typography, Chip, Tooltip, IconButton,
  Alert, LinearProgress, Stack, Collapse, Button, Divider,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';

const API = process.env.REACT_APP_API_URL || '';

const SEVERITY_META = {
  critical: { color: '#ef4444', label: '緊急', bg: 'rgba(239,68,68,0.10)' },
  warn:     { color: '#f59e0b', label: '建議', bg: 'rgba(245,158,11,0.10)' },
  info:     { color: '#22d3ee', label: '機會', bg: 'rgba(34,211,238,0.08)' },
};

const ACTION_META = {
  retire:       { emoji: '🪦', label: '退役', tip: '到策略頁點🪦按鈕（或目前 UI 是停用 + delete）' },
  pause:        { emoji: '⏸️',  label: '暫停', tip: '到策略頁點⏹ 停止' },
  apply_params: { emoji: '🔧', label: '套用最佳參數', tip: '到策略頁點🔧（藍綠色）開優化結果，選最佳那行按「套用」' },
  fan_out:      { emoji: '📡', label: '一鍵擴幣種', tip: '到策略頁點📡（紫色）開 fan-out modal' },
  mtf_caution:  { emoji: '⚠️',  label: '多 TF 衝突', tip: '不一定要動作，只是提醒：有訊號時建議多等一根 K' },
};

export default function AdvisorPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(true);

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
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, flexWrap: 'wrap' }}>
                    <Chip
                      label={sev.label}
                      size="small"
                      sx={{ bgcolor: sev.color, color: sev.color === '#22d3ee' ? '#000' : '#fff', fontWeight: 700, height: 20 }}
                    />
                    <Tooltip title={act.tip}>
                      <Typography variant="body2" fontWeight={700}>
                        {act.emoji} {act.label}
                      </Typography>
                    </Tooltip>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      ·
                    </Typography>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      #{item.strategy_id} {item.strategy_name}
                    </Typography>
                  </Box>
                  <Typography variant="caption" sx={{ display: 'block', color: 'text.primary', lineHeight: 1.5 }}>
                    {item.reason}
                  </Typography>
                </Box>
              );
            })}
          </Stack>
        </Collapse>
      </CardContent>
    </Card>
  );
}
