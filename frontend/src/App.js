import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material';
import Layout from './components/Layout';
import AuthGate from './components/AuthGate';
import AiStream from './components/AiStream';
import Dashboard from './pages/Dashboard';
import Strategies from './pages/Strategies';
import Candidates from './pages/Candidates';
import Trades from './pages/Trades';
import Audit from './pages/Audit';
import Settings from './pages/Settings';
// Phase 12.23: USDT 订阅相关页面
import Pricing from './pages/Pricing';
import Checkout from './pages/Checkout';
import Terms from './pages/Terms';
import RefundPolicy from './pages/RefundPolicy';
import Privacy from './pages/Privacy';
import LandingPage from './pages/LandingPage';
import Login from './pages/Login';
import MarketingNav from './components/MarketingNav';
import UpgradeModal from './components/UpgradeModal';
import './auth';   // 全局 fetch wrap 副作用

const globalStyle = document.createElement('style');
globalStyle.textContent = `
  :root {
    /* Phase 12.15.6: 金融科技混合 — 取代 cyberpunk neon multi-color */
    --bg-void: #0a0e1a;
    --bg-deep: #070a13;
    --bg-mid: #10172b;
    --bg-surface: #10172b;
    --bg-surface-elevated: #1a2240;
    --bg-glass: rgba(16, 23, 43, 0.6);
    --border: rgba(148, 163, 184, 0.12);
    --border-hot: rgba(148, 163, 184, 0.24);
    --primary: #a78bfa;
    --primary-glow: rgba(167, 139, 250, 0.5);
    --accent: #a78bfa;
    --accent-glow: rgba(167, 139, 250, 0.4);
    /* Phase 12.25: 删 neon-pink (unused) — 留 neon-purple alias 给 brand 紫 */
    --neon-purple: #a78bfa;
    --gold: #f7a600;
    --gold-deep: #d68900;
    --warn-yellow: #f7a600;
    --success: #00d4aa;
    --error: #ff4757;
    --error-bright: #ff4757;
    --warning: #f7a600;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --text-faint: #64748b;
  }

  html, body, #root {
    background: var(--bg-void);
    color: var(--text);
    margin: 0;
    min-height: 100vh;
    overflow-x: hidden;
  }

  body {
    /* 純 dark navy + subtle 暖 cyan 一道光暈在右上 — 金融科技風 */
    background:
      radial-gradient(ellipse 50% 30% at 85% -5%, rgba(167,139,250,0.06), transparent 70%),
      linear-gradient(180deg, #0a0e1a 0%, #070a13 100%);
    background-attachment: fixed;
    font-feature-settings: 'tnum' 1, 'cv11' 1;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    position: relative;
  }

  /* === 網格背景（去掉 — 金融感不需要 cyberpunk 網格）=== */
  body::before {
    display: none;
  }

  /* CRT 條紋已移除 - GPU 開銷大 */

  /* === Scan line：只在進站時掃一次，避免持續 GPU 渲染 === */
  @keyframes scanline-once {
    0% { transform: translate3d(0, 0, 0); opacity: 0; }
    10% { opacity: 1; }
    90% { opacity: 1; }
    100% { transform: translate3d(0, 100vh, 0); opacity: 0; }
  }
  .global-scanline {
    position: fixed;
    left: 0; right: 0; top: 0;
    height: 80px;
    background: linear-gradient(
      to bottom,
      transparent 0%,
      rgba(167, 139, 250, 0.08) 50%,
      transparent 100%
    );
    pointer-events: none;
    z-index: 9997;
    animation: scanline-once 2.5s ease-out 1;
    will-change: transform, opacity;
  }

  /* === 數字 mono === */
  .num-mono {
    font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
    font-feature-settings: 'tnum' 1, 'zero' 1;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }

  /* === Phase 12.15.12: 微透明 panel 让 neural backdrop 透过 === */
  .glass-card {
    background: rgba(16, 23, 43, 0.88);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(148, 163, 184, 0.1);
    border-radius: 8px;
    position: relative;
    transition: border-color 200ms;
  }
  .glass-card:hover {
    border-color: rgba(167, 139, 250, 0.25);
  }

  /* === 深層 panel（卡中卡）=== */
  .glass-inner {
    background: rgba(7, 10, 19, 0.6);
    border: 1px solid rgba(148, 163, 184, 0.08);
    border-radius: 6px;
  }

  /* === 数据行 — table-like 紧凑 row === */
  .data-row {
    display: flex;
    align-items: center;
    padding: 8px 12px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.06);
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
    transition: background-color 120ms;
  }
  .data-row:hover {
    background-color: rgba(167, 139, 250, 0.04);
  }
  .data-row:last-child {
    border-bottom: none;
  }

  /* === Section label — 给 panel 内部分组用 === */
  .section-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #64748b;
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }
  .section-label::before {
    content: '';
    width: 2px;
    height: 12px;
    background: #a78bfa;
    box-shadow: 0 0 6px rgba(167,139,250,0.6);
  }

  /* === 脈衝點 === */
  @keyframes pulse-dot {
    0%, 100% { transform: scale(1); opacity: 1; box-shadow: 0 0 8px currentColor; }
    50% { transform: scale(1.5); opacity: 0.6; box-shadow: 0 0 16px currentColor; }
  }
  .pulse-dot { animation: pulse-dot 1.8s ease-in-out infinite; }

  /* === 雷達脈衝環（單環版，輕量）=== */
  @keyframes radar-pulse {
    0% { transform: scale3d(0.5, 0.5, 1); opacity: 0.8; }
    100% { transform: scale3d(2.5, 2.5, 1); opacity: 0; }
  }
  .radar-pulse-container {
    position: relative;
    width: 12px; height: 12px;
    display: inline-block;
  }
  .radar-pulse-dot {
    position: absolute;
    width: 8px; height: 8px;
    top: 2px; left: 2px;
    border-radius: 50%;
    background: var(--success);
    box-shadow: 0 0 6px var(--success);
    z-index: 2;
  }
  .radar-pulse-ring {
    /* 動畫已關閉以減少持續 repaint；保留靜態樣式 */
    animation: none !important;
    position: absolute;
    width: 12px; height: 12px;
    top: 0; left: 0;
    border-radius: 50%;
    border: 2px solid var(--success);
    animation: radar-pulse 2s ease-out infinite;
    will-change: transform, opacity;
  }

  /* === 流光邊框 === */
  @keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }
  .glow-border {
    position: relative;
  }
  .glow-border::after {
    /* Phase 5.5+ — 移除了 shimmer 動畫（持續 repaint 影響整站效能）。
       保留 class 兼容既有 markup，但只給靜態微邊框。 */
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    padding: 1px;
    border: 1px solid rgba(99, 102, 241, 0.25);
    pointer-events: none;
  }

  /* Glitch 已移除 — filter:hue-rotate 開銷大 */

  /* === 終端打字效果（caret 閃爍）=== */
  @keyframes caret-blink {
    0%, 50% { opacity: 1; }
    51%, 100% { opacity: 0; }
  }
  .caret {
    display: inline-block;
    width: 8px;
    height: 1em;
    background: var(--accent);
    margin-left: 4px;
    vertical-align: text-bottom;
    animation: caret-blink 1s steps(1) infinite;
    box-shadow: 0 0 8px var(--accent);
  }

  /* === 警告斜紋（黃黑）=== */
  .warning-stripes {
    background-image: repeating-linear-gradient(
      -45deg,
      rgba(250, 204, 21, 0.18),
      rgba(250, 204, 21, 0.18) 8px,
      rgba(0, 0, 0, 0.35) 8px,
      rgba(0, 0, 0, 0.35) 16px
    );
  }

  /* === 文字光暈 === */
  /* 文字光暈降低 — 從雙層 24/48px 收成單層 12px 0.4 (效能 + 清晰兼顧) */
  .glow-text-primary { text-shadow: 0 0 12px rgba(99, 102, 241, 0.4); }
  .glow-text-accent  { text-shadow: 0 0 12px rgba(167, 139, 250, 0.4); }
  .glow-text-success { text-shadow: 0 0 12px rgba(34, 197, 94, 0.4); }
  .glow-text-error   { text-shadow: 0 0 12px rgba(239, 68, 68, 0.4); }
  .glow-text-gold    { text-shadow: 0 0 12px rgba(251, 191, 36, 0.35); }

  /* === Ticker 跑馬燈（GPU 加速）=== */
  @keyframes ticker-scroll {
    0% { transform: translate3d(0, 0, 0); }
    100% { transform: translate3d(-50%, 0, 0); }
  }
  .ticker-content {
    display: inline-block;
    white-space: nowrap;
    /* ticker-scroll 動畫已關閉 — 持續 transform 重繪影響整站效能 */
    will-change: auto;
  }

  /* === 數據更新閃爍 === */
  @keyframes data-flash {
    0% { background-color: transparent; }
    20% { background-color: rgba(99, 102, 241, 0.25); }
    100% { background-color: transparent; }
  }
  .data-flash { animation: data-flash 800ms ease; }

  /* === Sparkline 小圖容器 === */
  .spark-cell {
    display: inline-block;
    vertical-align: middle;
  }

  /* === Recharts tooltip 玻璃版 === */
  .recharts-default-tooltip {
    background: rgba(8, 10, 24, 0.92) !important;
    backdrop-filter: blur(16px) saturate(160%);
    border: 1px solid rgba(99, 102, 241, 0.4) !important;
    border-radius: 8px !important;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6), 0 0 40px rgba(99, 102, 241, 0.2) !important;
    padding: 12px 16px !important;
  }
  .recharts-tooltip-label {
    color: #94a3b8 !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 6px !important;
  }
  .recharts-tooltip-item {
    color: #e2e8f0 !important;
    font-size: 13px !important;
    font-family: 'JetBrains Mono', monospace;
  }
  .recharts-tooltip-item-value { font-weight: 600 !important; }

  /* === Scrollbar === */
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: rgba(99, 102, 241, 0.04); }
  ::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, rgba(99, 102, 241, 0.4), rgba(167, 139, 250, 0.4));
    border-radius: 4px;
  }
  ::-webkit-scrollbar-thumb:hover {
    background: linear-gradient(180deg, rgba(99, 102, 241, 0.7), rgba(167, 139, 250, 0.7));
  }

  ::selection { background: rgba(99, 102, 241, 0.45); color: #fff; }

  /* === Reduced motion 對殘障 / 低端裝置友善 === */
  @media (prefers-reduced-motion: reduce) {
    .pulse-dot, .radar-pulse-ring, .ticker-content,
    .glow-border::after, .global-scanline, .caret {
      animation: none !important;
    }
  }

  /* === 低端裝置 fallback：縮小 blur === */
  @media (max-width: 768px) {
    .glass-card, .MuiCard-root, .MuiPaper-root {
      backdrop-filter: blur(8px) !important;
      -webkit-backdrop-filter: blur(8px) !important;
    }
  }
`;
document.head.appendChild(globalStyle);

// Phase 12.15.7: 全局重寫 MUI base theme → 金融科技混合 (Robinhood/Bybit)
// 之前所有 panel 內的 indigo / 紫色 / cyberpunk 渐变都來自這裡，一次換完全部跟著走
const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary:   { main: '#a78bfa', light: '#c4b5fd', dark: '#7c3aed' },    // cyan (system chrome)
    secondary: { main: '#f7a600', light: '#fbbf24' },                       // Bybit 金黃 (高亮)
    success:   { main: '#00d4aa', light: '#34d399' },                       // Robinhood teal-green
    error:     { main: '#ff4757', light: '#fb7185' },                       // 玫瑰红
    warning:   { main: '#f7a600', light: '#fbbf24' },
    info:      { main: '#a78bfa' },
    background: {
      default: '#0a0e1a',     // 主背景 dark navy
      paper:   '#10172b',     // panel 表面 — 实色，不再 backdrop-blur cyberpunk 玻璃
    },
    divider: 'rgba(148, 163, 184, 0.12)',
    text: {
      primary:   '#e2e8f0',
      secondary: '#94a3b8',
      disabled:  '#64748b',
    },
  },
  typography: {
    fontFamily: '"Inter", "Noto Sans TC", -apple-system, "Segoe UI", Roboto, sans-serif',
    h4: { fontWeight: 700, letterSpacing: '-0.02em' },
    h5: { fontWeight: 700, letterSpacing: '-0.01em' },
    h6: { fontWeight: 600, letterSpacing: '-0.005em' },
    subtitle1: { fontWeight: 600 },
    subtitle2: { fontWeight: 600 },
    body1: { letterSpacing: 0 },
    body2: { letterSpacing: 0, fontSize: '0.82rem' },
    button: { letterSpacing: 0.3, textTransform: 'none', fontWeight: 600 },
    caption: { letterSpacing: 0.3, fontWeight: 500, fontSize: '0.72rem' },
    overline: { letterSpacing: 1.2, fontWeight: 700, fontSize: '0.65rem' },
  },
  shape: { borderRadius: 8 },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#10172b',
          border: '1px solid rgba(148, 163, 184, 0.12)',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(16, 23, 43, 0.88)',   // 12.15.12: 微透明让 neural backdrop 透过
          border: '1px solid rgba(148, 163, 184, 0.1)',
          borderRadius: 8,
          backdropFilter: 'blur(8px)',
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { fontWeight: 600, textTransform: 'none', borderRadius: 6 },
        containedPrimary: {
          backgroundColor: '#a78bfa',
          color: '#0a0e1a',
          '&:hover': {
            backgroundColor: '#7c3aed',
            boxShadow: '0 0 16px rgba(167, 139, 250, 0.4)',
          },
        },
        containedSecondary: {
          backgroundColor: '#f7a600',
          color: '#0a0e1a',
          '&:hover': { backgroundColor: '#d68900' },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 600, fontSize: 11, letterSpacing: 0.2 },
        outlined: { borderColor: 'rgba(148, 163, 184, 0.24)' },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderBottom: '1px solid rgba(148, 163, 184, 0.08)',
          fontFamily: '"Inter", "Noto Sans TC", sans-serif',
          fontSize: '0.78rem',
          padding: '8px 12px',
        },
        head: {
          color: '#64748b',
          fontWeight: 700,
          fontSize: '0.65rem',
          textTransform: 'uppercase',
          letterSpacing: 0.8,
          backgroundColor: '#0a0e1a',
          padding: '10px 12px',
          borderBottom: '1px solid rgba(148, 163, 184, 0.18)',
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          '&:hover': { backgroundColor: 'rgba(148, 163, 184, 0.04)' },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: {
          backgroundColor: '#a78bfa',
          height: 2,
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: 'none', fontWeight: 600, fontSize: 13,
          color: '#94a3b8',
          '&.Mui-selected': { color: '#a78bfa' },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#0a0e1a',
          borderBottom: '1px solid rgba(148, 163, 184, 0.12)',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundImage: 'none',
          backgroundColor: '#070a13',
          borderRight: '1px solid rgba(148, 163, 184, 0.12)',
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { backgroundColor: 'rgba(148, 163, 184, 0.08)' },
        bar: { backgroundColor: '#a78bfa' },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: { borderColor: 'rgba(148, 163, 184, 0.12)' },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          backgroundColor: '#10172b',
          '& fieldset': { borderColor: 'rgba(148, 163, 184, 0.16)' },
          '&:hover fieldset': { borderColor: 'rgba(148, 163, 184, 0.32) !important' },
          '&.Mui-focused fieldset': { borderColor: '#a78bfa !important' },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 6 },
        standardSuccess: { backgroundColor: 'rgba(0,212,170,0.1)', color: '#34d399', border: '1px solid rgba(0,212,170,0.3)' },
        standardError: { backgroundColor: 'rgba(255,71,87,0.1)', color: '#fb7185', border: '1px solid rgba(255,71,87,0.3)' },
        standardWarning: { backgroundColor: 'rgba(247,166,0,0.1)', color: '#fbbf24', border: '1px solid rgba(247,166,0,0.3)' },
        standardInfo: { backgroundColor: 'rgba(167,139,250,0.1)', color: '#c4b5fd', border: '1px solid rgba(167,139,250,0.3)' },
      },
    },
  },
});

export default function App() {
  return (
    <ThemeProvider theme={darkTheme}>
      <CssBaseline />
      {/* Phase 12.20: 删 global-scanline 顶部扫描线（cyber 装饰） */}
      <BrowserRouter>
        {/* Phase 12.24.5: 全局 upgrade modal — 监听 fetch 402 自动弹出 */}
        <UpgradeModal />
        <Routes>
          {/* Phase 12.26: Marketing 公开路由（无需登录，无 sidebar）*/}
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<Login />} />
          <Route path="/pricing" element={<><MarketingNav /><Pricing /></>} />
          <Route path="/checkout" element={<><MarketingNav /><Checkout /></>} />
          <Route path="/terms" element={<><MarketingNav /><Terms /></>} />
          <Route path="/refund-policy" element={<><MarketingNav /><RefundPolicy /></>} />
          <Route path="/privacy" element={<><MarketingNav /><Privacy /></>} />

          {/* Phase 12.26: 受保护 app 路由（AuthGate + sidebar Layout）*/}
          <Route path="/" element={<AuthGate><Layout /></AuthGate>}>
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="strategies" element={<Strategies />} />
            <Route path="candidates" element={<Candidates />} />
            <Route path="trades" element={<Trades />} />
            <Route path="audit" element={<Audit />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
