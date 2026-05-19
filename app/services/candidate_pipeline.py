"""候選策略 pipeline orchestrator — Phase 4

把單一 StrategyCandidate 推一步：translate → sandbox verify → 標記狀態。
（自動回測在 Phase 4.4 的 backtest_pipeline 處理。）
"""
from __future__ import annotations

from app.extensions import db
from app.models import StrategyCandidate, BacktestResult
from app.services.candidate_sandbox import verify_signal_fn, load_signal_fn
from app.services.llm_translator import translate, LLMTranslatorError


# 候選策略回測通過門檻 — Sharpe ≥ 此值才標 'qualified'
QUALIFIED_SHARPE = 1.5


def translate_and_verify(candidate_id: int) -> dict:
    """LLM 翻譯 + 沙箱驗證一個 candidate。回傳更新後的 dict。

    狀態流轉：pending → translating → translated（成功）/ error（失敗）
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


def backtest_candidate(candidate_id: int, *, candle_limit: int = 2000, symbol: str = 'BTC/USDT') -> dict:
    """跑單一候選策略的回測。要求 status 為 'translated' 或 'qualified'（再跑一次）/ 'error'（重試）。

    流程：load_signal_fn → fetch K 線 → run_backtest(signal_fn=...) → 寫 BacktestResult
       → 依 Sharpe 標 qualified / translated。

    狀態流轉：(translated|qualified|error) → backtesting → qualified（Sharpe ≥ 1.5）/ translated（不夠）/ error
    """
    from app.services.exchange_service import fetch_ohlcv_history
    from app.services.backtest_engine import run_backtest

    c = StrategyCandidate.query.get(candidate_id)
    if c is None:
        return {'ok': False, 'error': f'candidate {candidate_id} not found'}

    if c.status not in ('translated', 'qualified', 'error'):
        return {'ok': False, 'error': f'candidate status must be translated/qualified/error, got {c.status}'}

    if not c.parsed_signal or not c.signal_fn_name:
        return {'ok': False, 'error': 'candidate has no parsed_signal / signal_fn_name (run translate first)'}

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

    try:
        result = run_backtest(
            c.candidate_type or 'candidate',
            c.default_params or {},
            candles,
            timeframe=timeframe,
            signal_fn=signal_fn,
        )
    except Exception as e:
        c.status = 'error'
        c.error_log = f'run_backtest: {type(e).__name__}: {e}'
        db.session.commit()
        return {'ok': False, 'error': c.error_log, 'candidate': c.to_dict()}

    if result.get('status') == 'error':
        c.status = 'error'
        c.error_log = f'backtest: {result.get("error_message", "unknown")}'
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
        position_size_usdt=50.0,
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
        duration_ms=result['duration_ms'],
        status='completed',
    )
    db.session.add(bt)
    db.session.flush()   # 取 id

    c.backtest_result_id = bt.id
    sharpe = result.get('sharpe_ratio')
    if sharpe is not None and sharpe >= QUALIFIED_SHARPE:
        c.status = 'qualified'
    else:
        c.status = 'translated'   # 維持可再 backtest / 手動 promote
    c.error_log = None
    db.session.commit()

    return {
        'ok': True,
        'candidate': c.to_dict(include_code=False),
        'backtest': bt.to_dict(include_curve=False),
        'qualified': c.status == 'qualified',
    }


def promote_candidate(candidate_id: int, *, name: str | None = None, symbol: str = 'BTC/USDT') -> dict:
    """把 qualified candidate 推上線 — 建立 Strategy 條目 + 註冊到 strategy_engine。

    狀態流轉：qualified → promoted
    回傳：{ok, strategy: {...}, candidate: {...}} 或 {ok: False, error}
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

    # 建立 Strategy 條目
    strategy = Strategy(
        name=name or f'{c.source_name or "candidate"} (#{c.id})',
        type=promoted_type,
        category=c.category or 'swing',
        params=c.default_params or {},
        symbol=symbol,
        timeframe=c.timeframe or '4h',
        status='stopped',   # 預設停用，由 user 在 UI 啟用
        max_positions=1,
        max_daily_loss=10.0,
        candidate_id=c.id,
    )
    db.session.add(strategy)
    db.session.flush()   # 拿 strategy.id

    c.status = 'promoted'
    c.promoted_strategy_id = strategy.id
    c.error_log = None
    db.session.commit()

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
