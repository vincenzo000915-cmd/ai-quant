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
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium';
import MenuIcon from '@mui/icons-material/Menu';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import PersonIcon from '@mui/icons-material/Person';
import LogoutIcon from '@mui/icons-material/Logout';
import PeopleIcon from '@mui/icons-material/People';
import AttachMoneyIcon from '@mui/icons-material/AttachMoney';
import FactCheckIcon from '@mui/icons-material/FactCheck';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import { getUser, onUserChange, logout } from '../auth';
import { palette, typo } from '../theme';
import TelegramChip from './TelegramChip';

const DRAWER_WIDTH = 220;
const DRAWER_COLLAPSED = 64;

// 主导航 (所有 user 可见)
const NAV_MAIN = [
  { label: '儀表板', icon: <DashboardIcon />, path: '/dashboard' },
  { label: '策略管理', icon: <AutoGraphIcon />, path: '/strategies' },
  { label: '候選池', icon: <HubIcon />, path: '/candidates' },
  { label: '交易紀錄', icon: <ReceiptLongIcon />, path: '/trades' },
  { label: '系統設定', icon: <SettingsIcon />, path: '/settings' },
  { label: '订阅', icon: <WorkspacePremiumIcon />, path: '/pricing' },
];

// Phase 14j: 管理后台分组 (仅 role=admin 可见)
const NAV_ADMIN = [
  { label: '会员管理', icon: <PeopleIcon />, path: '/admin/users' },
  { label: '订阅收入', icon: <AttachMoneyIcon />, path: '/admin/revenue' },
  { label: '跨用戶日誌', icon: <FactCheckIcon />, path: '/admin/audit' },
  { label: '系統审计', icon: <HistoryIcon />, path: '/audit' },
];

function getNavItems(user) {
  // Backwards-compat: 平铺所有可见 nav (mobile bottom nav 等用)
  const isAdmin = user?.role === 'admin';
  return isAdmin ? [...NAV_MAIN, ...NAV_ADMIN] : NAV_MAIN;
}

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
            {/* Phase 14k-116: 内页 brand mark 用 SVG 跟 favicon 同款 K 线趋势 (取代 generic ShowChartIcon) */}
            <Box sx={{
              width: 32, height: 32, borderRadius: 1,
              bgcolor: palette.accent, color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 0 16px ${palette.accentGlow}`,
            }}>
              <Box component="svg" viewBox="0 0 64 64" sx={{ width: 22, height: 22 }}>
                <path d="M12 46 L22 36 L30 42 L46 22 M40 22 L46 22 L46 28"
                      stroke="currentColor" strokeWidth="4.5"
                      fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                <circle cx="22" cy="36" r="2.5" fill="currentColor"/>
                <circle cx="30" cy="42" r="2.5" fill="currentColor"/>
              </Box>
            </Box>
            <Box>
              <Typography sx={{ fontSize: 14, fontWeight: 700, color: palette.text, lineHeight: 1.1 }}>
                Quant Pro
              </Typography>
              <Typography sx={{ fontSize: 10, fontWeight: 500, color: palette.textMuted, fontFamily: typo.mono, letterSpacing: 0.3 }}>
                v14k · OKX + HL
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
      {(() => {
        const renderNavItem = ({ label, icon, path }, keyPrefix = '') => {
          const active = location.pathname === path || (path !== '/' && location.pathname.startsWith(path + '/'));
          return (
            <Tooltip key={keyPrefix + path} title={open ? '' : label} placement="right">
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
        };
        const isAdmin = user?.role === 'admin';
        return (
          <>
            <List sx={{ mt: 1, px: 1 }}>
              {NAV_MAIN.map(it => renderNavItem(it, 'main-'))}
            </List>
            {isAdmin && (
              <>
                <Divider sx={{ borderColor: palette.border, mx: 1.5, my: 1.5 }} />
                {open && (
                  <Box sx={{ px: 2, mb: 0.5, display: 'flex', alignItems: 'center', gap: 0.75 }}>
                    <AdminPanelSettingsIcon sx={{ fontSize: 12, color: '#a78bfa' }} />
                    <Typography variant="caption" sx={{
                      fontSize: 10, fontWeight: 700, letterSpacing: 1.2,
                      color: '#a78bfa', textTransform: 'uppercase',
                    }}>
                      管理后台
                    </Typography>
                  </Box>
                )}
                <List sx={{ px: 1, pt: 0 }}>
                  {NAV_ADMIN.map(it => renderNavItem(it, 'admin-'))}
                </List>
              </>
            )}
          </>
        );
      })()}
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
              {/* Phase 12.43: Telegram channel chip - 顶部活跃用户曝光 */}
              <TelegramChip variant="icon" />
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
                    sx={{ bgcolor: 'rgba(167,139,250,0.12)', color: 'primary.light', borderColor: 'primary.dark', cursor: 'pointer' }}
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

        {/* Mobile Bottom Navigation — Phase 14k-21: 限定 5 个主导航
            admin 后台留给抽屉 (BottomNav 项超过 5 会挤爆) */}
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
                minWidth: 0,
                padding: '6px 4px',
                '&.Mui-selected': {
                  color: palette.accent,
                },
              },
              '& .MuiBottomNavigationAction-label': {
                fontSize: '0.62rem',
                marginTop: '2px',
              },
            }}
          >
            {NAV_MAIN.slice(0, 5).map(({ label, path }) => (
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
