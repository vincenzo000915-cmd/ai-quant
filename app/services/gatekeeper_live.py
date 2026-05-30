"""Phase 15 学习飞轮②: 守门员 live 扫描 — 接 live 入场路径 (灰度: off | shadow | live)

蓝图 project-phase15-blueprint 九.6 (user 2026-05-30 授权当学费). 守门员实时扫描市场 →
决策 → (shadow: 记录+通知不下单 / live: 真下单) → 平仓回填真盈亏 → P&L 校准飞轮.

灰度三档 (config gatekeeper_live_mode):
  off    — 不动 (默认)
  shadow — 每15分扫, 记录实时 live 决策 (source='live'), enter 时 TG 通知"现在会开X", **不下单**.
           先看几轮实时决策对不对, 再翻 live.
  live   — 在 shadow 基础上接 _place_order 真下单 (第二段, 含执行保真问题).

安全闸 (全守):
  - halted (kill switch 首页按钮 / DD halt) → 直接 skip, 不开仓.
  - 守门员独占: live 开启时现有策略由 _run_signals 让路 (见 strategy_tasks 改动).
  - 仓位/杠杆 = AI 难度基调按 target 自配 (profit_difficulty.leverage_cap), 非手动写死 (user 定).
  - L1 杠杆感知止损下限 + 预算闸 在真下单段复用现有 _place_order 路径.

user 定 (2026-05-30): 先只 ETH+AVAX (已 offline 验证), 15m base + 5m aux (核心小波段维度,
5m 看微观/猎杀/动能/MTF), 每 15 分轮询.
"""
from __future__ import annotations

# user 2026-05-30: 先只 ETH+AVAX (offline 滚动验证过), 坐实后扩
WATCHED_SYMBOLS = ['ETH/USDT', 'AVAX/USDT']
BASE_TF = '15m'   # 策略决策维度 (画像配 15m)
AUX_TF = '5m'     # 更细市场维度 (富感知读 5m 算微观/猎杀/动能/MTF)


def _to_candles(rows) -> list:
    if not rows:
        return []
    return [{'open': x['open'], 'high': x['high'], 'low': x['low'],
             'close': x['close'], 'volume': x['volume'], 'timestamp': x['timestamp']}
            for x in rows]


def _target_and_days() -> tuple[float, int]:
    """从 active ProfitTarget 取 目标% + 剩余天 (AI 难度基调的输入)。无则给保守默认。"""
    try:
        from app.models import ProfitTarget
        import datetime as _dt
        pt = ProfitTarget.query.filter_by(status='active').order_by(ProfitTarget.id.desc()).first()
        if pt:
            days = 30
            if pt.deadline:
                days = max(1, (pt.deadline - _dt.datetime.utcnow()).days)
            return float(pt.target_pct or 5.0), days
    except Exception:
        pass
    return 5.0, 30


def gatekeeper_live_cycle() -> dict:
    """守门员一轮 live 扫描 (beat */15 调). 返回 {mode, scanned, decisions:[...]}。"""
    from app.services.config_service import get_config
    cfg = get_config()
    mode = cfg.get('gatekeeper_live_mode', 'off')
    if mode == 'off':
        return {'mode': 'off', 'scanned': 0, 'decisions': []}
    # 安全闸: kill switch / DD halt 时直接 skip (守门员真下单路径受 halted 管)
    if cfg.get('halted'):
        return {'mode': mode, 'halted': True, 'scanned': 0, 'decisions': [],
                'note': f"halted({cfg.get('halt_reason')}) → 守门员不开仓"}

    from app.services.exchange_service import fetch_ohlcv
    from app.services.gatekeeper import gatekeeper_decide
    from app.services.profit_difficulty import profit_difficulty, monthly_equiv

    target_pct, days_remaining = _target_and_days()
    lev_cap = profit_difficulty(monthly_equiv(target_pct, days_remaining)).get('leverage_cap') or 5
    decisions = []
    for sym in WATCHED_SYMBOLS:
        try:
            base = _to_candles(fetch_ohlcv(sym, BASE_TF, limit=400))
            aux = _to_candles(fetch_ohlcv(sym, AUX_TF, limit=1200))
            if len(base) < 60 or len(aux) < 60:
                decisions.append({'symbol': sym, 'action': 'skip', 'reason': '数据不足'})
                continue
            # base 对齐 aux 起点 (保证两 feed 同窗口, 防 MTF 错位)
            base = [c for c in base if c['timestamp'] >= aux[0]['timestamp']]
            d = gatekeeper_decide(sym, base, aux, BASE_TF,
                                  target_pct=target_pct, days_remaining=days_remaining,
                                  lev=float(lev_cap), record=True, record_source='live')
            d['symbol'] = sym
            decisions.append({k: d.get(k) for k in
                              ('symbol', 'action', 'regime', 'direction', 'strategy',
                               'expected_ev', 'match_score', 'reason', 'decision_id')})
            if d.get('action') == 'enter':
                if mode == 'shadow':
                    _notify_shadow_enter(sym, d, target_pct)
                elif mode == 'live':
                    _execute_live_enter(sym, d, base, aux, cfg)  # 第二段实现
        except Exception as e:
            decisions.append({'symbol': sym, 'action': 'error',
                              'reason': f'{type(e).__name__}: {e}'})
    return {'mode': mode, 'scanned': len(WATCHED_SYMBOLS), 'decisions': decisions}


def _notify_shadow_enter(symbol: str, d: dict, target_pct: float):
    """影子档: enter 决策 TG 通知 user "守门员现在会开 X" (不下单, 给 user 看实时决策质量)。"""
    try:
        from app.services import telegram_service
        sym_zh = symbol.split('/')[0]
        txt = (f"👁️ <b>守门员影子决策</b> (未下单)\n"
               f"现在会开: <b>{sym_zh}</b> {d.get('regime')}/{d.get('direction')}\n"
               f"策略: {d.get('strategy')} · 预期EV {d.get('expected_ev'):.3f} · 配对分 {d.get('match_score')}\n"
               f"参数: SL {(d.get('params') or {}).get('init_sl_pct')}%\n"
               f"<i>影子档=只记录看决策对不对, 翻 live 才真下单</i>")
        telegram_service.send(txt, force=True)
    except Exception as e:
        print(f'[gatekeeper_live] notify error: {type(e).__name__}: {e}')


def _execute_live_enter(symbol: str, d: dict, base: list, aux: list, cfg: dict):
    """live 档真下单 — 第二段实现 (接 _place_order + 执行保真分批TP). 暂不实现, 防误触真钱。"""
    raise NotImplementedError('守门员 live 真下单 = 第二段 (影子看顺眼后建)')
