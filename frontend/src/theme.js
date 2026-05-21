// Phase 12.15.3: 統一 theme constants — 取代散在各 component 的 inline color hex
//
// 設計方向：dark navy + slate + 1 個 accent (cyan)，pnl 紅綠，其他中性。
// 減 neon / 減 glow / 減多色。SaaS-grade「乾淨可信」感而非 cyberpunk demo。

export const palette = {
  // 背景層次
  bg: '#0a0e1a',          // 主背景 dark navy
  bgDeep: '#070a13',
  surface: '#10172b',     // panel 表面
  surface2: '#1a2240',    // hover / 次級表面
  surfaceSubtle: 'rgba(255,255,255,0.02)',

  // 邊框
  border: 'rgba(148,163,184,0.12)',
  borderHot: 'rgba(148,163,184,0.24)',
  borderAccent: 'rgba(6,182,212,0.3)',

  // 文字
  text: '#e2e8f0',
  textMuted: '#94a3b8',
  textFaint: '#64748b',
  textDim: '#475569',

  // 主 accent — cyan 不太刺眼，作為 hero 主色
  accent: '#06b6d4',
  accentDim: '#0891b2',
  accentGlow: 'rgba(6,182,212,0.18)',

  // 暖 accent — 給「人情味」 dashboard 用 (Phase 12.15.3 user 反饋太冷)
  warmAccent: '#fb923c',    // 暖橙
  warmAccentDim: '#ea580c',

  // 狀態色 — 採柔和飽和度而非霓虹
  success: '#10b981',     // 暗綠 (比 #22c55e 柔和)
  error: '#f43f5e',       // 玫瑰紅 (比 #ef4444 暖)
  warning: '#f59e0b',     // 琥珀
  info: '#6366f1',

  // PnL 專用
  pnlPositive: '#10b981',
  pnlNegative: '#f43f5e',
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

// 狀態 chip 顏色 map（StatusChip 用）
export const statusColors = {
  running:  { bg: 'rgba(34,197,94,0.12)',  fg: palette.success, label: '运行中' },
  stopped:  { bg: 'rgba(148,163,184,0.1)', fg: palette.textMuted, label: '已停止' },
  paused:   { bg: 'rgba(245,158,11,0.12)', fg: palette.warning, label: '已暂停' },
  retired:  { bg: 'rgba(100,116,139,0.1)', fg: palette.textFaint, label: '已退役' },
  pending:  { bg: 'rgba(99,102,241,0.1)',  fg: palette.info, label: '待处理' },
  qualified:{ bg: 'rgba(6,182,212,0.12)',  fg: palette.accent, label: '已合格' },
  rejected: { bg: 'rgba(239,68,68,0.1)',   fg: palette.error, label: '已拒绝' },
  error:    { bg: 'rgba(239,68,68,0.12)',  fg: palette.error, label: '错误' },
  translated:{ bg: 'rgba(168,85,247,0.12)', fg: '#a855f7', label: '已翻译' },
  backtesting:{ bg: 'rgba(245,158,11,0.12)', fg: palette.warning, label: '回测中' },
  promoted: { bg: 'rgba(34,197,94,0.1)',   fg: palette.success, label: '已上线' },
  open:     { bg: 'rgba(34,197,94,0.1)',   fg: palette.success, label: '开仓中' },
  closed:   { bg: 'rgba(148,163,184,0.1)', fg: palette.textMuted, label: '已平' },
};

export default { palette, radii, spacing, typo, pnlColor, statusColors };
