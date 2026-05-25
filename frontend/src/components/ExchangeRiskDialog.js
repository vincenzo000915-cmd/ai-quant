// Phase 14k-6: 交易所风险声明 dialog (OKX / Hyperliquid 共用)
// 不强制弹窗 — 在绑定卡底部以小字链接呈现, 点开看
// 目的: 法律免责 + user 知情决策

import React from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
  Typography, Box, List, ListItem, ListItemIcon, ListItemText,
  Chip, Divider, Alert,
} from '@mui/material';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import GppMaybeIcon from '@mui/icons-material/GppMaybe';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import HubIcon from '@mui/icons-material/Hub';
import TimerOffIcon from '@mui/icons-material/TimerOff';
import GavelIcon from '@mui/icons-material/Gavel';

const OKX_RISKS = [
  {
    icon: <AccountBalanceIcon sx={{ color: '#f87171' }} />,
    title: '托管风险 (FTX 教训)',
    desc: 'OKX 是中心化交易所, 你的 USDT 实际存在 OKX 公司钱包. 若公司破产 / 挪用客户资产 (FTX 2022), 资金可能无法追回. 建议盈利定期提到自有钱包.',
  },
  {
    icon: <GavelIcon sx={{ color: '#fbbf24' }} />,
    title: '监管 / KYC 冻结',
    desc: 'OKX 接受多国监管. 美国 OFAC / 中国监管 / 当地税务都可能要求 OKX 冻结特定账户. KYC 不通过会被风控限制提币.',
  },
  {
    icon: <GppMaybeIcon sx={{ color: '#fbbf24' }} />,
    title: 'API key 泄漏',
    desc: '你绑给系统的 API key 拥有 Trade 权限. 系统已 AES-256 加密存储 + 不写 log, 但极端情况 (服务器被黑 / 内部威胁) 仍可能泄漏. 建议: OKX 后台限定 API IP 白名单 + 不开启提币权限.',
  },
  {
    icon: <WarningAmberIcon sx={{ color: '#94a3b8' }} />,
    title: '系统下单失败 / 滑点',
    desc: 'OKX API 偶尔限频或宕机. 系统会重试 + Telegram 告警, 但极端行情可能错过止损. 建议手动监控大仓位.',
  },
];

const HL_RISKS = [
  {
    icon: <HubIcon sx={{ color: '#f87171' }} />,
    title: 'Bridge 合约风险',
    desc: 'Hyperliquid 用 Arbitrum 上一个 custodial bridge 合约保管 USDC. 历史上类似 bridge 被黑过 9 位数 (Wormhole / Ronin 2022). HL bridge 审计过但审计无法保 100%.',
  },
  {
    icon: <WarningAmberIcon sx={{ color: '#f87171' }} />,
    title: '链 halt',
    desc: 'HL 是独立 L1, 仅 ~16-21 个验证者. 验证者出 bug / 网络分区时, 整条链可能停几小时到几天 (参考 Solana 历史 halt). 期间无法交易也无法提款.',
  },
  {
    icon: <GavelIcon sx={{ color: '#fbbf24' }} />,
    title: '验证者治理 (JELLY 2025-03)',
    desc: '2025-03 HL 验证者集体投票手动结算 JELLY 代币并 delist, 证明验证者有权力推翻正常交易规则. 你的 USDC 安全, 但极端情况持仓收益可能被强制平在不利价.',
  },
  {
    icon: <TimerOffIcon sx={{ color: '#fbbf24' }} />,
    title: 'Agent 180 天到期',
    desc: 'HL agent wallet 默认 180 天有效, 过期后自动交易停 (系统会提前 14 天 Telegram 警告 + UI 红色). 过期需 user 主钱包重新签名授权.',
  },
  {
    icon: <GppMaybeIcon sx={{ color: '#94a3b8' }} />,
    title: '团队/治理风险',
    desc: 'HL 团队握 ~70% 代币 + 全部验证者. 团队若抛弃项目 / 被美国制裁, bridge 可能被冻结, 所有用户提款受影响 (类似 Tornado Cash 2022).',
  },
];

const ADVICE = [
  { tier: '< $1k', text: '直接用, 损失上限可控' },
  { tier: '$1k - $10k', text: '可以用, 但每周 withdraw 一次盈利到自己钱包' },
  { tier: '$10k - $50k', text: '分散 — 交易所部分 + 冷钱包部分' },
  { tier: '$50k+', text: '不要 all-in 任何单一交易所, 跨 2-3 个 + 冷钱包' },
];

export default function ExchangeRiskDialog({ open, onClose, exchange = 'okx' }) {
  const isHL = exchange === 'hyperliquid';
  const risks = isHL ? HL_RISKS : OKX_RISKS;
  const title = isHL ? 'Hyperliquid 交易风险' : 'OKX 交易风险';
  const color = isHL ? '#a78bfa' : '#60a5fa';

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ borderBottom: `2px solid ${color}33`, fontWeight: 700 }}>
        ⚠️ {title}
      </DialogTitle>
      <DialogContent dividers>
        <Alert severity="warning" sx={{ mb: 2 }}>
          交易加密货币本身有风险 (价格波动 + 杠杆). 此外, 不同交易所有不同的「平台风险」.
          阅读以下条款并理解后再绑定.
        </Alert>

        <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
          {isHL ? 'Hyperliquid 平台特有风险' : 'OKX 平台特有风险'}
        </Typography>
        <List dense>
          {risks.map((r, i) => (
            <ListItem key={i} sx={{ alignItems: 'flex-start', py: 1.2 }}>
              <ListItemIcon sx={{ minWidth: 36, mt: 0.5 }}>{r.icon}</ListItemIcon>
              <ListItemText
                primary={<Typography variant="body2" fontWeight={700}>{r.title}</Typography>}
                secondary={<Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.3 }}>{r.desc}</Typography>}
              />
            </ListItem>
          ))}
        </List>

        <Divider sx={{ my: 2 }} />

        <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
          💡 资金管理建议
        </Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 0.8 }}>
          {ADVICE.map((a, i) => (
            <React.Fragment key={i}>
              <Chip label={a.tier} size="small" sx={{ fontWeight: 700, justifySelf: 'start' }} />
              <Typography variant="body2" color="text.secondary">{a.text}</Typography>
            </React.Fragment>
          ))}
        </Box>

        <Divider sx={{ my: 2 }} />

        <Alert severity="info">
          <strong>本系统的角色</strong>: 量化执行工具, 不持有你的资金, 不替你做交易决策.
          所有交易由你提供的 API key / agent 主动签名发起.
          系统不对交易所平台风险负责.
        </Alert>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>我已阅读并理解</Button>
      </DialogActions>
    </Dialog>
  );
}
