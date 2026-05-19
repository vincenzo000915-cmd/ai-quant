"""Celery 定時任務 — 模擬盤模式（不下真單）"""
import random
import time
from datetime import datetime
from app.extensions import celery_app, db
from app.models import Strategy, Position, Trade, Order, Candle
from app.services.exchange_service import get_ticker
from app.services.strategy_engine import get_signal, get_candle_df

# ===== 模擬盤設定 =====
SIMULATED_BALANCE = 100.0       # 模擬本金 $100
LEVERAGE = 15                   # 15x 槓桿
TRADE_SIZE_USDT = 10.0          # 每次下單 $10（$100 本金切 10 份，15x 槓桿 = $150 名義倉位/筆）
STOP_LOSS_PCT = 5.0             # 5% 止損
TAKE_PROFIT_PCT = 8.0           # 8% 止盈


def _simulated_order(symbol, side, amount_usdt, price):
    """模擬下單（不發送到交易所）"""
    return {
        'id': f'sim_{int(time.time()*1000)}_{random.randint(1000,9999)}',
        'symbol': symbol,
        'side': side,
        'type': 'market',
        'amount': amount_usdt / price,  # 換算為BTC數量
        'price': price,
        'cost': amount_usdt,
        'fee': {'cost': amount_usdt * 0.001, 'currency': 'USDT'},  # 0.1% 手續費
        'status': 'closed',
        'simulated': True,
    }


@celery_app.task
def fetch_market_data():
    """定時獲取市場數據（每小時執行）"""
    strategies = Strategy.query.filter_by(status='running').all()
    symbols = set((s.symbol, s.timeframe) for s in strategies)

    for symbol, timeframe in symbols:
        try:
            from app.services.exchange_service import fetch_ohlcv
            fetch_ohlcv(symbol, timeframe, limit=500)
        except Exception as e:
            print(f'[fetch] {symbol} {timeframe} 失敗: {e}')
    return f'已更新 {len(symbols)} 組K線'


@celery_app.task
def run_strategy_signals(strategy_id=None):
    """執行策略信號計算 — 波段/長線（4h）"""
    return _run_signals(strategy_id, category_filter=None)


@celery_app.task
def run_strategy_signals_short():
    """短線策略（1h）"""
    return _run_signals(None, category_filter='short')


@celery_app.task
def run_strategy_signals_ultra():
    """極短策略（15m）"""
    return _run_signals(None, category_filter='ultra')


def _run_signals(strategy_id=None, category_filter=None):
    """執行策略信號計算（模擬盤模式）"""
    if strategy_id:
        strategies = Strategy.query.filter_by(id=strategy_id, status='running').all()
    elif category_filter:
        strategies = Strategy.query.filter_by(status='running', category=category_filter).all()
    else:
        strategies = Strategy.query.filter_by(status='running').filter(
            Strategy.category.in_(['swing', 'long'])
        ).all()

    if not strategies:
        return '無運行中的策略'

    results = []
    for s in strategies:
        try:
            # 取得K線
            candles = Candle.query.filter_by(
                symbol=s.symbol, timeframe=s.timeframe
            ).order_by(Candle.timestamp.asc()).all()

            if len(candles) < 30:
                results.append(f'{s.name}: K線不足({len(candles)})')
                continue

            df = get_candle_df([c.to_dict() for c in candles])
            signal = get_signal(s.type, df, s.params)

            if signal == 'hold':
                results.append(f'{s.name}: 無信號')
                continue

            # 取得持倉狀態
            position = Position.query.filter_by(
                strategy_id=s.id, status='open'
            ).first()

            if signal in ('buy', 'long') and position:
                results.append(f'{s.name}: 已有持倉，跳過信號')
                continue

            if signal in ('sell', 'close') and not position:
                results.append(f'{s.name}: 無持倉，跳過信號')
                continue

            # 獲取當前價格
            ticker = get_ticker(s.symbol)
            price = ticker['price']

            if signal in ('buy', 'long'):
                # 計算倉位：$50 USDT / price = BTC數量
                amount_btc = TRADE_SIZE_USDT / price
                amount_btc = round(amount_btc, 6)
                
                # 名義倉位價值
                notional = amount_btc * price * LEVERAGE

                order = _simulated_order(s.symbol, 'buy', TRADE_SIZE_USDT, price)
                
                pos = Position(
                    strategy_id=s.id,
                    symbol=s.symbol,
                    side='long',
                    size=amount_btc,
                    entry_price=price,
                    current_price=price,
                    status='open',
                )
                db.session.add(pos)
                db.session.commit()
                results.append(
                    f'✅ {s.name}: 模擬買入 {amount_btc} BTC @ ${price:.1f} '
                    f'(本金${TRADE_SIZE_USDT:.0f}, 槓桿{LEVERAGE}x, '
                    f'名義${notional:.0f})'
                )

            elif signal in ('sell', 'close') and position:
                # 計算PnL
                pnl_raw = (price - position.entry_price) * position.size
                pnl_leveraged = pnl_raw * LEVERAGE
                pnl_pct = ((price - position.entry_price) / position.entry_price) * 100 * LEVERAGE

                order = _simulated_order(s.symbol, 'sell', position.size * price, price)
                
                trade = Trade(
                    position_id=position.id,
                    strategy_id=s.id,
                    symbol=s.symbol,
                    side='long',
                    entry_price=position.entry_price,
                    exit_price=price,
                    quantity=position.size,
                    pnl=pnl_leveraged,
                    pnl_percent=pnl_pct,
                    entry_time=position.opened_at,
                    exit_time=datetime.utcnow(),
                    reason='signal',
                )
                position.status = 'closed'
                position.closed_at = datetime.utcnow()
                position.realized_pnl = pnl_leveraged
                db.session.add(trade)
                db.session.commit()
                results.append(
                    f'✅ {s.name}: 平倉 @ ${price:.1f} '
                    f'PnL=${pnl_leveraged:.2f} ({pnl_pct:+.2f}%)'
                )

        except Exception as e:
            results.append(f'{s.name}: 錯誤 - {e}')
            db.session.rollback()

    return ' | '.join(results)


@celery_app.task
def update_positions():
    """更新持倉當前價格和浮動盈虧（含槓桿）"""
    positions = Position.query.filter_by(status='open').all()
    for pos in positions:
        try:
            ticker = get_ticker(pos.symbol)
            pos.current_price = ticker['price']
            raw_pnl = (ticker['price'] - pos.entry_price) * pos.size
            pos.unrealized_pnl = raw_pnl * LEVERAGE
        except Exception as e:
            print(f'[update] 持倉 {pos.id} 更新失敗: {e}')
    db.session.commit()
    return f'已更新 {len(positions)} 個持倉'


@celery_app.task
def check_stop_loss():
    """檢查止損止盈（含槓桿）"""
    positions = Position.query.filter_by(status='open').all()
    triggered = []
    for pos in positions:
        try:
            ticker = get_ticker(pos.symbol)
            current = ticker['price']
            raw_pnl_pct = ((current - pos.entry_price) / pos.entry_price) * 100
            pnl_pct = raw_pnl_pct * LEVERAGE

            if pnl_pct <= -STOP_LOSS_PCT:
                order = _simulated_order(pos.symbol, 'sell', pos.size * current, current)
                pnl = raw_pnl_pct * pos.size * pos.entry_price * LEVERAGE / 100
                trade = Trade(
                    position_id=pos.id,
                    strategy_id=pos.strategy_id,
                    symbol=pos.symbol,
                    side='long',
                    entry_price=pos.entry_price,
                    exit_price=current,
                    quantity=pos.size,
                    pnl=pnl,
                    pnl_percent=pnl_pct,
                    entry_time=pos.opened_at,
                    exit_time=datetime.utcnow(),
                    reason='stop_loss',
                )
                pos.status = 'closed'
                pos.closed_at = datetime.utcnow()
                pos.realized_pnl = pnl
                db.session.add(trade)
                db.session.commit()
                triggered.append(f'{pos.symbol} 止損 @ ${current:.1f} ({pnl_pct:.1f}%)')

            elif pnl_pct >= TAKE_PROFIT_PCT:
                order = _simulated_order(pos.symbol, 'sell', pos.size * current, current)
                pnl = raw_pnl_pct * pos.size * pos.entry_price * LEVERAGE / 100
                trade = Trade(
                    position_id=pos.id,
                    strategy_id=pos.strategy_id,
                    symbol=pos.symbol,
                    side='long',
                    entry_price=pos.entry_price,
                    exit_price=current,
                    quantity=pos.size,
                    pnl=pnl,
                    pnl_percent=pnl_pct,
                    entry_time=pos.opened_at,
                    exit_time=datetime.utcnow(),
                    reason='take_profit',
                )
                pos.status = 'closed'
                pos.closed_at = datetime.utcnow()
                pos.realized_pnl = pnl
                db.session.add(trade)
                db.session.commit()
                triggered.append(f'{pos.symbol} 止盈 @ ${current:.1f} ({pnl_pct:.1f}%)')

        except Exception as e:
            print(f'[sl] 檢查失敗: {e}')

    return f'觸發 {len(triggered)} 個' if triggered else '無觸發'


# ===== Phase 5.3: 策略健康監控 / 自動退役 =====

# 退役門檻（從 candidate_pipeline 借同一套）
RETIRE_SHARPE_FULL = 0.3       # 全段 Sharpe 跌破這個 → 退役
RETIRE_SHARPE_OOS = 0.0        # OOS Sharpe 跌破 0 → 真的不行了
RETIRE_MIN_TRADES = 8          # 樣本不足就不退役（避免短期噪音誤判）


@celery_app.task
def monitor_strategy_health():
    """每日跑 — 對每個 running 策略做新 walkforward 回測，跌穿門檻就自動退役。

    退役 = status='retired' + retired_at + retire_reason，
    跟 user 手動 'stopped' 區分。Position 不動（讓 SL/TP 自然觸發）。
    """
    from datetime import datetime
    from app.services.exchange_service import fetch_ohlcv_history
    from app.services.backtest_engine import run_walkforward_backtest
    from app.services.strategy_engine import get_signal
    from app.services.candidate_sandbox import load_signal_fn
    from app.models import StrategyCandidate, BacktestResult

    running = Strategy.query.filter_by(status='running').all()
    if not running:
        return 'no running strategies'

    actions = []
    for s in running:
        try:
            candles = fetch_ohlcv_history(s.symbol, s.timeframe, total_limit=2000)
            if len(candles) < 200:
                actions.append(f'{s.name}: 跳過 (K線不足 {len(candles)})')
                continue

            # candidate-backed 策略要動態載入 signal_fn
            signal_fn = None
            if s.candidate_id:
                c = StrategyCandidate.query.get(s.candidate_id)
                if c and c.parsed_signal and c.signal_fn_name:
                    try:
                        signal_fn = load_signal_fn(c.parsed_signal, c.signal_fn_name)
                    except Exception as e:
                        actions.append(f'{s.name}: 跳過 (signal_fn 載入失敗: {e})')
                        continue

            wf = run_walkforward_backtest(
                s.type, s.params or {}, candles,
                timeframe=s.timeframe, signal_fn=signal_fn,
            )

            if wf.get('status') == 'error':
                actions.append(f'{s.name}: 回測錯誤 {wf.get("error_message")}')
                continue

            full = wf['full']
            oos = wf.get('out_sample') or {}
            full_sh = full.get('sharpe_ratio')
            oos_sh = oos.get('sharpe_ratio')
            total_trades = full.get('total_trades', 0)

            # 寫 BacktestResult 留檔（不論退不退）
            bt = BacktestResult(
                strategy_id=s.id, strategy_type=s.type,
                params_snapshot=s.params or {}, symbol=s.symbol, timeframe=s.timeframe,
                leverage=15.0, position_size_usdt=10.0,
                stop_loss_pct=5.0, take_profit_pct=8.0, initial_capital=100.0,
                period_start=full['period_start'], period_end=full['period_end'],
                candle_count=full['candle_count'],
                total_trades=full['total_trades'], winning_trades=full['winning_trades'],
                losing_trades=full['losing_trades'], win_rate=full['win_rate'],
                total_pnl=full['total_pnl'], avg_pnl=full['avg_pnl'],
                avg_win=full['avg_win'], avg_loss=full['avg_loss'],
                profit_factor=full['profit_factor'],
                max_drawdown=full['max_drawdown'], max_drawdown_pct=full['max_drawdown_pct'],
                sharpe_ratio=full_sh, final_equity=full['final_equity'],
                annual_return_pct=full['annual_return_pct'],
                equity_curve=full['equity_curve'], trades_json=full['trades'],
                walkforward_json=wf, duration_ms=full['duration_ms'],
                status='completed',
            )
            db.session.add(bt)

            # 退役判斷
            retire_reasons = []
            if total_trades < RETIRE_MIN_TRADES:
                # 樣本太少，不主動退役但記錄一下
                pass
            else:
                if full_sh is not None and full_sh < RETIRE_SHARPE_FULL:
                    retire_reasons.append(f'full Sharpe {full_sh:.2f} < {RETIRE_SHARPE_FULL}')
                if oos_sh is not None and oos_sh < RETIRE_SHARPE_OOS:
                    retire_reasons.append(f'OOS Sharpe {oos_sh:.2f} < {RETIRE_SHARPE_OOS}')

            if retire_reasons:
                s.status = 'retired'
                s.retired_at = datetime.utcnow()
                s.retire_reason = f'auto-retire @ {datetime.utcnow().isoformat(timespec="seconds")}: ' + '; '.join(retire_reasons)
                actions.append(f'🔴 {s.name} retired: {", ".join(retire_reasons)}')
            else:
                actions.append(f'✅ {s.name} OK (full Sharpe={full_sh}, OOS={oos_sh}, trades={total_trades})')

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            actions.append(f'{s.name}: EXCEPTION {type(e).__name__}: {e}')

    return ' | '.join(actions)


# ===== Phase 5.2: 候選池自動回測 =====

@celery_app.task
def auto_backtest_translated_candidates(max_count: int = 20):
    """每小時跑 — 把 status='translated' 的候選自動拉去 walk-forward 回測。
    通過門檻變 qualified，沒通過繼續 translated 等下次（如果 user 修了 params）。
    """
    from app.services.candidate_pipeline import backtest_all_translated
    result = backtest_all_translated(max_count=max_count)
    return f'auto-backtest: {result["count"]} 個跑完，{result["qualified"]} 個合格'


# ===== Phase 5.1: 自動爬蟲 + 翻譯 =====

@celery_app.task
def auto_crawl_github(max_files_per_repo: int = 10):
    """每日跑 GitHub 爬蟲，把新策略灌進候選池（status=pending，dedup by source_url）"""
    from app.services.crawlers.github import crawl_all
    try:
        result = crawl_all(max_files_per_repo=max_files_per_repo)
        t = result['totals']
        return f'crawl: 偵測 {t["detected"]} 新增 {t["inserted"]} 略過 {t["skipped"]} 錯誤 {t["errors"]}'
    except Exception as e:
        return f'crawl 失敗: {type(e).__name__}: {e}'


@celery_app.task
def auto_translate_pending(max_count: int = 5):
    """容器內走 Anthropic SDK 翻譯 pending 候選 — 需要 ANTHROPIC_API_KEY。
    沒 key 就跳過、log 一行（user 應改用 host 端 translate_cli.py 跑 host cron）。
    """
    import os
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return 'auto-translate skipped: no ANTHROPIC_API_KEY in env. 改用 host 端 translate_cli.py + crontab'

    from app.models import StrategyCandidate
    from app.services.candidate_pipeline import translate_and_verify

    pending = StrategyCandidate.query.filter_by(status='pending').order_by(StrategyCandidate.id).limit(max_count).all()
    if not pending:
        return 'auto-translate: 無 pending 候選'

    ok = err = 0
    for c in pending:
        try:
            r = translate_and_verify(c.id)
            if r.get('ok'):
                ok += 1
            else:
                err += 1
        except Exception:
            err += 1
    return f'auto-translate: {ok} 成功 / {err} 失敗 (共 {len(pending)} 個)'
