// Phase 8.1: 全局 fetch wrap — 自動帶 Bearer token；401 觸發 onUnauthorized

const STORAGE_KEY = 'quant_api_token';

let _token = (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY)) || '';
const _listeners = new Set();

export function getToken() { return _token; }

export function setToken(t) {
  _token = t || '';
  if (typeof localStorage !== 'undefined') {
    if (_token) localStorage.setItem(STORAGE_KEY, _token);
    else localStorage.removeItem(STORAGE_KEY);
  }
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
      // 對 /api/auth/check 自身的 401 不要遞迴觸發
      const url = typeof input === 'string' ? input : (input?.url || '');
      if (!url.includes('/api/auth/check')) {
        _triggerUnauthorized('401');
      }
    }
    return res;
  };
  window.__quantFetchWrapped = true;
}

// 啟動時驗一次當前 token 是否有效
export async function verifyToken() {
  try {
    const r = await fetch('/api/auth/check');
    const body = await r.json();
    if (!body.enabled) return { enabled: false, ok: true };
    if (body.ok) return { enabled: true, ok: true };
    return { enabled: true, ok: false };
  } catch {
    return { enabled: true, ok: false };
  }
}
