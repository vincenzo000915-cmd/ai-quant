import React, { useState } from 'react';
import {
  Box, Typography, Card, CardContent, TextField, Button, Grid,
  Divider, Alert, Switch, FormControlLabel, Chip,
  InputAdornment, CircularProgress, Tabs, Tab, Slider, IconButton,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import KeyIcon from '@mui/icons-material/Key';
import SecurityIcon from '@mui/icons-material/Security';
import NotificationsIcon from '@mui/icons-material/Notifications';

const API = process.env.REACT_APP_API_URL || '';

export default function Settings() {
  const [tab, setTab] = useState(0);
  const [apiKey, setApiKey] = useState('');
  const [secret, setSecret] = useState('');
  const [passphrase, setPassphrase] = useState('');
  const [testnet, setTestnet] = useState(true);
  const [showSecret, setShowSecret] = useState(false);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState('');

  const riskParams = [
    { key: 'maxDrawdown', label: '最大回撤', val: 20, unit: '%' },
    { key: 'maxPositionSize', label: '單筆倉位', val: 10, unit: '%' },
    { key: 'dailyLossLimit', label: '每日虧損上限', val: 5, unit: '%' },
    { key: 'stopLoss', label: '預設止損', val: 2, unit: '%' },
    { key: 'takeProfit', label: '預設止盈', val: 4, unit: '%' },
  ];
  const [risk, setRisk] = useState(riskParams.reduce((a, r) => ({ ...a, [r.key]: r.val }), {}));

  const handleSave = async () => {
    setSaving(true);
    setSuccess('');
    setTimeout(() => { setSuccess('設定已儲存'); setSaving(false); }, 800);
  };

  return (
    <Box>
      <Typography variant="h5" fontWeight={700} mb={3}>系統設定</Typography>
      {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}
      <Card sx={{ bgcolor: 'background.paper' }}>
        <Box sx={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ px: 2 }}>
            <Tab icon={<KeyIcon fontSize="small" />} iconPosition="start" label="交易所 API" />
            <Tab icon={<SecurityIcon fontSize="small" />} iconPosition="start" label="風控參數" />
            <Tab icon={<NotificationsIcon fontSize="small" />} iconPosition="start" label="通知設定" />
          </Tabs>
        </Box>
        <CardContent sx={{ p: 3 }}>
          {tab === 0 && (
            <Grid container spacing={3}>
              <Grid item xs={12}><Chip label="OKX" color="primary" size="small" sx={{ mb: 1 }} /></Grid>
              <Grid item xs={12} md={6}>
                <TextField label="API Key" fullWidth value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField label="Secret Key" fullWidth type={showSecret ? 'text' : 'password'} value={secret}
                  onChange={(e) => setSecret(e.target.value)}
                  InputProps={{ endAdornment: <InputAdornment position="end"><IconButton onClick={() => setShowSecret(!showSecret)} size="small">{showSecret ? <VisibilityOffIcon /> : <VisibilityIcon />}</IconButton></InputAdornment> }} />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField label="Passphrase" fullWidth value={passphrase} onChange={(e) => setPassphrase(e.target.value)} helperText="OKX 必填" />
              </Grid>
              <Grid item xs={12} md={6}>
                <FormControlLabel control={<Switch checked={testnet} onChange={(e) => setTestnet(e.target.checked)} color="warning" />}
                  label={<Box><Typography>使用測試網</Typography><Typography variant="caption" color="text.secondary">Testnet 環境</Typography></Box>} />
              </Grid>
            </Grid>
          )}
          {tab === 1 && (
            <Grid container spacing={3}>
              {riskParams.map(({ key, label, unit }) => (
                <Grid item xs={12} md={6} key={key}>
                  <Typography variant="body2" gutterBottom>{label}: <strong style={{ color: '#00e5ff' }}>{risk[key]}{unit}</strong></Typography>
                  <Slider value={risk[key]} min={1} max={50} step={1}
                    onChange={(_, v) => setRisk({ ...risk, [key]: v })}
                    sx={{ color: 'primary.main' }} />
                </Grid>
              ))}
            </Grid>
          )}
          {tab === 2 && (
            <Typography color="text.secondary">通知設定（Telegram / Email）可後續配置</Typography>
          )}
          <Divider sx={{ my: 3 }} />
          <Button variant="contained" startIcon={saving ? <CircularProgress size={16} /> : <SaveIcon />}
            onClick={handleSave} disabled={saving}>
            {saving ? '儲存中...' : '儲存設定'}
          </Button>
        </CardContent>
      </Card>
    </Box>
  );
}
