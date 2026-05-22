// Phase 8.1 + 11.1.5 + 12.24.5: 全局 fetch wrap + user auth + tier upgrade prompt

// 402 触发 — UI 监听这个 event 显示 upgrade modal
let _upgradeListeners = [];
export function onUpgradeRequired(fn) {
  _upgradeListeners.push(fn);
  return () => { _upgradeListeners = _upgradeListeners.filter(x => x !== fn); };
}
function _triggerUpgrade(body) {
  for (const fn of _upgradeListeners) {
    try { fn(body); } catch (e) { /* */ }
  }
}

//
// 雙軌：
//  - System Bearer token（從 .env 拿） — admin 後門
//  - User JWT（email + password 登入後拿）
//  兩者都存在 localStorage 同一個 key。

const STORAGE_KEY = 'quant_api_token';
const USER_KEY = 'quant_user';

let _token = (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY)) || '';
let _user = null;
try {
  const cached = typeof localStorage !== 'undefined' ? localStorage.getItem(USER_KEY) : null;
  if (cached) _user = JSON.parse(cached);
} catch { _user = null; }

const _listeners = new Set();
const _userListeners = new Set();

export function getToken() { return _token; }
export function getUser() { return _user; }

export function setToken(t) {
  _token = t || '';
  if (typeof localStorage !== 'undefined') {
    if (_token) localStorage.setItem(STORAGE_KEY, _token);
    else localStorage.removeItem(STORAGE_KEY);
  }
}

export function setUser(u) {
  _user = u || null;
  if (typeof localStorage !== 'undefined') {
    if (_user) localStorage.setItem(USER_KEY, JSON.stringify(_user));
    else localStorage.removeItem(USER_KEY);
  }
  _userListeners.forEach(fn => { try { fn(_user); } catch {/* */} });
}

export function onUserChange(fn) {
  _userListeners.add(fn);
  return () => _userListeners.delete(fn);
}

export function onUnauthorized(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

function _triggerUnauthorized(reason) {
  _listeners.forEach(fn => { try { fn(reason); } catch {/* */} });
}

// === Wrap global fetch 一次 ===
if (typeof window !== 'undefined' && !window.__quantFetchWrapped) {
  const orig = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const headers = new Headers(init.headers || {});
    if (_token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${_token}`);
    }
    const res = await orig(input, { ...init, headers });
    if (res.status === 401) {
      const url = typeof input === 'string' ? input : (input?.url || '');
      // 對 /api/auth/* 自身的 401 不要遞迴觸發（登入失敗、token 驗證等）
      if (!url.includes('/api/auth/')) {
        _triggerUnauthorized('401');
      }
    }
    // Phase 12.24.5: 402 = Payment Required (tier 不够) → 弹 upgrade modal
    if (res.status === 402) {
      try {
        const cloned = res.clone();
        const body = await cloned.json();
        _triggerUpgrade(body);
      } catch (e) { /* */ }
    }
    return res;
  };
  window.__quantFetchWrapped = true;
}

// 啟動時驗一次當前 token 是否有效；順便載入 user info
export async function verifyToken() {
  try {
    const r = await fetch('/api/auth/check');
    const body = await r.json();
    if (!body.enabled) return { enabled: false, ok: true, isSystem: false, userId: null };
    if (body.ok) {
      // 若是 user JWT，順便拉 me
      if (body.user_id) {
        try {
          const meRes = await fetch('/api/auth/me');
          if (meRes.ok) {
            const meBody = await meRes.json();
            if (meBody.user) setUser(meBody.user);
          }
        } catch {/* */}
      } else if (body.is_system) {
        // system token = admin 後門，無 user 物件
        setUser({ id: 1, email: 'admin (system token)', role: 'admin', subscription_tier: 'pro', _is_system: true });
      }
      return { enabled: true, ok: true, isSystem: body.is_system, userId: body.user_id };
    }
    return { enabled: true, ok: false, isSystem: false, userId: null };
  } catch {
    return { enabled: true, ok: false, isSystem: false, userId: null };
  }
}

// === Phase 11.1.5: email + password 登入 / 註冊 ===

export async function loginWithPassword(email, password) {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const body = await res.json();
  if (!res.ok) return { ok: false, error: body.error || `HTTP ${res.status}` };
  setToken(body.access_token);
  setUser(body.user);
  return { ok: true, user: body.user };
}

export async function registerWithPassword(email, password) {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const body = await res.json();
  if (!res.ok) return { ok: false, error: body.error || `HTTP ${res.status}` };
  setToken(body.access_token);
  setUser(body.user);
  return { ok: true, user: body.user };
}

export function logout() {
  setToken('');
  setUser(null);
  // 觸發 AuthGate 重新進 locked
  _triggerUnauthorized('logout');
}
