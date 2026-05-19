import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Strategies from './pages/Strategies';
import Trades from './pages/Trades';
import Settings from './pages/Settings';

// 全域樣式 — 玻璃 / 網格背景 / 動畫 / Recharts tooltip
const globalStyle = document.createElement('style');
globalStyle.textContent = `
  :root {
    --bg-deep: #05060f;
    --bg-mid: #0a0d1e;
    --bg-surface: rgba(20, 24, 44, 0.55);
    --bg-surface-strong: rgba(28, 32, 56, 0.85);
    --border: rgba(99, 102, 241, 0.18);
    --border-strong: rgba(99, 102, 241, 0.35);
    --primary: #6366f1;
    --primary-glow: rgba(99, 102, 241, 0.45);
    --accent: #06b6d4;
    --accent-glow: rgba(6, 182, 212, 0.45);
    --success: #22c55e;
    --error: #ef4444;
    --warning: #f59e0b;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --text-faint: #475569;
  }

  html, body, #root {
    background: var(--bg-deep);
    color: var(--text);
    margin: 0;
    min-height: 100vh;
    overflow-x: hidden;
  }

  body {
    background:
      radial-gradient(ellipse at top left, rgba(99, 102, 241, 0.08), transparent 50%),
      radial-gradient(ellipse at bottom right, rgba(6, 182, 212, 0.06), transparent 50%),
      linear-gradient(180deg, #05060f 0%, #08091a 100%);
    background-attachment: fixed;
    font-feature-settings: 'tnum' 1, 'cv11' 1;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  /* 細微網格背景 */
  body::before {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background-image:
      linear-gradient(rgba(99, 102, 241, 0.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(99, 102, 241, 0.04) 1px, transparent 1px);
    background-size: 48px 48px;
    pointer-events: none;
    z-index: 0;
    mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
  }

  /* 數字 mono */
  .num-mono {
    font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
    font-feature-settings: 'tnum' 1, 'zero' 1;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }

  /* 玻璃卡 */
  .glass-card {
    background: var(--bg-surface);
    backdrop-filter: blur(20px) saturate(140%);
    -webkit-backdrop-filter: blur(20px) saturate(140%);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow:
      0 1px 0 0 rgba(255, 255, 255, 0.04) inset,
      0 8px 24px -8px rgba(0, 0, 0, 0.5);
    transition: border-color 240ms ease, box-shadow 240ms ease;
  }
  .glass-card:hover {
    border-color: var(--border-strong);
    box-shadow:
      0 1px 0 0 rgba(255, 255, 255, 0.06) inset,
      0 8px 32px -4px rgba(99, 102, 241, 0.2);
  }

  /* 脈衝點 */
  @keyframes pulse-dot {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.4); opacity: 0.5; }
  }
  .pulse-dot {
    animation: pulse-dot 2s ease-in-out infinite;
  }

  /* 數據更新閃爍 */
  @keyframes data-flash {
    0% { background-color: transparent; }
    50% { background-color: rgba(99, 102, 241, 0.15); }
    100% { background-color: transparent; }
  }
  .data-flash {
    animation: data-flash 600ms ease;
  }

  /* 流光邊框（重要 KPI） */
  @keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }
  .glow-border {
    position: relative;
    overflow: hidden;
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
      rgba(99, 102, 241, 0.4) 30%,
      rgba(6, 182, 212, 0.5) 50%,
      rgba(99, 102, 241, 0.4) 70%,
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

  /* 主要 KPI 數字的光暈 */
  .glow-text-primary {
    text-shadow: 0 0 24px rgba(99, 102, 241, 0.4);
  }
  .glow-text-success {
    text-shadow: 0 0 24px rgba(34, 197, 94, 0.5);
  }
  .glow-text-error {
    text-shadow: 0 0 24px rgba(239, 68, 68, 0.5);
  }

  /* Recharts tooltip — 玻璃版 */
  .recharts-default-tooltip {
    background: rgba(15, 18, 36, 0.92) !important;
    backdrop-filter: blur(12px);
    border: 1px solid rgba(99, 102, 241, 0.35) !important;
    border-radius: 8px !important;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4), 0 0 24px rgba(99, 102, 241, 0.15) !important;
    padding: 10px 14px !important;
  }
  .recharts-tooltip-label {
    color: #94a3b8 !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px !important;
  }
  .recharts-tooltip-item {
    color: #e2e8f0 !important;
    font-size: 13px !important;
    font-family: 'JetBrains Mono', monospace;
  }
  .recharts-tooltip-item-value {
    font-weight: 600 !important;
  }

  /* scrollbar 配主題 */
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb {
    background: rgba(99, 102, 241, 0.25);
    border-radius: 4px;
  }
  ::-webkit-scrollbar-thumb:hover { background: rgba(99, 102, 241, 0.4); }

  /* 選擇文字 */
  ::selection { background: rgba(99, 102, 241, 0.35); color: #fff; }
`;
document.head.appendChild(globalStyle);

const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#6366f1', light: '#818cf8', dark: '#4f46e5' },
    secondary: { main: '#06b6d4', light: '#22d3ee' },
    success: { main: '#22c55e', light: '#4ade80' },
    error: { main: '#ef4444', light: '#f87171' },
    warning: { main: '#f59e0b', light: '#fbbf24' },
    info: { main: '#06b6d4' },
    background: {
      default: '#05060f',
      paper: 'rgba(20, 24, 44, 0.55)',
    },
    divider: 'rgba(99, 102, 241, 0.15)',
    text: {
      primary: '#e2e8f0',
      secondary: '#94a3b8',
    },
  },
  typography: {
    fontFamily: '"Inter", "Noto Sans TC", -apple-system, "Segoe UI", Roboto, sans-serif',
    h4: { fontWeight: 700, letterSpacing: -0.02 },
    h5: { fontWeight: 700, letterSpacing: -0.02 },
    h6: { fontWeight: 600, letterSpacing: -0.01 },
    subtitle1: { fontWeight: 600, letterSpacing: 0 },
    subtitle2: { fontWeight: 600 },
    body1: { letterSpacing: 0 },
    body2: { letterSpacing: 0 },
    button: { letterSpacing: 0.3, textTransform: 'none', fontWeight: 600 },
    caption: { letterSpacing: 0.4, fontWeight: 500 },
    overline: { letterSpacing: 1.5, fontWeight: 600, fontSize: '0.65rem' },
  },
  shape: { borderRadius: 10 },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(20, 24, 44, 0.55)',
          backdropFilter: 'blur(20px) saturate(140%)',
          WebkitBackdropFilter: 'blur(20px) saturate(140%)',
          border: '1px solid rgba(99, 102, 241, 0.18)',
          boxShadow: '0 1px 0 0 rgba(255, 255, 255, 0.04) inset, 0 8px 24px -8px rgba(0, 0, 0, 0.5)',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(20, 24, 44, 0.55)',
          backdropFilter: 'blur(20px) saturate(140%)',
          WebkitBackdropFilter: 'blur(20px) saturate(140%)',
          border: '1px solid rgba(99, 102, 241, 0.18)',
          boxShadow: '0 1px 0 0 rgba(255, 255, 255, 0.04) inset, 0 8px 24px -8px rgba(0, 0, 0, 0.5)',
          transition: 'border-color 240ms ease, box-shadow 240ms ease',
          '&:hover': {
            borderColor: 'rgba(99, 102, 241, 0.35)',
            boxShadow: '0 1px 0 0 rgba(255, 255, 255, 0.06) inset, 0 8px 32px -4px rgba(99, 102, 241, 0.2)',
          },
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          fontWeight: 600,
          textTransform: 'none',
          letterSpacing: 0.3,
          borderRadius: 8,
        },
        containedPrimary: {
          background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
          boxShadow: '0 0 0 1px rgba(99, 102, 241, 0.3), 0 4px 16px -4px rgba(99, 102, 241, 0.5)',
          '&:hover': {
            background: 'linear-gradient(135deg, #818cf8 0%, #6366f1 100%)',
            boxShadow: '0 0 0 1px rgba(99, 102, 241, 0.5), 0 4px 24px -4px rgba(99, 102, 241, 0.7)',
          },
        },
        outlinedPrimary: {
          borderColor: 'rgba(99, 102, 241, 0.4)',
          '&:hover': {
            borderColor: 'rgba(99, 102, 241, 0.7)',
            background: 'rgba(99, 102, 241, 0.08)',
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 600, letterSpacing: 0.2 },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderBottom: '1px solid rgba(99, 102, 241, 0.1)',
          fontFamily: '"Inter", "Noto Sans TC", sans-serif',
        },
        head: {
          color: '#94a3b8',
          fontWeight: 600,
          fontSize: '0.7rem',
          textTransform: 'uppercase',
          letterSpacing: 0.8,
          backgroundColor: 'transparent',
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
          backgroundColor: 'rgba(10, 13, 30, 0.7)',
          backdropFilter: 'blur(20px) saturate(140%)',
          WebkitBackdropFilter: 'blur(20px) saturate(140%)',
          borderBottom: '1px solid rgba(99, 102, 241, 0.12)',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundImage: 'none',
          backgroundColor: 'rgba(10, 13, 30, 0.7)',
          backdropFilter: 'blur(24px) saturate(140%)',
          WebkitBackdropFilter: 'blur(24px) saturate(140%)',
          borderRight: '1px solid rgba(99, 102, 241, 0.12)',
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: {
          backgroundColor: 'rgba(99, 102, 241, 0.12)',
        },
        bar: {
          background: 'linear-gradient(90deg, #6366f1, #06b6d4)',
        },
      },
    },
  },
});

export default function App() {
  return (
    <ThemeProvider theme={darkTheme}>
      <CssBaseline />
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
