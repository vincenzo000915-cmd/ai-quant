import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Strategies from './pages/Strategies';
import Trades from './pages/Trades';
import Settings from './pages/Settings';

// Recharts tooltip 樣式（金融專業風）
const globalStyle = document.createElement('style');
globalStyle.textContent = `
  body {
    font-feature-settings: 'tnum' 1, 'cv11' 1;
    -webkit-font-smoothing: antialiased;
  }
  .recharts-default-tooltip {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 6px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
    padding: 10px 14px !important;
  }
  .recharts-tooltip-label {
    color: #94a3b8 !important;
    font-weight: 500 !important;
    font-size: 12px !important;
    margin-bottom: 4px !important;
  }
  .recharts-tooltip-item {
    color: #f1f5f9 !important;
    font-size: 13px !important;
  }
  .recharts-tooltip-item-value {
    font-weight: 600 !important;
  }
  /* 數字專用 mono 字體 class */
  .num-mono {
    font-feature-settings: 'tnum' 1;
    font-variant-numeric: tabular-nums;
  }
`;
document.head.appendChild(globalStyle);

// 金融專業 dark theme（深藍 + 白 + 綠紅，無霓虹）
const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#3b82f6', light: '#60a5fa', dark: '#2563eb' },   // 藍
    secondary: { main: '#8b5cf6' },                                    // 紫（次要）
    success: { main: '#10b981', light: '#34d399' },                    // 漲綠
    error: { main: '#ef4444', light: '#f87171' },                      // 跌紅
    warning: { main: '#f59e0b' },                                      // 黃
    info: { main: '#06b6d4' },
    background: {
      default: '#0f172a',  // slate-900
      paper: '#1e293b',    // slate-800
    },
    divider: '#334155',     // slate-700
    text: {
      primary: '#f1f5f9',   // slate-100
      secondary: '#94a3b8', // slate-400
    },
  },
  typography: {
    fontFamily: '"Inter", "Noto Sans TC", -apple-system, "Segoe UI", Roboto, sans-serif',
    h4: { fontWeight: 700, letterSpacing: 0 },
    h5: { fontWeight: 700, letterSpacing: 0 },
    h6: { fontWeight: 600, letterSpacing: 0 },
    subtitle1: { fontWeight: 600, letterSpacing: 0 },
    subtitle2: { fontWeight: 600, letterSpacing: 0 },
    body1: { letterSpacing: 0 },
    body2: { letterSpacing: 0 },
    button: { letterSpacing: 0.3, textTransform: 'none', fontWeight: 600 },
    caption: { letterSpacing: 0 },
  },
  shape: { borderRadius: 8 },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: { backgroundColor: '#0f172a' },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid #334155',
          boxShadow: 'none',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          border: '1px solid #334155',
          boxShadow: 'none',
          transition: 'border-color 120ms ease',
          '&:hover': { borderColor: '#475569' },
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
        },
        containedPrimary: {
          background: '#3b82f6',
          '&:hover': { background: '#2563eb' },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 600, letterSpacing: 0 },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderBottom: '1px solid #334155',
          fontFamily: '"Inter", "Noto Sans TC", sans-serif',
        },
        head: {
          color: '#94a3b8',
          fontWeight: 600,
          fontSize: '0.75rem',
          textTransform: 'uppercase',
          letterSpacing: 0.5,
          backgroundColor: 'transparent',
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: { backgroundColor: '#3b82f6', height: 3 },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
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
