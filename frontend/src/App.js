import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Strategies from './pages/Strategies';
import Trades from './pages/Trades';
import Settings from './pages/Settings';

const globalStyle = document.createElement('style');
globalStyle.textContent = `
  :root {
    --bg-void: #03040c;
    --bg-deep: #05060f;
    --bg-mid: #0a0d1e;
    --bg-surface: rgba(20, 24, 44, 0.45);
    --bg-glass: rgba(15, 18, 36, 0.6);
    --border: rgba(99, 102, 241, 0.2);
    --border-hot: rgba(99, 102, 241, 0.5);
    --primary: #6366f1;
    --primary-glow: rgba(99, 102, 241, 0.6);
    --accent: #06b6d4;
    --accent-glow: rgba(6, 182, 212, 0.55);
    --neon-pink: #ec4899;
    --neon-purple: #a855f7;
    --gold: #fbbf24;
    --gold-deep: #f59e0b;
    --warn-yellow: #facc15;
    --success: #22c55e;
    --error: #ef4444;
    --error-bright: #ff3355;
    --warning: #f59e0b;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --text-faint: #475569;
  }

  html, body, #root {
    background: var(--bg-void);
    color: var(--text);
    margin: 0;
    min-height: 100vh;
    overflow-x: hidden;
  }

  body {
    background:
      radial-gradient(ellipse 80% 50% at top left, rgba(99, 102, 241, 0.12), transparent 60%),
      radial-gradient(ellipse 60% 40% at bottom right, rgba(6, 182, 212, 0.08), transparent 60%),
      radial-gradient(ellipse 70% 60% at 30% 70%, rgba(168, 85, 247, 0.06), transparent 60%),
      linear-gradient(180deg, #03040c 0%, #05060f 100%);
    background-attachment: fixed;
    font-feature-settings: 'tnum' 1, 'cv11' 1;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    position: relative;
  }

  /* === 全螢幕 CRT 掃描線（極淡）=== */
  body::before {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background-image:
      linear-gradient(rgba(99, 102, 241, 0.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(99, 102, 241, 0.04) 1px, transparent 1px);
    background-size: 56px 56px;
    pointer-events: none;
    z-index: 0;
    mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
  }

  body::after {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent 0px,
      transparent 2px,
      rgba(255, 255, 255, 0.012) 3px,
      transparent 3px
    );
    pointer-events: none;
    z-index: 9998;
  }

  /* === 慢速 scan line 從上往下掃 === */
  @keyframes scanline {
    0% { transform: translateY(0); }
    100% { transform: translateY(100vh); }
  }
  .global-scanline {
    position: fixed;
    left: 0; right: 0; top: 0;
    height: 80px;
    background: linear-gradient(
      to bottom,
      transparent 0%,
      rgba(99, 102, 241, 0.04) 40%,
      rgba(6, 182, 212, 0.08) 50%,
      rgba(99, 102, 241, 0.04) 60%,
      transparent 100%
    );
    pointer-events: none;
    z-index: 9997;
    animation: scanline 8s linear infinite;
  }

  /* === 數字 mono === */
  .num-mono {
    font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
    font-feature-settings: 'tnum' 1, 'zero' 1;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }

  /* === 玻璃卡（多層次 Vision Pro 風）=== */
  .glass-card {
    background: var(--bg-surface);
    backdrop-filter: blur(24px) saturate(160%);
    -webkit-backdrop-filter: blur(24px) saturate(160%);
    border: 1px solid var(--border);
    border-radius: 14px;
    box-shadow:
      0 1px 0 0 rgba(255, 255, 255, 0.05) inset,
      0 0 0 1px rgba(99, 102, 241, 0.04) inset,
      0 12px 32px -12px rgba(0, 0, 0, 0.6),
      0 0 60px -20px rgba(99, 102, 241, 0.15);
    transition: all 280ms cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
  }
  .glass-card:hover {
    border-color: var(--border-hot);
    transform: translateY(-1px);
    box-shadow:
      0 1px 0 0 rgba(255, 255, 255, 0.08) inset,
      0 16px 40px -10px rgba(0, 0, 0, 0.6),
      0 0 80px -16px rgba(99, 102, 241, 0.3);
  }

  /* === 深層玻璃（卡中卡）=== */
  .glass-inner {
    background: rgba(8, 10, 22, 0.5);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(99, 102, 241, 0.1);
    border-radius: 8px;
  }

  /* === 脈衝點 === */
  @keyframes pulse-dot {
    0%, 100% { transform: scale(1); opacity: 1; box-shadow: 0 0 8px currentColor; }
    50% { transform: scale(1.5); opacity: 0.6; box-shadow: 0 0 16px currentColor; }
  }
  .pulse-dot { animation: pulse-dot 1.8s ease-in-out infinite; }

  /* === 雷達脈衝環 === */
  @keyframes radar-pulse {
    0% { transform: scale(0.5); opacity: 0.8; }
    100% { transform: scale(3); opacity: 0; }
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
    box-shadow: 0 0 8px var(--success);
    z-index: 2;
  }
  .radar-pulse-ring {
    position: absolute;
    width: 12px; height: 12px;
    top: 0; left: 0;
    border-radius: 50%;
    border: 2px solid var(--success);
    animation: radar-pulse 2s ease-out infinite;
  }
  .radar-pulse-ring:nth-child(2) { animation-delay: 0.7s; }

  /* === 流光邊框 === */
  @keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }
  .glow-border {
    position: relative;
  }
  .glow-border::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    padding: 1px;
    background: linear-gradient(
      90deg,
      transparent 0%,
      rgba(99, 102, 241, 0.5) 25%,
      rgba(6, 182, 212, 0.6) 50%,
      rgba(168, 85, 247, 0.5) 75%,
      transparent 100%
    );
    background-size: 200% 100%;
    -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite: xor;
    mask-composite: exclude;
    animation: shimmer 4s linear infinite;
    pointer-events: none;
  }

  /* === Glitch 標題效果 === */
  @keyframes glitch-shift {
    0%, 95%, 100% { transform: translate(0); filter: none; }
    96% { transform: translate(-1px, 1px); filter: hue-rotate(15deg); }
    97% { transform: translate(1px, -1px); filter: hue-rotate(-15deg); }
    98% { transform: translate(-1px, -1px); }
  }
  .glitch { animation: glitch-shift 6s ease-in-out infinite; }

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
  .glow-text-primary { text-shadow: 0 0 24px rgba(99, 102, 241, 0.6), 0 0 48px rgba(99, 102, 241, 0.2); }
  .glow-text-accent  { text-shadow: 0 0 24px rgba(6, 182, 212, 0.6), 0 0 48px rgba(6, 182, 212, 0.2); }
  .glow-text-success { text-shadow: 0 0 24px rgba(34, 197, 94, 0.6), 0 0 48px rgba(34, 197, 94, 0.2); }
  .glow-text-error   { text-shadow: 0 0 24px rgba(239, 68, 68, 0.6), 0 0 48px rgba(239, 68, 68, 0.2); }
  .glow-text-gold    { text-shadow: 0 0 24px rgba(251, 191, 36, 0.5), 0 0 48px rgba(251, 191, 36, 0.2); }

  /* === Ticker 跑馬燈 === */
  @keyframes ticker-scroll {
    0% { transform: translateX(0); }
    100% { transform: translateX(-50%); }
  }
  .ticker-content {
    display: inline-block;
    white-space: nowrap;
    animation: ticker-scroll 60s linear infinite;
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
    background: linear-gradient(180deg, rgba(99, 102, 241, 0.4), rgba(6, 182, 212, 0.4));
    border-radius: 4px;
  }
  ::-webkit-scrollbar-thumb:hover {
    background: linear-gradient(180deg, rgba(99, 102, 241, 0.7), rgba(6, 182, 212, 0.7));
  }

  ::selection { background: rgba(99, 102, 241, 0.45); color: #fff; }
`;
document.head.appendChild(globalStyle);

const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#6366f1', light: '#818cf8', dark: '#4f46e5' },
    secondary: { main: '#06b6d4', light: '#22d3ee' },
    success: { main: '#22c55e', light: '#4ade80' },
    error: { main: '#ef4444', light: '#f87171' },
    warning: { main: '#fbbf24', light: '#fcd34d' },
    info: { main: '#06b6d4' },
    background: {
      default: '#03040c',
      paper: 'rgba(20, 24, 44, 0.55)',
    },
    divider: 'rgba(99, 102, 241, 0.18)',
    text: {
      primary: '#e2e8f0',
      secondary: '#94a3b8',
    },
  },
  typography: {
    fontFamily: '"Inter", "Noto Sans TC", -apple-system, "Segoe UI", Roboto, sans-serif',
    h4: { fontWeight: 800, letterSpacing: -0.02 },
    h5: { fontWeight: 700, letterSpacing: -0.02 },
    h6: { fontWeight: 600, letterSpacing: -0.01 },
    subtitle1: { fontWeight: 600 },
    subtitle2: { fontWeight: 600 },
    body1: { letterSpacing: 0 },
    body2: { letterSpacing: 0, fontSize: '0.82rem' },
    button: { letterSpacing: 0.5, textTransform: 'none', fontWeight: 600 },
    caption: { letterSpacing: 0.4, fontWeight: 500, fontSize: '0.72rem' },
    overline: { letterSpacing: 1.8, fontWeight: 700, fontSize: '0.65rem' },
  },
  shape: { borderRadius: 10 },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(20, 24, 44, 0.45)',
          backdropFilter: 'blur(24px) saturate(160%)',
          WebkitBackdropFilter: 'blur(24px) saturate(160%)',
          border: '1px solid rgba(99, 102, 241, 0.2)',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(20, 24, 44, 0.45)',
          backdropFilter: 'blur(24px) saturate(160%)',
          WebkitBackdropFilter: 'blur(24px) saturate(160%)',
          border: '1px solid rgba(99, 102, 241, 0.2)',
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { fontWeight: 600, textTransform: 'none', borderRadius: 8 },
        containedPrimary: {
          background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
          boxShadow: '0 0 0 1px rgba(99, 102, 241, 0.3), 0 4px 16px -4px rgba(99, 102, 241, 0.5)',
          '&:hover': {
            background: 'linear-gradient(135deg, #818cf8 0%, #6366f1 100%)',
            boxShadow: '0 0 0 1px rgba(99, 102, 241, 0.5), 0 4px 24px -4px rgba(99, 102, 241, 0.7)',
          },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderBottom: '1px solid rgba(99, 102, 241, 0.08)',
          fontFamily: '"Inter", "Noto Sans TC", sans-serif',
          fontSize: '0.78rem',
          padding: '8px 12px',
        },
        head: {
          color: '#64748b',
          fontWeight: 700,
          fontSize: '0.65rem',
          textTransform: 'uppercase',
          letterSpacing: 1.2,
          backgroundColor: 'rgba(8, 10, 24, 0.3)',
          padding: '10px 12px',
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: {
          background: 'linear-gradient(90deg, #6366f1, #06b6d4)',
          height: 3,
          borderRadius: 2,
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(8, 10, 24, 0.7)',
          backdropFilter: 'blur(24px) saturate(160%)',
          WebkitBackdropFilter: 'blur(24px) saturate(160%)',
          borderBottom: '1px solid rgba(99, 102, 241, 0.15)',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(8, 10, 24, 0.75)',
          backdropFilter: 'blur(28px) saturate(160%)',
          WebkitBackdropFilter: 'blur(28px) saturate(160%)',
          borderRight: '1px solid rgba(99, 102, 241, 0.15)',
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { backgroundColor: 'rgba(99, 102, 241, 0.1)' },
        bar: { background: 'linear-gradient(90deg, #6366f1, #06b6d4, #a855f7)' },
      },
    },
  },
});

export default function App() {
  return (
    <ThemeProvider theme={darkTheme}>
      <CssBaseline />
      <div className="global-scanline" />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="strategies" element={<Strategies />} />
            <Route path="trades" element={<Trades />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
