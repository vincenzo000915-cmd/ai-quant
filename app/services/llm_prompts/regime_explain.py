"""Phase 11.5.5: regime 解讀 prompt

輸入：regime data 來自 /api/regime/running
輸出：中文段落「現在像 XXXX 年那種盤整偏弱趨勢，VWAP/SuperTrend 系怕橫盤」

5 分鐘 cache（regime 變化慢）。
"""
from __future__ import annotations

import hashlib
import json

from app.services.llm_provider import call_llm

SYSTEM_PROMPT = """你是專業量化市場分析師。User 給你當前各 (symbol, timeframe)
的 regime 數據（ADX 趨勢強度 + Hurst 指數 + 標籤 strong_trend/weak_trend/range/unknown）
以及每個 running 策略的 affinity 配對結果（fit good/ok/bad）。

請用 3 段中文回答（200 字以內）：

1. **市場現況**：總結現在多少 symbol/tf 在趨勢、多少在盤整，並挑代表性的一個描述（ADX/Hurst 具體值）。
2. **歷史類比**（重要）：把當前 regime 跟「某年某月那種行情」類比，幫 user 建立直覺。但只用泛指年份月份（如 "2023 年 8 月那種橫盤"），不要編造具體事件。
3. **策略建議**：哪些策略類型在當前 regime 容易賺/賠（基於 fit 數據），給 1-2 條操作建議。

注意：
- 不要承諾市場接下來怎麼走
- 不給投資建議，只解讀數據
- 末尾固定加：「⚠️ 此為 regime 解讀，非市場預測。」"""


def explain_regime(user_id: int, regime_data: dict) -> dict:
    """主入口。regime_data = 整個 /api/regime/running 的回傳。"""
    if not regime_data or not regime_data.get('per_strategy'):
        return {'ok': False, 'error': '當前無 running 策略，無 regime 數據'}

    # 5 分鐘 cache：(regimes labels + ADX 第一位小數) 作 key
    sig_payload = []
    for sk, rv in (regime_data.get('regimes') or {}).items():
        sig_payload.append([sk, rv.get('regime'), round(float(rv.get('adx') or 0), 1)])
    sig_payload.sort()
    sig = json.dumps(sig_payload, sort_keys=True)
    cache_key = 'regime:' + hashlib.sha256(sig.encode()).hexdigest()[:24]

    # 給 LLM 的 prompt：把 regime + per_strategy 整理成簡潔表
    prompt_lines = ['以下是當前市場 regime 數據：\n\n## Per (symbol, timeframe)\n']
    for sk, rv in (regime_data.get('regimes') or {}).items():
        prompt_lines.append(
            f'- {sk}: regime={rv.get("regime")}, ADX={rv.get("adx", "?")}, '
            f'Hurst={rv.get("hurst", "?")}'
        )
    prompt_lines.append('\n## Per running strategy fit\n')
    for s in regime_data.get('per_strategy', [])[:20]:
        prompt_lines.append(
            f'- #{s.get("strategy_id")} {s.get("name", "?")} ({s.get("type")}, {s.get("symbol")}@{s.get("timeframe")}): '
            f'regime={s.get("regime", "?")}, fit={s.get("fit", "?")}, affinity={s.get("affinity", "?")}'
        )
    prompt = '\n'.join(prompt_lines)

    return call_llm(
        user_id=user_id,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=1200,
        cache_key=cache_key,
    )
