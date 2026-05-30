"""Phase 15 钥匙: AI 经理 — 守门员的参数大脑 (user 2026-05-30 命名+定义)

角色区分 (user 定):
  · 守门员 (gatekeeper): 执行循环 — 扫描/富感知/配对/检测信号/回测EV/下单. 机械操盘手.
  · AI 经理 (ai_manager): 大脑 — 握着人给的月盈利目标(→难度基调), 守门员每来一个信号就问经理
    "请给参数", 经理**带着 难度基调 + 富感知 + 策略画像 临场判断**给这一单的 lev/SL/TP/R/仓位.

这是"AI 驱动 = prompt = moat"真正进 live 循环的那一步 (之前守门员是纯机械: 公式杠杆+SL网格扫).
关键: AI 经理**睁着眼(富感知)+ 懂这策略(画像)**给参数, 不是瞎套公式. 行情踩中策略弱点 → 经理可
判断更保守甚至 skip. 蓝图 project-phase15-blueprint 第八节 (参数→AI动态判断, 我写prompt).

⚠️ 经理给的参数仍在难度**信封**内 (杠杆≤上限/R≤缩放), 返回后守门员再回测EV把关 — 经理判断 + 回测验证 双保险.
"""
from __future__ import annotations

import json

SYSTEM = """你是量化操盘的 AI 经理. 守门员(机械执行层)检测到某策略信号触发, 来问你要这一单的参数.
你握着用户的月盈利目标(=难度基调/约束信封). 你要**结合 难度基调 + 当前市场富感知 + 这个策略的画像**,
临场判断给出这一单的参数. 关键: 你睁着眼(感知)且懂这策略(画像)——若当前行情正好踩中这策略的弱点
(如震荡市用突破策略), 你该更保守、缩小R/杠杆, 甚至判断不该开(skip). 别机械套公式.
只输出 JSON, 无 markdown."""


def ai_manager_params(symbol: str, strategy_type: str, perception: dict, profile: dict,
                      target_pct: float, days_remaining: int, user_id: int = 1) -> dict:
    """守门员问 AI 经理要参数. 返回 {ok, skip, leverage, init_sl_pct, tp1_r, tp2_r, tp3_r,
    position_size_usdt, reason_zh}. 失败/异常 → ok=False (守门员回退机械参数)。"""
    from app.services.llm_provider import call_llm
    from app.services.profit_difficulty import difficulty_guidance_block, profit_difficulty, monthly_equiv

    diff = profit_difficulty(monthly_equiv(target_pct, days_remaining))
    lev_cap = diff.get('leverage_cap') or 5
    if diff.get('blocked'):
        return {'ok': True, 'skip': True, 'reason_zh': '盈利目标超系统上限, 经理拒绝开仓'}

    ind = {k: (v or {}).get('state') for k, v in (perception.get('indicators') or {}).items()}
    pa = perception.get('price_action') or {}
    prof = profile or {}
    prompt = f"""## 盈利目标难度 (你的约束信封)
{difficulty_guidance_block(target_pct, days_remaining)}

## 当前市场富感知 (你的眼睛)
- regime={perception.get('regime')} 方向={perception.get('direction')} 波动={perception.get('volatility')} 量={perception.get('volume')}
- MTF多周期对齐={perception.get('mtf_aligned')} · 动能={pa.get('momentum')} · 猎杀针={pa.get('hunt')} · 形态={pa.get('pattern')}
- 指标状态: {json.dumps(ind, ensure_ascii=False)}
- 资金费={perception.get('funding')}

## 这个策略的画像 (你懂它在做什么)
- 策略: {strategy_type}
- 进场逻辑: {prof.get('entry_logic')}
- edge来源: {prof.get('edge_source')}
- 弱点(什么环境失效): {prof.get('weakness')}
- 适配: regime_fit={prof.get('regime_fit')} · timeframe_fit={prof.get('timeframe_fit')} · 方向={prof.get('direction')}

## 任务: 给这一单的参数 (JSON)
{{
  "skip": false,                  // 若当前行情正好踩中这策略弱点(如震荡市+突破策略)、判断不该开 → true
  "leverage": 数字,               // ≤ {lev_cap} (难度上限)
  "init_sl_pct": 数字,            // 初始止损价格距离% (杠杆前). 行情噪音大/弱点环境→给宽点防扫
  "tp1_r": 0.5, "tp2_r": 1.2, "tp3_r": 2.0,   // 盈亏比R倍数. 难度难 or 行情弱 → 可等比缩小求稳
  "position_size_usdt": 数字,     // 保证金, 难度激进可大、保守小
  "reason_zh": "为什么这样给 (结合当前行情 + 这策略的edge/弱点 一句话)"
}}
在难度信封内(杠杆≤{lev_cap}), 贴合当前行情和这策略特性. 踩中弱点就skip或更保守."""

    try:
        r = call_llm(user_id=user_id, prompt=prompt, system=SYSTEM, max_tokens=600, model='opus',
                     cache_key=None)   # 每单实时判断, 不缓存
        if not r.get('ok'):
            return {'ok': False, 'error': r.get('error')}
        from app.services.llm_prompts.strategy_generate import _extract_json
        p = _extract_json(r['text'])
        if p.get('skip'):
            return {'ok': True, 'skip': True, 'reason_zh': p.get('reason_zh', '经理判断不开')}
        # 验证/夹紧在难度信封内 (经理判断 + 硬约束双保险)
        lev = _clamp(float(p.get('leverage', lev_cap)), 1, lev_cap)
        sl = _clamp(float(p.get('init_sl_pct', 0.8)), 0.3, 5.0)
        out = {
            'ok': True, 'skip': False,
            'leverage': lev,
            'init_sl_pct': sl,
            'tp1_r': _clamp(float(p.get('tp1_r', 0.5)), 0.2, 3),
            'tp2_r': _clamp(float(p.get('tp2_r', 1.2)), 0.4, 5),
            'tp3_r': _clamp(float(p.get('tp3_r', 2.0)), 0.6, 8),
            'position_size_usdt': _clamp(float(p.get('position_size_usdt', 10)), 1, 1000),
            'reason_zh': p.get('reason_zh', ''),
        }
        return out
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}


def _clamp(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except Exception:
        return lo
