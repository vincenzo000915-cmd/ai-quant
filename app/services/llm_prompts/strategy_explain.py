"""Phase 11.5.3: 策略解釋 — 第一個 AI demo

輸入：strategy (Strategy ORM 物件 或 dict)
輸出：dict {ok, text, model_used, provider_used, cached, usage, latency_ms, error?}

Prompt 設計：拿策略 type/params/symbol/category/timeframe，請 LLM 用 3-5 段
中文（300 字內）說明邏輯、適合市場、怕的市場、關鍵參數方向。
末尾固定 disclaimer。

Cache key 含 (type, params canonical JSON, symbol, timeframe) — 同樣參數
24h 內復用，避免重複燒 token。
"""
from __future__ import annotations

import hashlib
import json

from app.services.llm_provider import call_llm


SYSTEM_PROMPT = """你是專業量化交易顧問。用戶會給你一個策略的技術配置，請用清晰中文（簡體優先）回答 3-5 段：

1. **本質**（一句話）：這策略邏輯是什麼？
2. **賺什麼市場**：在什麼市況下會獲利（趨勢 / 震蕩 / 突破 / 反轉），具體場景描述。
3. **怕什麼市場**：什麼情境會虧損或頻繁失效（盤整 / 假突破 / 流動性枯竭 等）。
4. **關鍵參數**：列出 1-2 個用戶該重點調整的參數，說明調大/調小的影響。
5. **使用建議**：給普通用戶 1-2 句具體建議（時間框架、倉位、配對等）。

注意：
- 不要承諾盈利、不要給出具體買賣信號
- 不要說「這策略一定能賺」之類絕對話
- 末尾固定加：「⚠️ 量化策略不保證盈利，請結合風控自行判斷。」
- 控制 300 字以內，言之有物
- 用 markdown 格式（**粗體** 標題）便於閱讀"""


def _build_prompt(strategy_dict: dict) -> str:
    params_str = json.dumps(strategy_dict.get('params') or {}, ensure_ascii=False, indent=2)
    return (
        f"請解釋以下量化策略：\n\n"
        f"- 策略類型 (type): {strategy_dict.get('type')}\n"
        f"- 策略名稱: {strategy_dict.get('name')}\n"
        f"- 交易品種: {strategy_dict.get('symbol')}\n"
        f"- 時間框架: {strategy_dict.get('timeframe')}\n"
        f"- 類別: {strategy_dict.get('category')}（short=短線 / swing=波段 / long=長線 / ultra=極短）\n"
        f"- 參數: ```json\n{params_str}\n```\n\n"
        f"請按系統提示的 5 個段落回答。"
    )


def explain_strategy(user_id: int, strategy_dict: dict) -> dict:
    """主入口。回傳 call_llm 的標準結構 + 加 'strategy_id' 便利"""
    if not strategy_dict.get('type'):
        return {'ok': False, 'error': '策略缺少 type 字段', 'text': ''}

    # 24h cache：(type, params, symbol, timeframe) hash
    sig = json.dumps([
        strategy_dict.get('type'),
        strategy_dict.get('params'),
        strategy_dict.get('symbol'),
        strategy_dict.get('timeframe'),
    ], sort_keys=True, ensure_ascii=False, default=str)
    cache_key = 'explain:' + hashlib.sha256(sig.encode('utf-8')).hexdigest()[:24]

    prompt = _build_prompt(strategy_dict)
    return call_llm(
        user_id=user_id,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=1500,
        cache_key=cache_key,
    )
