// Phase 14k-5: 智能交易所绑定区
// - 非 team user: 只能绑 1 个 (OKX OR HL 互斥)
//   · 都没绑 → 显示二选一 segment + 对应卡
//   · 已绑 → 只显示绑了那个的卡
// - team user: 两张卡都显示, 可绑多个

import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, CardContent, Typography, Box, ToggleButton, ToggleButtonGroup,
  Alert, Chip, Tooltip, Stack,
} from '@mui/material';
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium';
import OkxBindingCard from './OkxBindingCard';
import HyperliquidBindingCard from './HyperliquidBindingCard';

const PURPLE = '#a78bfa';

export default function ExchangeBindingSection() {
  const [binding, setBinding] = useState(null);    // {bound, primary, is_team, can_bind_multi}
  const [picked, setPicked] = useState('okx');     // 当 bound=[] 时让 user 选哪个

  const refresh = useCallback(async () => {
    try {
      const r = await fetch('/api/me/exchange-binding');
      if (r.ok) {
        const data = await r.json();
        setBinding(data);
        if (data.bound?.length === 1) {
          setPicked(data.bound[0]);
        } else if (!data.bound?.length) {
          setPicked('okx');    // 默认从 OKX 起
        }
      }
    } catch {}
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  if (!binding) return null;

  const { bound, is_team } = binding;

  // ─── Team / Admin: 两张都显示, 顺便提示能多绑 ───
  if (is_team) {
    return (
      <Box>
        <Alert severity="info" icon={<WorkspacePremiumIcon />} sx={{ mb: 2 }}>
          <strong>团队版 / Admin</strong> — 可同时绑定 OKX 和 Hyperliquid, 每个策略可指定单独的交易所.
        </Alert>
        <OkxBindingCard />
        <HyperliquidBindingCard />
      </Box>
    );
  }

  // ─── 普通 user: 单绑 ───
  // 已绑某个 → 只显示该卡 + 提示
  if (bound.length === 1) {
    const cur = bound[0];
    const other = cur === 'okx' ? 'Hyperliquid' : 'OKX';
    return (
      <Box>
        <Alert severity="success" sx={{ mb: 2 }}>
          已绑定 <strong>{cur === 'okx' ? 'OKX' : 'Hyperliquid'}</strong>.
          想换到 <strong>{other}</strong>? 先解绑当前, 或 <Tooltip title="团队版可同时绑定多个交易所" arrow><span style={{ color: PURPLE, fontWeight: 600 }}>升级团队版</span></Tooltip>.
        </Alert>
        {cur === 'okx' ? <OkxBindingCard /> : <HyperliquidBindingCard />}
      </Box>
    );
  }

  // 还没绑 → 让 user 二选一
  return (
    <Box>
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
            选择你的交易所
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            普通账户限定 1 个交易所. 选好后绑定 API key 即可开始交易.
            {' '}
            <Tooltip title="团队版可同时绑定 OKX + Hyperliquid, 适合多账户运营" arrow>
              <Chip
                icon={<WorkspacePremiumIcon sx={{ fontSize: 14 }} />}
                label="想多绑?升级团队版"
                size="small"
                sx={{ bgcolor: `${PURPLE}22`, color: PURPLE, cursor: 'help' }}
              />
            </Tooltip>
          </Typography>
          <ToggleButtonGroup
            value={picked}
            exclusive
            onChange={(_, v) => v && setPicked(v)}
            size="small"
            sx={{ mb: 1 }}
          >
            <ToggleButton value="okx" sx={{ px: 3 }}>
              <Stack alignItems="flex-start" spacing={0.3}>
                <Typography variant="body2" fontWeight={700}>OKX</Typography>
                <Typography variant="caption" color="text.secondary">CEX · 永续合约</Typography>
              </Stack>
            </ToggleButton>
            <ToggleButton value="hyperliquid" sx={{ px: 3 }}>
              <Stack alignItems="flex-start" spacing={0.3}>
                <Typography variant="body2" fontWeight={700} sx={{ color: PURPLE }}>Hyperliquid</Typography>
                <Typography variant="caption" color="text.secondary">DEX · 手续费低 50%+</Typography>
              </Stack>
            </ToggleButton>
          </ToggleButtonGroup>
        </CardContent>
      </Card>

      {picked === 'okx' ? <OkxBindingCard /> : <HyperliquidBindingCard />}
    </Box>
  );
}
