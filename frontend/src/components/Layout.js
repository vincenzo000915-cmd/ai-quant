import React, { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  Box, Drawer, AppBar, Toolbar, Typography, List, ListItem,
  ListItemButton, ListItemIcon, ListItemText, IconButton, Chip,
  Divider, Tooltip, useTheme, useMediaQuery, BottomNavigation,
  BottomNavigationAction,
} from '@mui/material';
import DashboardIcon from '@mui/icons-material/Dashboard';
import AutoGraphIcon from '@mui/icons-material/AutoGraph';
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong';
import SettingsIcon from '@mui/icons-material/Settings';
import HubIcon from '@mui/icons-material/Hub';
import MenuIcon from '@mui/icons-material/Menu';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';

const DRAWER_WIDTH = 220;
const DRAWER_COLLAPSED = 64;

const NAV_ITEMS = [
  { label: '儀表板', icon: <DashboardIcon />, path: '/dashboard' },
  { label: '策略管理', icon: <AutoGraphIcon />, path: '/strategies' },
  { label: '候選池', icon: <HubIcon />, path: '/candidates' },
  { label: '交易紀錄', icon: <ReceiptLongIcon />, path: '/trades' },
  { label: '系統設定', icon: <SettingsIcon />, path: '/settings' },
];

const navIconMap = {
  '/dashboard': <DashboardIcon />,
  '/strategies': <AutoGraphIcon />,
  '/candidates': <HubIcon />,
  '/trades': <ReceiptLongIcon />,
  '/settings': <SettingsIcon />,
};

export default function Layout() {
  const [open, setOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  const drawerContent = (
    <>
      <Toolbar sx={{ justifyContent: open ? 'space-between' : 'center', px: 1 }}>
        {open && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <ShowChartIcon sx={{ color: 'primary.main' }} />
            <Typography variant="subtitle1" fontWeight={700} color="text.primary" noWrap>
              量化交易
            </Typography>
          </Box>
        )}
        {!isMobile && (
          <IconButton onClick={() => setOpen(!open)} size="small">
            {open ? <ChevronLeftIcon /> : <MenuIcon />}
          </IconButton>
        )}
      </Toolbar>
      <Divider sx={{ borderColor: 'rgba(255,255,255,0.06)' }} />
      <List sx={{ mt: 1 }}>
        {NAV_ITEMS.map(({ label, icon, path }) => {
          const active = location.pathname === path;
          return (
            <Tooltip key={path} title={open ? '' : label} placement="right">
              <ListItem disablePadding sx={{ mb: 0.5 }}>
                <ListItemButton
                  onClick={() => { navigate(path); if (isMobile) setMobileOpen(false); }}
                  sx={{
                    mx: 1, borderRadius: 1.5,
                    bgcolor: active ? 'rgba(59,130,246,0.12)' : 'transparent',
                    '&:hover': { bgcolor: 'rgba(59,130,246,0.08)' },
                    justifyContent: open ? 'initial' : 'center',
                    px: open ? 2 : 1.5,
                  }}
                >
                  <ListItemIcon sx={{ minWidth: open ? 36 : 'auto', color: active ? 'primary.main' : 'text.secondary' }}>
                    {icon}
                  </ListItemIcon>
                  {open && (
                    <ListItemText
                      primary={label}
                      primaryTypographyProps={{
                        fontSize: 14, fontWeight: active ? 600 : 400,
                        color: active ? 'primary.main' : 'text.primary',
                      }}
                    />
                  )}
                </ListItemButton>
              </ListItem>
            </Tooltip>
          );
        })}
      </List>
      <Box sx={{ mt: 'auto', p: 2 }}>
        {open && (
          <Chip
            icon={<FiberManualRecordIcon sx={{ fontSize: '10px !important' }} />}
            label="系統運行中" size="small"
            sx={{ bgcolor: 'rgba(0,230,118,0.15)', color: 'success.main', fontSize: 11 }}
          />
        )}
      </Box>
    </>
  );

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
      {/* Desktop Drawer */}
      {!isMobile && (
        <Drawer
          variant="permanent"
          sx={{
            width: open ? DRAWER_WIDTH : DRAWER_COLLAPSED,
            flexShrink: 0,
            '& .MuiDrawer-paper': {
              width: open ? DRAWER_WIDTH : DRAWER_COLLAPSED,
              transition: theme.transitions.create('width', {
                easing: theme.transitions.easing.sharp,
                duration: theme.transitions.duration.enteringScreen,
              }),
              overflow: 'hidden',
              bgcolor: 'background.paper',
              borderRight: '1px solid rgba(255,255,255,0.06)',
            },
          }}
        >
          {drawerContent}
        </Drawer>
      )}

      {/* Mobile Drawer (temporary) */}
      {isMobile && (
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          sx={{
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH,
              bgcolor: 'background.paper',
              borderRight: '1px solid rgba(255,255,255,0.06)',
            },
          }}
        >
          {drawerContent}
        </Drawer>
      )}

      <Box sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* AppBar */}
        <AppBar position="static" elevation={0}
          sx={{ bgcolor: 'background.paper', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <Toolbar sx={{ justifyContent: 'space-between', minHeight: { xs: 48, sm: 56 } }}>
            {isMobile && (
              <IconButton edge="start" onClick={() => setMobileOpen(true)} size="small" sx={{ mr: 1 }}>
                <MenuIcon />
              </IconButton>
            )}
            <Typography variant="h6" fontWeight={600} sx={{ fontSize: { xs: '0.9rem', sm: '1.1rem' } }}>
              {NAV_ITEMS.find((n) => n.path === location.pathname)?.label ?? '量化交易系統'}
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <FiberManualRecordIcon sx={{ color: 'success.main', fontSize: { xs: 10, sm: 12 } }} />
              <Typography variant="caption" color="success.main" sx={{ display: { xs: 'none', sm: 'block' } }}>已連線</Typography>
            </Box>
          </Toolbar>
        </AppBar>

        {/* Page Content */}
        <Box sx={{ flexGrow: 1, overflow: 'auto', p: { xs: 1.5, sm: 3 }, pb: { xs: 8, sm: 3 } }}>
          <Outlet />
        </Box>

        {/* Mobile Bottom Navigation */}
        {isMobile && (
          <BottomNavigation
            value={location.pathname}
            onChange={(_, value) => navigate(value)}
            sx={{
              position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 1200,
              bgcolor: 'background.paper',
              borderTop: '1px solid rgba(255,255,255,0.06)',
              '& .MuiBottomNavigationAction-root': {
                color: 'text.secondary',
                '&.Mui-selected': {
                  color: 'primary.main',
                },
              },
            }}
          >
            {NAV_ITEMS.map(({ label, path }) => (
              <BottomNavigationAction
                key={path}
                label={<Typography variant="caption" sx={{ fontSize: 10 }}>{label}</Typography>}
                icon={navIconMap[path]}
                value={path}
              />
            ))}
          </BottomNavigation>
        )}
      </Box>
    </Box>
  );
}
