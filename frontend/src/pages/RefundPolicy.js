// Phase 12.23: 退款政策 — USDT 不退款
import React from 'react';
import LegalPage from '../components/LegalPage';

const SECTIONS = [
  {
    heading: '核心原则 · Core Principle',
    paragraphs: [
      '<strong>Quant Pro 一经付款不予退款。</strong>本政策适用于所有订阅 tier（Basic / Pro / Team）和所有付款周期（月 / 季 / 半年 / 年）。',
      '我们采用 USDT 链上付款。USDT 交易在区块链上<strong>不可逆</strong>，技术层面无法追回。订阅前请充分使用免费 Preview 浏览功能验证产品再决定付费。',
    ],
  },
  {
    heading: '为什么不退款 · Why No Refunds',
    paragraphs: [
      '加密货币订阅 SaaS 普遍采用不退款政策，原因：',
    ],
    list: [
      '<strong>USDT 链上不可逆</strong> — 与法币不同，加密支付一旦确认无法撤销',
      '<strong>防滥用</strong> — 退款机制会被恶意用户利用（套用 → 退款 → 重新注册）',
      '<strong>注册即免费试用</strong> — 提供完整 Preview UI + demo 数据让用户付前充分验证',
      '<strong>不持有用户资金</strong> — 我们是工具提供商，不像交易所托管用户资金',
      '<strong>软件工具非投资产品</strong> — 工具费跟用户策略盈亏无关',
    ],
  },
  {
    heading: '哪些情况确实不退款 · Cases Not Eligible',
    paragraphs: [
      '以下情况<strong>明确不予退款</strong>：',
    ],
    list: [
      '用户主动取消订阅（订阅期内已付款项不退，但可使用至当前周期结束）',
      '用户因策略亏损要求退款 — 工具费跟交易结果无关',
      '用户因不满产品功能 — 注册时可免费 Preview 充分浏览',
      '账户被暂停或终止（违反 <a href="/terms" style="color:#a78bfa">服务条款</a> 或本政策）',
      '付错 tier、付错周期、付错链 — USDT 链上不可逆',
      '用户司法管辖区限制 — 用户须自行确认合规',
      '订阅期间产生的 LLM API 费用（用户 BYO key，token 费用直接付给 Anthropic / OpenAI / Gemini）',
    ],
  },
  {
    heading: '极少数例外 · Rare Exceptions',
    paragraphs: [
      '以下<strong>例外情况</strong>下，我们可能酌情处理（不构成承诺）：',
    ],
    list: [
      '<strong>系统重大故障</strong> — 服务持续不可用超过 7 天（不含已通知的维护），按比例补偿剩余订阅天数',
      '<strong>双重收费</strong> — 用户因技术故障导致同一周期重复付款，多付部分可退（需提供链上 tx hash）',
      '<strong>付款未到账</strong> — USDT 转账成功但系统未识别（通常发生在错链 / 错地址），我们尽力协助但<strong>不保证</strong>找回',
    ],
    paragraphs2: ['以上例外情况须用户主动联系 <code>vincenzo000915@gmail.com</code> 并提供完整链上证据。处理周期 7-14 工作日。'],
  },
  {
    heading: '取消订阅 · Cancellation',
    paragraphs: [
      '用户可随时取消订阅，操作：Settings → 订阅 → 取消自动续费。',
      '取消后：',
    ],
    list: [
      '当前订阅周期内继续享有完整功能直至周期结束',
      '周期结束后自动降级为 Preview 模式（保留账户但功能锁住）',
      '7 天宽限期内续费可保留所有数据；超过则进入冷存档（90 天后清理）',
      '已付款项<strong>不予退还</strong>',
    ],
  },
  {
    heading: '升级 / 降级 · Tier Changes',
    paragraphs: [
      '<strong>升级</strong>（Basic → Pro / Team）：按剩余天数比例计算差价，需补付 USDT 后立即生效。',
      '<strong>降级</strong>（Pro → Basic）：在当前订阅周期结束后生效，<strong>不退</strong>差价。',
    ],
  },
  {
    heading: '争议解决 · Disputes',
    paragraphs: [
      '如对本政策有异议，请优先邮件 <code>vincenzo000915@gmail.com</code> 协商。无法协商解决的，依 <a href="/terms" style="color:#a78bfa">服务条款</a> 走新加坡国际仲裁中心（SIAC）仲裁。',
      '<strong>用户不得</strong>通过链上诋毁、社交媒体攻击、虚假投诉等方式施压。此类行为会导致账户立即终止且<strong>不退余款</strong>。',
    ],
  },
];

export default function RefundPolicy() {
  return (
    <LegalPage
      title="退款政策 · Refund Policy"
      subtitle="USDT 订阅一经付款不予退款 — 注册时请充分使用 Preview 验证再决定订阅"
      lastUpdated="2026-05-22"
      sections={SECTIONS}
    />
  );
}
