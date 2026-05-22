"""Phase 11.5.4: 自然語言 → strategy signal function

輸入：user 自然語言描述（例「我想要結合 RSI 反向 + 布林帶擠壓的短線多策略」）
輸出：strategy_candidates row（status='translated'），可選地立刻 backtest

LLM 要返回嚴格 JSON：
{
  "candidate_type": "rsi_bb_squeeze_short",   // snake_case slug
  "signal_fn_name": "rsi_bb_squeeze_signal",
  "category": "short",                        // short | swing | long | ultra
  "timeframe": "15m",                          // 15m | 30m | 1h | 4h | 1d | 1w
  "default_params": { "rsi_period": 14, ... },
  "parsed_signal": "def rsi_bb_squeeze_signal(df, params):\\n    ...",
  "llm_notes": "用 RSI < 30 + 布林帶擠壓觸發 long..."
}

流程：
1. call_llm → 解析 JSON
2. candidate_sandbox.verify_signal_fn() 沙箱驗證
3. 寫 strategy_candidates 表 (status='translated'，user_id 是當前 actor)
4. 失敗回 ok=False + error
"""
from __future__ import annotations

import datetime
import json
import re

from app.extensions import db
from app.models import StrategyCandidate
from app.services.candidate_sandbox import verify_signal_fn
from app.services.llm_provider import call_llm


# 給 strategy_engine signal function 沙箱可用的 API
SANDBOX_API_DOC = """
你會寫 Python signal function，輸入是 pandas.DataFrame df（含 columns: open/high/low/close/volume, index=timestamp）
與 dict params。返回字串信號 'buy' / 'sell' / 'hold' 之一（也可用 'long'/'short'/'close'）。

可用：pandas as pd, numpy as np, 以及 ta 套件 (ta.trend, ta.momentum, ta.volatility, ta.volume)。
**不准** import os/sys/subprocess/socket/open file/network。
**不准** 寫 while True / 無限迴圈。
寫法範例：
    def my_signal(df, params):
        rsi_period = params.get('rsi_period', 14)
        if len(df) < rsi_period + 5:
            return 'hold'
        rsi = ta.momentum.RSIIndicator(df['close'], window=rsi_period).rsi()
        last = rsi.iloc[-1]
        if last < 30:
            return 'buy'
        if last > 70:
            return 'sell'
        return 'hold'
"""

SYSTEM_PROMPT = f"""你是專業量化策略工程師。User 用自然語言描述一個策略想法，
你要生成**能通過嚴格回測門檻 (OOS Sharpe ≥ 1.5)** 的策略 JSON。

{SANDBOX_API_DOC}

## 🔴 真實交易成本必須計入策略邏輯：
- OKX 雙邊成本 = fee 0.05%×2 + slippage 0.05%×2 = **每筆 0.20%**
- 高頻策略 (>50 trades/月) 必被 fee 吃光小波段利潤
- **避免**：scalping、5m/15m mean reversion、嚴格觸發即動
- **偏好**：4h/1d 等待大波段；trend filter + vol filter 自然降頻

## 必須包含的設計元素：
1. **Trend filter**（EMA50/200 過濾逆勢）
2. **Vol/regime filter**（ATR 或 BB width 判盤整 vs 趨勢）
3. **嚴格觸發條件**（多重 AND，自然降頻到 5-30 trades/月）
4. 不要 overfit：用標準閾值 30/70/0.5，不用魔法數字

## 範例對比（學這個）：

❌ **差**：`if rsi < 30: return 'buy'` — 太頻繁 + 逆勢被打爛
✅ **好**：`if rsi < 30 and close > ema200 and bb_width < 0.05: return 'buy'` — trend filter + squeeze 過濾

返回 JSON schema（**所有欄位必填**）：
{{
  "candidate_type": "snake_case slug",
  "signal_fn_name": "..._signal",
  "category": "short" | "swing" | "long" | "ultra",
  "timeframe": "15m" | "30m" | "1h" | "4h" | "1d" | "1w",
  "default_params": {{}},
  "parsed_signal": "完整 def signal_fn_name(df, params): ...（含 trend filter + 嚴格觸發）",
  "llm_notes": "說明：預估月 trade 頻率 / 用了什麼 filter / 適合什麼市況 / 何時失效"
}}

要求：
- 不要 markdown fenced block 包 JSON
- 所有字串雙引號（JSON 標準）
- parsed_signal 內 \\n 用字面 newline
- timeframe 跟 category 匹配
- 同時有 buy / sell 路徑
- 預期月頻率寫在 llm_notes
"""


def _extract_json(text: str) -> dict | None:
    """LLM 偶爾會包 ```json ... ``` 或前後有解釋文字。嘗試多種方式提取"""
    text = text.strip()
    # 1. 直接 parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. ```json ... ``` block
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 第一個 { 到最後 } 之間
    a = text.find('{')
    b = text.rfind('}')
    if a >= 0 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except json.JSONDecodeError:
            pass
    return None


REQUIRED_FIELDS = {'candidate_type', 'signal_fn_name', 'category', 'timeframe',
                   'default_params', 'parsed_signal', 'llm_notes'}


def generate_strategy(user_id: int, description: str) -> dict:
    """主入口：自然語言 → candidate row。

    回 {ok, candidate_id?, candidate_dict?, llm_meta, error?}
    """
    if not (description and description.strip()):
        return {'ok': False, 'error': '描述不能為空'}
    if len(description) > 2000:
        return {'ok': False, 'error': '描述太長（最多 2000 字符）'}

    llm = call_llm(
        user_id=user_id,
        prompt=description.strip(),
        system=SYSTEM_PROMPT,
        max_tokens=4000,
    )
    if not llm.get('ok'):
        return {'ok': False, 'error': f'LLM 失敗: {llm.get("error")}', 'llm_meta': llm}

    spec = _extract_json(llm['text'])
    if spec is None:
        return {'ok': False, 'error': 'LLM 輸出無法解析成 JSON',
                'llm_meta': llm, 'raw_output': llm['text'][:500]}

    missing = REQUIRED_FIELDS - set(spec.keys())
    if missing:
        return {'ok': False, 'error': f'LLM 輸出缺欄位: {sorted(missing)}',
                'llm_meta': llm, 'raw_spec': spec}

    # sandbox 驗證
    verify = verify_signal_fn(spec['parsed_signal'], spec['signal_fn_name'],
                              spec.get('default_params') or {})
    if not verify.get('ok'):
        return {'ok': False, 'error': f'sandbox 驗證失敗: {verify.get("error")}',
                'llm_meta': llm, 'raw_spec': spec, 'verify': verify}

    # 防衝突：候選池若已有同 candidate_type
    existing = StrategyCandidate.query.filter_by(candidate_type=spec['candidate_type']).first()
    candidate_type = spec['candidate_type']
    if existing:
        candidate_type = f'{candidate_type}_{int(datetime.datetime.utcnow().timestamp())}'

    rec = StrategyCandidate(
        source='manual',
        source_name=f'AI 生成 (user {user_id})',
        source_author=f'user:{user_id}',
        source_meta={'description': description, 'llm_provider': llm.get('provider_used'),
                     'llm_model': llm.get('model_used')},
        raw_code=description,
        raw_lang='nl',                        # natural language
        parsed_signal=spec['parsed_signal'],
        signal_fn_name=spec['signal_fn_name'],
        candidate_type=candidate_type,
        category=spec.get('category', 'swing'),
        timeframe=spec.get('timeframe', '4h'),
        default_params=spec.get('default_params') or {},
        llm_notes=spec.get('llm_notes'),
        llm_model=llm.get('model_used', 'unknown'),
        status='translated',
    )
    db.session.add(rec)
    db.session.commit()
    return {
        'ok': True,
        'candidate_id': rec.id,
        'candidate': rec.to_dict(include_code=False),
        'verify': verify,
        'llm_meta': {
            'provider_used': llm.get('provider_used'),
            'model_used': llm.get('model_used'),
            'usage': llm.get('usage'),
            'latency_ms': llm.get('latency_ms'),
        },
    }
