// Phase 12.23: 隐私政策
import React from 'react';
import LegalPage from '../components/LegalPage';

const SECTIONS = [
  {
    heading: '收集的信息 · Information We Collect',
    paragraphs: [
      '我们仅收集服务正常运转所必需的信息：',
    ],
    list: [
      '<strong>账户信息</strong> — 邮箱、bcrypt 哈希密码（不存明文）、订阅 tier',
      '<strong>OKX API credentials</strong> — 用 <code>AES-256-GCM (Fernet)</code> 加密存 DB',
      '<strong>LLM API key</strong>（Pro 用户）— 同 Fernet 加密',
      '<strong>策略数据</strong> — 用户配置的策略 / params / 回测结果',
      '<strong>交易记录</strong> — 通过用户 OKX key 执行的 orders / trades / positions',
      '<strong>系统日志</strong> — audit log、错误日志、性能指标',
      '<strong>付款记录</strong> — USDT 链上 tx hash、订阅周期',
    ],
  },
  {
    heading: '不收集 · We Do NOT Collect',
    paragraphs: [
      '我们<strong>不</strong>收集：',
    ],
    list: [
      '身份证 / 护照 / KYC 资料',
      '银行卡 / 信用卡 / 银行账号',
      '手机号 / 实名信息',
      '生物特征（指纹 / 面部）',
      '浏览器 fingerprint / 第三方 cookie / 广告 ID',
      '用户在其他平台的数据',
    ],
  },
  {
    heading: '信息使用 · How We Use',
    paragraphs: [
      '收集的信息仅用于：',
    ],
    list: [
      '提供服务（策略运行、回测、AI 分析、Telegram 通知）',
      '账户安全（防滥用、防 brute-force 登录）',
      '账单（USDT 订阅识别、tier 升降级）',
      '产品改进（聚合匿名化数据分析功能使用情况）',
      '法律合规（响应执法机关 lawful request）',
    ],
  },
  {
    heading: '数据安全 · Security',
    paragraphs: [
      '我们采用业内标准实践保护用户数据：',
    ],
    list: [
      '<strong>静态加密</strong> — OKX / LLM credentials 用 Fernet AES-256-GCM',
      '<strong>传输加密</strong> — HTTPS / TLS 1.3',
      '<strong>密码哈希</strong> — bcrypt cost 12，不可逆',
      '<strong>API 鉴权</strong> — JWT + system token，scoped query',
      '<strong>访问控制</strong> — admin 看不到普通 user 的 OKX key 明文',
      '<strong>备份加密</strong> — DB 备份 gzip，存独立位置',
    ],
    paragraphs2: ['但<strong>没有系统是 100% 安全的</strong>。用户须妥善保管账户密码，开启 OKX API 的 trade scope 时建议限定 IP 白名单。'],
  },
  {
    heading: '不卖数据 · We Do NOT Sell Data',
    paragraphs: [
      '我们<strong>不</strong>出售、不分享、不交换用户个人数据给任何第三方（不包括下列必要情况）：',
    ],
    list: [
      '<strong>交易所</strong>（OKX）— 仅通过用户自己绑定的 API key 调用，必要的下单 / 拉余额',
      '<strong>LLM provider</strong>（Anthropic / OpenAI / Gemini）— Pro 用户调 AI features 时把 prompt + 必要上下文发给用户自己绑的 LLM key',
      '<strong>USDT 网络节点</strong>（TRON / Ethereum）— 验证用户付款 tx',
      '<strong>邮件服务</strong>（如使用第三方 SMTP）— 仅发送系统通知',
      '<strong>执法机关</strong>（lawful request）— 在收到正式司法 / 行政命令时配合',
    ],
  },
  {
    heading: '匿名聚合数据 · Anonymized Aggregates',
    paragraphs: [
      '我们可能使用<strong>聚合</strong>且<strong>不可识别到个人</strong>的数据用于：',
    ],
    list: [
      '产品改进（"30% 用户使用 Ichimoku 策略"）',
      'AI prompt 优化（统计哪些 candidate 通过 OOS Sharpe，提炼成功模式）',
      '公开市场报告（不含任何用户具体策略 / 仓位 / PnL）',
    ],
    paragraphs2: ['这些数据剥离 <code>user_id</code> 及其他标识，无法还原到个人。'],
  },
  {
    heading: 'Cookie 与跟踪 · Cookies',
    paragraphs: [
      '我们仅使用<strong>必需的 cookie</strong>：',
    ],
    list: [
      '<code>quant_api_token</code> — JWT，仅用于登录状态保持',
      '会话 cookie — 浏览器关闭即失效',
    ],
    paragraphs2: ['我们<strong>不</strong>使用 Google Analytics、Mixpanel、Facebook Pixel 等第三方跟踪。'],
  },
  {
    heading: '用户权利 · Your Rights',
    paragraphs: [
      '用户随时可以：',
    ],
    list: [
      '<strong>查看</strong> — Settings 页查看账户数据',
      '<strong>导出</strong> — 邮件申请导出全部数据（含策略 / trades / audit log），7 天内提供',
      '<strong>修改</strong> — 修改邮箱 / 密码 / OKX key',
      '<strong>删除</strong> — 邮件申请删除账户（保留账单数据 7 年合规要求，其他立即删除）',
      '<strong>撤销同意</strong> — 取消订阅 + 删除账户即视为完全撤销',
    ],
  },
  {
    heading: '未成年人 · Minors',
    paragraphs: [
      '本服务<strong>不向 18 岁以下用户提供</strong>。如发现未成年人注册，将立即删除账户和数据，且不退还任何已付费用。',
    ],
  },
  {
    heading: '联系方式 · Contact',
    paragraphs: [
      '隐私问题或数据请求联系：<code>vincenzo000915@gmail.com</code>',
      '邮件主题请注明 <strong>[Privacy Request]</strong>，我们 7 天内回复。',
    ],
  },
];

export default function Privacy() {
  return (
    <LegalPage
      title="隐私政策 · Privacy Policy"
      subtitle="我们只收集服务运转必需的数据，不卖、不滥用、不跟踪"
      lastUpdated="2026-05-22"
      sections={SECTIONS}
    />
  );
}
