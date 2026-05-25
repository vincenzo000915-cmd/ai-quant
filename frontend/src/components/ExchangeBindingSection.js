// Phase 14k-7: 智能交易所绑定区 + 一键自动切换
// 非 team user 已绑 OKX 时, 也显示 HL 卡 (顶 banner "保存即切换 + 迁 N 策略")
// 反向同理. 不需要手动解绑.
// team user: 两张都显示, 互不干扰.

import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Alert, Snackbar,
} from '@mui/material';
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium';
import OkxBindingCard from './OkxBindingCard';
import HyperliquidBindingCard from './HyperliquidBindingCard';

const PURPLE = '#a78bfa';

export default function ExchangeBindingSection() {
  const [binding, setBinding] = useState(null);
  const [strategyCounts, setStrategyCounts] = useState({ okx: 0, hyperliquid: 0 });
  const [switchToast, setSwitchToast] = useState(null);   // {message, severity}

  const refresh = useCallback(async () => {
    try {
      const [bindRes, stratRes] = await Promise.all([
        fetch('/api/me/exchange-binding').then(r => r.json()),
        fetch('/api/strategies').then(r => r.json()).catch(() => []),
      ]);
      setBinding(bindRes);
      const counts = { okx: 0, hyperliquid: 0 };
      (stratRes || []).forEach(s => {
        const ex = (s.exchange || 'okx').toLowerCase();
        if (counts[ex] != null) counts[ex]++;
      });
      setStrategyCounts(counts);
    } catch {}
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // 子卡保存成功 (含 switch) 时回调
  const handleSaved = useCallback((data) => {
    if (data?.switch) {
      setSwitchToast({
        severity: 'success',
        message: data.switch.message || '切换完成',
      });
    }
    refresh();
  }, [refresh]);

  if (!binding) return null;

  const { bound, is_team } = binding;

  // ─── Team / Admin: 两张并列, 互不影响 ───
  if (is_team) {
    return (
      <Box>
        <Alert severity="info" icon={<WorkspacePremiumIcon />} sx={{ mb: 2 }}>
          <strong>团队版 / Admin</strong> — 可同时绑定 OKX 和 Hyperliquid, 每个策略可指定单独的交易所.
        </Alert>
        <OkxBindingCard onSaved={handleSaved} />
        <HyperliquidBindingCard onSaved={handleSaved} />
        {switchToast && (
          <Snackbar open autoHideDuration={5000} onClose={() => setSwitchToast(null)}>
            <Alert severity={switchToast.severity} onClose={() => setSwitchToast(null)}>{switchToast.message}</Alert>
          </Snackbar>
        )}
      </Box>
    );
  }

  // ─── 普通 user ───
  // - 没绑过 → 两张卡都显, 都是 fresh 绑定
  // - 绑了 OKX → 两张卡都显, HL 卡顶 banner "保存即切换 + 迁 N 策略"
  // - 绑了 HL → 反向同理
  const otherExchange = bound[0] === 'okx' ? 'hyperliquid' : (bound[0] === 'hyperliquid' ? 'okx' : null);
  const migrateCount = otherExchange ? strategyCounts[bound[0]] : 0;

  const switchHintForCard = (cardExchange) => {
    // 这张卡是 user 没绑的那个 → 显切换 banner
    if (bound.length === 1 && cardExchange === otherExchange && cardExchange !== bound[0]) {
      const fromName = bound[0] === 'okx' ? 'OKX' : 'Hyperliquid';
      const toName = cardExchange === 'okx' ? 'OKX' : 'Hyperliquid';
      return (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          🔄 <strong>保存即一键切换</strong>: 此操作将自动解绑 <strong>{fromName}</strong> +
          把 <strong>{migrateCount}</strong> 个 {fromName} 策略迁移到 <strong>{toName}</strong>.
          {migrateCount === 0 && ' (你没有 ' + fromName + ' 策略, 切换无影响)'}
        </Alert>
      );
    }
    return null;
  };

  return (
    <Box>
      {!bound.length && (
        <Alert severity="info" sx={{ mb: 2 }}>
          普通账户限定 1 个交易所. 绑哪个都行, 后期想换直接绑另一个即可 (系统自动迁移策略).
        </Alert>
      )}

      <Box>
        {switchHintForCard('okx')}
        <OkxBindingCard onSaved={handleSaved} />
      </Box>

      <Box>
        {switchHintForCard('hyperliquid')}
        <HyperliquidBindingCard onSaved={handleSaved} />
      </Box>

      {switchToast && (
        <Snackbar open autoHideDuration={5000} onClose={() => setSwitchToast(null)}>
          <Alert severity={switchToast.severity} onClose={() => setSwitchToast(null)}>{switchToast.message}</Alert>
        </Snackbar>
      )}
    </Box>
  );
}
