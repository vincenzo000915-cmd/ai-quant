"""Phase 15 第一条: 盈利目标难度分级 → 给 AI 的调参基调指导 (prompt engineering)

蓝图 project-phase15-blueprint 第八节 (AI驱动): 订阅用户只说"要盈利X%", AI 按**难度等级 + 行情**
动态调参 (R/杠杆/仓位/激进保守). 本模块把 月化等价 → 难度等级 + **给 AI 的基调指导文本**, 注入合成/
调参 prompt. 难度定"激进/保守基调", AI 在基调约束内结合行情动态定具体值 (难度=约束, 行情=AI 判断).

分级阈值对齐前端 ProfitTargetCard / routes.py 守门 (≤15🟢 / 15-30🟡 / 30-50🔴 / >50⛔).

⚠️ 调参基调 (每档对应的 R缩放/杠杆/仓位取向) 是 prompt 的核心 = moat, **待 user 实战校准** —
   当前为初版方向 (求稳→保守, 进取→基准, 激进→放大但控风险), 数值/措辞 user 定。
"""
from __future__ import annotations


def monthly_equiv(target_pct: float, days_remaining: int) -> float:
    """目标% / 剩余天 → 月化等价% (对齐 routes.py / 前端公式)。"""
    d = max(1, days_remaining)
    return ((1 + target_pct / 100) ** (30.0 / d) - 1) * 100


def profit_difficulty(monthly_eq: float) -> dict:
    """月化等价% → 难度等级 + 调参基调。返回 {tier, emoji, label, stance, blocked}。

    stance = 给 AI 的"激进/保守基调" (AI 据此 + 行情动态定 R/杠杆/仓位)。
    """
    # r_scale=基准盈亏比R的缩放; leverage_cap=该档杠杆上限 (user 2026-05-29 校准:
    # 稳健R×0.7低杠杆 / 进取基准R适中 / 激进R同进取靠杠杆放大上限15 / ⛔拒绝)
    if monthly_eq > 50:
        return {'tier': 'extreme', 'emoji': '⛔', 'label': '不现实', 'blocked': True,
                'r_scale': None, 'leverage_cap': None,
                'stance': '超出系统支持上限(月化50%). 应拒绝/警告 user 降目标或拉长周期, 不合成激进到自毁的策略.'}
    if monthly_eq > 30:
        return {'tier': 'aggressive', 'emoji': '🔴', 'label': '激进', 'blocked': False,
                'r_scale': 1.0, 'leverage_cap': 15,
                'stance': ('顶级量化水平, **靠杠杆放大收益, 不放大盈亏比**: R 同进取(基准 0.5/1.2/2, 操作守则不变), '
                           '杠杆上限15、仓位积极, 接受止损更频繁. 仍守"TP1先保本+分批落袋", 绝不赌单笔.')}
    if monthly_eq > 15:
        return {'tier': 'ambitious', 'emoji': '🟡', 'label': '进取', 'blocked': False,
                'r_scale': 1.0, 'leverage_cap': 10,
                'stance': ('高于一线基金平均但现实: 基准盈亏比(TP1/2/3≈0.5/1.2/2 R), 适中杠杆(≤10)/仓位, '
                           '平衡求赚与求稳. 行情好按基准, 行情难临时等比缩小 R.')}
    return {'tier': 'safe', 'emoji': '🟢', 'label': '稳健', 'blocked': False,
            'r_scale': 0.7, 'leverage_cap': 5,
            'stance': ('稳健可持续, 求稳求赚不求大: 盈亏比 R 在基准上**×0.7**(更快落袋保本), 低杠杆(≤5)/小仓, '
                       '止损给足空间不被噪音扫, 交易少而精. 宁可少赚不可大亏.')}


def difficulty_guidance_block(target_pct: float, days_remaining: int) -> str:
    """生成注入 AI prompt 的"难度→调参基调"文本块。"""
    meq = monthly_equiv(target_pct, days_remaining)
    d = profit_difficulty(meq)
    cap = f"杠杆上限 {d['leverage_cap']}x" if d.get('leverage_cap') else "—"
    rs = f"基准R ×{d['r_scale']}" if d.get('r_scale') is not None else "—"
    return (
        f"## 盈利目标难度 (决定调参基调)\n"
        f"- 目标 +{target_pct}% / {days_remaining}天 → 月化等价 {meq:.1f}% → {d['emoji']} {d['label']}\n"
        f"- **调参基调**: {d['stance']}\n"
        f"- **硬约束**: 盈亏比 {rs} · {cap} (基准 TP1/2/3 = 0.5/1.2/2 R, 仓位 50%/30%/20%)\n"
        f"- 你要在这个基调下, **结合当前行情(regime/波动/胜率)动态定** 盈亏比(R≤上述缩放)、杠杆(≤上限)、仓位 —— "
        f"难度是约束, 行情是你的判断. 保守难度别用激进参数, 激进难度也别赌单笔(守 TP1 保本+分批).\n"
    )


# ============================================================
# 面向前端 UI 的难度判断 (单一真相源: 前端 ProfitTargetCard 改调本函数 API,
# 不再本地写死阈值/文案 — user 2026-05-29 定统一真相源)
# ============================================================

_UI_STYLE = {
    'safe':       {'label': '🟢 稳健',     'color': '#34d399'},
    'ambitious':  {'label': '🟡 进取',     'color': '#fbbf24'},
    'aggressive': {'label': '🔴 激进',     'color': '#f87171'},
    'extreme':    {'label': '⛔ 超出上限', 'color': '#f87171'},
}


def difficulty_for_ui(target_pct: float, days_remaining: int) -> dict:
    """前端难度展示用 (阈值/文案/颜色/保存控制的单一真相源)。
    返回 {monthly_eq, level, label, color, warning, can_save, needs_confirm, tiers}。
    """
    meq = monthly_equiv(target_pct, days_remaining)
    d = profit_difficulty(meq)
    tier = d['tier']
    warning = {
        'extreme': f"月化 {meq:.0f}% 超出系统支持上限 (50%). 一流量化年化 ~30%, 此设置不切实际. 请降目标或拉长周期.",
        'aggressive': f"月化 {meq:.0f}% 属顶级量化水平, 停损会非常频繁. 需要 user 心理承受波动.",
        'ambitious': f"月化 {meq:.0f}% 高于一线基金平均 (年化 30% ≈ 月 2.4%), 现实但有挑战.",
        'safe': '',
    }.get(tier, '')
    style = _UI_STYLE[tier]
    return {
        'monthly_eq': round(meq, 1),
        'level': tier,
        'label': style['label'],
        'color': style['color'],
        'warning': warning,
        'can_save': tier != 'extreme',
        'needs_confirm': tier == 'aggressive',
        'leverage_cap': d.get('leverage_cap'),
        'r_scale': d.get('r_scale'),
        'tiers': [
            {'range': '≤15%', 'emoji': '🟢', 'color': '#34d399'},
            {'range': '15-30%', 'emoji': '🟡', 'color': '#fbbf24'},
            {'range': '30-50%', 'emoji': '🔴', 'color': '#f87171'},
            {'range': '>50%', 'emoji': '⛔', 'color': '#94a3b8'},
        ],
    }
