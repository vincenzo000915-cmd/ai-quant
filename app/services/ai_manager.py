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


# 各交易所 taker 费率% (单边). HL DEX 低, OKX swap 高. EV/TP 判断必须含费率否则贴近TP被吃光.
EXCHANGE_FEE_PCT = {'hyperliquid': 0.035, 'okx': 0.05}


def exchange_fee_pct(exchange: str) -> float:
    return EXCHANGE_FEE_PCT.get((exchange or '').lower(), 0.05)


def instrument_constraints(exchange: str, symbol: str, lev: float) -> dict:
    """本单路由所的合约规格 + 成本 (喂给 AI 经理). 让经理在 [可行下限, 权益上限] 真实区间挑参数,
    且知道最小颗数 → 把仓位切得能干净退出 (防灰尘仓: 颗数太粗的币如 DOGE 不能细分).
    拉取失败 → 保守回退 HL $10 默认. lev 仅用于换算 min_margin。"""
    ex = (exchange or 'hyperliquid').lower()
    base_ccy = symbol.split('/')[0]
    out = {'exchange': ex, 'fee_pct': exchange_fee_pct(ex), 'min_notional': 10.0,
           'lot_desc': '未知(按保守处理)', 'price': 0.0, 'ok': False}
    try:
        from app.services.exchange_service import get_ticker
        out['price'] = float(get_ticker(symbol)['price'])
    except Exception:
        pass
    try:
        if ex == 'okx':
            from app.services.okx_meta import get_okx_instrument
            inst = get_okx_instrument(symbol)
            if inst and out['price'] > 0:
                ctval = float(inst['contract_size']); minsz = float(inst['min_size']); lotsz = float(inst['lot_size'])
                out.update({'min_notional': round(minsz * ctval * out['price'], 2),
                            'lot_step_base': lotsz * ctval,
                            'lot_desc': f'最小{minsz:g}张(每张{ctval:g}{base_ccy})→最小{round(minsz*ctval,6):g}{base_ccy}, 每跳{round(lotsz*ctval,6):g}{base_ccy}',
                            'ok': True})
        else:  # hyperliquid: 全币最小 $10 名义; 颗数精度 = szDecimals
            from app.services.hl_meta import get_hl_entry
            entry = get_hl_entry(symbol)
            sz_dec = int(entry.get('szDecimals')) if entry else 6
            out.update({'min_notional': 10.0, 'lot_step_base': 10 ** (-sz_dec),
                        'lot_desc': f'最小名义$10, 颗数精度{sz_dec}位(最小增量{10**(-sz_dec):g}{base_ccy})',
                        'ok': True})
    except Exception:
        pass
    out['min_margin'] = round(out['min_notional'] / lev, 2) if lev else out['min_notional']
    return out


def ai_manager_params(symbol: str, strategy_type: str, perception: dict, profile: dict,
                      target_pct: float, days_remaining: int, user_id: int = 1,
                      exchange: str = 'hyperliquid', base_tf: str = '15m',
                      available_usdt: float | None = None) -> dict:
    """守门员问 AI 经理要参数. 返回 {ok, skip, leverage, init_sl_pct, tp1_r, tp2_r, tp3_r,
    position_size_usdt, reason_zh}. 失败/异常 → ok=False (守门员回退机械参数)。
    exchange: 本单路由的交易所 (规格/费率/最小单都按它喂给经理)。
    available_usdt: 守门员组合层资金闸算好的**可用额度**(已扣安全垫+已开仓占用); 经理在此额度内下注,
                    不再按总权益(否则每个币各按总额1/3 → 叠起来满仓). None=offline回退拉总权益。"""
    from app.services.llm_provider import call_llm
    from app.services.profit_difficulty import difficulty_guidance_block, profit_difficulty, monthly_equiv

    diff = profit_difficulty(monthly_equiv(target_pct, days_remaining))
    lev_cap = diff.get('leverage_cap') or 5
    if diff.get('blocked'):
        return {'ok': True, 'skip': True, 'reason_zh': '盈利目标超系统上限, 经理拒绝开仓'}

    # 经理的眼睛之三: 本单交易所的合约规格 + 费率. 没有 → 经理给的保证金可能 <最小名义被静默跳过,
    # 或切到 <最小颗数留灰尘仓 (user 2026-05-30 指出灰尘仓根因); 没费率 → 贴近TP被手续费吃光算不准EV.
    con = instrument_constraints(exchange, symbol, lev_cap)

    # 经理的眼睛之二: 可用资金. 守门员传 available_usdt(组合层资金闸: 权益×(1−安全垫)−已开仓占用)→
    # 经理在**剩余额度**内下注, 单笔视角不会当子弹无限 (user 2026-05-30 定: 资金感知是守门员的活).
    # 没传 → 回退拉总权益 (offline). 事故根因: 经理凭空挑本金挑出 > 账户的保证金一仓吃光 (AVAX $80 砸 $68).
    if available_usdt is not None:
        equity = max(0.0, float(available_usdt)); equity_label = '本单可用额度(已扣安全垫+其它已开仓)'
    else:
        try:
            from app.services.llm_prompts.strategy_recommend import _get_user_capital
            equity = float(_get_user_capital(user_id) or 0.0)
        except Exception:
            equity = 0.0
        equity_label = '当前可用权益(统一账户 现货+合约)'

    ind = {k: (v or {}).get('state') for k, v in (perception.get('indicators') or {}).items()}
    pa = perception.get('price_action') or {}
    prof = profile or {}
    equity_txt = (f"约 ${equity:.2f}" if equity > 0 else "暂时拉取失败(按保守小仓处理)")
    track_record = _manager_track_record(strategy_type, perception.get('regime'),
                                         perception.get('direction'), base_tf)
    prompt = f"""## 盈利目标难度 (你的约束信封)
{difficulty_guidance_block(target_pct, days_remaining)}

## 账户可用资金 (硬约束 — position_size_usdt 是保证金, 按这个定)
- {equity_label}: {equity_txt}
- position_size_usdt = 这一单投入的**保证金**(不是名义); 名义 = 保证金 × 杠杆.
- 这个数字已是守门员**留好其它仓和安全垫后给你的额度** → 你最多用到它, 别超.
- 铁律: 单仓保证金**绝不超过上面这个额度**; 难度激进也最多占一部分(如 1/3 ~ 1/2), 保守更小.
  额度小($10~$30)就老实开小仓, 一仓占满=没有容错, 一根反向针就逼近强平.

## 本单交易所规格 + 成本 (硬约束 — 算 EV / 切仓位必看)
- 路由交易所: {con['exchange']} · taker 手续费 {con['fee_pct']}%/单边 (开+平+每次分批都收, 贴近的TP1会被吃掉一截)
- 最小名义: ${con['min_notional']} → 你给的 (保证金 × 杠杆) **必须 ≥ 此值**, 否则下不出去被跳过
- 颗数规格: {con['lot_desc']} — 仓位要能按这精度**干净切成 TP1/2/3 + 末段全平, 别留 <最小单的零头(灰尘仓平不掉)**
- 据此最小保证金 ≈ ${con['min_margin']}(=最小名义÷你选的杠杆); 在 [${con['min_margin']}, 可用权益] 之间挑

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

{track_record}

## 任务: 给这一单的参数 (JSON)
{{
  "skip": false,                  // 若当前行情正好踩中这策略弱点(如震荡市+突破策略)、判断不该开 → true
  "leverage": 数字,               // ≤ {lev_cap} (难度上限)
  "init_sl_pct": 数字,            // 初始止损价格距离% (杠杆前). 行情噪音大/弱点环境→给宽点防扫
  "tp1_r": 0.5, "tp2_r": 1.2, "tp3_r": 2.0,   // 盈亏比R倍数(在哪几个位置止盈). 难度难 or 行情弱 → 可等比缩小求稳
  "tp1_frac": 0.5, "tp2_frac": 0.3,   // 头档/中段各平多少比例(尾段=剩余自动). 吃头中段不贪尾:
                                      // 强趋势可少吃早段多留尾(tp1_frac小)、震荡/弱势多吃早段落袋(tp1_frac大). 各0.2~0.6, 两者和≤0.85(尾段至少留0.15)
  "position_size_usdt": 数字,     // 保证金(≤可用权益, 单仓占可用的合理比例; 难度激进可大、保守小)
  "reason_zh": "为什么这样给 (结合当前行情 + 这策略的edge/弱点 一句话)"
}}
在难度信封内(杠杆≤{lev_cap}), 贴合当前行情和这策略特性. 踩中弱点就skip或更保守.
**资金费**(上面富感知里的 funding): 正费率=多头付空头(做多是成本/做空收益), 负反之; 持仓跨结算窗会累积,
极端费率要纳入 EV 和方向判断 (如高正费率=多头拥挤, 可能是做空的信号)."""

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
        # 保证金双边硬约束: 上限=可用权益(别超账户总额); 下限=最小名义÷杠杆(否则<最小单被静默跳过).
        # equity 拉取失败 → 保守 $20 上限. 与 leverage clamp 到 lev_cap 同性质.
        max_margin = equity if equity > 0 else 20.0
        min_margin = round(con['min_notional'] / lev, 2) if lev else con['min_notional']
        if min_margin > max_margin + 1e-9:   # 资金连此所最小单都开不起 → 不开 (别硬塞超额)
            return {'ok': True, 'skip': True,
                    'reason_zh': f'可用资金 ${max_margin:.0f} 不足以开 {con["exchange"]} 最小单(需保证金≥${min_margin:.0f})'}
        default_margin = _clamp(10.0, min_margin, max_margin)
        # 分批比例 (Gap A, user 2026-05-30 给经理控制权): 头/中段各 0.2~0.6, 两者和≤0.85 保证尾段≥0.15
        # (吃头中段不贪尾 = 经理控形状). tp3_frac = 剩余, 由出场引擎自动算.
        tp1_frac = _clamp(float(p.get('tp1_frac', 0.5)), 0.2, 0.6)
        tp2_frac = _clamp(float(p.get('tp2_frac', 0.3)), 0.2, 0.6)
        if tp1_frac + tp2_frac > 0.85:           # 留尾段 ≥ 0.15
            scale = 0.85 / (tp1_frac + tp2_frac)
            tp1_frac = round(tp1_frac * scale, 4); tp2_frac = round(tp2_frac * scale, 4)
        out = {
            'ok': True, 'skip': False,
            'leverage': lev,
            'init_sl_pct': sl,
            'tp1_r': _clamp(float(p.get('tp1_r', 0.5)), 0.2, 3),
            'tp2_r': _clamp(float(p.get('tp2_r', 1.2)), 0.4, 5),
            'tp3_r': _clamp(float(p.get('tp3_r', 2.0)), 0.6, 8),
            'tp1_frac': tp1_frac, 'tp2_frac': tp2_frac,
            'position_size_usdt': _clamp(float(p.get('position_size_usdt', default_margin)), min_margin, max_margin),
            'reason_zh': p.get('reason_zh', ''),
            'fee_pct': con['fee_pct'],   # 本单路由所费率 → 守门员 EV 回测 + 出场用对
        }
        return out
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}


def _manager_track_record(strategy_type: str, regime: str, direction: str, base_tf: str) -> str:
    """缺口①修 (user 2026-05-30): 从学习飞轮取'本策略×当前市场格子'的历史实测 → 喂给经理自我校准,
    闭合飞轮 (此前 experience_block 只喂给合成AI, 没喂给控制EV的经理 = 经理对战绩失忆).
    含 ev_bias = 实测−预期 (负=经理/守门员以往高估了EV → 这次该收敛). 无样本→空串(诚实)。"""
    try:
        from app.services.gatekeeper_learning import summarize_experience
        exp = summarize_experience(timeframe=base_tf, min_samples=2)
    except Exception:
        return ''
    if not exp:
        return ''
    exact = [e for e in exp if e['strategy'] == strategy_type
             and e['regime'] == regime and e['direction'] == direction]
    same_strat = [e for e in exp if e['strategy'] == strategy_type
                  and (e['regime'], e['direction']) != (regime, direction)]
    lines = []
    if exact:
        e = exact[0]; bias = e.get('ev_bias')
        bias_txt = ''
        if bias is not None and e.get('avg_expected_ev') is not None:
            bias_txt = (f", 你以往预期EV均{e['avg_expected_ev']:+.3f}→实测偏差{bias:+.3f}"
                        f"({'⚠️你高估了EV' if bias < 0 else '实测好于预期'})")
        lines.append(f"- **当前格子 {strategy_type}@{regime}/{direction}/{base_tf}**: "
                     f"历史{e['samples']}笔, 实测均pnl {e['avg_realized_pnl']:+.3f}, 胜率{e['win_rate']*100:.0f}%{bias_txt}")
    for e in same_strat[:2]:
        lines.append(f"- 同策略其它格子 @{e['regime']}/{e['direction']}: "
                     f"实测均pnl {e['avg_realized_pnl']:+.3f}, 胜率{e['win_rate']*100:.0f}% (n={e['samples']})")
    if not lines:
        return ''
    return ("## 你的历史战绩 (学习飞轮回填 — 校准这次判断, 不是稳赚保证)\n" + '\n'.join(lines)
            + "\n→ 当前格子历史亏 / 你以往高估EV → 这次更保守(缩R/缩仓)甚至skip; 历史稳赚可适度自信.")


def _clamp(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except Exception:
        return lo
