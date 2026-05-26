"""候選策略 pipeline orchestrator — Phase 4

把單一 StrategyCandidate 推一步：translate → sandbox verify → 標記狀態。
（自動回測在 Phase 4.4 的 backtest_pipeline 處理。）
"""
from __future__ import annotations

from app.extensions import db
from app.models import StrategyCandidate, BacktestResult
from app.services.candidate_sandbox import verify_signal_fn, load_signal_fn
from app.services.llm_translator import translate, translate_via_provider, LLMTranslatorError


# 候選策略 qualified 門檻（Phase 5.4 嚴格化）
QUALIFIED_SHARPE_IS = 1.5        # in-sample Sharpe
QUALIFIED_SHARPE_OOS = 0.8       # out-of-sample 較寬鬆，但必須是正的且合理
QUALIFIED_MAX_DECAY_PCT = 70     # OOS sharpe 相對 IS 衰減超過 70% → 過擬合 reject
QUALIFIED_MIN_TRADES_PER_SIDE = 5  # IS / OOS 各自至少這麼多筆，否則 Sharpe 估不準


def translate_and_verify(candidate_id: int, *, user_id: int | None = None) -> dict:
    """LLM 翻譯 + 沙箱驗證一個 candidate。回傳更新後的 dict。

    狀態流轉：pending → translating → translated（成功）/ error（失敗）

    Phase 11.5.9: user_id 不為 None 走 translate_via_provider（admin claude_cli /
    user BYO API）；None 走舊 translate() 用 env ANTHROPIC_API_KEY（host cron 用）。
    """
    c = StrategyCandidate.query.get(candidate_id)
    if c is None:
        return {'ok': False, 'error': f'candidate {candidate_id} not found'}

    if not c.raw_code or not c.raw_code.strip():
        c.status = 'error'
        c.error_log = 'raw_code is empty'
        db.session.commit()
        return {'ok': False, 'error': 'raw_code empty', 'candidate': c.to_dict()}

    c.status = 'translating'
    c.error_log = None
    db.session.commit()

    # ---- LLM 翻譯 ----
    try:
        if user_id is not None:
            parsed = translate_via_provider(
                raw_code=c.raw_code,
                raw_lang=c.raw_lang or 'python',
                source_name=c.source_name or 'unknown',
                source_author=c.source_author or 'unknown',
                source_url=c.source_url or '',
                user_id=user_id,
            )
        else:
            parsed = translate(
                raw_code=c.raw_code,
                raw_lang=c.raw_lang or 'python',
                source_name=c.source_name or 'unknown',
                source_author=c.source_author or 'unknown',
                source_url=c.source_url or '',
            )
    except LLMTranslatorError as e:
        c.status = 'error'
        c.error_log = f'translate: {e}'
        db.session.commit()
        return {'ok': False, 'error': str(e), 'candidate': c.to_dict()}
    except Exception as e:
        c.status = 'error'
        c.error_log = f'translate unexpected: {type(e).__name__}: {e}'
        db.session.commit()
        return {'ok': False, 'error': f'{type(e).__name__}: {e}', 'candidate': c.to_dict()}

    # ---- 沙箱驗證 ----
    verify = verify_signal_fn(
        source=parsed['signal_fn_source'],
        fn_name=parsed['signal_fn_name'],
        default_params=parsed.get('default_params') or {},
    )
    if not verify['ok']:
        c.status = 'error'
        c.parsed_signal = parsed['signal_fn_source']   # 留住翻譯產物方便事後 debug
        c.signal_fn_name = parsed['signal_fn_name']
        c.candidate_type = parsed['candidate_type']
        c.category = parsed['category']
        c.timeframe = parsed['timeframe']
        c.default_params = parsed['default_params']
        c.llm_notes = parsed['notes']
        c.llm_model = parsed['model']
        c.error_log = f'sandbox: {verify["error"]}'
        db.session.commit()
        return {'ok': False, 'error': f'sandbox: {verify["error"]}', 'verify': verify, 'candidate': c.to_dict()}

    # ---- 成功 ----
    c.parsed_signal = parsed['signal_fn_source']
    c.signal_fn_name = parsed['signal_fn_name']
    c.candidate_type = parsed['candidate_type']
    c.category = parsed['category']
    c.timeframe = parsed['timeframe']
    c.default_params = parsed['default_params']
    c.llm_notes = parsed['notes']
    c.llm_model = parsed['model']
    c.status = 'translated'
    c.error_log = None
    db.session.commit()

    return {
        'ok': True,
        'candidate': c.to_dict(include_code=True),
        'verify': verify,
        'usage': parsed.get('usage'),
    }


def backtest_candidate(candidate_id: int, *, candle_limit: int = 2000, symbol: str | None = None) -> dict:
    """跑單一候選策略的回測。要求 status 為 'translated' 或 'qualified'（再跑一次）/ 'error'（重試）。

    流程：load_signal_fn → fetch K 線 → run_backtest(signal_fn=...) → 寫 BacktestResult
       → 依 Sharpe 標 qualified / translated。

    Symbol 解析優先級（Phase 12.39 修 — 之前硬編碼 BTC 導致 AVAX live 用 BTC 回測決策）：
      1. 顯式參數 symbol
      2. candidate.source_meta['symbol']（AI improve / generate 寫的目標 symbol）
      3. SystemConfig.default_backtest_symbol（user 當前 LIVE 主 symbol）
      4. 'BTC/USDT' last-resort fallback

    狀態流轉：(translated|qualified|error) → backtesting → qualified（Sharpe ≥ 1.5）/ translated（不夠）/ error
    """
    from app.services.exchange_service import fetch_ohlcv_history
    from app.services.backtest_engine import run_walkforward_backtest

    c = StrategyCandidate.query.get(candidate_id)
    if c is None:
        return {'ok': False, 'error': f'candidate {candidate_id} not found'}

    if c.status not in ('translated', 'qualified', 'error'):
        return {'ok': False, 'error': f'candidate status must be translated/qualified/error, got {c.status}'}

    if not c.parsed_signal or not c.signal_fn_name:
        return {'ok': False, 'error': 'candidate has no parsed_signal / signal_fn_name (run translate first)'}

    if symbol is None:
        meta_symbol = (c.source_meta or {}).get('symbol') if c.source_meta else None
        if meta_symbol:
            symbol = meta_symbol
        else:
            from app.services.config_service import get as cfg_get
            symbol = cfg_get('default_backtest_symbol', 'BTC/USDT')

    c.status = 'backtesting'
    c.error_log = None
    db.session.commit()

    # 載入沙箱中的 callable
    try:
        signal_fn = load_signal_fn(c.parsed_signal, c.signal_fn_name)
    except Exception as e:
        c.status = 'error'
        c.error_log = f'load_signal_fn: {type(e).__name__}: {e}'
        db.session.commit()
        return {'ok': False, 'error': c.error_log, 'candidate': c.to_dict()}

    timeframe = c.timeframe or '4h'
    candles = fetch_ohlcv_history(symbol, timeframe, total_limit=candle_limit)
    if not candles:
        c.status = 'error'
        c.error_log = 'no candles fetched'
        db.session.commit()
        return {'ok': False, 'error': c.error_log, 'candidate': c.to_dict()}

    # Phase 5.4: walk-forward 取代單段回測
    try:
        # Phase 9.5: 帶上 cfg 的 slippage/fee
        from app.services.config_service import get_config
        cfg = get_config()
        wf = run_walkforward_backtest(
            c.candidate_type or 'candidate',
            c.default_params or {},
            candles,
            timeframe=timeframe,
            signal_fn=signal_fn,
            slippage_pct=cfg.get('backtest_slippage_pct', 0.05),
            fee_pct=cfg.get('backtest_fee_pct', 0.05),
        )
    except Exception as e:
        c.status = 'error'
        c.error_log = f'walkforward: {type(e).__name__}: {e}'
        db.session.commit()
        return {'ok': False, 'error': c.error_log, 'candidate': c.to_dict()}

    if wf.get('status') == 'error':
        c.status = 'error'
        c.error_log = f'walkforward: {wf.get("error_message", "unknown")}'
        db.session.commit()
        return {'ok': False, 'error': c.error_log, 'candidate': c.to_dict()}

    result = wf['full']
    if result.get('status') == 'error':
        c.status = 'error'
        c.error_log = f'backtest full: {result.get("error_message", "unknown")}'
        db.session.commit()
        return {'ok': False, 'error': c.error_log, 'candidate': c.to_dict()}

    # 寫 BacktestResult — strategy_id=NULL 表示候選回測（未 promote），
    # 由 strategy_candidates.backtest_result_id 反向關聯。
    bt = BacktestResult(
        strategy_id=None,
        strategy_type=c.candidate_type or 'candidate',
        params_snapshot=c.default_params or {},
        symbol=symbol,
        timeframe=timeframe,
        leverage=15.0,
        position_size_usdt=10.0,
        stop_loss_pct=5.0,
        take_profit_pct=8.0,
        initial_capital=100.0,
        period_start=result['period_start'],
        period_end=result['period_end'],
        candle_count=result['candle_count'],
        total_trades=result['total_trades'],
        winning_trades=result['winning_trades'],
        losing_trades=result['losing_trades'],
        win_rate=result['win_rate'],
        total_pnl=result['total_pnl'],
        avg_pnl=result['avg_pnl'],
        avg_win=result['avg_win'],
        avg_loss=result['avg_loss'],
        profit_factor=result['profit_factor'],
        max_drawdown=result['max_drawdown'],
        max_drawdown_pct=result['max_drawdown_pct'],
        sharpe_ratio=result['sharpe_ratio'],
        final_equity=result['final_equity'],
        annual_return_pct=result['annual_return_pct'],
        equity_curve=result['equity_curve'],
        trades_json=result['trades'],
        walkforward_json=wf,
        duration_ms=result['duration_ms'],
        status='completed',
    )
    db.session.add(bt)
    db.session.flush()   # 取 id

    c.backtest_result_id = bt.id

    # Phase 5.4: qualified 門檻 = IS sharpe ≥ 1.5 AND OOS sharpe ≥ 0.8 AND decay ≤ 70%
    is_res = wf.get('in_sample') or {}
    oos_res = wf.get('out_sample') or {}
    is_sh = is_res.get('sharpe_ratio')
    oos_sh = oos_res.get('sharpe_ratio')
    decay = wf.get('decay_pct')

    qualified_reasons = []
    is_trades = is_res.get('total_trades') or 0
    oos_trades = oos_res.get('total_trades') or 0
    if is_trades < QUALIFIED_MIN_TRADES_PER_SIDE:
        qualified_reasons.append(f'IS trades={is_trades} < {QUALIFIED_MIN_TRADES_PER_SIDE} (Sharpe 樣本不足)')
    if oos_trades < QUALIFIED_MIN_TRADES_PER_SIDE:
        qualified_reasons.append(f'OOS trades={oos_trades} < {QUALIFIED_MIN_TRADES_PER_SIDE} (Sharpe 樣本不足)')
    if is_sh is None or is_sh < QUALIFIED_SHARPE_IS:
        qualified_reasons.append(f'IS sharpe={is_sh} < {QUALIFIED_SHARPE_IS}')
    if oos_sh is None or oos_sh < QUALIFIED_SHARPE_OOS:
        qualified_reasons.append(f'OOS sharpe={oos_sh} < {QUALIFIED_SHARPE_OOS}')
    if decay is not None and decay > QUALIFIED_MAX_DECAY_PCT:
        qualified_reasons.append(f'OOS decay={decay}% > {QUALIFIED_MAX_DECAY_PCT}% (suspected overfit)')

    if not qualified_reasons:
        c.status = 'qualified'
        c.error_log = None
    else:
        c.status = 'translated'
        c.error_log = 'not qualified: ' + '; '.join(qualified_reasons)
    db.session.commit()

    return {
        'ok': True,
        'candidate': c.to_dict(include_code=False),
        'backtest': bt.to_dict(include_curve=False),
        'qualified': c.status == 'qualified',
        'walkforward': {
            'is_sharpe': is_sh, 'oos_sharpe': oos_sh, 'decay_pct': decay,
            'is_trades': is_res.get('total_trades'), 'oos_trades': oos_res.get('total_trades'),
        },
        'qualified_reasons': qualified_reasons,
    }


def promote_candidate(candidate_id: int, *, name: str | None = None, symbol: str = 'BTC/USDT',
                      owner_user_id: int | None = None) -> dict:
    """把 qualified candidate 推上線 — 建立 Strategy 條目 + 註冊到 strategy_engine。

    狀態流轉：qualified → promoted
    回傳：{ok, strategy: {...}, candidate: {...}} 或 {ok: False, error}

    Phase 11.1.3: owner_user_id 指定新策略歸屬。預設 1 (admin) 給 Celery / 內部腳本用。
    """
    from app.models import Strategy
    from app.services.strategy_engine import register_candidate_signal
    from app.services.candidate_sandbox import load_signal_fn

    c = StrategyCandidate.query.get(candidate_id)
    if c is None:
        return {'ok': False, 'error': f'candidate {candidate_id} not found'}
    if c.status != 'qualified':
        return {'ok': False, 'error': f'candidate status must be qualified, got {c.status}'}
    if not c.candidate_type or not c.parsed_signal or not c.signal_fn_name:
        return {'ok': False, 'error': 'candidate missing candidate_type / parsed_signal / signal_fn_name'}

    # candidate_type 加 cand_ 前綴避免和原 strategy_engine 靜態 map 衝突
    if c.candidate_type.startswith('cand_'):
        promoted_type = c.candidate_type
    else:
        promoted_type = f'cand_{c.candidate_type}'

    # 唯一性檢查 — 同 type 已存在就拒絕
    existing = Strategy.query.filter_by(type=promoted_type).first()
    if existing:
        return {'ok': False, 'error': f'strategy type "{promoted_type}" already exists (id={existing.id})'}

    # 註冊到 in-memory 注冊表（這個 worker 即刻可用；其他 worker 會在 lookup 時冷啟動）
    try:
        signal_fn = load_signal_fn(c.parsed_signal, c.signal_fn_name)
        register_candidate_signal(promoted_type, signal_fn)
    except Exception as e:
        return {'ok': False, 'error': f'load_signal_fn before promote: {type(e).__name__}: {e}'}

    # Phase 14k-5/13: exchange 选择优先级:
    # 1) candidate.source_meta.target_exchange (AI 推荐时已指定 — team 多绑场景)
    # 2) primary_exchange(owner_uid) (普通 user 兜底)
    try:
        from app.services.exchange_binding import primary_exchange
        _owner_uid = owner_user_id if owner_user_id is not None else 1
        _cand_meta = c.source_meta or {}
        _exchange = _cand_meta.get('target_exchange') or primary_exchange(_owner_uid)
    except Exception:
        _exchange = 'okx'

    # 建立 Strategy 條目
    from app.services.strategy_naming import format_strategy_name
    strategy = Strategy(
        name=name or format_strategy_name(c, symbol=symbol),
        type=promoted_type,
        category=c.category or 'swing',
        params=c.default_params or {},
        symbol=symbol,
        timeframe=c.timeframe or '4h',
        exchange=_exchange,                 # Phase 14k-5
        status='stopped',   # 預設停用，由 user 在 UI 啟用
        max_positions=1,
        max_daily_loss=10.0,
        candidate_id=c.id,
        user_id=owner_user_id if owner_user_id is not None else 1,
    )
    db.session.add(strategy)
    db.session.flush()   # 拿 strategy.id

    c.status = 'promoted'
    c.promoted_strategy_id = strategy.id
    c.error_log = None
    db.session.commit()

    # Phase 14k-32 修: promote 后立刻 async 拉 K 线, 避免新策略首小时跑信号撞 K线不足(0)
    try:
        from app.tasks.strategy_tasks import fetch_symbol_ohlcv
        fetch_symbol_ohlcv.apply_async(args=[strategy.symbol, strategy.timeframe], countdown=5)
    except Exception as e:
        print(f'[promote] fetch_symbol_ohlcv async dispatch failed: {e}')

    return {
        'ok': True,
        'strategy': strategy.to_dict(),
        'candidate': c.to_dict(include_code=False),
        'note': f'strategy created with type="{promoted_type}", status=stopped. 啟用前建議手動 review params。',
    }


def backtest_all_translated(max_count: int | None = None) -> dict:
    """批次跑所有 status='translated' 的候選回測。"""
    q = StrategyCandidate.query.filter_by(status='translated')
    if max_count:
        q = q.limit(max_count)
    items = q.all()
    results = []
    for c in items:
        try:
            r = backtest_candidate(c.id)
            results.append({
                'id': c.id, 'name': c.source_name, 'ok': r['ok'],
                'qualified': r.get('qualified', False),
                'sharpe': r.get('backtest', {}).get('sharpe_ratio') if r.get('ok') else None,
                'error': r.get('error') if not r.get('ok') else None,
            })
        except Exception as e:
            results.append({'id': c.id, 'name': c.source_name, 'ok': False, 'error': f'{type(e).__name__}: {e}'})
    qualified = sum(1 for r in results if r.get('qualified'))
    return {'count': len(results), 'qualified': qualified, 'results': results}
