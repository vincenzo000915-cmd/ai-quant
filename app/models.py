import datetime
from app.extensions import db


class Strategy(db.Model):
    """策略配置"""
    __tablename__ = 'strategies'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # ma_crossover / rsi / macd / bollinger / combo
    category = db.Column(db.String(10), default='swing')  # short(短線) / swing(波段) / long(長線)
    params = db.Column(db.JSON, default={})           # 策略參數
    symbol = db.Column(db.String(20), default='BTC/USDT')
    timeframe = db.Column(db.String(10), default='4h')
    status = db.Column(db.String(20), default='stopped')  # running / paused / stopped
    max_positions = db.Column(db.Integer, default=1)
    max_daily_loss = db.Column(db.Float, default=10.0)
    # Phase 4.6: 從候選池 promote 來的策略，連回 candidate 方便溯源
    candidate_id = db.Column(db.Integer, db.ForeignKey('strategy_candidates.id'), nullable=True)
    # Phase 5.3: 自動退役紀錄 — status='retired' 時填入
    retired_at = db.Column(db.DateTime, nullable=True)
    retire_reason = db.Column(db.Text, nullable=True)
    # Phase 10.6: 一鍵 fan-out — 同 template_group 的兄弟實例由同一個 source 衍生
    # 值 = source strategy id（自身也填，以便 GROUP BY 拿到完整家族）
    template_group = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.datetime.utcnow)

    orders = db.relationship('Order', backref='strategy', lazy='dynamic')
    positions = db.relationship('Position', backref='strategy', lazy='dynamic')
    trades = db.relationship('Trade', backref='strategy', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'category': self.category or 'swing',
            'params': self.params,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'active': self.status == 'running',
            'status': self.status,
            'exchange': 'OKX',
            'max_positions': self.max_positions,
            'max_daily_loss': self.max_daily_loss,
            'candidate_id': self.candidate_id,
            'retired_at': self.retired_at.isoformat() if self.retired_at else None,
            'retire_reason': self.retire_reason,
            'template_group': self.template_group,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Order(db.Model):
    """交易訂單"""
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id'))
    exchange = db.Column(db.String(20), default='binance')
    symbol = db.Column(db.String(20))
    side = db.Column(db.String(10))       # buy / sell
    type = db.Column(db.String(10))       # market / limit
    amount = db.Column(db.Float)
    price = db.Column(db.Float)
    status = db.Column(db.String(20), default='open')  # open / filled / cancelled / partial
    filled_amount = db.Column(db.Float, default=0)
    avg_price = db.Column(db.Float)
    order_id = db.Column(db.String(100))  # 交易所訂單ID
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'strategy_id': self.strategy_id,
            'symbol': self.symbol,
            'side': self.side,
            'type': self.type,
            'amount': self.amount,
            'price': self.price,
            'status': self.status,
            'filled_amount': self.filled_amount,
            'avg_price': self.avg_price,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Position(db.Model):
    """當前持倉"""
    __tablename__ = 'positions'

    id = db.Column(db.Integer, primary_key=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id'))
    symbol = db.Column(db.String(20))
    side = db.Column(db.String(10))       # long / short
    size = db.Column(db.Float)            # 持倉數量
    entry_price = db.Column(db.Float)
    current_price = db.Column(db.Float)
    unrealized_pnl = db.Column(db.Float, default=0)
    realized_pnl = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='open')  # open / closed
    # Phase 9.4: 開倉時計算好的絕對止損 / 止盈價（ATR mode 用）；NULL 表示走 flat % rule
    sl_price = db.Column(db.Float, nullable=True)
    tp_price = db.Column(db.Float, nullable=True)
    opened_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    closed_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'strategy_id': self.strategy_id,
            'symbol': self.symbol,
            'side': self.side,
            'size': self.size,
            'entry_price': self.entry_price,
            'current_price': self.current_price,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl,
            'status': self.status,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
        }


class Trade(db.Model):
    """已平倉交易紀錄"""
    __tablename__ = 'trades'

    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(db.Integer, db.ForeignKey('positions.id'))
    strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id'))
    symbol = db.Column(db.String(20))
    side = db.Column(db.String(10))
    entry_price = db.Column(db.Float)
    exit_price = db.Column(db.Float)
    quantity = db.Column(db.Float)
    pnl = db.Column(db.Float)
    pnl_percent = db.Column(db.Float)
    entry_time = db.Column(db.DateTime)
    exit_time = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    reason = db.Column(db.String(50))  # signal / stop_loss / take_profit

    def to_dict(self):
        return {
            'id': self.id,
            'strategy_id': self.strategy_id,
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'quantity': self.quantity,
            'pnl': self.pnl,
            'pnl_percent': self.pnl_percent,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'reason': self.reason,
        }


class BacktestResult(db.Model):
    """策略回測結果（真實歷史 K 線跑出來的）"""
    __tablename__ = 'backtest_results'

    id = db.Column(db.Integer, primary_key=True)
    # nullable: NULL 表示這是候選策略的回測（strategy 還沒 promote 進 strategies 表）
    strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id'), nullable=True)
    strategy_type = db.Column(db.String(50), nullable=False)
    params_snapshot = db.Column(db.JSON, default={})       # 跑回測時的參數快照
    symbol = db.Column(db.String(20), default='BTC/USDT')
    timeframe = db.Column(db.String(10), default='4h')

    # 回測設定
    leverage = db.Column(db.Float, default=15.0)
    position_size_usdt = db.Column(db.Float, default=10.0)
    stop_loss_pct = db.Column(db.Float, default=5.0)
    take_profit_pct = db.Column(db.Float, default=8.0)
    initial_capital = db.Column(db.Float, default=100.0)

    # 期間
    period_start = db.Column(db.BigInteger)                # K 線起始 timestamp
    period_end = db.Column(db.BigInteger)
    candle_count = db.Column(db.Integer)

    # 統計
    total_trades = db.Column(db.Integer, default=0)
    winning_trades = db.Column(db.Integer, default=0)
    losing_trades = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0)              # %
    total_pnl = db.Column(db.Float, default=0)             # 含槓桿後的累積 PnL
    avg_pnl = db.Column(db.Float, default=0)
    avg_win = db.Column(db.Float, default=0)
    avg_loss = db.Column(db.Float, default=0)
    profit_factor = db.Column(db.Float)                    # None 表示無虧損交易
    max_drawdown = db.Column(db.Float, default=0)          # 最大回撤金額
    max_drawdown_pct = db.Column(db.Float, default=0)      # %
    sharpe_ratio = db.Column(db.Float)
    final_equity = db.Column(db.Float, default=0)
    annual_return_pct = db.Column(db.Float, default=0)

    # 詳細資料（JSON 存）
    equity_curve = db.Column(db.JSON, default=[])          # [{ ts, equity, drawdown }]
    trades_json = db.Column(db.JSON, default=[])           # [{ entry, exit, pnl, reason, side }]
    # Phase 5.4: walk-forward 驗證結果 — {full, in_sample, out_sample, is_ratio, split_ts, decay_pct}
    walkforward_json = db.Column(db.JSON, default={})

    # 元資料
    duration_ms = db.Column(db.Integer)                    # 跑回測耗時
    status = db.Column(db.String(20), default='completed') # completed / error / running
    error_message = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def to_dict(self, include_curve=False):
        d = {
            'id': self.id,
            'strategy_id': self.strategy_id,
            'strategy_type': self.strategy_type,
            'params_snapshot': self.params_snapshot,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'leverage': self.leverage,
            'position_size_usdt': self.position_size_usdt,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'initial_capital': self.initial_capital,
            'period_start': self.period_start,
            'period_end': self.period_end,
            'candle_count': self.candle_count,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'total_pnl': self.total_pnl,
            'avg_pnl': self.avg_pnl,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            'profit_factor': self.profit_factor,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'sharpe_ratio': self.sharpe_ratio,
            'final_equity': self.final_equity,
            'annual_return_pct': self.annual_return_pct,
            'duration_ms': self.duration_ms,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        # walkforward 摘要永遠回傳（小，但有 IS/OOS sharpe）；明細只在 include_curve 時回
        wf = self.walkforward_json or {}
        if wf:
            d['walkforward'] = {
                'is_ratio': wf.get('is_ratio'),
                'split_ts': wf.get('split_ts'),
                'decay_pct': wf.get('decay_pct'),
                'is_sharpe': (wf.get('in_sample') or {}).get('sharpe_ratio'),
                'oos_sharpe': (wf.get('out_sample') or {}).get('sharpe_ratio'),
                'is_trades': (wf.get('in_sample') or {}).get('total_trades'),
                'oos_trades': (wf.get('out_sample') or {}).get('total_trades'),
                'is_ar': (wf.get('in_sample') or {}).get('annual_return_pct'),
                'oos_ar': (wf.get('out_sample') or {}).get('annual_return_pct'),
                'is_maxdd': (wf.get('in_sample') or {}).get('max_drawdown_pct'),
                'oos_maxdd': (wf.get('out_sample') or {}).get('max_drawdown_pct'),
            }
        if include_curve:
            d['equity_curve'] = self.equity_curve or []
            d['trades_json'] = self.trades_json or []
            if wf:
                d['walkforward_full'] = wf
        return d


class SystemConfig(db.Model):
    """單一行設定 (id=1) — paper/live 模式、本金、倉位、槓桿、SL/TP 等。

    用 row pattern 而不是 key/value，因為欄位有強型別、好查、好寫 migration。
    """
    __tablename__ = 'system_config'

    id = db.Column(db.Integer, primary_key=True)
    trading_mode = db.Column(db.String(10), default='paper')  # 'paper' | 'live'（live 暫鎖）
    capital_usdt = db.Column(db.Float, default=100.0)         # 模擬本金 / 真實本金
    leverage = db.Column(db.Float, default=15.0)
    trade_size_usdt = db.Column(db.Float, default=10.0)       # 每筆下單金額
    stop_loss_pct = db.Column(db.Float, default=5.0)          # 槓桿後的 PnL %
    take_profit_pct = db.Column(db.Float, default=8.0)
    max_daily_loss_usdt = db.Column(db.Float, default=10.0)

    # Phase 6.1: 全局風控狀態。halted=True 時拒絕所有新開倉
    halted = db.Column(db.Boolean, default=False)
    halt_reason = db.Column(db.Text, nullable=True)
    halted_at = db.Column(db.DateTime, nullable=True)

    # Phase 9.3: 動態倉位設定
    sizing_mode = db.Column(db.String(20), default='flat')   # 'flat' | 'vol_target' | 'sharpe_weighted'
    target_vol_pct = db.Column(db.Float, default=1.5)        # 目標日波動率 % (vol_target 用)
    sizing_min_mult = db.Column(db.Float, default=0.3)
    sizing_max_mult = db.Column(db.Float, default=3.0)
    # Phase 9.4: 止損模式
    sl_mode = db.Column(db.String(20), default='flat_pct')   # 'flat_pct' | 'atr'
    atr_period = db.Column(db.Integer, default=14)
    atr_sl_mult = db.Column(db.Float, default=2.0)           # SL 距離 = k × ATR
    atr_tp_mult = db.Column(db.Float, default=3.0)           # TP 距離 = k × ATR

    # Phase 9.5: 回測滑點 + 手續費（live 不用，OKX 自動扣）
    backtest_slippage_pct = db.Column(db.Float, default=0.05)   # 每側 0.05% 估算市價單滑點
    backtest_fee_pct = db.Column(db.Float, default=0.05)        # OKX SWAP taker = 0.05%/side

    # Phase 10.8: 智能托管 — auto-apply advisor recommendations
    auto_apply_enabled = db.Column(db.Boolean, default=False)
    # 允許自動套用的 action 類型清單（subset of: apply_params / pause / retire / fan_out）
    auto_apply_actions = db.Column(db.JSON, default=list)
    auto_apply_max_per_day = db.Column(db.Integer, default=5)
    # Phase 10.9: fan_out 兄弟跑完回測且 OOS Sharpe >= 阈值才自動 start
    fan_out_auto_start = db.Column(db.Boolean, default=False)
    fan_out_min_oos_sharpe = db.Column(db.Float, default=1.0)
    # Phase 10.10: 自動 promote 合格候選成 strategy
    auto_promote_max_per_day = db.Column(db.Integer, default=2)
    auto_promote_min_oos_sharpe = db.Column(db.Float, default=1.5)

    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            'trading_mode': self.trading_mode,
            'capital_usdt': self.capital_usdt,
            'leverage': self.leverage,
            'trade_size_usdt': self.trade_size_usdt,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'max_daily_loss_usdt': self.max_daily_loss_usdt,
            'halted': self.halted,
            'halt_reason': self.halt_reason,
            'halted_at': self.halted_at.isoformat() if self.halted_at else None,
            'sizing_mode': self.sizing_mode,
            'target_vol_pct': self.target_vol_pct,
            'sizing_min_mult': self.sizing_min_mult,
            'sizing_max_mult': self.sizing_max_mult,
            'sl_mode': self.sl_mode,
            'atr_period': self.atr_period,
            'atr_sl_mult': self.atr_sl_mult,
            'atr_tp_mult': self.atr_tp_mult,
            'backtest_slippage_pct': self.backtest_slippage_pct,
            'backtest_fee_pct': self.backtest_fee_pct,
            'auto_apply_enabled': bool(self.auto_apply_enabled),
            'auto_apply_actions': list(self.auto_apply_actions or []),
            'auto_apply_max_per_day': self.auto_apply_max_per_day or 5,
            'fan_out_auto_start': bool(self.fan_out_auto_start),
            'fan_out_min_oos_sharpe': self.fan_out_min_oos_sharpe or 1.0,
            'auto_promote_max_per_day': self.auto_promote_max_per_day or 2,
            'auto_promote_min_oos_sharpe': self.auto_promote_min_oos_sharpe or 1.5,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class AuditLog(db.Model):
    """Phase 8.4: 审计日志 — 任何 mutating 事件都記一條"""
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), nullable=False, index=True)
    # config_change | halt | unhalt | kill_switch | promote | reject | retire |
    # candidate_translate | candidate_backtest | order_placed | order_failed | live_mode_flip
    actor = db.Column(db.String(50), default='system')   # 'system' | 'user' | 'user:<id>' (未來 SaaS)
    context = db.Column(db.JSON, default={})
    ip = db.Column(db.String(45))                        # IPv4/IPv6
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'event_type': self.event_type,
            'actor': self.actor,
            'context': self.context or {},
            'ip': self.ip,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ParamOptimization(db.Model):
    """Phase 10.2: walk-forward 參數網格搜尋的執行紀錄與結果。"""
    __tablename__ = 'param_optimizations'

    id = db.Column(db.Integer, primary_key=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id', ondelete='CASCADE'), nullable=False, index=True)
    status = db.Column(db.String(20), default='pending')   # pending / running / completed / error
    grid = db.Column(db.JSON, default={})                  # {'period': [7,10,14], 'multiplier': [2,3]}
    baseline_params = db.Column(db.JSON, default={})       # 跑前的 strategy.params
    baseline_oos_sharpe = db.Column(db.Float)              # 基線 walk-forward OOS Sharpe
    candidate_results = db.Column(db.JSON, default=[])     # [{params, is_sharpe, oos_sharpe, decay_pct, total_trades, ...}]
    best_params = db.Column(db.JSON)
    best_oos_sharpe = db.Column(db.Float)
    combos_total = db.Column(db.Integer, default=0)
    combos_done = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    def to_dict(self, include_results=True):
        d = {
            'id': self.id,
            'strategy_id': self.strategy_id,
            'status': self.status,
            'grid': self.grid or {},
            'baseline_params': self.baseline_params or {},
            'baseline_oos_sharpe': self.baseline_oos_sharpe,
            'best_params': self.best_params,
            'best_oos_sharpe': self.best_oos_sharpe,
            'combos_total': self.combos_total,
            'combos_done': self.combos_done,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }
        if include_results:
            d['candidate_results'] = self.candidate_results or []
        return d


class StrategyCandidate(db.Model):
    """策略候選池 — 來自爬蟲（TradingView / GitHub）+ LLM 翻譯的策略，待回測 / 待 promote"""
    __tablename__ = 'strategy_candidates'

    id = db.Column(db.Integer, primary_key=True)

    # 來源
    source = db.Column(db.String(20), nullable=False)        # 'tradingview' / 'github' / 'manual'
    source_url = db.Column(db.String(500))
    source_name = db.Column(db.String(200))                  # 策略原名（爬到的）
    source_author = db.Column(db.String(200))
    source_meta = db.Column(db.JSON, default={})             # likes / stars / 評論數 / 抓取時間等

    # 原始碼
    raw_code = db.Column(db.Text)
    raw_lang = db.Column(db.String(20))                      # 'pine' / 'python' / 'js'

    # LLM 翻譯產出
    parsed_signal = db.Column(db.Text)                       # 完整 Python signal function source
    signal_fn_name = db.Column(db.String(100))               # 例 'tv_xyz_signal'
    candidate_type = db.Column(db.String(50))                # 給 strategies.type 用的 slug
    category = db.Column(db.String(10), default='swing')
    timeframe = db.Column(db.String(10), default='4h')
    default_params = db.Column(db.JSON, default={})
    llm_notes = db.Column(db.Text)                           # LLM 對策略邏輯的說明
    llm_model = db.Column(db.String(50))                     # 用哪個 model 翻的

    # Pipeline 狀態
    status = db.Column(db.String(20), default='pending', index=True)
    # pending / translating / translated / backtesting / qualified / rejected / promoted / error
    error_log = db.Column(db.Text)

    # 關聯
    backtest_result_id = db.Column(db.Integer, db.ForeignKey('backtest_results.id'))
    promoted_strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id'))

    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    backtest = db.relationship('BacktestResult', foreign_keys=[backtest_result_id])
    promoted_strategy = db.relationship('Strategy', foreign_keys=[promoted_strategy_id])

    def to_dict(self, include_code=False):
        d = {
            'id': self.id,
            'source': self.source,
            'source_url': self.source_url,
            'source_name': self.source_name,
            'source_author': self.source_author,
            'source_meta': self.source_meta or {},
            'raw_lang': self.raw_lang,
            'signal_fn_name': self.signal_fn_name,
            'candidate_type': self.candidate_type,
            'category': self.category,
            'timeframe': self.timeframe,
            'default_params': self.default_params or {},
            'llm_notes': self.llm_notes,
            'llm_model': self.llm_model,
            'status': self.status,
            'error_log': self.error_log,
            'backtest_result_id': self.backtest_result_id,
            'promoted_strategy_id': self.promoted_strategy_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_code:
            d['raw_code'] = self.raw_code
            d['parsed_signal'] = self.parsed_signal
        return d


class Candle(db.Model):
    """K線數據（本地緩存）"""
    __tablename__ = 'candles'

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    timestamp = db.Column(db.BigInteger, nullable=False)
    open = db.Column(db.Float)
    high = db.Column(db.Float)
    low = db.Column(db.Float)
    close = db.Column(db.Float)
    volume = db.Column(db.Float)

    __table_args__ = (
        db.UniqueConstraint('symbol', 'timeframe', 'timestamp', name='uix_candle'),
    )

    def to_dict(self):
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'timestamp': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
        }
