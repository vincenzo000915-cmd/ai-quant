// Phase 12.23: 服务条款 — USDT 订阅版
import React from 'react';
import LegalPage from '../components/LegalPage';

const SECTIONS = [
  {
    heading: '服务性质 · Service Nature',
    paragraphs: [
      '本服务（"<strong>Quant Pro</strong>"，下称"我们"）是<strong>软件工具租赁服务（SaaS）</strong>，提供量化交易策略池、回测引擎、风险控制、AI 辅助分析等技术工具。',
      '我们<strong>不是</strong>投资顾问 / 资产管理 / 信托 / 经纪商。我们<strong>不</strong>持有用户资金、<strong>不</strong>替用户下单、<strong>不</strong>提供任何形式的投资建议或盈利保证。所有交易由用户通过自己绑定的交易所 API（OKX）执行，资金始终在用户自己的交易所账户内。',
    ],
  },
  {
    heading: '不构成投资建议 · No Investment Advice',
    paragraphs: [
      '本平台展示的任何策略、回测数据、AI 生成的分析、Telegram 通知、Dashboard 内容均<strong>不构成投资建议、要约或推荐</strong>。',
      '过往回测表现不代表未来收益。<strong>70% 量化散户首年亏损</strong>是行业基线现实。用户须独立判断、自行承担风险。',
    ],
  },
  {
    heading: '账户与订阅 · Account & Subscription',
    paragraphs: [
      '注册后可<strong>免费浏览</strong>系统 UI 和 demo 数据，但实际使用功能（新增策略 / LIVE 实盘 / 回测 / AI features）需订阅 <strong>Basic 及以上</strong> tier，最少订阅 1 个月。',
      '订阅周期内功能完整解锁。订阅期满前未续费的账户会在宽限期（7 天）后自动降级为 Preview 模式（保留账户但功能锁住）。',
    ],
    list: [
      '<strong>Basic</strong> — $50 USDT / 月，工具基础包',
      '<strong>Pro</strong> — $125 USDT / 月，含 AI features + BYO LLM key',
      '<strong>Team</strong> — $250+ USDT / 月，多账户 + 团队功能',
      '预付折扣：3 月 -10% / 6 月 -20% / 1 年 -30%',
    ],
  },
  {
    heading: '付款方式 · Payment',
    paragraphs: [
      '订阅费仅支持 <strong>USDT (TRC20 / ERC20)</strong> 链上付款。我们不接受法币、信用卡、PayPal 等其他支付方式。',
      'USDT 链上交易<strong>不可逆</strong>。请务必确认订阅 tier 和周期再付款。误付的资金<strong>无法退还</strong>。',
    ],
  },
  {
    heading: '不退款政策 · No Refunds',
    paragraphs: [
      '所有 USDT 订阅<strong>一经付款不予退款</strong>，包括但不限于：',
    ],
    list: [
      '用户主动取消订阅 — 订阅期内已付款项不退',
      '用户因策略亏损要求退款 — 软件工具费跟策略盈亏无关',
      '用户因不满产品功能 — 注册时已免费浏览 7 天 demo，付款前应充分了解',
      '账户被暂停或终止（因违反本条款）— 已付订阅期不退',
      '付错 tier / 付错周期 — USDT 链上不可逆，请付款前确认',
    ],
  },
  {
    heading: '服务原样提供 · AS-IS',
    paragraphs: [
      '服务按"现状（AS-IS）"提供。我们<strong>不保证</strong>：',
    ],
    list: [
      '服务永远可用、不中断、无 bug',
      '策略能盈利（回测好的策略未必能在未来市场盈利）',
      'AI 生成的内容准确、完整、可靠',
      '与交易所（OKX）的 API 集成永久兼容',
      '在所有司法管辖区合法可用',
    ],
  },
  {
    heading: '用户责任 · User Responsibility',
    paragraphs: [
      '用户须对以下事项<strong>独立负责</strong>：',
    ],
    list: [
      '<strong>资金安全</strong> — 本地保管 OKX API key、自检 LIVE 模式风险、设置合理 SL/TP',
      '<strong>策略选择</strong> — 启用哪些策略、什么参数、什么 symbol 完全由用户决定',
      '<strong>风险管理</strong> — 杠杆倍数、单笔仓位、止损规则、daily loss cap 全由用户配置',
      '<strong>合规</strong> — 用户所在司法管辖区对加密货币交易、量化工具使用的合规性',
      '<strong>账户安全</strong> — 妥善保管账户密码、不分享 OKX key',
    ],
  },
  {
    heading: '暂停 / 终止 · Suspension & Termination',
    paragraphs: [
      '我们保留<strong>立即暂停或终止</strong>账户的权利，在以下情况下：',
    ],
    list: [
      '违反本条款或退款政策',
      '滥用服务（自动化注册多账号、攻击系统、爬取数据等）',
      '欺诈、虚假宣传、利用服务从事违法活动',
      '所在司法管辖区对服务有限制（OFAC 制裁地区等）',
      '长期 (90+ 天) 未活跃的免费账户',
    ],
    paragraphs2: ['账户被暂停 / 终止时，剩余订阅期<strong>不予退款</strong>。'],
  },
  {
    heading: '数据 · Data',
    paragraphs: [
      '用户的 OKX API key 使用 <code>AES-256-GCM (Fernet)</code> 加密存于数据库，解密 key 仅在 Celery worker 内存中使用，不写磁盘。',
      '用户的策略代码、回测结果、交易历史等仅本人可见。我们<strong>不出售用户数据</strong>。',
      '匿名化后的回测数据（剥离 user_id）可能用于产品改进、AI 训练数据筛选。具体详见 <a href="/privacy" style="color:#a78bfa">隐私政策</a>。',
    ],
  },
  {
    heading: '司法管辖与限制 · Jurisdiction',
    paragraphs: [
      '本服务可能对以下地区的用户不提供：<strong>美国、中国大陆、北朝鲜、伊朗、叙利亚</strong>及 OFAC 制裁名单地区。用户须自行确认所在地区使用本服务的合规性。',
      '任何争议适用<strong>新加坡法律</strong>，由新加坡国际仲裁中心（SIAC）仲裁解决。',
    ],
  },
  {
    heading: '条款变更 · Changes',
    paragraphs: [
      '我们可能不定期更新本条款。重大变更会在 Dashboard 显著位置通知用户。继续使用服务视为接受新条款。',
      '联系：<code>vincenzo000915@gmail.com</code>',
    ],
  },
];

export default function Terms() {
  return (
    <LegalPage
      title="服务条款 · Terms of Service"
      subtitle="使用 Quant Pro 服务前请仔细阅读本条款"
      lastUpdated="2026-05-22"
      sections={SECTIONS}
    />
  );
}
