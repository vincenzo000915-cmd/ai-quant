"""Phase 15 P2: 盘感判断层 — AI 操盘手的「确定性判别闸」

定位 (project-edge-ideas 北极星 / 铁律):
- 信号(策略) → 执行 之间的 **gate**: 否决逆势/猎杀开仓 (entry_gate) + 真反转锁利出场 (exit_gate)。
- **确定性、可回测、可归因** 的规则/过滤器, 不做 LLM 实时裁量, 不随机覆盖某笔 (不污染归因)。
  AI 的盘感体现为"更好的规则", 不是临场 discretion。校准靠 P4 真实 P&L, 不靠 TA lore。
- 核心判别全部基于 candle_patterns 纯函数 (量价+MA结构+MACD柱方向+细TF形态) → 同一份口径
  回测↔live 都能跑 (回测真理: 拦掉的坏单 > 杀掉的好单, 才上 live)。
- regime/correlation/LLM(market_analyst) 实时查 → 回测里会前视错位, 故**不进核心否决**;
  留作 P4 的 live-only 增强 (只会更保守, 不放松回测验证过的否决)。

操作手法 (user "15m 策略看 5m 反转", project-profit-protection-exit 要点3):
- **细 TF (aux, 5m)**: 看形态/猎杀针 — user 肉眼在 5m 看到的顶底拒绝针。
- **策略 TF (base, 15m)**: 看 MACD柱动能崩塌 + MA 结构 — 反转 thesis 的 TF (#44 崩塌在 15m)。

判别哲学 (2026-05-29 七笔实证, 验证锚):
- #46 AVAX 逆势开空 (ETH已翻多+底部诱空) → entry_gate 该否决。
- #44 ETH 空 真反转 (柱崩塌+价测MA20+V反弹) → exit_gate 该锁利 (本可保 +5~8% 而非 -8.6%)。
- #43 AVAX give-back 时柱**扩张** (诱多 head-fake) → **不该锁** (扛住吃 +10%)。← 关键: 别被单一信号带走。
- #40/41/42 清晨震荡 → entry_gate 该过滤 (无动能确认的盲目突破)。

⚠️ 多信号**合议**才否决/锁利 (避免单信号误杀): 一个放量猎杀针=强证据(权重2)直接够; 或形态+MA两弱信号(各1)凑够2。
   阈值/权重是 P4 用真实 P&L 校准的对象, 当前用业界先验 + 5-29 实证标定的保守起点。
"""
from __future__ import annotations

from typing import Optional

from app.services import candle_patterns as cp


# 累计否决/锁利阈值: votes 权重和 >= 此值才动作 (合议, 防单信号误杀)
_VOTE_THRESHOLD = 2.0


def _side_dir(side: str) -> str:
    """开仓方向 → 押注方向: long 押涨(bullish) / short 押跌(bearish)。"""
    return 'bullish' if side in ('long', 'buy') else 'bearish'


def _opposite(d: Optional[str], side: str) -> bool:
    """形态/信号方向 d 是否与开仓押注方向相反 (= 逆势证据)。"""
    if not d:
        return False
    return d != _side_dir(side)


def _ma(closes: list, n: int) -> Optional[float]:
    """简单移动均线 (纯函数)。"""
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _candles_from(obj) -> list:
    """把 base df (DataFrame) 或 candles(list) 统一成 candles list。"""
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    # pandas DataFrame
    try:
        return obj.to_dict('records')
    except Exception:
        return []


# ============================================================
# 入场闸 — 否决逆势/猎杀开仓
# ============================================================

def evaluate_entry(side: str, base_candles: list,
                   aux_candles: Optional[list] = None) -> dict:
    """否决"逆势开仓"。返回 {ok, reason, votes, signals}。

    votes: [(name, weight, detail)] 否决证据; 权重和 >= _VOTE_THRESHOLD → ok=False。
    - 反向放量猎杀针 (诱多/诱空直接证据, 权重2): 开多撞顶部猎杀针 / 开空撞底部猎杀针。
    - 反向反转形态 (权重1): 射击之星/吞没等与押注方向相反且 strength>=0.5。
    - relief-bounce 陷阱 (权重1): 开多但价在 MA20 下且 MACD柱仍负 (反弹失败于MA20, ETH实证)
      / 开空但价在 MA20 上且柱仍正 (假跌破)。
    """
    pa_src = aux_candles if (aux_candles and len(aux_candles) >= 25) else base_candles
    if not pa_src or len(pa_src) < 25:
        return {'ok': True, 'reason': '数据不足, 放行 (fail-open)', 'votes': [], 'signals': {}}

    pa = cp.read_price_action(pa_src)
    votes = []

    # 1. 反向放量猎杀针 (最强: 诱多/诱空的直接证据)
    hunt = pa['hunt']
    if hunt.get('is_hunt') and _opposite(hunt.get('direction'), side):
        votes.append(('hunt_wick', 2.0, hunt['reason']))

    # 2. 反向反转形态
    pat = pa['pattern']
    if _opposite(pat.get('direction'), side) and pat.get('strength', 0) >= 0.5:
        votes.append(('reversal_pattern', 1.0, pat['reason']))

    # 3. relief-bounce / 假突破陷阱 (价 vs MA20 + MACD柱方向, base TF 更稳)
    closes = [c['close'] for c in base_candles]
    ma20 = _ma(closes, 20)
    mom = cp.momentum_state(base_candles)
    hist = mom.get('hist')
    if ma20 is not None and hist is not None:
        price = closes[-1]
        if side in ('long', 'buy') and price < ma20 and hist < 0:
            votes.append(('relief_bounce', 1.0,
                          f'追多于 relief bounce: 价{price:.4f}<MA20{ma20:.4f} 且 MACD柱仍负({hist:.2f}) → 反弹失败于MA20 (ETH实证)'))
        elif side in ('short', 'sell') and price > ma20 and hist > 0:
            votes.append(('false_breakdown', 1.0,
                          f'追空于假跌破: 价{price:.4f}>MA20{ma20:.4f} 且 MACD柱仍正({hist:.2f}) → 假破位扫空单'))

    score = sum(w for _, w, _ in votes)
    ok = score < _VOTE_THRESHOLD
    if ok:
        reason = '放行' + (f' (有 {score:.0f} 票逆势证据但未达否决阈值)' if votes else '')
    else:
        reason = '否决逆势开仓: ' + '; '.join(f'[{n}]{d}' for n, _, d in votes)
    return {'ok': ok, 'reason': reason, 'votes': votes,
            'signals': {'pattern': pat, 'hunt': hunt, 'momentum': mom, 'ma20': ma20}}


# ============================================================
# 出场闸 — 真反转确认 → 锁利出场 (区分诱多 head-fake)
# ============================================================

def evaluate_exit(side: str, base_candles: list,
                  aux_candles: Optional[list] = None,
                  entry_price: Optional[float] = None,
                  current_price: Optional[float] = None,
                  activate_pct: float = 0.8) -> dict:
    """**利润锁**: 浮盈达激活阈值后, 真反转确认 → lock=True 锁利出场。返回 {lock, reason, votes, signals}。

    ⚠️ 这是"利润锁"不是"反向止损" (B0/14k-158 教训: 震荡 breakout 上激进 exit = −EV/whipsaw):
    - **只在已浮盈 (有利价格变动 >= activate_pct) 时才考虑锁利**; 亏损时反转交给 SL, 不在此乱平
      (#43 峰值 0.84%价/8.4%杠杆 / #44 真峰值 1.3%价/13%杠杆 → activate_pct=0.8%价 在猎杀spike前落袋)。
    - 真反转 (该锁) vs 诱多 head-fake (该扛) 判别 — **多信号合议防误杀** (阈值2):
      动能崩塌/翻号(权重1) + 反向形态(权重1) + 价破/收复MA20(权重1), 须凑够2票。
    - 动能仍**扩张** → 直接不锁 (#43 诱多 head-fake, 扛住吃 +10%)。
    """
    if not base_candles or len(base_candles) < 25:
        return {'lock': False, 'reason': '数据不足', 'votes': [], 'signals': {}}

    # 利润锁门槛: 未达浮盈激活阈值 → 不锁 (亏损反转交给 SL, 利润锁只锁利润, 防震荡 whipsaw)
    if entry_price and current_price and entry_price > 0:
        if side in ('long', 'buy'):
            fav_pct = (current_price - entry_price) / entry_price * 100
        else:
            fav_pct = (entry_price - current_price) / entry_price * 100
        if fav_pct < activate_pct:
            return {'lock': False,
                    'reason': f'浮盈{fav_pct:.2f}%<激活阈值{activate_pct}% → 不锁 (亏损反转归 SL 管)',
                    'votes': [], 'signals': {'fav_pct': round(fav_pct, 3)}}

    mom = cp.momentum_state(base_candles)
    # #43 教训: 动能仍扩张 = 同向没死 = 诱多 head-fake → 绝不锁利 (扛)
    if mom.get('state') == 'expanding':
        return {'lock': False, 'reason': f'动能仍扩张({mom.get("hist")}) → 诱多 head-fake, 扛 (不锁)',
                'votes': [], 'signals': {'momentum': mom}}

    votes = []
    # 1. 动能崩塌/翻号 (权重1 — 须与形态/MA 合议, 单信号不锁防 whipsaw)
    if mom.get('state') == 'collapsing':
        votes.append(('momentum_collapse', 1.0, mom['reason']))

    # 2. 反向形态确认 (细 TF 拒绝针与持仓方向相反 = 反转 tell)
    pa_src = aux_candles if (aux_candles and len(aux_candles) >= 25) else base_candles
    pa = cp.read_price_action(pa_src)
    pat = pa['pattern']
    # 持多遇顶部拒绝(bearish) / 持空遇底部拒绝(bullish) = 反向 = 反转
    if _opposite(pat.get('direction'), side) and pat.get('strength', 0) >= 0.5:
        votes.append(('reversal_pattern', 1.0, pat['reason']))

    # 3. 价收复/跌破 MA20 (结构反转确认)
    closes = [c['close'] for c in base_candles]
    ma20 = _ma(closes, 20)
    if ma20 is not None:
        price = closes[-1]
        if side in ('long', 'buy') and price < ma20:
            votes.append(('break_ma20', 1.0, f'持多但价{price:.4f}跌破MA20{ma20:.4f} → 趋势结构破'))
        elif side in ('short', 'sell') and price > ma20:
            votes.append(('reclaim_ma20', 1.0, f'持空但价{price:.4f}收复MA20{ma20:.4f} → 空头结构破 (#44 价测MA20)'))

    score = sum(w for _, w, _ in votes)
    lock = score >= _VOTE_THRESHOLD
    reason = ('真反转确认→锁利: ' + '; '.join(f'[{n}]{d}' for n, _, d in votes)) if lock \
             else f'反转证据不足({score:.0f}票) → 持有'
    return {'lock': lock, 'reason': reason, 'votes': votes,
            'signals': {'pattern': pat, 'momentum': mom, 'ma20': ma20}}


# ============================================================
# 工厂 — 产出喂给 backtest_engine.run_backtest 的 gate 闭包 (回测验证用)
# ============================================================

def make_entry_gate():
    """返回 entry_gate(ctx)->{ok,reason}, 供 run_backtest 在开仓决策点调用。"""
    def _gate(ctx):
        base = _candles_from(ctx.get('df'))
        aux = ctx.get('aux')
        r = evaluate_entry(ctx['side'], base, aux)
        return {'ok': r['ok'], 'reason': r['reason']}
    return _gate


def make_exit_gate():
    """返回 exit_gate(ctx)->{lock,reason}, 供 run_backtest 在持仓决策点调用。"""
    def _gate(ctx):
        base = _candles_from(ctx.get('df'))
        aux = ctx.get('aux')
        pos = ctx.get('position') or {}
        r = evaluate_exit(ctx['side'], base, aux,
                          entry_price=pos.get('entry_price'),
                          current_price=ctx.get('price'))
        return {'lock': r['lock'], 'reason': r['reason']}
    return _gate
