"""Phase 14b: Catalog-first AI 推荐 (取代 strategy_improve_v8 主路径)

不再让 LLM 凭空发明，从 vetted catalog 选最 fit user 当前情境的。
LLM 角色：score + explain，不发明（除非 mode='full_auto' 时调 v8 invent）

Flow:
  1. 拉 user portfolio + symbol regimes
  2. 拉 catalog (status='qualified', source='catalog')
  3. Rule-based score each catalog 适配度:
     - regime match (+30)
     - 当前 user 未持有该 type (+20)
     - symbol fit (+10)
     - verified_oos_sharpe 越高 +
  4. 选 top N → clone catalog 行 → 写新 candidate (status='qualified')
  5. 根据 ai_decision_mode 决定下一步:
     - manual: stop here (走 AiPickPanel 等 user)
     - semi_auto: verified_oos_sharpe ≥ 2.5 → 直接 promote+start
     - full_auto: 全部 promote+start (+ 调 v8 invent 兜底)
"""
from __future__ import annotations

import datetime
from typing import Any

from app.extensions import db
from app.models import Strategy, StrategyCandidate
from app.services.user_scope import scoped_query


def _user_running_summary(user_id: int) -> dict:
    """拉 user 现有 portfolio 摘要"""
    running = scoped_query(Strategy).filter_by(status='running').all()
    return {
        'count': len(running),
        'symbols': sorted({s.symbol for s in running if s.symbol}),
        'types': sorted({s.type for s in running}),
        'categories': sorted({s.category for s in running if s.category}),
    }


def _get_user_capital(user_id: int = 1, exchange: str | None = None) -> float:
    """Phase 14k-12: 按 user 主交易所拉 USDT 余额.
    primary='okx' → OKX env (admin) 或 user OKX creds
    primary='hyperliquid' → HL agent 拉 (spot+perp unified)

    Phase 14k-13: exchange 显式指定 → 跳过 primary 用指定的 (team 多绑分别算资金)
    """
    if exchange:
        primary = exchange.lower()
    else:
        try:
            from app.services.exchange_binding import primary_exchange
            primary = primary_exchange(user_id)
        except Exception:
            primary = 'okx'

    try:
        if primary == 'hyperliquid':
            from app.services.hyperliquid_creds import get_decrypted_for_user as _hc
            from app.services.hyperliquid_service import fetch_balance as _hb
            creds = _hc(user_id)
            if creds:
                bal = _hb(creds=creds)
                return float(bal.get('USDT', {}).get('total', 0))
        # 默认 OKX
        from app.services.exchange_service import fetch_balance, _env_creds, _resolve_creds
        if user_id == 1:
            bal = fetch_balance(creds=_env_creds())
        else:
            creds = _resolve_creds(user_id)
            bal = fetch_balance(creds=creds) if creds else {}
        usdt = bal.get('USDT', {})
        return float(usdt.get('total', 0)) if isinstance(usdt, dict) else float(usdt or 0)
    except Exception:
        return 0.0


def _get_ticker_price_cache(extra_symbols: list[str] | None = None) -> dict[str, float]:
    """批量拉主流币 ticker price (失败 silent return empty).
    Phase 14k-19: HL universe 14 主流 perps 全拉 (避免 matrix 选 SUI/ARB 等 symbol 时 price=0)
    """
    from app.services.exchange_service import get_ticker
    syms = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT',
            'ARB/USDT', 'OP/USDT', 'MATIC/USDT', 'DOGE/USDT',
            'LINK/USDT', 'APT/USDT', 'INJ/USDT', 'SUI/USDT',
            'TIA/USDT', 'BNB/USDT']
    if extra_symbols:
        for s in extra_symbols:
            if s not in syms:
                syms.append(s)
    prices = {}
    for sym in syms:
        try:
            t = get_ticker(sym)
            prices[sym] = float(t.get('price', 0))
        except Exception:
            pass
    return prices


def _hl_min_notional(symbol: str, price: float) -> float:
    """Phase 14k-10: HL 最小开仓 notional. HL 用 szDecimals 控制最小颗粒度.
    BTC szDecimals=5 → min sz = 0.00001 BTC ≈ $0.7 at $70k.
    若 meta API 拉不到, fallback $1 保守值.
    """
    if not price:
        return 1.0
    try:
        from app.services.hyperliquid_service import _info_client, hl_base
        info = _info_client('mainnet')
        meta = info.meta()
        base = hl_base(symbol)
        for u in (meta.get('universe') or []):
            if u.get('name') == base:
                sz_dec = int(u.get('szDecimals', 4))
                min_sz = 10 ** (-sz_dec)
                return min_sz * price
    except Exception:
        pass
    return 1.0


def _is_capital_feasible(entry: StrategyCandidate, user_capital: float, prices: dict,
                         trade_size_usdt: float = 10, exchange: str = 'okx',
                         override_symbols: list[str] | None = None) -> tuple[bool, str, str | None]:
    """Phase 14e+14k-10+14k-19: 检查 user 资金能否下单该 catalog 策略.
    exchange='okx' → 用 ccxt OKX contract size (BTC 0.01 = ~$770).
    exchange='hyperliquid' → 用 HL szDecimals 算 min sz (BTC 0.00001 = ~$0.7).
    override_symbols: 14k-19 — 指定具体 symbol 列表 (matrix path 用), 跳过 fit_symbols 限制

    返回 (feasible, reason, best_symbol)
    """
    from app.services.symbols import get_contract_size
    cm = entry.catalog_meta or {}
    fit_symbols = override_symbols or cm.get('fit_symbols') or []
    rec_risk = cm.get('recommended_risk') or {}
    lev = float(rec_risk.get('leverage') or 3)
    exchange = (exchange or 'okx').lower()

    # 每笔 USDT × lev = notional 上限
    max_notional = trade_size_usdt * lev

    best_sym = None
    for sym in fit_symbols:
        price = prices.get(sym, 0)
        if not price:
            continue

        if exchange == 'hyperliquid':
            min_notional = _hl_min_notional(sym, price)
        else:
            # 14k-46: get_contract_size 在 unsupported 时 raise → 推荐路径吞掉, 跳过该 sym
            try:
                contract_size = get_contract_size(sym)
            except ValueError:
                continue
            if not contract_size:
                continue
            min_notional = contract_size * price

        # 留 50% buffer (real_notional/intended_notional > 1.5 trigger 跳过守门)
        if max_notional >= min_notional * 0.67:
            best_sym = sym
            return True, f'{sym} ({exchange}): min ${min_notional:.2f}, max ${max_notional:.0f} OK', sym

    if not fit_symbols:
        return True, 'no fit_symbols constraint', None
    return False, f'capital ${user_capital:.0f} × lev {lev}x = ${max_notional:.0f} < min ({exchange})', None


def _detect_user_regimes(user_symbols: list[str]) -> dict[str, str]:
    """每 symbol 当前 regime label"""
    try:
        from app.services.regime_detector import detect_regime
    except Exception:
        return {}
    result = {}
    for sym in user_symbols or ['AVAX/USDT', 'BTC/USDT']:
        for tf in ('4h', '1h'):
            try:
                r = detect_regime(sym, tf)
                result[f'{sym}@{tf}'] = r.get('regime', 'unknown')
            except Exception:
                pass
    return result


# Regime label → catalog ideal_regimes 模糊匹配
REGIME_FAMILY = {
    'trending': ['trending', 'expanding_vol', 'multi_week', 'late_trend'],
    'strong_trend': ['trending', 'expanding_vol', 'multi_week'],
    'weak_trend': ['trending', 'turning_point', 'late_trend'],
    'ranging': ['ranging', 'low_adx', 'mean_reverting', 'intraday', 'post_consolidation'],
    'choppy': ['ranging', 'low_adx'],
    'high_vol': ['high_vol', 'expanding_vol', 'volatility_expansion'],
    'low_vol': ['post_consolidation', 'mean_reverting'],
}


def _score_catalog_entry(entry: StrategyCandidate, user: dict, regimes: dict) -> tuple[int, list[str]]:
    """Rule-based 评分 catalog 候选适配 user。返回 (score, reasons)"""
    score = 0
    reasons = []
    cm = entry.catalog_meta or {}

    # 1. verified Sharpe baseline (0-40 points)
    sharpe = float(cm.get('verified_oos_sharpe') or 1.5)
    sharpe_pts = int(min(40, sharpe * 18))
    score += sharpe_pts
    reasons.append(f'verified Sharpe={sharpe} (+{sharpe_pts})')

    # 2. Regime 匹配 (Phase 14k-37: match +30, mismatch -80 强罚)
    # Why: matrix bonus 用 sharpe×15 加分,高 sharpe trend 策略在 range 市场会碾压 reversion
    # 不强罚 → AI 永远选历史最好的 trend, 不管当前是 range. 用户 24h 0 trades 就是这造成
    ideal = set(cm.get('ideal_regimes') or [])
    if ideal and regimes:
        user_regimes_flat = set()
        for k, v in regimes.items():
            user_regimes_flat.update(REGIME_FAMILY.get(v, [v]))
        match = ideal & user_regimes_flat
        if match:
            score += 30
            reasons.append(f'regime match: {list(match)[:2]} (+30)')
        else:
            score -= 80
            reasons.append(f'regime mismatch -80 (ideal={list(ideal)[:2]} vs current={list(user_regimes_flat)[:2]})')

    # 3. Type 多样化 — user 已有同 type 不加分
    if entry.candidate_type.replace('cat_', '') in [t.replace('cat_', '') for t in user.get('types', [])]:
        reasons.append('type already running (-)')
    else:
        score += 15
        reasons.append('new type for portfolio (+15)')

    # 4. Symbol fit — 至少有一个 user 已 symbols 在 fit_symbols
    fit_symbols = set(cm.get('fit_symbols') or [])
    user_syms = set(user.get('symbols') or [])
    if fit_symbols and user_syms and (fit_symbols & user_syms):
        score += 10
        reasons.append('symbol fit (+10)')

    # 5. Category 平衡 — user 已有同 category 不太加分
    if entry.category not in user.get('categories', []):
        score += 5
        reasons.append(f'category {entry.category} 新颖 (+5)')

    return score, reasons


def _pick_symbol_for_recommendation(entry: StrategyCandidate, user_symbols: list[str],
                                      prices: dict | None = None,
                                      capital: float = 0,
                                      trade_size_usdt: float = 10) -> str:
    """从 catalog 的 fit_symbols 选最 fit 且**资金可行**的 symbol
    优先级: feasible fit ∩ user_symbols > feasible fit > user_symbols[0] > 'AVAX/USDT'
    """
    from app.services.symbols import get_contract_size
    fit = (entry.catalog_meta or {}).get('fit_symbols') or []
    rec_risk = (entry.catalog_meta or {}).get('recommended_risk') or {}
    lev = float(rec_risk.get('leverage') or 3)
    max_notional = trade_size_usdt * lev

    def _feasible(sym):
        if not prices:
            return True
        # 14k-46: get_contract_size unsupported → raise; 这里转 False 跳过
        try:
            cs = get_contract_size(sym)
        except ValueError:
            return False
        price = prices.get(sym, 0)
        if not price or not cs:
            return False
        return max_notional >= cs * price * 0.67

    # 1. fit ∩ user_symbols 中 feasible
    for s in (user_symbols or []):
        if s in fit and _feasible(s):
            return s
    # 2. fit 中 feasible 的
    for s in fit:
        if _feasible(s):
            return s
    # 3. user_symbols 第一个
    if user_symbols:
        return user_symbols[0]
    # 4. 默认
    if fit:
        return fit[0]
    return 'AVAX/USDT'


def _adapt_risk_to_capital(rec_risk: dict, symbol: str, capital: float, prices: dict,
                            trade_size_default: float = 10, exchange: str = 'okx') -> dict:
    """Phase 14e + 14k-37: 把 catalog 的 recommended_risk 自适应 user 实际资金 + 交易所.
    确保 position_size × leverage ≥ min contract notional × 1.5 (留 buffer)
    确保 position_size ≤ capital × 20% (单笔不超 20% 资金)

    14k-37: exchange-aware — HL 用 szDecimals (BTC min ~$0.7); OKX 用 ctVal (BTC min ~$770)
    """
    from app.services.symbols import get_contract_size
    adapted = dict(rec_risk or {})
    rec_lev = float(adapted.get('leverage') or 3)
    price = prices.get(symbol, 0) if prices else 0
    exchange_lc = (exchange or 'okx').lower()

    if not (price and capital > 0):
        adapted['position_size_usdt'] = trade_size_default
        return adapted

    # 14k-37: 按交易所算 min_notional
    if exchange_lc == 'hyperliquid':
        min_notional = _hl_min_notional(symbol, price) * 1.5    # HL 用 szDecimals
    else:
        # 14k-46: get_contract_size unsupported → raise; 推荐路径转 trade_size_default fallback
        try:
            contract_size = get_contract_size(symbol)
        except ValueError:
            adapted['position_size_usdt'] = trade_size_default
            return adapted
        if not contract_size:
            adapted['position_size_usdt'] = trade_size_default
            return adapted
        min_notional = contract_size * price * 1.5

    max_capital_per_trade = capital * 0.20         # 单笔最多 20% 资金
    target_per_trade = max(trade_size_default, capital * 0.10)  # 14k-38: 期望每笔 ~10% 资金 (HL min 小时 needed_size 微小会让仓位失真)

    # 算需要的 position_size 让 notional 至少能开 1 contract
    needed_size = min_notional / rec_lev

    # 14k-38 fix: 之前 final = min(needed, cap) 永远拿 needed (HL min 小 → 仓位极小)
    # 正确: 取期望 target 但不低于 min、不超 cap
    final_size = max(needed_size, target_per_trade)
    final_size = min(final_size, max_capital_per_trade)

    # 但 final_size × rec_lev 还不够开 → 提杠杆 (cap 10x)
    if final_size * rec_lev < min_notional:
        new_lev = min(10, int(min_notional / final_size) + 1)
        if new_lev * final_size >= min_notional:
            adapted['leverage'] = new_lev
            adapted['_lev_bumped'] = f'{rec_lev}x → {new_lev}x (足够开最小合约)'

    adapted['position_size_usdt'] = round(final_size, 2)
    adapted['_capital_at_recommend'] = round(capital, 2)
    adapted['_min_contract_notional'] = round(min_notional, 2)
    return adapted


def _clone_catalog_to_candidate(entry: StrategyCandidate, user_id: int, symbol: str,
                                  capital: float = 0, prices: dict | None = None,
                                  trade_size_default: float = 10,
                                  target_exchange: str = 'okx') -> StrategyCandidate:
    """克隆 catalog → 新 candidate (avoid 模板被消费)
    Phase 14e: 同时自适应 risk_params 到 user 实际资金
    Phase 14k-13: target_exchange 记 source_meta, 让 promote_candidate 知道分配哪个交易所
    """
    from app.services.strategy_naming import prettify_candidate_type
    cm = entry.catalog_meta or {}
    rec_risk = cm.get('recommended_risk') or {}
    # 14e + 14k-37: 自适应 risk 按 target_exchange (OKX/HL 两套独立 min_notional)
    adapted_risk = _adapt_risk_to_capital(rec_risk, symbol, capital, prices or {}, trade_size_default,
                                            exchange=target_exchange)
    timestamp = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')
    cloned_type = f'{entry.candidate_type}_u{user_id}_{timestamp}'
    display_name = cm.get('display_name') or prettify_candidate_type(entry.candidate_type)
    clone = StrategyCandidate(
        user_id=user_id,    # 14k-54: per-user scope (catalog 主模板 user_id=NULL 全局)
        source='catalog_clone',
        source_url=entry.source_url,
        source_name=f'AI 推荐 · {display_name}',
        source_author=entry.source_author,
        source_meta={
            'symbol': symbol,
            'risk_params': adapted_risk,
            'cloned_from_catalog_id': entry.id,
            'cloned_at': timestamp,
            'description': cm.get('description'),
            'display_name': display_name,
            'target_exchange': target_exchange,    # Phase 14k-13
        },
        raw_code=f'# Cloned from catalog id={entry.id}\n{entry.raw_code or ""}',
        raw_lang=entry.raw_lang,
        parsed_signal=entry.parsed_signal,
        signal_fn_name=entry.signal_fn_name,
        candidate_type=cloned_type,
        category=entry.category,
        timeframe=entry.timeframe,
        default_params=entry.default_params or {},
        llm_notes=cm.get('description'),
        llm_model='human_curated',
        status='qualified',                 # catalog 已 vetted
        catalog_meta={**cm, 'cloned_for_user': user_id, 'recommended_symbol': symbol},
        backtest_result_id=entry.backtest_result_id,
    )
    db.session.add(clone)
    db.session.flush()
    return clone


def _maybe_auto_apply(clone: StrategyCandidate, user_id: int, mode: str, cfg: dict) -> dict | None:
    """根据 mode 决定是否自动 promote+start，含 guardrails"""
    if mode == 'manual':
        return None
    cm = clone.catalog_meta or {}
    sharpe = float(cm.get('verified_oos_sharpe') or 1.5)
    sym = (clone.source_meta or {}).get('symbol') or 'AVAX/USDT'

    # Phase 14e: Concentration guard — 同 (symbol, TF, category) 已 running 则 skip
    overlap = scoped_query(Strategy).filter_by(
        status='running', symbol=sym, timeframe=clone.timeframe,
        category=clone.category,
    ).first()
    if overlap:
        return {'skipped': True,
                'reason': f'已 running 同 (symbol={sym}, TF={clone.timeframe}, cat={clone.category}) 策略 #{overlap.id}，避免过度集中'}

    # Guardrails
    n_running = scoped_query(Strategy).filter_by(status='running').count()
    max_running = int(cfg.get('auto_apply_max_running', 8))
    if n_running >= max_running:
        return {'skipped': True, 'reason': f'running {n_running} >= max {max_running}'}

    if cfg.get('halted'):
        return {'skipped': True, 'reason': 'system halted'}

    # 今日已 auto-applied 数
    today_start = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    from app.models import AuditLog
    today_auto = AuditLog.query.filter(
        AuditLog.actor == 'auto:strategy_recommend',
        AuditLog.event_type == 'candidate_promote_and_start',
        AuditLog.created_at >= today_start,
    ).count()
    max_per_day = int(cfg.get('auto_promote_max_per_day', 2))
    if today_auto >= max_per_day:
        return {'skipped': True, 'reason': f'today auto-applied {today_auto} >= max {max_per_day}'}

    # semi_auto: 仅 Sharpe ≥ 2.5 自动
    if mode == 'semi_auto' and sharpe < 2.5:
        return {'skipped': True, 'reason': f'semi_auto: Sharpe {sharpe} < 2.5 (走面板)'}

    # 通过 — 自动 promote+start
    from app.services.candidate_pipeline import promote_candidate as do_promote
    rp = (clone.source_meta or {}).get('risk_params') or {}
    sym = (clone.source_meta or {}).get('symbol') or 'AVAX/USDT'
    promote_res = do_promote(clone.id, symbol=sym, owner_user_id=user_id)
    if not promote_res.get('ok'):
        return {'skipped': True, 'reason': f'promote fail: {promote_res.get("error", "")[:100]}'}
    sid = promote_res['strategy']['id']

    # 写 risk_params + start
    s = Strategy.query.get(sid)
    if s:
        p = dict(s.params or {})
        p['risk_params'] = {k: v for k, v in rp.items() if v is not None}
        s.params = p
        s.status = 'running'
        db.session.commit()
        try:
            from app.tasks.strategy_tasks import run_strategy_signals
            run_strategy_signals.delay(sid)
        except Exception:
            pass

    # audit
    try:
        from app.services.audit import log as audit
        audit('candidate_promote_and_start',
              actor='auto:strategy_recommend',
              user_id=user_id,
              candidate_id=clone.id,
              strategy_id=sid,
              risk_params=rp,
              symbol=sym,
              mode=mode,
              sharpe=sharpe)
    except Exception:
        pass

    # Telegram (admin 用 admin chat，其他 user 暂不通知)
    # Phase 14k-18: 措辞美化, 去 raw 字段名
    try:
        from app.services.telegram_service import send as _tg
        if user_id == 1:
            # Pretty name from catalog_meta description or candidate_type
            cm = clone.catalog_meta or {}
            pretty_name = cm.get('description', '').split('—')[0].strip() or clone.candidate_type
            # 字段命名兼容: sl_pct / stop_loss_pct, tp_pct / take_profit_pct
            lev = rp.get('leverage')
            sl = rp.get('stop_loss_pct') or rp.get('sl_pct')
            tp = rp.get('take_profit_pct') or rp.get('tp_pct')
            ord_type = {'market': '市价', 'maker': '挂单', 'maker_with_fallback': '挂单+市价'}.get(
                rp.get('order_type', 'market'), rp.get('order_type', '市价'))
            mode_zh = {'manual': '手动', 'semi_auto': '半自动', 'full_auto': '全自动'}.get(mode, mode)
            risk_line_parts = []
            if lev: risk_line_parts.append(f'杠杆 {lev}x')
            if sl: risk_line_parts.append(f'止损 {sl}%')
            if tp: risk_line_parts.append(f'止盈 {tp}%')
            risk_line_parts.append(f'{ord_type}')
            risk_line = ' · '.join(risk_line_parts)

            _tg(
                f'🤖 <b>AI 自动上线新策略 · Auto-Promoted</b>（{mode_zh}模式 / {mode}）\n'
                f'#{sid} {pretty_name}\n'
                f'交易对 / Symbol: {sym} · 回测 / Sharpe: {sharpe}\n'
                f'{risk_line}\n\n'
                f'已运行 / Running · <a href="https://ai-quant.medias-ai.cloud/">控制台 / Console</a>',
                event_key='auto_apply'
            )
    except Exception:
        pass

    return {'applied': True, 'strategy_id': sid, 'sharpe': sharpe}


def _max_recommend_for_capital(capital_usdt: float) -> int:
    """14k-20: 推荐数随资金线性扩 (资金多上更多策略)"""
    if capital_usdt < 100: return 3
    if capital_usdt < 500: return 4
    if capital_usdt < 2000: return 6
    return 8


def recommend_strategies(user_id: int, *, max_recommend: int | None = None) -> dict:
    """Phase 14k-13/20: 主入口 — 按 user 绑定的交易所分发推荐.

    max_recommend: 显式指定 → 用; None → 按 user 资金自适应 (3/4/6/8).

    - 普通 user (单绑) → 调一次 _recommend_for_exchange 返单结果
    - team user (多绑) → 对每个 bound exchange 各调一次, 合并结果
      (team 工作量翻倍, 不是给 user 多个选择, 而是 AI 帮多账户都跑)
    """
    from app.services.exchange_binding import bound_exchanges, is_team_tier

    bound = bound_exchanges(user_id)
    if not bound:
        return {
            'ok': True, 'recommendations': [],
            'message': '未绑定任何交易所, 请先去 Settings 绑 OKX 或 Hyperliquid',
            'bound_exchanges': [],
        }

    # 14k-20: 资金自适应 max_recommend (default)
    if max_recommend is None:
        capital = _get_user_capital(user_id)
        max_recommend = _max_recommend_for_capital(capital)

    # team: 每个 exchange 各跑一次; 普通 user: 单个 exchange
    if is_team_tier(user_id) and len(bound) > 1:
        all_recs = []
        per_exchange = {}
        for ex in bound:
            sub = _recommend_for_exchange(user_id, ex, max_recommend=max_recommend)
            per_exchange[ex] = sub
            all_recs.extend(sub.get('recommendations', []))
        return {
            'ok': True,
            'mode': sub.get('mode') if all_recs else 'manual',
            'recommendations': all_recs,
            'by_exchange': per_exchange,
            'bound_exchanges': bound,
            'total_recommendations': len(all_recs),
        }

    # 普通 user 或 team 只绑 1 个
    return _recommend_for_exchange(user_id, bound[0], max_recommend=max_recommend)


def _recommend_for_exchange(user_id: int, target_exchange: str, *, max_recommend: int = 3) -> dict:
    """针对单一交易所跑 catalog 推荐.
    Phase 14k-13: 从 recommend_strategies 拆出, 内部所有 capital/feasibility 都用 target_exchange.
    """
    from app.services.config_service import get_config
    cfg = get_config()
    mode = cfg.get('ai_decision_mode', 'manual')

    user = _user_running_summary(user_id)
    regimes = _detect_user_regimes(user['symbols'])
    user_capital = _get_user_capital(user_id, exchange=target_exchange)
    prices = _get_ticker_price_cache()
    trade_size = float(cfg.get('trade_size_usdt') or 10)

    catalog = StrategyCandidate.query.filter_by(source='catalog', status='qualified').all()
    if not catalog:
        return {'ok': False, 'error': 'catalog 为空，先跑 seed_catalog.py'}

    user_exchange = target_exchange    # 14k-13: 强制按 target 算 feasibility

    # Phase 14e: 先 filter 不 feasible 的
    feasible_catalog = []
    infeasible = []
    for entry in catalog:
        ok, reason, _ = _is_capital_feasible(entry, user_capital, prices, trade_size, exchange=user_exchange)
        if ok:
            feasible_catalog.append(entry)
        else:
            infeasible.append({'type': entry.candidate_type, 'reason': reason})

    if not feasible_catalog:
        return {
            'ok': True,
            'mode': mode,
            'recommendations': [],
            'user_state': user,
            'user_capital_usdt': user_capital,
            'infeasible_count': len(infeasible),
            'infeasible_examples': infeasible[:5],
            'message': f'资金 ${user_capital:.0f} 不足以下单任何 catalog 策略最小合约。建议加资金或降 lev/trade_size',
        }

    # Phase 14e: 拉过去 30 天 trade history — 避免推荐已亏损的 strategy type
    losing_types = set()
    try:
        from app.models import Trade
        from sqlalchemy import func
        recent = (db.session.query(
            Strategy.type,
            func.coalesce(func.sum(Trade.pnl), 0).label('pnl'),
            func.count(Trade.id).label('n'),
        ).join(Trade, Trade.strategy_id == Strategy.id)
         .filter(Trade.exit_time > datetime.datetime.utcnow() - datetime.timedelta(days=30))
         .group_by(Strategy.type).all())
        for row in recent:
            if row.pnl < 0 and row.n >= 3:
                # 30 天内 3+ 笔且累计亏 → 该类型暂时避开
                losing_types.add(row.type.replace('cand_', '').replace('cat_', ''))
    except Exception:
        pass

    # Score 所有 feasible catalog
    scored = []
    for entry in feasible_catalog:
        s, reasons = _score_catalog_entry(entry, user, regimes)
        # 14e: 历史亏损 type 减分
        base_type = entry.candidate_type.replace('cat_', '')
        if any(lt in base_type or base_type in lt for lt in losing_types):
            s -= 25
            reasons.append(f'历史 30 天 {base_type} 亏损 (-25)')
        scored.append((entry, s, reasons))
    scored.sort(key=lambda x: -x[1])

    # Phase 14e: diversification — top max_recommend 强制不同 category
    top = []
    seen_categories = set()
    for entry, s, reasons in scored:
        if len(top) >= max_recommend:
            break
        if entry.category in seen_categories:
            continue
        top.append((entry, s, reasons))
        seen_categories.add(entry.category)
    # 如果不同 category 不够，补上次优 (允许同 category)
    if len(top) < max_recommend:
        remaining = [(e, s, r) for e, s, r in scored if (e, s, r) not in top]
        top.extend(remaining[:max_recommend - len(top)])

    # 14k-16: 从 verified matrix 池选 — 不再每次重测
    # matrix 已离线 batch 跑过 catalog × symbol × exchange, 只取 is_verified=true 的组合
    from app.services.catalog_matrix import get_verified_for_exchange
    verified_pool = get_verified_for_exchange(target_exchange)
    if not verified_pool:
        return {
            'ok': True, 'mode': mode, 'recommendations': [],
            'user_state': user, 'user_capital_usdt': user_capital,
            'message': f'{target_exchange} verified 池为空. 请先跑 catalog batch-backtest (POST /api/admin/catalog-batch-backtest)',
        }

    # 14k-20: 先拉 user running 策略, filter 掉同 (symbol, TF, category) 的 matrix entry
    # 避免推荐重复 clone 然后被 concentration guard 卡在 panel
    running_occupied = set()
    for s in scoped_query(Strategy).filter_by(status='running').all():
        running_occupied.add((s.symbol, s.timeframe, s.category))

    # 把 catalog_id → (catalog_entry, best_matrix_row) 对齐. 每个 catalog 取 oos_sharpe 最高的 symbol.
    # 14k-20: 但跳过已被 running 占据的 (symbol, TF, category) 槽位
    catalog_by_id = {c.id: c for c in catalog}
    best_per_catalog = {}
    for m in verified_pool:
        entry = catalog_by_id.get(m.catalog_id)
        if entry is None:
            continue
        # check concentration: 已 occupy → 这个 (catalog, symbol) 组合不该推
        if (m.symbol, entry.timeframe, entry.category) in running_occupied:
            continue
        cur = best_per_catalog.get(m.catalog_id)
        if cur is None or (m.oos_sharpe or 0) > (cur.oos_sharpe or 0):
            best_per_catalog[m.catalog_id] = m

    # 重新 score: 用 matrix 里的真 sharpe + 原 _score_catalog_entry 加权
    matrix_scored = []
    for cat_id, mx in best_per_catalog.items():
        entry = catalog_by_id.get(cat_id)
        if entry is None:
            continue
        # 14k-19: 用 matrix 实际 symbol check, 不再受 catalog.fit_symbols 限制
        # 14k-37 (14k-36 修正): symbol 守门按 target_exchange:
        #   OKX → is_supported (SUPPORTED_SYMBOLS dict, ctVal 必知)
        #   HL → meta 能拉到 szDecimals (universe 200+ pair 多, dict 维护不动)
        if (target_exchange or 'okx').lower() == 'okx':
            from app.services.symbols import is_supported
            if not is_supported(mx.symbol, exchange='okx'):    # 14k-46.1: 显式 exchange
                continue
        else:
            # HL: 用 _hl_min_notional 拉 meta 验证 (拉不到 = 不在 HL universe)
            try:
                hl_min = _hl_min_notional(mx.symbol, prices.get(mx.symbol, 1.0))
                if hl_min >= 100:  # > $100 显然 fallback (meta 没拉到走 $1.0 default × price 大)
                    # 实际 hl_min 应该是 几分钱 到 几块, > 100 表示 meta 拉不到 + price 很大走 fallback
                    pass  # 让它过, _adapt_risk_to_capital 再用 HL min 验
            except Exception:
                pass
        ok, _, _ = _is_capital_feasible(entry, user_capital,
                                          {mx.symbol: prices.get(mx.symbol, 0)},
                                          trade_size, exchange=target_exchange,
                                          override_symbols=[mx.symbol])
        if not ok:
            continue
        s, reasons = _score_catalog_entry(entry, user, regimes)
        # bonus: matrix oos_sharpe 越高加分越多
        s += int(round((mx.oos_sharpe or 0) * 15))
        reasons.insert(0, f'✓ 真实回测: OOS Sharpe {mx.oos_sharpe:.2f} on {mx.symbol} (IS {mx.is_sharpe:.2f}, decay {mx.decay_pct:.0f}%, {mx.full_total_trades} trades)')
        matrix_scored.append((entry, mx, s, reasons))

    matrix_scored.sort(key=lambda x: -x[2])

    # Phase 14k-19/20: category 配额平衡 — 资金多就多上, 但仍跨 long/short/swing 分配
    # 目标配额表 (max_recommend → {category: 上限}):
    # 3 → 1 long + 1 short + 1 swing
    # 4 → 1 long + 1 short + 2 swing
    # 5 → 2 long + 1 short + 2 swing
    # 6 → 2 long + 2 short + 2 swing
    # 7 → 2 long + 2 short + 3 swing
    # 8 → 2 long + 2 short + 3 swing + 1 ultra (若 catalog 有)
    quotas_map = {
        3: {'long': 1, 'short': 1, 'swing': 1, 'ultra': 0},
        4: {'long': 1, 'short': 1, 'swing': 2, 'ultra': 0},
        5: {'long': 2, 'short': 1, 'swing': 2, 'ultra': 0},
        6: {'long': 2, 'short': 2, 'swing': 2, 'ultra': 0},
        7: {'long': 2, 'short': 2, 'swing': 3, 'ultra': 0},
        8: {'long': 2, 'short': 2, 'swing': 3, 'ultra': 1},
    }
    quotas = dict(quotas_map.get(max_recommend, quotas_map[3]))
    selected = []
    seen_base_types = set()
    def _base_type(c): return c.candidate_type or ''

    # 第一轮: 按配额选, 同 base_type 不重复
    for entry, mx, s, reasons in matrix_scored:
        if len(selected) >= max_recommend:
            break
        cat = entry.category or 'swing'
        if quotas.get(cat, 0) <= 0:
            continue    # 该 category 配额满了
        if _base_type(entry) in seen_base_types:
            continue
        selected.append((entry, mx, s, reasons))
        quotas[cat] -= 1
        seen_base_types.add(_base_type(entry))

    # 第二轮 fallback: 配额不满 (某 category 池空) → 同 base_type 不重复填
    if len(selected) < max_recommend:
        for entry, mx, s, reasons in matrix_scored:
            if len(selected) >= max_recommend:
                break
            if (entry, mx, s, reasons) in selected:
                continue
            if _base_type(entry) in seen_base_types:
                continue
            selected.append((entry, mx, s, reasons))
            seen_base_types.add(_base_type(entry))

    # Phase 14k-37 B: 动态 regime 配额 — 按 user 当前 regime 分布 rebalance
    # Why: category 配额 (long/short/swing) 只管 timeframe 风格, 不管市场 regime.
    # range 市场塞 trend 策略会空跑 → 必须保证 selection 跟 user symbols 实际 regime 匹配
    REGIME_FAMILY_RANGE = {'ranging', 'mean_reverting', 'low_adx', 'post_consolidation', 'intraday', 'cyclic'}
    REGIME_FAMILY_TREND = {'trending', 'strong_trend', 'expanding_vol', 'multi_week', 'late_trend', 'turning_point', 'high_vol'}

    def _entry_regime_type(e):
        ideal = set((e.catalog_meta or {}).get('ideal_regimes') or [])
        if ideal & REGIME_FAMILY_RANGE:
            return 'reversion'
        if ideal & REGIME_FAMILY_TREND:
            return 'trend'
        return 'unknown'

    if regimes:
        user_range = sum(1 for v in regimes.values() if v in ('ranging', 'range', 'choppy', 'low_vol'))
        user_trend = sum(1 for v in regimes.values() if v in ('trending', 'strong_trend', 'weak_trend', 'high_vol'))
        user_total = user_range + user_trend
        if user_total > 0:
            range_ratio = user_range / user_total
            trend_ratio = user_trend / user_total
            sel_rev_count = sum(1 for e, _, _, _ in selected if _entry_regime_type(e) == 'reversion')
            sel_trend_count = sum(1 for e, _, _, _ in selected if _entry_regime_type(e) == 'trend')
            sel_types_set = {e.candidate_type for e, _, _, _ in selected}

            # Phase 14k-38: B 替换 — 不仅 skip selected 已有, 也 skip 当前 running 的 type
            # (上轮 14k-37 bug: 找到 reversion 但已 running, _maybe_auto_apply 拒, B 没找下一个)
            running_types = {s.type.replace('cand_', '') for s in scoped_query(Strategy).filter_by(status='running').all()}
            skip_types = sel_types_set | running_types

            def _find_replacement(target_regime: str):
                """从 matrix_scored 找最高分 target_regime 且不在 skip_types 的 entry."""
                for entry, mx, sc, rs in matrix_scored:
                    if _entry_regime_type(entry) != target_regime:
                        continue
                    # 比对去 cat_ 前缀的 base type
                    base = entry.candidate_type
                    if base in skip_types:
                        continue
                    # 也 skip selected 里已有的 (避免重复)
                    if base in sel_types_set:
                        continue
                    return entry, mx, sc, rs
                return None

            # range 主导 + selection 缺 reversion → 替换最低分 trend → 最高分非 running reversion
            if range_ratio >= 0.5 and sel_rev_count == 0 and sel_trend_count > 0:
                trend_idx = [i for i, (e, _, _, _) in enumerate(selected) if _entry_regime_type(e) == 'trend']
                replace_idx = trend_idx[-1] if trend_idx else None
                if replace_idx is not None:
                    found = _find_replacement('reversion')
                    if found:
                        entry, mx, sc, rs = found
                        selected[replace_idx] = (entry, mx, sc, rs + [f'regime rebalance: user {range_ratio:.0%} range → 换入 reversion'])
            elif trend_ratio >= 0.5 and sel_trend_count == 0 and sel_rev_count > 0:
                rev_idx = [i for i, (e, _, _, _) in enumerate(selected) if _entry_regime_type(e) == 'reversion']
                replace_idx = rev_idx[-1] if rev_idx else None
                if replace_idx is not None:
                    found = _find_replacement('trend')
                    if found:
                        entry, mx, sc, rs = found
                        selected[replace_idx] = (entry, mx, sc, rs + [f'regime rebalance: user {trend_ratio:.0%} trend → 换入 trend'])

    # Clone + auto-apply. clone 继承 matrix backtest_result_id
    recommendations = []
    for entry, mx, score, reasons in selected:
        sym = mx.symbol     # 用 matrix 的 best symbol
        clone = _clone_catalog_to_candidate(entry, user_id, sym, user_capital, prices, trade_size,
                                              target_exchange=target_exchange)
        # 继承 matrix backtest_result_id, panel 直接显真 metrics
        if mx.backtest_result_id:
            clone.backtest_result_id = mx.backtest_result_id
        # 验证过了, 直接 qualified
        clone.status = 'qualified'
        sm = dict(clone.source_meta or {})
        sm['matrix_id'] = mx.id
        sm['verified_oos_sharpe'] = mx.oos_sharpe
        clone.source_meta = sm
        db.session.commit()

        adapted_risk = (clone.source_meta or {}).get('risk_params') or {}
        auto = _maybe_auto_apply(clone, user_id, mode, cfg)
        if auto and auto.get('skipped'):
            sm = dict(clone.source_meta or {})
            sm['auto_skip_reason'] = auto.get('reason', '')
            clone.source_meta = sm
            db.session.commit()
        recommendations.append({
            'catalog_id': entry.id,
            'catalog_type': entry.candidate_type,
            'target_exchange': target_exchange,
            'cloned_id': clone.id,
            'cloned_type': clone.candidate_type,
            'symbol': sym,
            'category': entry.category,
            'timeframe': entry.timeframe,
            'verified_sharpe': (entry.catalog_meta or {}).get('verified_oos_sharpe'),
            'recommended_risk_original': (entry.catalog_meta or {}).get('recommended_risk'),
            'recommended_risk': adapted_risk,    # ★ adapted to capital
            'description': (entry.catalog_meta or {}).get('description'),
            'score': score,
            'reasons': reasons,
            'auto_apply': auto,
            'source': 'catalog',
        })

    # Phase 14d: full_auto 模式且 catalog top score < 高门槛 → 触发 v8 invent
    invent_result = None
    if mode == 'full_auto':
        catalog_max_score = top[0][1] if top else 0
        if catalog_max_score < 80:
            # catalog 没有显著好选 → 尝试 invent
            try:
                from app.services.llm_prompts.strategy_improve_v8 import improve_strategies_v8
                v8_r = improve_strategies_v8(
                    user_id=user_id, max_iterations=1, target_count=1,
                    enable_external_research=True,
                )
                invent_result = {
                    'attempted': True,
                    'submitted_count': len(v8_r.get('submitted', [])),
                    'rejected_count': len(v8_r.get('rejected', [])),
                }
                # invent 输出 — apply paper-only guard
                for sub in v8_r.get('submitted', []):
                    cid = sub.get('candidate_id')
                    if not cid:
                        continue
                    metric_sharpe = (sub.get('metrics') or {}).get('oos_sharpe', 0)
                    if metric_sharpe < 2.0:
                        invent_result.setdefault('rejected_low_sharpe', []).append(
                            {'candidate_id': cid, 'sharpe': metric_sharpe}
                        )
                        continue
                    # Mark for paper-only 7 天
                    cand = StrategyCandidate.query.get(cid)
                    if cand:
                        meta = dict(cand.source_meta or {})
                        meta['paper_only_days'] = 7
                        meta['source_label'] = 'AI invented (paper-only 7d)'
                        cand.source_meta = meta
                    # Try auto-apply (with paper-only flag)
                    auto_invent = _maybe_auto_apply_invent(cand, user_id, mode, cfg)
                    recommendations.append({
                        'cloned_id': cid,
                        'cloned_type': cand.candidate_type if cand else '?',
                        'symbol': (cand.source_meta or {}).get('symbol') if cand else None,
                        'verified_sharpe': metric_sharpe,
                        'source': 'invented',
                        'auto_apply': auto_invent,
                        'paper_only_days': 7,
                    })
            except Exception as e:
                invent_result = {'attempted': True, 'error': f'{type(e).__name__}: {e}'}

    db.session.commit()
    return {
        'ok': True,
        'mode': mode,
        'user_state': user,
        'regimes': regimes,
        'catalog_size': len(catalog),
        'feasible_catalog_count': len(feasible_catalog),
        'user_capital_usdt': user_capital,
        'recommendations': recommendations,
        'invent_result': invent_result,
    }


def _maybe_auto_apply_invent(cand, user_id: int, mode: str, cfg: dict) -> dict | None:
    """Phase 14d: invent 出的策略走 paper-only 7 天再升 LIVE"""
    if mode != 'full_auto' or not cand:
        return None
    from app.services.candidate_pipeline import promote_candidate as do_promote
    sym = (cand.source_meta or {}).get('symbol') or 'AVAX/USDT'
    rp = (cand.source_meta or {}).get('risk_params') or {}

    # Guardrail: 总 running 限制
    n_running = scoped_query(Strategy).filter_by(status='running').count()
    if n_running >= int(cfg.get('auto_apply_max_running', 8)):
        return {'skipped': True, 'reason': f'running {n_running} >= max'}

    promote_res = do_promote(cand.id, symbol=sym, owner_user_id=user_id)
    if not promote_res.get('ok'):
        return {'skipped': True, 'reason': f'promote fail: {promote_res.get("error", "")[:100]}'}
    sid = promote_res['strategy']['id']
    s = Strategy.query.get(sid)
    if s:
        p = dict(s.params or {})
        p['risk_params'] = {k: v for k, v in rp.items() if v is not None}
        # Phase 14d: paper-only 7 天
        import datetime as _dt
        p['paper_only_until'] = (_dt.datetime.utcnow() + _dt.timedelta(days=7)).isoformat()
        s.params = p
        s.status = 'running'
        db.session.commit()
        try:
            from app.tasks.strategy_tasks import run_strategy_signals
            run_strategy_signals.delay(sid)
        except Exception:
            pass

    # audit
    try:
        from app.services.audit import log as audit
        audit('candidate_promote_and_start_paper_only',
              actor='auto:strategy_recommend_invent',
              user_id=user_id, candidate_id=cand.id, strategy_id=sid,
              risk_params=rp, symbol=sym,
              paper_only_until_days=7)
    except Exception:
        pass

    return {'applied': True, 'paper_only_days': 7, 'strategy_id': sid}


# ============================================================
# Phase 14h: AI 推荐解释 LLM 化
# 给一条 clone candidate (推荐结果) → 调 user 的 LLM 生成 1-2 句中文解释 + 风险提示
# Fallback 到 catalog_meta.description + rule-based reasons
# 缓存 12h (catalog_id + symbol 不变 → 解释稳定)
# ============================================================

_EXPLAIN_SYSTEM = """你是量化交易顾问。根据 catalog 策略元数据 + 用户当前资金/持仓状态 + 市场环境，写 1-2 句中文解释，告诉用户为什么这条策略适合他现在。
要求:
- 第一句: 为什么 fit (匹配 user 的 X + 利用 Y 市场环境)
- 第二句: 风险/注意事项 (避开什么环境)
- 中文, 简洁, 口语化, 不要罗列指标参数
- 不要寒暄, 不要"建议你"开头, 直接陈述
输出严格 JSON: {"explanation": "...", "risk_warning": "..."}"""


def _build_explain_prompt(entry, sym: str, user: dict, regimes: dict,
                          user_capital: float, score: int, reasons: list) -> str:
    cm = entry.catalog_meta or {}
    fit_regimes = cm.get('ideal_regimes') or []
    avoid = cm.get('avoid_when') or '-'
    desc = cm.get('description') or '-'
    rec_risk = cm.get('recommended_risk') or {}
    sharpe = cm.get('verified_oos_sharpe') or '-'
    cur_regime = regimes.get(sym, {}) if isinstance(regimes, dict) else {}

    return f"""## 策略
- 类型: {entry.candidate_type}
- 中文描述: {desc}
- 适合环境: {', '.join(fit_regimes) if fit_regimes else '-'}
- 避开: {avoid}
- OOS Sharpe: {sharpe}
- 推荐 risk: leverage={rec_risk.get('leverage')}x, SL={rec_risk.get('sl_pct')}%, TP={rec_risk.get('tp_pct')}%

## 用户状态
- 资金: ${user_capital:.0f}
- 现有 running 策略数: {user.get('count', 0)}
- 持仓品种: {', '.join(user.get('symbols', []) or ['(无)'])}
- 持仓类别: {', '.join(user.get('categories', []) or ['(无)'])}

## 推荐 symbol + 当前市场
- 推荐: {sym}
- 当前 {sym} 环境: {cur_regime if cur_regime else '(数据不足)'}

## 评分依据 (rule-based)
{chr(10).join('- ' + r for r in reasons[:5])}

请输出严格 JSON。"""


def explain_recommendation(user_id: int, clone_candidate_id: int) -> dict:
    """给一条 clone candidate, 生成 LLM 中文解释 + 风险提示.

    返回 {ok, explanation, risk_warning, fallback, source: 'llm'|'rule_based'|'cache'}
    """
    clone = StrategyCandidate.query.get(clone_candidate_id)
    if not clone:
        return {'ok': False, 'error': 'candidate not found'}

    src_meta = clone.source_meta or {}
    cm = clone.catalog_meta or {}
    catalog_id = src_meta.get('cloned_from_catalog_id')
    sym = src_meta.get('symbol') or (cm.get('recommended_symbol') if cm else None) or 'BTC/USDT'
    desc = cm.get('description') or '(无描述)'
    avoid = cm.get('avoid_when') or '-'

    # 解析回原 catalog (取最新 ideal_regimes/description)
    catalog_entry = StrategyCandidate.query.get(catalog_id) if catalog_id else None
    use_entry = catalog_entry or clone

    user = _user_running_summary(user_id)
    regimes = _detect_user_regimes([sym]) if sym else {}
    user_capital = _get_user_capital(user_id)
    score = src_meta.get('score', 0)
    reasons = src_meta.get('reasons') or []

    # Cache key — catalog_id + sym 唯一决定解释内容
    cache_key = f'reco_expl:{user_id}:{catalog_id or use_entry.id}:{sym}'

    prompt = _build_explain_prompt(use_entry, sym, user, regimes, user_capital, score, reasons)

    try:
        from app.services.llm_provider import call_llm
        res = call_llm(
            user_id=user_id,
            prompt=prompt,
            system=_EXPLAIN_SYSTEM,
            max_tokens=400,
            cache_key=cache_key,
            timeout=20,
        )
    except Exception as e:
        return {
            'ok': True,
            'source': 'rule_based',
            'explanation': desc,
            'risk_warning': f'避免: {avoid}',
            'fallback_reason': f'llm exception: {type(e).__name__}',
        }

    if not res.get('ok'):
        return {
            'ok': True,
            'source': 'rule_based',
            'explanation': desc,
            'risk_warning': f'避免: {avoid}',
            'fallback_reason': res.get('error', '')[:100],
        }

    text = (res.get('text') or '').strip()
    # 解析 JSON
    import json
    import re
    parsed = None
    try:
        parsed = json.loads(text)
    except Exception:
        # try extract first {...}
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                pass

    if not parsed or not isinstance(parsed, dict):
        return {
            'ok': True,
            'source': 'rule_based',
            'explanation': desc,
            'risk_warning': f'避免: {avoid}',
            'fallback_reason': f'llm output not parseable: {text[:80]}',
        }

    return {
        'ok': True,
        'source': 'cache' if res.get('cached') else 'llm',
        'explanation': (parsed.get('explanation') or desc).strip(),
        'risk_warning': (parsed.get('risk_warning') or f'避免: {avoid}').strip(),
        'provider_used': res.get('provider_used'),
        'cached': bool(res.get('cached')),
    }
