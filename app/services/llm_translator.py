"""LLM 策略翻譯器 — Phase 4

把爬到的 Pine Script / Python / JS 策略邏輯翻成跟 strategy_engine.py 兼容的 signal function。

設計重點：
- 用 Anthropic Claude API（claude-sonnet-4-6，性價比高，code task 已夠用）
- System prompt 用 prompt caching（每個翻譯都重用同一份規則 + in-context examples）
- Output 強制 JSON（schema 固定）— 用 <output>...</output> tag 包夾，避開 model 亂加說明
- 翻譯產物**不直接信任** — 還要過 candidate_sandbox.verify_signal_fn

需要環境變數：ANTHROPIC_API_KEY
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

DEFAULT_MODEL = os.environ.get('LLM_TRANSLATOR_MODEL', 'claude-sonnet-4-6')


SYSTEM_PROMPT = """You translate trading strategies from Pine Script / Python / JS into a Python `signal function` compatible with our backtest engine.

## OUTPUT CONTRACT (strict)
Reply ONLY with one `<output>...</output>` block containing a JSON object with these fields:
- `signal_fn_name`: snake_case identifier, must match the `def` in `signal_fn_source`, end with `_signal`
- `signal_fn_source`: full Python source of the function (no surrounding markdown, no extra functions, single `def`)
- `default_params`: dict of named hyperparameters that the function reads from its `params` argument
- `category`: one of `ultra` (15m), `short` (1h), `swing` (4h), `long` (4h+)
- `timeframe`: one of `15m`, `1h`, `4h`
- `candidate_type`: short snake_case slug (no spaces) used as dispatch key; should reflect the strategy idea
- `notes`: 2-4 sentence plain-English description of the entry/exit logic and any caveats from the translation

No other prose outside the `<output>` block.

## STRATEGY ENGINE CONTRACT
The function signature is:

```python
def <name>_signal(df, params=None) -> str:
    # df is a pandas DataFrame with columns: timestamp, open, high, low, close, volume (sorted ascending)
    # params is a dict; read with params.get('key', default) — must NOT crash if params is None or empty
    # Return exactly one of: 'buy', 'sell', 'hold'  (we also accept 'long'/'short'/'close' aliases)
    ...
```

Hard rules:
1. Pure function. No file/network/socket I/O, no print, no global state.
2. Imports allowed inside the function body: `pandas as pd`, `numpy as np`, `ta`, `math`. Use module names already in scope; **do not write `import`** — pretend `pd`, `np`, `ta`, `math` are already imported.
3. Handle insufficient history: if `len(df) < required_window`, return `'hold'`.
4. Decision uses ONLY data up to `df.iloc[-1]` — never look ahead.
5. Default `params` values must reproduce the source strategy's documented defaults.
6. Pine Script `crossover(a, b)`: `a.iloc[-2] <= b.iloc[-2] and a.iloc[-1] > b.iloc[-1]`. Always use shifted comparison, not just current bar.
7. If the source strategy is a long-only (no shorts), only emit `'buy'` for entry and `'sell'` for exit. If it uses both directions, return `'buy'` on long entry and `'sell'` on short entry — our engine treats `'sell'` as close-existing-long for now.
8. Library `ta` (Bukosabino) usage:
   - `ta.trend.ema_indicator(close, window=n)` — EMA series
   - `ta.trend.sma_indicator(close, window=n)` — SMA series
   - `ta.momentum.rsi(close, window=n)`
   - `ta.trend.MACD(close, window_slow, window_fast, window_sign)` → `.macd()`, `.macd_signal()`, `.macd_diff()`
   - `ta.volatility.BollingerBands(close, window=n, window_dev=k)` → `.bollinger_hband()`, `.bollinger_lband()`, `.bollinger_mavg()`
   - `ta.volatility.AverageTrueRange(high, low, close, window=n).average_true_range()`
   - `ta.trend.ADXIndicator(high, low, close, window=n).adx()`
   - `ta.momentum.StochasticOscillator(high, low, close, window=k, smooth_window=d).stoch()` / `.stoch_signal()`
   - `ta.trend.CCIIndicator(high, low, close, window=n).cci()`
   - `ta.trend.PSARIndicator(high, low, close, step=s, max_step=m).psar()`

## IN-CONTEXT EXAMPLES

### Example 1 — RSI mean reversion (input: Python-ish pseudo)
```
if RSI(close, 14) crosses above 30: buy
if RSI(close, 14) crosses below 70: sell
```

Output:
```python
def rsi_reversion_signal(df, params=None):
    p = params or {}
    period = p.get('period', 14)
    oversold = p.get('oversold', 30)
    overbought = p.get('overbought', 70)
    if df is None or len(df) < period + 5:
        return 'hold'
    rsi = ta.momentum.rsi(df['close'], window=period)
    prev, curr = rsi.iloc[-2], rsi.iloc[-1]
    if prev <= oversold and curr > oversold:
        return 'buy'
    if prev >= overbought and curr < overbought:
        return 'sell'
    return 'hold'
```

### Example 2 — Pine Script SuperTrend (input)
```
//@version=5
atr = ta.atr(period)
up = hl2 - mult * atr
dn = hl2 + mult * atr
// supertrend flip logic
if direction[1] == 1 and close < up: direction := -1
if direction[1] == -1 and close > dn: direction := 1
longCondition = direction == 1 and direction[1] == -1
shortCondition = direction == -1 and direction[1] == 1
```

Output:
```python
def supertrend_signal(df, params=None):
    p = params or {}
    period = p.get('period', 10)
    multiplier = p.get('multiplier', 3)
    if df is None or len(df) < period + 5:
        return 'hold'
    hl2 = (df['high'] + df['low']) / 2
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=period).average_true_range()
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr
    direction = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        prev = direction.iloc[i - 1]
        if prev == 1 and df['close'].iloc[i] < lower_basic.iloc[i]:
            direction.iloc[i] = -1
        elif prev == -1 and df['close'].iloc[i] > upper_basic.iloc[i]:
            direction.iloc[i] = 1
        else:
            direction.iloc[i] = prev
    if direction.iloc[-1] == 1 and direction.iloc[-2] == -1:
        return 'buy'
    if direction.iloc[-1] == -1 and direction.iloc[-2] == 1:
        return 'sell'
    return 'hold'
```

### Example 3 — Donchian breakout (Python source already exists, just normalize)
Output:
```python
def donchian_breakout_signal(df, params=None):
    p = params or {}
    period = p.get('period', 20)
    if df is None or len(df) < period + 2:
        return 'hold'
    upper = df['high'].rolling(period).max()
    lower = df['low'].rolling(period).min()
    close = df['close'].iloc[-1]
    if close > upper.iloc[-2]:
        return 'buy'
    if close < lower.iloc[-2]:
        return 'sell'
    return 'hold'
```

Remember: ONE `<output>` JSON block, no other text."""


USER_TEMPLATE = """Translate this {raw_lang} strategy into our signal function format.

Source name: {source_name}
Source author: {source_author}
Source URL: {source_url}

Raw code:
```{raw_lang}
{raw_code}
```

Produce the `<output>` JSON now."""


_OUTPUT_RE = re.compile(r'<output>\s*(\{.*?\})\s*</output>', re.DOTALL)


def build_full_prompt(*, raw_code: str, raw_lang: str = 'python',
                      source_name: str = 'unknown', source_author: str = 'unknown',
                      source_url: str = '') -> str:
    """把 SYSTEM_PROMPT + USER_TEMPLATE 串成一條給 CLI/外部 LLM 用的純文字 prompt。"""
    user_msg = USER_TEMPLATE.format(
        raw_lang=raw_lang or 'python',
        source_name=source_name or 'unknown',
        source_author=source_author or 'unknown',
        source_url=source_url or '',
        raw_code=(raw_code or '')[:30000],
    )
    return SYSTEM_PROMPT + '\n\n' + user_msg


def build_prompt_for_candidate(candidate_id: int) -> dict:
    """從 DB 抓出 candidate，組好 prompt 文字（host 端會用這個）"""
    from app.models import StrategyCandidate
    c = StrategyCandidate.query.get(candidate_id)
    if c is None:
        raise LLMTranslatorError(f'candidate {candidate_id} not found')
    if not c.raw_code or not c.raw_code.strip():
        raise LLMTranslatorError(f'candidate {candidate_id} has no raw_code')
    return {
        'candidate_id': c.id,
        'source_name': c.source_name or 'unknown',
        'raw_lang': c.raw_lang or 'python',
        'prompt': build_full_prompt(
            raw_code=c.raw_code,
            raw_lang=c.raw_lang or 'python',
            source_name=c.source_name or 'unknown',
            source_author=c.source_author or 'unknown',
            source_url=c.source_url or '',
        ),
    }


def save_translation_for_candidate(candidate_id: int, raw_output: str, model_label: str = 'claude-cli') -> dict:
    """收到 CLI/外部 LLM 的回應後，解析 + 沙箱驗證 + 寫回 DB。
    跟 candidate_pipeline.translate_and_verify 共用後段邏輯，只是不調 SDK。
    """
    from app.extensions import db
    from app.models import StrategyCandidate
    from app.services.candidate_sandbox import verify_signal_fn

    c = StrategyCandidate.query.get(candidate_id)
    if c is None:
        return {'ok': False, 'error': f'candidate {candidate_id} not found'}

    # 解析
    try:
        parsed = _parse_output(raw_output)
    except LLMTranslatorError as e:
        c.status = 'error'
        c.error_log = f'parse: {e}'
        db.session.commit()
        return {'ok': False, 'error': str(e), 'candidate': c.to_dict()}

    # 沙箱驗證
    verify = verify_signal_fn(
        source=parsed['signal_fn_source'],
        fn_name=parsed['signal_fn_name'],
        default_params=parsed.get('default_params') or {},
    )
    # 先寫入翻譯產物（即使沙箱失敗也保留，方便 debug）
    c.parsed_signal = parsed['signal_fn_source']
    c.signal_fn_name = parsed['signal_fn_name']
    c.candidate_type = parsed['candidate_type']
    c.category = parsed['category']
    c.timeframe = parsed['timeframe']
    c.default_params = parsed['default_params']
    c.llm_notes = parsed['notes']
    c.llm_model = model_label

    if not verify['ok']:
        c.status = 'error'
        c.error_log = f'sandbox: {verify["error"]}'
        db.session.commit()
        return {'ok': False, 'error': f'sandbox: {verify["error"]}', 'candidate': c.to_dict(), 'verify': verify}

    c.status = 'translated'
    c.error_log = None
    db.session.commit()
    return {'ok': True, 'candidate': c.to_dict(include_code=False), 'verify': verify}


class LLMTranslatorError(Exception):
    pass


def _get_client():
    """延遲 import，避免沒裝 anthropic 時整個 routes 載入失敗"""
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise LLMTranslatorError(f'anthropic SDK not installed: {e}')
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key:
        raise LLMTranslatorError('ANTHROPIC_API_KEY not set in env')
    return Anthropic(api_key=key)


def _parse_output(text: str) -> dict:
    m = _OUTPUT_RE.search(text)
    if not m:
        raise LLMTranslatorError(f'no <output>{{...}}</output> block in model reply; got: {text[:400]}')
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise LLMTranslatorError(f'invalid JSON inside <output>: {e}; raw: {m.group(1)[:300]}')

    required = {'signal_fn_name', 'signal_fn_source', 'default_params', 'category', 'timeframe', 'candidate_type', 'notes'}
    missing = required - set(obj.keys())
    if missing:
        raise LLMTranslatorError(f'missing keys: {sorted(missing)}')

    if obj['category'] not in {'ultra', 'short', 'swing', 'long'}:
        raise LLMTranslatorError(f'invalid category: {obj["category"]}')
    if obj['timeframe'] not in {'15m', '1h', '4h'}:
        raise LLMTranslatorError(f'invalid timeframe: {obj["timeframe"]}')
    if not isinstance(obj['default_params'], dict):
        raise LLMTranslatorError(f'default_params must be dict, got {type(obj["default_params"])}')
    if not re.match(r'^[a-z][a-z0-9_]*$', obj['candidate_type']):
        raise LLMTranslatorError(f'candidate_type must be snake_case: {obj["candidate_type"]}')
    if f"def {obj['signal_fn_name']}(" not in obj['signal_fn_source']:
        raise LLMTranslatorError(f'signal_fn_name "{obj["signal_fn_name"]}" not found as def in source')

    return obj


def translate(
    *,
    raw_code: str,
    raw_lang: str = 'python',
    source_name: str = 'unknown',
    source_author: str = 'unknown',
    source_url: str = '',
    model: Optional[str] = None,
) -> dict:
    """呼叫 Claude API 翻譯一段策略代碼，回傳結構化結果。

    回傳：{
        'signal_fn_name', 'signal_fn_source',
        'default_params', 'category', 'timeframe', 'candidate_type', 'notes',
        'model', 'usage' (token 用量)
    }
    失敗時 raise LLMTranslatorError。
    """
    if not raw_code or not raw_code.strip():
        raise LLMTranslatorError('raw_code is empty')

    client = _get_client()
    model = model or DEFAULT_MODEL

    user_msg = USER_TEMPLATE.format(
        raw_lang=raw_lang or 'python',
        source_name=source_name or 'unknown',
        source_author=source_author or 'unknown',
        source_url=source_url or '',
        raw_code=raw_code[:30000],   # 防爆 token
    )

    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[{
            'type': 'text',
            'text': SYSTEM_PROMPT,
            'cache_control': {'type': 'ephemeral'},  # 跨候選共用系統提示
        }],
        messages=[{'role': 'user', 'content': user_msg}],
    )

    text = ''.join(b.text for b in resp.content if getattr(b, 'type', None) == 'text')
    parsed = _parse_output(text)
    parsed['model'] = model
    parsed['usage'] = {
        'input_tokens': getattr(resp.usage, 'input_tokens', None),
        'output_tokens': getattr(resp.usage, 'output_tokens', None),
        'cache_creation_input_tokens': getattr(resp.usage, 'cache_creation_input_tokens', None),
        'cache_read_input_tokens': getattr(resp.usage, 'cache_read_input_tokens', None),
    }
    return parsed
