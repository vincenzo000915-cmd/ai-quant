import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Strategies from './pages/Strategies';
import Trades from './pages/Trades';
import Settings from './pages/Settings';

// Global style overrides
const globalStyle = document.createElement('style');
globalStyle.textContent = `
  .recharts-default-tooltip {
    background-color: #0d0d1a !important;
    border: 1px solid rgba(0, 240, 255, 0.4) !important;
    border-radius: 8px !important;
    box-shadow: 0 0 20px rgba(0, 240, 255, 0.2) !important;
    padding: 10px 14px !important;
  }
  .recharts-tooltip-label {
    color: #00f0ff !important;
    font-weight: 700 !important;
  }
  .recharts-tooltip-item {
    color: #ffffff !important;
  }
  .recharts-tooltip-item-value {
    color: #00e5ff !important;
  }
`;
document.head.appendChild(globalStyle);

const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#00f0ff' },
    secondary: { main: '#ff00ff' },
    success: { main: '#00ff88' },
    error: { main: '#ff0055' },
    warning: { main: '#ffaa00' },
    background: { default: '#0a0a14', paper: '#12121e' },
  },
  typography: {
    fontFamily: '"Courier New", "Roboto Mono", monospace',
    h5: { fontWeight: 700, letterSpacing: 3, textShadow: '0 0 10px rgba(0,240,255,0.3)' },
    h6: { fontWeight: 600, letterSpacing: 2 },
    body2: { letterSpacing: 0.5 },
    caption: { letterSpacing: 1 },
  },
  shape: { borderRadius: 4 },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid rgba(0,240,255,0.15)',
          boxShadow: '0 0 20px rgba(0,240,255,0.05), inset 0 0 20px rgba(0,240,255,0.02)',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          border: '1px solid rgba(0,240,255,0.2)',
          boxShadow: '0 0 15px rgba(0,240,255,0.08), inset 0 0 30px rgba(0,240,255,0.02)',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          fontFamily: '"Courier New", monospace',
          letterSpacing: 2,
          borderWidth: 2,
          '&:hover': { borderWidth: 2, boxShadow: '0 0 20px rgba(0,240,255,0.3)' },
        },
        containedPrimary: {
          background: 'linear-gradient(135deg, #00f0ff 0%, #0088ff 100%)',
          color: '#000',
          fontWeight: 700,
          '&:hover': {
            background: 'linear-gradient(135deg, #00f0ff 0%, #0088ff 100%)',
            boxShadow: '0 0 30px rgba(0,240,255,0.5)',
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontFamily: '"Courier New", monospace', fontWeight: 600 },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderBottom: '1px solid rgba(0,240,255,0.08)', fontFamily: '"Courier New", monospace' },
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
