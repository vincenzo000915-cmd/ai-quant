// Phase 12.20: AI 金融科技風 — 紫主調 (Hyperliquid / Phantom Wallet 風)
//
// 設計方向：dark navy + slate + **紫主 accent** #a78bfa，PnL 紅綠保留。
// 紫 = AI 駕駛感 + 量化身份。glow 只在 AI 在做事的地方（精緻 highlight，不是 neon 散光）。
// 刪 cyberpunk 裝飾（NeuralBackdrop / 多色 CornerAccent）。資訊密度生產專業感。

export const palette = {
  // 背景層次
  bg: '#0a0e1a',          // 主背景 dark navy
  bgDeep: '#070a13',
  surface: 'rgba(16, 23, 43, 0.88)',
  surface2: 'rgba(26, 34, 64, 0.92)',
  surfaceSubtle: 'rgba(255,255,255,0.02)',

  // 邊框（紫调 — AI accent 全局，加深让紫色身份更明显）
  border: 'rgba(167, 139, 250, 0.18)',
  borderHot: 'rgba(167, 139, 250, 0.36)',
  borderAccent: 'rgba(167, 139, 250, 0.55)',

  // 文字
  text: '#e2e8f0',
  textMuted: '#94a3b8',
  textFaint: '#64748b',
  textDim: '#475569',

  // 主 accent — 紫罗兰 (AI 量化身份)
  accent: '#a78bfa',
  accentDim: '#7c3aed',
  accentGlow: 'rgba(167, 139, 250, 0.28)',
  accentBright: '#c4b5fd',

  // 暖 accent — 留給 warning / 個別 category（gold 不再做主色）
  warmAccent: '#f7a600',
  warmAccentDim: '#d68900',
  warmAccentGlow: 'rgba(247,166,0,0.2)',

  // AI 字段保留兼容（alias 到 accent — 同一种紫）
  ai: '#a78bfa',
  aiDim: '#7c3aed',
  aiGlow: 'rgba(167, 139, 250, 0.35)',
  aiBg: 'rgba(167, 139, 250, 0.08)',

  // 狀態色 — 金融科技風偏鮮明對比（不再柔和暗綠）
  success: '#00d4aa',     // Robinhood teal-green
  successGlow: 'rgba(0,212,170,0.25)',
  error: '#ff4757',       // 鮮艳紅但不刺眼
  errorGlow: 'rgba(255,71,87,0.25)',
  warning: '#f7a600',
  info: '#6366f1',

  // PnL 專用 — 強對比，這是交易工具最重要的數據
  pnlPositive: '#00d4aa',
  pnlNegative: '#ff4757',
  pnlNeutral: '#94a3b8',
};

export const radii = {
  sm: 6,
  md: 8,
  lg: 12,
  xl: 16,
};

export const spacing = {
  xs: 6,
  sm: 10,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
};

export const typo = {
  mono: '"JetBrains Mono", "Roboto Mono", "SF Mono", Menlo, monospace',
  sans: '"Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',

  // 標準字號（SaaS 級節制）
  display: { fontSize: '2rem', fontWeight: 700, lineHeight: 1.1, letterSpacing: '-0.02em' },
  h1:      { fontSize: '1.5rem', fontWeight: 700, lineHeight: 1.2, letterSpacing: '-0.01em' },
  h2:      { fontSize: '1.25rem', fontWeight: 700, lineHeight: 1.3 },
  h3:      { fontSize: '1rem', fontWeight: 600, lineHeight: 1.4 },
  body:    { fontSize: '0.875rem', fontWeight: 400, lineHeight: 1.5 },
  caption: { fontSize: '0.75rem', fontWeight: 400, lineHeight: 1.4, color: '#94a3b8' },
  label:   { fontSize: '0.6875rem', fontWeight: 600, lineHeight: 1.2, letterSpacing: '0.06em', textTransform: 'uppercase' },

  // 數據專用（mono）
  metric:  { fontSize: '1.75rem', fontWeight: 700, lineHeight: 1.1, fontFamily: '"JetBrains Mono", monospace', letterSpacing: '-0.02em' },
  metricSm:{ fontSize: '1.125rem', fontWeight: 700, lineHeight: 1.1, fontFamily: '"JetBrains Mono", monospace' },
};

// PnL 顏色 helper
export const pnlColor = (v) => {
  if (v == null || v === 0) return palette.pnlNeutral;
  return v > 0 ? palette.pnlPositive : palette.pnlNegative;
};

// 狀態 chip 顏色 map（StatusChip 用）— 沿用新金融科技色
export const statusColors = {
  running:  { bg: 'rgba(0,212,170,0.12)',   fg: palette.success, label: '运行中' },
  stopped:  { bg: 'rgba(148,163,184,0.1)',  fg: palette.textMuted, label: '已停止' },
  paused:   { bg: 'rgba(247,166,0,0.12)',   fg: palette.warning, label: '已暂停' },
  retired:  { bg: 'rgba(100,116,139,0.1)',  fg: palette.textFaint, label: '已退役' },
  pending:  { bg: 'rgba(99,102,241,0.1)',   fg: palette.info, label: '待处理' },
  qualified:{ bg: 'rgba(167,139,250,0.12)',   fg: palette.accent, label: '已合格' },
  rejected: { bg: 'rgba(255,71,87,0.1)',    fg: palette.error, label: '已拒绝' },
  error:    { bg: 'rgba(255,71,87,0.12)',   fg: palette.error, label: '错误' },
  translated:{ bg: 'rgba(168,85,247,0.12)', fg: '#a855f7', label: '已翻译' },
  backtesting:{ bg: 'rgba(247,166,0,0.12)', fg: palette.warning, label: '回测中' },
  promoted: { bg: 'rgba(0,212,170,0.1)',    fg: palette.success, label: '已上线' },
  open:     { bg: 'rgba(0,212,170,0.1)',    fg: palette.success, label: '开仓中' },
  closed:   { bg: 'rgba(148,163,184,0.1)',  fg: palette.textMuted, label: '已平' },
};

export default { palette, radii, spacing, typo, pnlColor, statusColors };
