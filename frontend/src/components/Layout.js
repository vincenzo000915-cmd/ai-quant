import React, { useState, useEffect } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  Box, Drawer, AppBar, Toolbar, Typography, List, ListItem,
  ListItemButton, ListItemIcon, ListItemText, IconButton, Chip,
  Divider, Tooltip, useTheme, useMediaQuery, BottomNavigation,
  BottomNavigationAction, Menu, MenuItem,
} from '@mui/material';
import DashboardIcon from '@mui/icons-material/Dashboard';
import AutoGraphIcon from '@mui/icons-material/AutoGraph';
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong';
import SettingsIcon from '@mui/icons-material/Settings';
import HubIcon from '@mui/icons-material/Hub';
import HistoryIcon from '@mui/icons-material/History';
import MenuIcon from '@mui/icons-material/Menu';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import PersonIcon from '@mui/icons-material/Person';
import LogoutIcon from '@mui/icons-material/Logout';
import { getUser, onUserChange, logout } from '../auth';
import { palette, typo } from '../theme';

const DRAWER_WIDTH = 220;
const DRAWER_COLLAPSED = 64;

const NAV_ITEMS = [
  { label: '儀表板', icon: <DashboardIcon />, path: '/dashboard' },
  { label: '策略管理', icon: <AutoGraphIcon />, path: '/strategies' },
  { label: '候選池', icon: <HubIcon />, path: '/candidates' },
  { label: '交易紀錄', icon: <ReceiptLongIcon />, path: '/trades' },
  { label: '審計日誌', icon: <HistoryIcon />, path: '/audit' },
  { label: '系統設定', icon: <SettingsIcon />, path: '/settings' },
];

const navIconMap = {
  '/dashboard': <DashboardIcon />,
  '/strategies': <AutoGraphIcon />,
  '/candidates': <HubIcon />,
  '/trades': <ReceiptLongIcon />,
  '/audit': <HistoryIcon />,
  '/settings': <SettingsIcon />,
};

export default function Layout() {
  const [open, setOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [user, setUser] = useState(getUser());
  const [userMenuAnchor, setUserMenuAnchor] = useState(null);
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  useEffect(() => onUserChange(setUser), []);

  const handleLogout = () => {
    setUserMenuAnchor(null);
    logout();
  };

  const drawerContent = (
    <>
      <Toolbar sx={{ justifyContent: open ? 'space-between' : 'center', px: 1.5, minHeight: '64px !important' }}>
        {open && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
            <Box sx={{
              width: 32, height: 32, borderRadius: 1,
              bgcolor: palette.accent, color: palette.bg,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 0 16px ${palette.accentGlow}`,
            }}>
              <ShowChartIcon sx={{ fontSize: 20 }} />
            </Box>
            <Box>
              <Typography sx={{ fontSize: 14, fontWeight: 700, color: palette.text, lineHeight: 1.1 }}>
                Quant Pro
              </Typography>
              <Typography sx={{ fontSize: 10, fontWeight: 500, color: palette.textMuted, fontFamily: typo.mono, letterSpacing: 0.3 }}>
                v0.1 · OKX
              </Typography>
            </Box>
          </Box>
        )}
        {!isMobile && (
          <IconButton onClick={() => setOpen(!open)} size="small" sx={{ color: palette.textMuted, '&:hover': { color: palette.text } }}>
            {open ? <ChevronLeftIcon fontSize="small" /> : <MenuIcon fontSize="small" />}
          </IconButton>
        )}
      </Toolbar>
      <Divider sx={{ borderColor: palette.border }} />
      <List sx={{ mt: 1, px: 1 }}>
        {NAV_ITEMS.map(({ label, icon, path }) => {
          const active = location.pathname === path;
          return (
            <Tooltip key={path} title={open ? '' : label} placement="right">
              <ListItem disablePadding sx={{ mb: 0.25 }}>
                <ListItemButton
                  onClick={() => { navigate(path); if (isMobile) setMobileOpen(false); }}
                  sx={{
                    borderRadius: 1,
                    position: 'relative',
                    bgcolor: active ? `${palette.accent}14` : 'transparent',
                    '&:hover': { bgcolor: active ? `${palette.accent}1a` : 'rgba(255,255,255,0.03)' },
                    justifyContent: open ? 'initial' : 'center',
                    px: open ? 1.5 : 1.5,
                    py: 0.85,
                    transition: 'background-color 120ms ease',
                    // active 左側 accent bar
                    ...(active && {
                      '&::before': {
                        content: '""',
                        position: 'absolute',
                        left: -8, top: '50%', transform: 'translateY(-50%)',
                        width: 3, height: 18,
                        background: palette.accent,
                        borderRadius: 1,
                        boxShadow: `0 0 8px ${palette.accent}`,
                      },
                    }),
                  }}
                >
                  <ListItemIcon sx={{
                    minWidth: open ? 32 : 'auto',
                    color: active ? palette.accent : palette.textMuted,
                    '& svg': { fontSize: 18 },
                  }}>
                    {icon}
                  </ListItemIcon>
                  {open && (
                    <ListItemText
                      primary={label}
                      primaryTypographyProps={{
                        fontSize: 13, fontWeight: active ? 600 : 500,
                        color: active ? palette.text : palette.textMuted,
                        letterSpacing: 0.2,
                      }}
                    />
                  )}
                </ListItemButton>
              </ListItem>
            </Tooltip>
          );
        })}
      </List>
      <Box sx={{ mt: 'auto', p: 1.5, borderTop: `1px solid ${palette.border}` }}>
        {open && (
          <Box sx={{
            display: 'flex', alignItems: 'center', gap: 0.75,
            px: 1, py: 0.5, borderRadius: 0.75,
            bgcolor: `${palette.success}10`,
            border: `1px solid ${palette.success}33`,
          }}>
            <Box sx={{
              width: 6, height: 6, borderRadius: '50%',
              bgcolor: palette.success,
              boxShadow: `0 0 6px ${palette.success}`,
              animation: 'pulse-dot 2s ease-in-out infinite',
            }} />
            <Typography sx={{ fontSize: 11, color: palette.success, fontWeight: 600, letterSpacing: 0.3 }}>
              系统运行中
            </Typography>
          </Box>
        )}
      </Box>
    </>
  );

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'transparent' }}>
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
              bgcolor: palette.bgDeep,
              borderRight: `1px solid ${palette.border}`,
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
              bgcolor: palette.bgDeep,
              borderRight: `1px solid ${palette.border}`,
            },
          }}
        >
          {drawerContent}
        </Drawer>
      )}

      <Box sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* AppBar */}
        <AppBar position="static" elevation={0}
          sx={{ bgcolor: palette.bg, borderBottom: `1px solid ${palette.border}` }}>
          <Toolbar sx={{ justifyContent: 'space-between', minHeight: { xs: 40, sm: 44 }, '@media (min-width: 600px)': { minHeight: 44 } }}>
            {isMobile && (
              <IconButton edge="start" onClick={() => setMobileOpen(true)} size="small" sx={{ mr: 1, color: palette.textMuted }}>
                <MenuIcon />
              </IconButton>
            )}
            {/* Phase 12.15.6: 去掉 AppBar 重複頁面標題 — drawer 高亮 + PageHeader 已說明在哪頁 */}
            <Box sx={{ flexGrow: 1 }} />
            <Box sx={{ display: 'flex', alignItems: 'center', gap: { xs: 0.5, sm: 1.5 } }}>
              <Box sx={{
                width: 6, height: 6, borderRadius: '50%',
                bgcolor: palette.success,
                boxShadow: `0 0 6px ${palette.success}`,
                animation: 'pulse-dot 2s ease-in-out infinite',
              }} />
              <Typography sx={{ display: { xs: 'none', sm: 'block' }, fontSize: 11, color: palette.success, fontWeight: 600, letterSpacing: 0.3 }}>已连线</Typography>
              {user && (
                <>
                  <Chip
                    icon={<PersonIcon sx={{ fontSize: 14 }} />}
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        <Typography variant="caption" sx={{ fontSize: 11, maxWidth: { xs: 90, sm: 200 }, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {user.email}
                        </Typography>
                        {user.role === 'admin' && (
                          <Typography variant="caption" sx={{ fontSize: 9, color: 'warning.main', fontWeight: 700 }}>
                            ADMIN
                          </Typography>
                        )}
                      </Box>
                    }
                    size="small"
                    clickable
                    onClick={(e) => setUserMenuAnchor(e.currentTarget)}
                    sx={{ bgcolor: 'rgba(6,182,212,0.12)', color: 'primary.light', borderColor: 'primary.dark', cursor: 'pointer' }}
                  />
                  <Menu
                    anchorEl={userMenuAnchor}
                    open={Boolean(userMenuAnchor)}
                    onClose={() => setUserMenuAnchor(null)}
                    anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                    transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                  >
                    <MenuItem disabled sx={{ opacity: '1 !important' }}>
                      <Box>
                        <Typography variant="caption" color="text.secondary">已登入</Typography>
                        <Typography variant="body2">{user.email}</Typography>
                        <Typography variant="caption" sx={{ color: 'primary.light' }}>
                          {user.subscription_tier?.toUpperCase() || 'FREE'} · {user.role}
                        </Typography>
                      </Box>
                    </MenuItem>
                    <Divider />
                    <MenuItem onClick={handleLogout}>
                      <LogoutIcon sx={{ fontSize: 16, mr: 1 }} />
                      <Typography variant="body2">登出</Typography>
                    </MenuItem>
                  </Menu>
                </>
              )}
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
              bgcolor: palette.bgDeep,
              borderTop: `1px solid ${palette.border}`,
              '& .MuiBottomNavigationAction-root': {
                color: palette.textMuted,
                '&.Mui-selected': {
                  color: palette.accent,
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
