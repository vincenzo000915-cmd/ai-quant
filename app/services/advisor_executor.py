"""Phase 10.8: auto-apply advisor recommendations (智能托管).

Reads the advisor's current recommendations and executes the subset
the user explicitly opted into via SystemConfig.auto_apply_actions.

Defence-in-depth safeguards (all required, none optional):
- halted=True             → 全部跳過（系統已 panic，不要再亂動）
- auto_apply_enabled=False → 全部跳過
- per-action opt-in        → action 不在白名單就跳過
- daily cap                → 超過 auto_apply_max_per_day 就停下
- audit + telegram         → 每個動作都留痕 + 推播
- never auto-retire LIVE   → 留個底線：實盤模式下不自動 retire（pause 可以）

This file is import-light so it can be called from both Flask routes
and Celery tasks without circular imports.
"""
from __future__ import annotations

import datetime
from typing import Callable

from app.extensions import db
from app.models import AuditLog, Strategy
from app.services.audit import log as audit
from app.services.config_service import get_config
from app.services.strategy_advisor import build_recommendations


FAN_OUT_DEFAULTS = ['ETH/USDT', 'SOL/USDT', 'AVAX/USDT']

# 永遠不會 auto 處理的 action（純資訊類）
INFO_ONLY = {'mtf_caution'}


def _today_count() -> int:
    """今日（UTC）已 auto-apply 過幾次。"""
    today = datetime.datetime.utcnow().date()
    # 14k-43: 只算真改 strategy 的 action, "排回测/排闪测/排 invent" 这种 async dispatch 不占 cap
    # (之前 propose 跟 apply 算同 cap, 1 轮 advisor 6 items 就占满)
    MUTATING_ACTIONS = {'apply_params', 'pause', 'retire', 'fan_out', 'promote_candidate',
                         'adjust_global_sizing', 'adjust_strategy_risk'}
    rows = (
        AuditLog.query
        .filter(AuditLog.event_type == 'advisor_auto_apply')
        .filter(AuditLog.created_at >= datetime.datetime.combine(today, datetime.time.min))
        .all()
    )
    return sum(1 for r in rows if (r.context or {}).get('action') in MUTATING_ACTIONS)


def _telegram_safe(text: str):
    try:
        from app.services.telegram_service import send as _tg
        _tg(text)
    except Exception:
        pass


def _execute_one(item: dict) -> tuple[bool, str]:
    """執行單個建議。回傳 (ok, message)。

    這裡直接呼叫 DB / 同步 helper，避免 import routes（會循環）。
    """
    action = item['action']
    sid = item['strategy_id']

    # Phase 14k-29 L6 + 14k-49: invent 全新策略 — 看 meta.invent_method 路由两种武器
    if action == 'invent_new_strategy':
        from app.services.audit import log as audit
        meta = item.get('meta', {}) or {}
        uid = meta.get('user_id') or 1
        invent_method = meta.get('invent_method', 'catalog_first')
        trigger_type = meta.get('trigger_type', 'lag_pool_thin')

        if invent_method == 'synth':
            # 14k-49: T2/T3/T4 trigger → LLM 直写 signal_fn (L3 dynamic synth)
            from app.tasks.strategy_tasks import synthesize_dynamic_strategy
            synthesize_dynamic_strategy.apply_async(
                args=[uid, meta.get('symbol')],
                kwargs={'hint': meta.get('synth_hint'), 'target_timeframe': meta.get('target_timeframe')},
                countdown=3,
            )
            audit('advisor_invent_proposed', user_id=uid,
                  trigger_type=trigger_type, invent_method='synth',
                  synth_hint=meta.get('synth_hint'),
                  target_timeframe=meta.get('target_timeframe'))
            tf = meta.get('target_timeframe')
            tf_say = {'15m': '15 分钟短线', '30m': '半小时短线', '1h': '1 小时',
                      '4h': '4 小时摆动', '1d': '日线长线'}.get(tf, tf or '')
            return True, f'AI 正在研究新的{tf_say}策略 (约 60 秒, 完成会自动回测验证)'

        # T1 lag_pool_thin → catalog-first (旧路径)
        from app.tasks.strategy_tasks import advisor_invent_strategy
        advisor_invent_strategy.apply_async(args=[uid], countdown=3)
        audit('advisor_invent_proposed', user_id=uid,
              trigger_type=trigger_type, invent_method='catalog_first',
              lag_pct=meta.get('lag_pct'))
        return True, 'AI 正在从策略库挑新模板 (约 60 秒)'

    # Phase 14k-28/30: 账户级 action — 14k-30 #3 user-scoped (per-user UserConfig override)
    if action == 'adjust_global_sizing':
        new_sizing = item.get('meta', {}).get('new_sizing') or {}
        if not new_sizing:
            return False, 'meta.new_sizing 缺失'
        safe = {}
        bounds = {
            'trade_size_usdt': (1.0, 1000.0),
            'leverage': (1.0, 20.0),
            'max_daily_loss_usdt': (1.0, 10000.0),
        }
        for k, v in new_sizing.items():
            if k not in bounds:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                return False, f'{k} 非数字: {v}'
            lo, hi = bounds[k]
            if not (lo <= v <= hi):
                return False, f'{k}={v} 超出合理范围 [{lo}, {hi}]'
            safe[k] = v
        if not safe:
            return False, '没有合法字段可应用 (回测覆盖字段 SL/TP 已被过滤)'
        from app.services.config_service import update as update_cfg
        uid = item.get('meta', {}).get('user_id')
        update_cfg(safe, user_id=uid)
        kv = ', '.join(f'{k}={v}' for k, v in safe.items())
        scope = f'user={uid}' if uid else 'system'
        return True, f'账户级 sizing ({scope}): {kv}'

    strategy = Strategy.query.get(sid)
    if not strategy:
        return False, f'strategy {sid} 不存在'

    if action == 'apply_params':
        new_params = item.get('meta', {}).get('best_params')
        if not isinstance(new_params, dict) or not new_params:
            return False, 'meta.best_params 缺失或無效'
        # Phase 14k-30: snapshot baseline 给 auto-revert
        before_params = dict(strategy.params or {})
        # Phase 14k-28: merge 保住 risk_params 等子项, 不被参数网格搜索结果(只含信号参数)清空
        merged = dict(strategy.params or {})
        merged.update(new_params)
        strategy.params = merged
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(strategy, 'params')
        db.session.commit()
        from app.services.audit import log as audit
        audit('ai_strategy_params_change', strategy_id=sid, action='apply_params',
              before_params=before_params, after_params=merged, changed_keys=list(new_params.keys()))
        kv = ', '.join(f'{k}={v}' for k, v in list(new_params.items())[:4])
        return True, f'优化参数: {kv}'

    if action == 'pause':
        if strategy.status != 'running':
            return False, f'status={strategy.status}, 無需暫停'
        # 14k-65: 守门员 — 有真 trades 历史的不能因 regime mismatch pause (追屁股反模式)
        # PSAR 类 trend follower 在 range 市本来 trade 频率就低, 但真出 trade 时是赚的
        # advisor 看 regime 直接 pause 会杀掉真有效的策略 → 重蹈 14k-64 救场覆辙
        from app.models import Trade
        total_trades = Trade.query.filter_by(strategy_id=sid).count()
        if total_trades >= 3:
            from sqlalchemy import func
            total_pnl = Trade.query.with_entities(
                func.coalesce(func.sum(Trade.pnl), 0)
            ).filter_by(strategy_id=sid).scalar() or 0
            if float(total_pnl) >= 0:
                return False, (f'策略已 {total_trades} 真 trades + PnL {float(total_pnl):+.2f} '
                              f'≥ 0, 不因 regime mismatch pause (避免追屁股反模式)')
        # 14k-65: revive 24h 内不能 pause (user 刚救场不要立刻杀掉)
        rp = (strategy.params or {}).get('risk_params') or {}
        if rp.get('_revived_by'):
            import datetime as _dt
            revive_time = strategy.updated_at or strategy.created_at
            if revive_time and (_dt.datetime.utcnow() - revive_time).total_seconds() < 86400:
                return False, f'策略 revive 不到 24h, 不能 pause (尊重 user 救场决定)'
        strategy.status = 'stopped'
        db.session.commit()
        return True, '已暫停'

    if action == 'retire':
        # 安全網：LIVE 模式絕不自動 retire（pause 已足夠）
        cfg = get_config()
        if cfg.get('trading_mode') == 'live':
            # Phase 10.9: 不再靜默 — 推 Telegram 告訴 user「該退役但跳過」
            _telegram_safe(
                f'⚠️ <b>AI 建议退役一个策略</b>（实盘安全机制：未自动执行）\n'
                f'#{sid} {strategy.name}\n'
                f'原因: {item.get("reason", "")[:200]}\n'
                f'如果你同意, 请到「策略列表」手动退役'
            )
            return False, 'LIVE 模式禁止自动 retire, 已推 Telegram 提醒手动处理'
        if strategy.status == 'retired':
            return False, '已 retired'
        reason = f"auto: {item.get('reason', '')[:200]}"
        strategy.status = 'retired'
        strategy.retired_at = datetime.datetime.utcnow()
        strategy.retire_reason = reason
        db.session.commit()
        return True, f'已退役（{reason}）'

    if action == 'promote_candidate':
        # Phase 10.10: 候選池 qualified → 上線
        # Phase 12.31: per-TF 門檻 (short 高 PF / long 低 trades 容差)
        from app.services.candidate_pipeline import promote_candidate as do_promote
        cfg = get_config()
        cid = item.get('meta', {}).get('candidate_id')
        oos = item.get('meta', {}).get('oos_sharpe')
        threshold = float(cfg.get('auto_promote_min_oos_sharpe', 1.5))
        if oos is None or oos < threshold:
            return False, f'OOS Sharpe {oos} < 阈值 {threshold}，跳過'

        # 拉 candidate 細節 + 回測結果做 per-TF gate
        from app.models import StrategyCandidate, BacktestResult
        cand = StrategyCandidate.query.get(cid)
        if cand and cand.backtest_result_id:
            bt = BacktestResult.query.get(cand.backtest_result_id)
            if bt:
                tf = cand.timeframe or '4h'
                # per-TF 門檻: (min PF, min trades, min AR%, min_ev_pct)
                # 14k-68: 加 EV 维度 — user 哲学 "追盈利率不追胜率", PF/AR 路 OR EV 路过即可
                tf_gates = {
                    '15m': (1.5, 60, 8, 0.2),
                    '30m': (1.5, 50, 8, 0.3),
                    '1h':  (1.4, 40, 7, 0.4),
                    '4h':  (1.4, 30, 7, 0.6),
                    '1d':  (1.3, 12, 5, 1.0),
                    '1w':  (1.2, 8,  4, 2.0),
                }
                min_pf, min_trades, min_ar, min_ev = tf_gates.get(tf, (1.5, 30, 8, 0.4))
                pf = bt.profit_factor or 0
                tr = bt.total_trades or 0
                ar = bt.annual_return_pct or 0
                ev_pct = (bt.total_pnl / tr / (bt.initial_capital or 100) * 100) if tr else 0
                # 14k-68: trades 不够样本仍拒 (EV 不可信)
                if tr < min_trades:
                    return False, f'TF={tf} trades {tr} < 阈值 {min_trades} (样本不足, EV 不可信)'
                # 双轨制: 传统 (PF + AR) OR 14k-68 EV — 任一过即放行
                traditional_ok = pf >= min_pf and ar >= min_ar
                ev_ok = ev_pct >= min_ev
                if not (traditional_ok or ev_ok):
                    return False, (f'TF={tf} 两条路都不过: PF {pf:.2f}/AR {ar:.1f}% '
                                   f'(需≥{min_pf}/{min_ar}%) AND EV {ev_pct:+.2f}% (需≥{min_ev}%)')
        # Phase 12.39: 不再硬編碼 BTC fallback — 優先讀 candidate.source_meta，再 config 默認
        symbol = item.get('meta', {}).get('symbol')
        if not symbol and cand:
            symbol = (cand.source_meta or {}).get('symbol')
        if not symbol:
            symbol = cfg.get('default_backtest_symbol', 'BTC/USDT')

        # 14k-58: capital utilization gate — 防资金分散到一堆策略
        # (Strategy 已在 top-level import, 别在 try 里再 import 让它变 local)
        try:
            from app.services.llm_prompts.strategy_recommend import _get_user_capital
            from app.services.exchange_binding import primary_exchange as _pex
            uid = item.get('meta', {}).get('user_id') or 1
            user_capital = _get_user_capital(uid, exchange=_pex(uid))
            if user_capital > 0:
                running_strats = Strategy.query.filter_by(status='running').all()
                total_reserved = sum(
                    float((rs.params or {}).get('risk_params', {}).get('position_size_usdt') or 0)
                    for rs in running_strats
                )
                new_size = float((cand.source_meta or {}).get('risk_params', {}).get('position_size_usdt') or 7) if cand else 7
                projected_util = (total_reserved + new_size) / user_capital * 100
                if projected_util > 70:
                    return False, (f'资金已用 ${total_reserved:.0f}/${user_capital:.0f}, '
                                   f'加新策略到 {projected_util:.0f}% > 70% → 拒 promote (防资金分散)')
        except Exception as e:
            # capital check 挂掉不挡 promote (避免 false negative)
            print(f'[14k-58] capital gate exception (skipped): {type(e).__name__}: {e}')

        result = do_promote(cid, symbol=symbol)
        if not result.get('ok'):
            return False, f'promote 失败: {result.get("error")}'
        new_sid = result['strategy']['id']
        # qualified 已過 walk-forward → 直接上線（user 要的就是不手動）
        new_strat = Strategy.query.get(new_sid)
        if new_strat:
            new_strat.status = 'running'
            db.session.commit()
        _telegram_safe(
            f'🚀 <b>AI 已自动上线新策略 · Auto-Promoted</b>\n'
            f'#{new_sid} · {new_strat.name if new_strat else "?"}\n'
            f'回测表现 / Sharpe = {oos:.2f}\n'
            f'已开始运行, 等待下次信号 · Running, awaiting next signal'
        )
        return True, f'已 promote 候選 #{cid} → strategy #{new_sid}（已啟動）'

    if action == 'fan_out':
        # 直接複用 routes 的邏輯太重；重寫精簡版
        import re
        from app.services.symbols import is_supported
        if strategy.template_group is None:
            strategy.template_group = strategy.id
        group = strategy.template_group
        existing = {s.symbol for s in Strategy.query.filter(Strategy.template_group == group).all()}
        base_name = re.sub(r'\s*\([A-Z]{2,6}\)\s*$', '', strategy.name).strip()
        created_objs = []
        # 14k-46.1: fan_out 走 source strategy 的 exchange (HL user 不应被 OKX universe 限制)
        src_exchange = (strategy.exchange or 'okx').lower()
        for sym in FAN_OUT_DEFAULTS:
            # 14k-46: is_supported 动态查 OKX/HL universe (按 exchange 分流, 14k-46.1)
            if not is_supported(sym, exchange=src_exchange) or sym == strategy.symbol or sym in existing:
                continue
            clone = Strategy(
                name=f'{base_name} ({sym.split("/")[0]})',
                type=strategy.type,
                category=strategy.category,
                params=dict(strategy.params or {}),
                symbol=sym,
                timeframe=strategy.timeframe,
                status='stopped',   # 永遠 stopped 等回測決定
                max_positions=strategy.max_positions,
                max_daily_loss=strategy.max_daily_loss,
                template_group=group,
            )
            db.session.add(clone)
            db.session.flush()  # 拿 id
            existing.add(sym)
            created_objs.append(clone)
        db.session.commit()
        if not created_objs:
            return False, '沒有可新增的兄弟（都已存在）'

        # Phase 10.9: 立刻排 Celery 回測 — 過門檻 + auto_start 才會啟動
        # 兄弟間 60s 錯峰，避免同時打 OKX 觸發 429
        from app.tasks.strategy_tasks import backtest_and_maybe_start
        for i, c in enumerate(created_objs):
            try:
                backtest_and_maybe_start.apply_async(args=[c.id], countdown=i * 60)
            except Exception:
                pass
        symbols_str = ', '.join(c.symbol for c in created_objs)
        return True, f'已建立 {len(created_objs)} 個兄弟（{symbols_str}），已排回測 — 過門檻才會自動啟動'

    if action == 'optimize_strategy_risk_full':
        # Phase 14k-29 L4: 排 async task 跑 SL/TP 闪测, 通过门槛后 task 内部自动 apply
        # 14k-31 修: 用 random countdown 60-240s 错峰, 避免本轮多策略并发撞 OKX 429
        import random
        from app.tasks.strategy_tasks import optimize_risk_and_apply
        delay = random.randint(60, 240)
        optimize_risk_and_apply.apply_async(args=[sid], countdown=delay)
        from app.services.audit import log as audit
        audit('risk_opt_proposed', strategy_id=sid, dispatch_delay_s=delay)
        return True, f'AI 正在重测止损/止盈, {delay} 秒后开始'

    if action == 'propose_signal_grid':
        # Phase 14k-29/30: 触发 ParamOptimization. 14k-30: 如 advisor 已让 LLM 提议 grid, 存进 opt.grid 让 task 用它而非死字典
        # 14k-31 修: 错峰 dispatch
        import random
        from app.models import ParamOptimization
        from app.tasks.strategy_tasks import optimize_strategy_params
        proposed_grid = item.get('meta', {}).get('proposed_grid')
        opt = ParamOptimization(strategy_id=sid, status='pending',
                                grid=proposed_grid or {})
        db.session.add(opt)
        db.session.commit()
        delay = random.randint(60, 240)
        optimize_strategy_params.apply_async(args=[opt.id], countdown=delay)
        from app.services.audit import log as audit
        audit('signal_grid_proposed', strategy_id=sid, optimization_id=opt.id,
              ai_proposed=bool(proposed_grid), rationale=item.get('meta', {}).get('rationale'),
              dispatch_delay_s=delay)
        suffix = '（AI 自己设计的参数范围）' if proposed_grid else '（用默认参数范围）'
        return True, f'AI 正在测试更好的参数组合 {suffix}, {delay} 秒后开始'

    if action == 'adjust_strategy_risk':
        # Phase 14k-28 L3: 单策略 risk_params 调整 (merge 进 strategy.params.risk_params)
        new_rp = item.get('meta', {}).get('new_risk_params') or {}
        if not new_rp:
            return False, 'meta.new_risk_params 缺失'
        # 安全护栏
        if 'leverage' in new_rp:
            v = float(new_rp['leverage'])
            if not (1.0 <= v <= 20.0):
                return False, f'leverage {v} 超出范围 [1, 20]'
        if 'position_size_usdt' in new_rp:
            v = float(new_rp['position_size_usdt'])
            if not (0.1 <= v <= 10000):
                return False, f'position_size_usdt {v} 超出范围'
        # 守: 这里只接受 leverage / position_size_usdt, 拒绝 SL/TP/信号参数 (backtest 真理)
        rejected = [k for k in new_rp if k not in ('leverage', 'position_size_usdt')]
        if rejected:
            return False, f'不接受字段 (回测覆盖): {rejected}'
        # Phase 14k-30: snapshot before
        before_params = dict(strategy.params or {})
        # merge 到 strategy.params.risk_params
        params = dict(strategy.params or {})
        rp = dict(params.get('risk_params') or {})
        rp.update(new_rp)
        params['risk_params'] = rp
        strategy.params = params
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(strategy, 'params')
        db.session.commit()
        from app.services.audit import log as audit
        audit('ai_strategy_params_change', strategy_id=sid, action='adjust_strategy_risk',
              before_params=before_params, after_params=params, changed_keys=list(new_rp.keys()))
        kv = ', '.join(f'{k}={v}' for k, v in new_rp.items())
        return True, f'策略 risk: {kv}'

    return False, f'未知 action: {action}'


def _today_count_action(action: str) -> int:
    """今日（UTC）某特定 action 已執行幾次。"""
    today = datetime.datetime.utcnow().date()
    rows = (
        AuditLog.query
        .filter(AuditLog.event_type == 'advisor_auto_apply')
        .filter(AuditLog.created_at >= datetime.datetime.combine(today, datetime.time.min))
        .all()
    )
    return sum(1 for r in rows if (r.context or {}).get('action') == action)


def run_auto_apply() -> dict:
    """主入口 — Celery task 跟手動觸發都呼這個。"""
    cfg = get_config()

    if cfg.get('halted'):
        return {'skipped': True, 'reason': 'system halted'}
    if not cfg.get('auto_apply_enabled'):
        return {'skipped': True, 'reason': 'auto_apply_enabled=False'}

    allowed = set(cfg.get('auto_apply_actions') or [])
    if not allowed:
        return {'skipped': True, 'reason': 'auto_apply_actions 為空'}

    daily_cap = int(cfg.get('auto_apply_max_per_day') or 5)
    promote_cap = int(cfg.get('auto_promote_max_per_day') or 2)
    already_today = _today_count()
    promote_today = _today_count_action('promote_candidate')
    remaining = max(0, daily_cap - already_today)
    # 14k-71: cap 满时不再早 return — 让 invent / propose_grid 等 async dispatch 仍可跑
    # daily cap 只限 mutating actions (改 strategy 本身), invent 是创新策略不该被卡
    # 14k-43 _today_count 已只算 mutating, 但 run_auto_apply 顶层 cap 检查太粗暴
    cap_full = (remaining == 0)

    recs = build_recommendations()
    items = recs.get('items', [])

    # 14k-43: MUTATING_ACTIONS 算 daily cap, 其它 (invent/propose_grid/optimize_risk_full) 不算
    MUTATING_ACTIONS = {'apply_params', 'pause', 'retire', 'fan_out', 'promote_candidate',
                         'adjust_global_sizing', 'adjust_strategy_risk'}

    applied: list[dict] = []
    skipped: list[dict] = []
    mutating_applied = 0   # 14k-71: 只数 mutating action 计 cap
    # 14k-72: 每轮 advisor 限 dispatch heavy async tasks (防 worker backlog 阻塞 prewarm/signal)
    # 一轮跑了 5 个 risk_opt + 5 个 grid → 10 task 同时排队, 4-worker pool 卡 30+ 分钟
    # heavy task = optimize_risk_and_apply / optimize_strategy_params / synthesize_dynamic_strategy
    HEAVY_ACTIONS_PER_CYCLE = 3
    heavy_dispatched = 0
    HEAVY_ACTIONS = {'optimize_strategy_risk_full', 'propose_signal_grid', 'invent_new_strategy'}

    for item in items:
        action = item['action']
        if action in INFO_ONLY:
            continue
        if action not in allowed:
            skipped.append({'item': item, 'why': f'{action} not in allowed actions'})
            continue
        # 14k-71: 只对 mutating actions 检 cap, 非 mutating (invent 等) 跳过此 check
        if action in MUTATING_ACTIONS and (mutating_applied >= remaining):
            skipped.append({'item': item, 'why': f'mutating cap {daily_cap}/day 已達 (invent 等不受限)'})
            continue
        # 14k-72: heavy async task 一轮限 3 个 (防 worker backlog)
        if action in HEAVY_ACTIONS and heavy_dispatched >= HEAVY_ACTIONS_PER_CYCLE:
            skipped.append({'item': item, 'why': f'本轮 heavy task {HEAVY_ACTIONS_PER_CYCLE} 已派, 其他下轮 (防 worker backlog)'})
            continue
        # promote_candidate 額外有自己的日限
        if action == 'promote_candidate':
            if promote_today + sum(1 for a in applied if a['action'] == 'promote_candidate') >= promote_cap:
                skipped.append({'item': item, 'why': f'promote 日限 {promote_cap} 已達'})
                continue

        ok, msg = _execute_one(item)
        rec = {
            'action': action,
            'strategy_id': item['strategy_id'],
            'strategy_name': item['strategy_name'],
            'reason': item['reason'],
            'ok': ok,
            'message': msg,
        }
        if ok:
            applied.append(rec)
            if action in MUTATING_ACTIONS:
                mutating_applied += 1   # 14k-71: 只数 mutating 算 cap
            if action in HEAVY_ACTIONS:
                heavy_dispatched += 1   # 14k-72: 数 heavy task 限本轮
            audit('advisor_auto_apply', actor='system',
                  action=action, strategy_id=item['strategy_id'],
                  reason=item['reason'][:300], message=msg)
        else:
            skipped.append({'item': item, 'why': msg})

    if applied:
        # 14k-33: action 中文化, 用 user 看得懂的描述
        ACTION_LABELS = {
            'apply_params': '调整信号参数',
            'pause': '暂停策略',
            'retire': '退役策略',
            'fan_out': '扩展到其他币种',
            'promote_candidate': '上线新策略',
            'adjust_global_sizing': '调整账户级仓位',
            'adjust_strategy_risk': '调整杠杆/仓位',
            'optimize_strategy_risk_full': '优化止损/止盈',
            'propose_signal_grid': '排程参数优化',
            'invent_new_strategy': '创建新候选策略',
        }
        lines = [f'🤖 <b>AI 已自动执行 {len(applied)} 项操作 · AI Auto-Apply ({len(applied)})</b>']
        for r in applied:
            label = ACTION_LABELS.get(r['action'], r['action'])
            lines.append(f"• {label}: #{r['strategy_id']} {r['strategy_name'][:30]} — {r['message']}")
        if already_today + len(applied) >= daily_cap:
            lines.append(f'\n今日已达上限 {daily_cap} 项, 剩下时间不会再自动操作.')
        _telegram_safe('\n'.join(lines))

    return {
        'skipped': False,
        'applied_count': len(applied),
        'applied': applied,
        'skipped_items': skipped,
        'today_count_before': already_today,
        'today_count_after': already_today + len(applied),
        'daily_cap': daily_cap,
    }
