"""候選策略沙箱驗證 — Phase 4

接到 LLM 翻譯產出的 Python 代碼後，在隔離 namespace 跑一次驗證：
1. exec 不報語法 / import error
2. 函式存在且 callable
3. 用合成 OHLCV DataFrame 連跑數次，回傳值合法（buy/sell/hold/long/short/close）

刻意**不**用 ast.parse 做靜態檢查 — LLM 偶爾會用合法但非 strategy_engine 風格的寫法，
靠 runtime 行為驗證比靜態白名單更穩。但 namespace 受限：禁止 os/subprocess/socket 等。
"""
from __future__ import annotations

import builtins
import math
import types
import numpy as np
import pandas as pd
import ta


VALID_SIGNALS = {'buy', 'sell', 'hold', 'long', 'short', 'close'}

# 沙箱允許 import 的模組白名單（任何不在此清單的 import 會 raise）
_ALLOWED_MODULES = {'numpy', 'np', 'pandas', 'pd', 'math', 'ta'}


def _build_dummy_candles(n: int = 250) -> pd.DataFrame:
    """生成合成 OHLCV，價格走勢混合上升 + 震盪 + 下跌 — 用於觸發多種信號路徑"""
    rng = np.random.default_rng(42)
    base = np.linspace(60000, 70000, n)
    noise = rng.normal(0, 500, n).cumsum() * 0.3
    close = base + noise
    open_ = close + rng.normal(0, 80, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 120, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 120, n))
    volume = rng.uniform(50, 500, n)
    ts = np.arange(n) * 14400 + 1700000000  # 4h interval, fake start

    return pd.DataFrame({
        'timestamp': ts,
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    """禁止沙箱 import 黑名單以外的模組"""
    top = name.split('.')[0]
    if top not in _ALLOWED_MODULES:
        raise ImportError(f'sandbox: import "{name}" not allowed')
    return __import__(name, globals, locals, fromlist, level)


def _make_sandbox_globals() -> dict:
    """構造受限 globals：允許 pandas/numpy/ta、塞掉危險 builtin"""
    safe_builtins = {
        k: getattr(builtins, k) for k in (
            'abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'filter', 'float',
            'int', 'isinstance', 'len', 'list', 'map', 'max', 'min', 'pow',
            'range', 'reversed', 'round', 'set', 'slice', 'sorted', 'str',
            'sum', 'tuple', 'type', 'zip', 'True', 'False', 'None',
            'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError',
            'ZeroDivisionError', 'AttributeError',
        ) if hasattr(builtins, k)
    }
    safe_builtins['__import__'] = _restricted_import
    return {
        '__builtins__': safe_builtins,
        'pd': pd,
        'np': np,
        'ta': ta,
        'math': math,
    }


def verify_signal_fn(
    source: str,
    fn_name: str,
    default_params: dict | None = None,
    *,
    n_calls: int = 5,
    min_window: int = 100,
) -> dict:
    """在沙箱跑一段 signal function source code，回傳驗證結果。

    回傳格式：
    {
      'ok': bool,
      'error': str | None,
      'signals_seen': list[str],   # 各次呼叫產出（除錯用）
      'has_buy': bool, 'has_sell': bool,  # 是否觸發過買賣（純 hold 也算 ok 但會標記）
    }
    """
    default_params = default_params or {}
    g = _make_sandbox_globals()

    # Step 1: exec source
    try:
        exec(compile(source, f'<candidate:{fn_name}>', 'exec'), g)
    except SyntaxError as e:
        return {'ok': False, 'error': f'syntax: {e}', 'signals_seen': [], 'has_buy': False, 'has_sell': False}
    except Exception as e:
        return {'ok': False, 'error': f'exec: {type(e).__name__}: {e}', 'signals_seen': [], 'has_buy': False, 'has_sell': False}

    # Step 2: 找函式
    fn = g.get(fn_name)
    if not callable(fn):
        # 容錯：source 可能含多個 def，找第一個 callable
        callables = [v for k, v in g.items() if not k.startswith('_') and callable(v) and isinstance(v, types.FunctionType)]
        if callables:
            fn = callables[0]
        else:
            return {'ok': False, 'error': f'function "{fn_name}" not found in source', 'signals_seen': [], 'has_buy': False, 'has_sell': False}

    # Step 3: 跑 n_calls 次，每次餵不同窗口
    df_full = _build_dummy_candles(n=min_window + n_calls * 10)
    signals_seen = []
    for k in range(n_calls):
        window_end = min_window + k * 10
        df_window = df_full.iloc[:window_end].copy()
        try:
            sig = fn(df_window, dict(default_params))
        except Exception as e:
            return {
                'ok': False,
                'error': f'runtime call #{k}: {type(e).__name__}: {e}',
                'signals_seen': signals_seen,
                'has_buy': any(s in ('buy', 'long') for s in signals_seen),
                'has_sell': any(s in ('sell', 'short', 'close') for s in signals_seen),
            }

        if not isinstance(sig, str) or sig.lower() not in VALID_SIGNALS:
            return {
                'ok': False,
                'error': f'invalid return on call #{k}: {sig!r} (expected one of {sorted(VALID_SIGNALS)})',
                'signals_seen': signals_seen,
                'has_buy': any(s in ('buy', 'long') for s in signals_seen),
                'has_sell': any(s in ('sell', 'short', 'close') for s in signals_seen),
            }
        signals_seen.append(sig.lower())

    return {
        'ok': True,
        'error': None,
        'signals_seen': signals_seen,
        'has_buy': any(s in ('buy', 'long') for s in signals_seen),
        'has_sell': any(s in ('sell', 'short', 'close') for s in signals_seen),
    }


def load_signal_fn(source: str, fn_name: str):
    """載入並回傳沙箱中的 callable（給 backtest_engine 用，配 signal_fn 參數）。

    不做驗證 — 假設先跑過 verify_signal_fn。執行同樣的受限 namespace。
    """
    g = _make_sandbox_globals()
    exec(compile(source, f'<candidate:{fn_name}>', 'exec'), g)
    fn = g.get(fn_name)
    if not callable(fn):
        # fallback: 第一個 def
        for k, v in g.items():
            if not k.startswith('_') and isinstance(v, types.FunctionType):
                return v
        raise ValueError(f'function "{fn_name}" not callable')
    return fn
