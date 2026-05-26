// Phase 14k-30 #4: AI 操作日记卡片 — 列出 AI 自动改了什么 (auto-revert / 闪测 / 调仓 / 上线 等)
import React, { useState, useEffect } from 'react';
import {
  Card, CardContent, Typography, Box, Chip, Stack, IconButton, Tooltip,
  CircularProgress, List, ListItem, ListItemText, Divider,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import HistoryIcon from '@mui/icons-material/History';

const API = process.env.REACT_APP_API_URL || '';

const EVENT_COLOR = {
  ai_change_reverted: 'warning',
  risk_opt_applied: 'success',
  ai_strategy_params_change: 'info',
  candidate_promote_and_start: 'success',
  advisor_invent_applied: 'success',
  risk_opt_no_lift: 'default',
  signal_grid_proposed: 'info',
  risk_opt_proposed: 'info',
  advisor_invent_proposed: 'info',
  sizing_advisor_recommend: 'default',
  advisor_auto_apply: 'primary',
};

const EVENT_LABEL = {
  ai_change_reverted: '⏪ 还原',
  risk_opt_applied: '⚡ SL/TP 闪测',
  ai_strategy_params_change: '🔧 改参',
  candidate_promote_and_start: '🚀 上线',
  advisor_invent_applied: '🧪 invent',
  risk_opt_no_lift: '— 闪测无提升',
  signal_grid_proposed: '🔍 grid 排程',
  risk_opt_proposed: '⏱ 闪测排程',
  advisor_invent_proposed: '⏱ invent 排程',
  sizing_advisor_recommend: '💰 sizing 评估',
  advisor_auto_apply: '✓ 执行',
};

function formatRelTime(iso) {
  if (!iso) return '';
  const t = new Date(iso);
  const diff = (Date.now() - t.getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)} 秒前`;
  if (diff < 3600) return `${Math.round(diff / 60)} 分前`;
  if (diff < 86400) return `${Math.round(diff / 3600)} 时前`;
  return `${Math.round(diff / 86400)} 天前`;
}

export default function AiActivityLogCard() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/me/ai-activity-log?limit=30`, { credentials: 'include' });
      if (r.ok) {
        const d = await r.json();
        setItems(d?.items || []);
      }
    } catch (e) {
      // silent
    }
    setLoading(false);
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);   // 1 min refresh
    return () => clearInterval(t);
  }, []);

  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon fontSize="small" color="primary" />
            <Typography variant="h6">AI 操作日记</Typography>
          </Box>
          <Tooltip title="刷新">
            <IconButton size="small" onClick={load} disabled={loading}>
              {loading ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Box>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          最近 AI 自动改了什么 (调参 / 闪测 / 还原 / 上线)，每分钟自动刷新
        </Typography>

        {items.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
            暂无 AI 活动记录
          </Typography>
        ) : (
          <List dense disablePadding sx={{ maxHeight: 320, overflow: 'auto' }}>
            {items.map((it, idx) => (
              <React.Fragment key={it.id}>
                <ListItem sx={{ px: 0, py: 0.5 }}>
                  <Stack direction="row" spacing={1} sx={{ width: '100%', alignItems: 'flex-start' }}>
                    <Chip
                      label={EVENT_LABEL[it.event_type] || it.event_type}
                      size="small"
                      color={EVENT_COLOR[it.event_type] || 'default'}
                      sx={{ minWidth: 110, fontSize: '0.7rem' }}
                    />
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
                        {it.summary}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatRelTime(it.created_at)}
                      </Typography>
                    </Box>
                  </Stack>
                </ListItem>
                {idx < items.length - 1 && <Divider />}
              </React.Fragment>
            ))}
          </List>
        )}
      </CardContent>
    </Card>
  );
}
