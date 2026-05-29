import datetime
from app.extensions import db


class OkxCredentials(db.Model):
    """Phase 11.2: per-user OKX API key（Fernet 加密存儲）。

    每 user 最多一組 OKX key (user_id UNIQUE)。admin (user_id=1) 不存這表 — 走 .env。
    解密只在 Celery / web 內存發生，不寫 log / 不落磁碟。
    """
    __tablename__ = 'okx_credentials'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True, index=True)
    # Fernet 加密 base64 字串
    encrypted_api_key = db.Column(db.Text, nullable=False)
    encrypted_secret = db.Column(db.Text, nullable=False)
    encrypted_passphrase = db.Column(db.Text, nullable=False)
    # 最後一次成功拉 OKX 餘額的時間（None = 從未驗證）
    verified_at = db.Column(db.DateTime, nullable=True)
    # 最後驗證錯誤訊息（給 UI 顯示）
    last_error = db.Column(db.Text, nullable=True)
    # user 可手動 disable 而不解綁
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self, include_masked=True):
        """to_dict 永遠不返回明文密鑰；include_masked 只回前 4 後 4 提示。"""
        d = {
            'id': self.id,
            'user_id': self.user_id,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'last_error': self.last_error,
            'is_active': bool(self.is_active),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_masked:
            # 解密只為了顯示前 4 後 4；該函式 caller 應確認 actor 是 owner
            from app.services.okx_creds import try_decrypt
            ak = try_decrypt(self.encrypted_api_key)
            d['api_key_masked'] = (ak[:4] + '…' + ak[-4:]) if ak and len(ak) > 8 else '****'
        return d


class LlmCredentials(db.Model):
    """Phase 11.5: per-user BYO LLM API key (Anthropic / OpenAI / Gemini)。

    一個 user 可綁多 provider。priority 數字小優先 — adapter 拿 user 綁的
    最高 priority active provider 用；rate-limit 失敗時 fallback 到下一個。

    Fernet 加密（沿用 11.2 的 OKX_CREDS_FERNET_KEY）。
    """
    __tablename__ = 'llm_credentials'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    provider = db.Column(db.String(20), nullable=False)   # 'anthropic' | 'openai' | 'gemini'
    encrypted_api_key = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    priority = db.Column(db.Integer, default=100)         # 小優先
    # 用戶可選的預設模型（None → adapter 用 provider 預設）
    default_model = db.Column(db.String(80), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    # 累計 token 統計（給 user 看用了多少）— 月度重設
    monthly_input_tokens = db.Column(db.BigInteger, default=0)
    monthly_output_tokens = db.Column(db.BigInteger, default=0)
    monthly_reset_at = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'provider', name='uix_llm_user_provider'),
    )

    def to_dict(self):
        """永遠不返回明文 api_key"""
        from app.services.okx_creds import try_decrypt
        ak = try_decrypt(self.encrypted_api_key) or ''
        masked = (ak[:4] + '…' + ak[-4:]) if len(ak) > 8 else '****'
        return {
            'id': self.id,
            'user_id': self.user_id,
            'provider': self.provider,
            'api_key_masked': masked,
            'is_active': bool(self.is_active),
            'priority': self.priority,
            'default_model': self.default_model,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'last_error': self.last_error,
            'monthly_input_tokens': self.monthly_input_tokens or 0,
            'monthly_output_tokens': self.monthly_output_tokens or 0,
            'monthly_reset_at': self.monthly_reset_at.isoformat() if self.monthly_reset_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class HyperliquidCredentials(db.Model):
    """Phase 14k: per-user Hyperliquid agent wallet (Fernet 加密 private key)

    HL 设计: user 在 hyperliquid 网站派生 agent wallet — agent 只能 trade,
    无法 transfer/withdraw, 主钱包永远不暴露给系统.

    agent_address — 0x... agent 钱包地址 (用于 sign user-of-record)
    main_address  — 0x... 主钱包地址 (用于 query positions/balance, info API)
    encrypted_agent_private_key — agent 钱包私钥 (ECDSA secp256k1, 32 bytes hex)
    """
    __tablename__ = 'hyperliquid_credentials'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True, index=True)
    agent_address = db.Column(db.String(60), nullable=False)
    main_address = db.Column(db.String(60), nullable=False)
    encrypted_agent_private_key = db.Column(db.Text, nullable=False)
    network = db.Column(db.String(10), default='mainnet')   # 'mainnet' | 'testnet'
    # Phase 14k-6: HL agent wallet 默认 180 天有效
    agent_expires_at = db.Column(db.DateTime, nullable=True)
    expiry_warned_at = db.Column(db.DateTime, nullable=True)   # last Telegram warning timestamp (dedup)
    verified_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self):
        """永远不返回 private key, 仅 address/状态."""
        days_remaining = None
        if self.agent_expires_at:
            delta = (self.agent_expires_at - datetime.datetime.utcnow()).total_seconds()
            days_remaining = max(0, int(delta // 86400))
        return {
            'id': self.id,
            'user_id': self.user_id,
            'agent_address': self.agent_address,
            'main_address': self.main_address,
            'network': self.network,
            'agent_expires_at': self.agent_expires_at.isoformat() if self.agent_expires_at else None,
            'days_remaining': days_remaining,
            'expired': days_remaining is not None and days_remaining <= 0,
            'expiring_soon': days_remaining is not None and 0 < days_remaining <= 14,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'last_error': self.last_error,
            'is_active': bool(self.is_active),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ProfitTarget(db.Model):
    """Phase 14k-22: per-user 利润目标跟踪 + DD 保护 + 自动复盘.

    每 user 一个 active target (status='active'). 目标达成后 status='achieved',
    超期未达 status='expired'. 系统自动跑 profit_progress_monitor 跟踪进度.
    """
    __tablename__ = 'profit_targets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    start_capital_usdt = db.Column(db.Float, nullable=False)        # 起始本金 (USDT)
    target_pct = db.Column(db.Float, nullable=False, default=20.0)  # 目标增幅 % (默认 20%)
    deadline = db.Column(db.DateTime, nullable=False)
    # 实时跟踪
    current_equity_usdt = db.Column(db.Float)                       # 最新 equity (定期更新)
    peak_equity_usdt = db.Column(db.Float)                          # 历史最高 equity (DD 用)
    last_progress_check_at = db.Column(db.DateTime)
    # 状态
    status = db.Column(db.String(20), default='active', index=True) # active | achieved | expired | paused
    achieved_at = db.Column(db.DateTime)
    expired_at = db.Column(db.DateTime)
    # 风控配置
    max_dd_pct = db.Column(db.Float, default=15.0)                  # 最大允许回撤 %
    daily_loss_halt_pct = db.Column(db.Float, default=5.0)          # 单日亏损达此 % 当日 halt
    # 警告去重
    last_lag_warned_at = db.Column(db.DateTime)                     # 上次"进度落后"警告时间
    last_tier_triggered_at = db.Column(db.DateTime)                 # 上次资金跨档 trigger
    last_tier_value = db.Column(db.Integer)                         # 上次跨过的档位 ($100/$500/$2000)
    last_ai_review_at = db.Column(db.DateTime)                      # 上次主动 trigger AI review
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def target_equity(self) -> float:
        """目标 equity = start × (1 + target_pct%)"""
        return self.start_capital_usdt * (1 + self.target_pct / 100)

    def days_remaining(self) -> int:
        if not self.deadline:
            return 0
        delta = (self.deadline - datetime.datetime.utcnow()).total_seconds()
        return max(0, int(delta / 86400))

    def days_elapsed(self) -> int:
        if not self.created_at:
            return 0
        return max(0, int((datetime.datetime.utcnow() - self.created_at).total_seconds() / 86400))

    def expected_equity_now(self) -> float:
        """按线性目标曲线, 当前应到的 equity (用于判定领先/落后)"""
        if not self.deadline or not self.created_at:
            return self.start_capital_usdt
        total_days = max(1, (self.deadline - self.created_at).total_seconds() / 86400)
        elapsed = max(0, (datetime.datetime.utcnow() - self.created_at).total_seconds() / 86400)
        progress = min(1.0, elapsed / total_days)
        gain = (self.target_equity() - self.start_capital_usdt) * progress
        return self.start_capital_usdt + gain

    def progress_pct(self) -> float:
        """已完成进度: 实际增益 / 目标增益"""
        if not self.current_equity_usdt:
            return 0
        actual_gain = self.current_equity_usdt - self.start_capital_usdt
        target_gain = self.target_equity() - self.start_capital_usdt
        return round((actual_gain / target_gain * 100) if target_gain else 0, 1)

    def dd_pct(self) -> float:
        """当前回撤 % (peak - current) / peak"""
        if not self.peak_equity_usdt or self.peak_equity_usdt <= 0:
            return 0
        cur = self.current_equity_usdt or self.peak_equity_usdt
        return round(max(0, (self.peak_equity_usdt - cur) / self.peak_equity_usdt * 100), 2)

    def to_dict(self):
        return {
            'id': self.id, 'user_id': self.user_id,
            'start_capital_usdt': self.start_capital_usdt,
            'target_pct': self.target_pct,
            'target_equity_usdt': round(self.target_equity(), 2),
            'current_equity_usdt': self.current_equity_usdt,
            'peak_equity_usdt': self.peak_equity_usdt,
            'expected_equity_now': round(self.expected_equity_now(), 2),
            'progress_pct': self.progress_pct(),
            'dd_pct': self.dd_pct(),
            'days_remaining': self.days_remaining(),
            'days_elapsed': self.days_elapsed(),
            'deadline': self.deadline.isoformat() if self.deadline else None,
            'status': self.status,
            'max_dd_pct': self.max_dd_pct,
            'daily_loss_halt_pct': self.daily_loss_halt_pct,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'achieved_at': self.achieved_at.isoformat() if self.achieved_at else None,
        }


class CatalogBacktestMatrix(db.Model):
    """Phase 14k-16: catalog × symbol × exchange 预先 batch-backtest 结果矩阵.

    取代「每次 AI 推荐都重测」, 改成离线 batch 一次 → AI 推荐瞬时从矩阵查 verified 池.
    UNIQUE (catalog_id, symbol, exchange) — TF 跟随 catalog 自带 (不存 TF, 因为 catalog 已绑死).
    """
    __tablename__ = 'catalog_backtest_matrix'

    id = db.Column(db.Integer, primary_key=True)
    catalog_id = db.Column(db.Integer, db.ForeignKey('strategy_candidates.id'), nullable=False, index=True)
    symbol = db.Column(db.String(20), nullable=False, index=True)
    exchange = db.Column(db.String(20), nullable=False, index=True)    # 'okx' | 'hyperliquid'
    backtest_result_id = db.Column(db.Integer, db.ForeignKey('backtest_results.id'), nullable=True)
    is_sharpe = db.Column(db.Float)
    oos_sharpe = db.Column(db.Float)
    decay_pct = db.Column(db.Float)
    is_trades = db.Column(db.Integer)
    oos_trades = db.Column(db.Integer)
    full_sharpe = db.Column(db.Float)
    full_total_trades = db.Column(db.Integer)
    full_max_drawdown_pct = db.Column(db.Float)
    is_verified = db.Column(db.Boolean, default=False, index=True)      # pass IS≥1.5 OOS≥0.8 decay≤70%
    reject_reason = db.Column(db.Text)
    backtest_ran_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('catalog_id', 'symbol', 'exchange', name='uix_catalog_sym_ex'),
    )

    def to_dict(self):
        return {
            'id': self.id, 'catalog_id': self.catalog_id,
            'symbol': self.symbol, 'exchange': self.exchange,
            'backtest_result_id': self.backtest_result_id,
            'is_sharpe': self.is_sharpe, 'oos_sharpe': self.oos_sharpe,
            'decay_pct': self.decay_pct,
            'is_trades': self.is_trades, 'oos_trades': self.oos_trades,
            'full_sharpe': self.full_sharpe,
            'full_total_trades': self.full_total_trades,
            'full_max_drawdown_pct': self.full_max_drawdown_pct,
            'is_verified': bool(self.is_verified),
            'reject_reason': self.reject_reason,
            'backtest_ran_at': self.backtest_ran_at.isoformat() if self.backtest_ran_at else None,
        }


class User(db.Model):
    """Phase 11.1: SaaS 用戶 — bcrypt 密碼，每 user 有自己的 strategies / positions / trades

    user_id=1 = 系統管理員（vincenzo000915@gmail.com），承接 11.1 之前的所有單用戶數據。
    其他 user 預設 free tier + paper-only（LIVE 模式 11.1 階段仅限 user_id=1）。
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)        # bcrypt
    role = db.Column(db.String(20), default='user')                  # 'admin' | 'user'
    subscription_tier = db.Column(db.String(20), default='free')     # 'free' | 'basic' | 'pro' | 'team'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'role': self.role,
            'subscription_tier': self.subscription_tier,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
        }


class Strategy(db.Model):
    """策略配置"""
    __tablename__ = 'strategies'

    id = db.Column(db.Integer, primary_key=True)
    # Phase 11.1.2: 多租戶 — 每策略歸屬某 user (admin=1)。nullable 是過渡期，等 11.1.3 INSERT path 全帶上後鎖 NOT NULL
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # ma_crossover / rsi / macd / bollinger / combo
    category = db.Column(db.String(10), default='swing')  # short(短線) / swing(波段) / long(長線)
    params = db.Column(db.JSON, default={})           # 策略參數
    symbol = db.Column(db.String(20), default='BTC/USDT')
    timeframe = db.Column(db.String(10), default='4h')
    status = db.Column(db.String(20), default='stopped')  # running / paused / stopped
    # Phase 14k: 交易所 — 'okx' (CEX swap, 默认) | 'hyperliquid' (DEX perp)
    exchange = db.Column(db.String(20), default='okx', index=True)
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
    # Phase 12.11: 2-strike retire — 連續兩次 health check 不過才退役
    retire_warning_count = db.Column(db.Integer, default=0)
    # 自動 revive 次數（給 future analysis 看哪些策略反覆死灰復燃）
    revive_count = db.Column(db.Integer, default=0)
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
            'exchange': self.exchange or 'okx',
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id'))
    # Phase 14k-136 (B1a): 仓位真实成交所 — 与 strategy.exchange 解耦, 为 B1b 跨所路由铺路.
    # 平仓/SL/TP/reconcile 一律用 pos.exchange (而非 strategy.exchange) 定位该仓在哪个所.
    exchange = db.Column(db.String(20), nullable=True)
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
    # Phase 14k-158: 移动止盈状态 — 持仓期最有利价 (long=最高/short=最低), trailing 棘轮基准.
    # NULL = 非 atr 仓/未初始化, trailing 不生效 (flat_pct 仓不受影响).
    peak_price = db.Column(db.Float, nullable=True)
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
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
    # Phase 11.1.2: NULL = 候選池 stage (system resource, 全局可見)；非 NULL = 跟 strategy 同 user
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
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
    # Phase 12.39: 候選回測默認 symbol — 改成跟 LIVE 一致避免數據外推（之前硬編碼 BTC/USDT 是 bug）
    default_backtest_symbol = db.Column(db.String(20), default='AVAX/USDT')
    # Phase 14k-14: admin 可临时禁用 OKX 路径 (专注 HL 测试)
    disable_okx_for_admin = db.Column(db.Boolean, default=False)

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

    # Phase 14c: AI decision mode (manual / semi_auto / full_auto)
    # manual = 走 AiRecentDecisions 面板等 user apply
    # semi_auto = verified_oos_sharpe ≥ 2.5 自动 apply，其他面板
    # full_auto = 全部自动 + 数据充分时允许 v8 invent (Pro tier 才能开)
    ai_decision_mode = db.Column(db.String(20), default='manual')
    auto_apply_max_running = db.Column(db.Integer, default=8)

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
            'default_backtest_symbol': self.default_backtest_symbol or 'AVAX/USDT',
            'disable_okx_for_admin': bool(self.disable_okx_for_admin),
            'auto_apply_enabled': bool(self.auto_apply_enabled),
            'auto_apply_actions': list(self.auto_apply_actions or []),
            'auto_apply_max_per_day': self.auto_apply_max_per_day or 5,
            'fan_out_auto_start': bool(self.fan_out_auto_start),
            'fan_out_min_oos_sharpe': self.fan_out_min_oos_sharpe or 1.0,
            'auto_promote_max_per_day': self.auto_promote_max_per_day or 2,
            'auto_promote_min_oos_sharpe': self.auto_promote_min_oos_sharpe or 1.5,
            'ai_decision_mode': self.ai_decision_mode or 'manual',
            'auto_apply_max_running': self.auto_apply_max_running or 8,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SignalWatcher(db.Model):
    """Phase 14k-45 L2: 事件驱动入场 watcher.

    AI brief 出 watch_indicators (eg "15m RSI < 30 + 4h close > SMA50")
    → 创建 watcher → check_signal_watchers task 每 5min 算条件 → 满足触发 strategy 入场.
    """
    __tablename__ = 'signal_watchers'

    id = db.Column(db.Integer, primary_key=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    symbol = db.Column(db.String(20), nullable=False)
    # AI 生成的条件 JSON, 简化结构:
    #   {"description_zh": "15m RSI < 30", "description_en": "...",
    #    "tf": "15m", "indicator": "rsi_14", "op": "<", "value": 30, "side": "buy"}
    # 复合条件用 list:
    #   [{tf, indicator, op, value}, ...]  全部满足才触发 (AND logic)
    conditions = db.Column(db.JSON, nullable=False)
    side = db.Column(db.String(10), default='buy')  # buy / sell / either
    source = db.Column(db.String(30), default='ai_brief')  # ai_brief | manual | strategy_signal
    status = db.Column(db.String(20), default='active', index=True)  # active | triggered | expired | cancelled
    triggered_at = db.Column(db.DateTime, nullable=True)
    triggered_price = db.Column(db.Float, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'strategy_id': self.strategy_id,
            'symbol': self.symbol,
            'conditions': self.conditions or [],
            'side': self.side,
            'source': self.source,
            'status': self.status,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'triggered_price': self.triggered_price,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UserConfig(db.Model):
    """Phase 14k-30 #3: per-user 配置覆盖 (sparse).

    SystemConfig 是全局 base; UserConfig 让每 user 覆盖部分字段 (sizing/lev/auto_apply 等).
    overrides 是 sparse JSON dict, 只存非默认值; get_config(user_id) 合并 base + overrides.
    """
    __tablename__ = 'user_config'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    overrides = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'overrides': self.overrides or {},
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class AuditLog(db.Model):
    """Phase 8.4: 审计日志 — 任何 mutating 事件都記一條"""
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id', ondelete='CASCADE'), nullable=False, index=True)
    status = db.Column(db.String(20), default='pending')   # pending / running / completed / error
    grid = db.Column(db.JSON, default={})                  # {'period': [7,10,14], 'multiplier': [2,3]}
    baseline_params = db.Column(db.JSON, default={})       # 跑前的 strategy.params
    baseline_oos_sharpe = db.Column(db.Float)              # 基線 walk-forward OOS Sharpe
    candidate_results = db.Column(db.JSON, default=[])     # [{params, is_sharpe, oos_sharpe, decay_pct, total_trades, ...}]
    best_params = db.Column(db.JSON)
    best_risk_params = db.Column(db.JSON)              # 14k-147 (D2): best 的风险维(lev/SL/TP), 供 D4 分离写回
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

    # Pipeline 狀態 (14k-51 加 stale_qualified / archived; 14k-52 dismissed/error 老定义)
    status = db.Column(db.String(20), default='pending', index=True)
    # pending / translating / translated / backtesting / qualified / stale_qualified
    # / archived / dismissed / promoted / error
    error_log = db.Column(db.Text)

    # 14k-54: user_id — multi-user SaaS scope. catalog 模板 user_id=NULL (全局共享)
    # 其它 (synth/research/improve/catalog_clone/manual/github) 必有 user_id
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    # Phase 14: Vetted catalog metadata (when source='catalog')
    catalog_meta = db.Column(db.JSON, default={})
    # {
    #   'citation': 'arxiv 2310.xxxxx / github.com/jesse-ai/jesse',
    #   'verified_oos_sharpe': 2.3,
    #   'verified_pf': 1.85,
    #   'ideal_regimes': ['trending', 'high_vol'],
    #   'fit_symbols': ['BTC/USDT', 'ETH/USDT'],
    #   'fit_tfs': ['4h', '1d'],
    #   'recommended_risk': {'leverage': 3, 'sl_pct': 8, 'tp_pct': 15, 'order_type': 'maker'},
    #   'avoid_when': 'choppy / low ADX',
    # }

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
            'catalog_meta': self.catalog_meta or {},
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


# ============================================================
# Phase 12.24: USDT 订阅 SaaS — payment + subscription tables
# ============================================================

class PaymentInvoice(db.Model):
    """Pending USDT 付款 invoice — 用户在 /checkout 创建后等链上确认"""
    __tablename__ = 'payment_invoices'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    plan = db.Column(db.String(20), nullable=False)            # basic / pro / team
    months = db.Column(db.Integer, nullable=False)             # 1 / 3 / 6 / 12
    discount_pct = db.Column(db.Integer, default=0)            # 0 / 10 / 20 / 30
    base_amount = db.Column(db.Numeric(12, 6), nullable=False) # 例如 337.500000 USDT
    suffix = db.Column(db.String(8), nullable=False)           # 6 位 dust suffix 如 .123456
    amount_due = db.Column(db.Numeric(12, 6), nullable=False)  # base_amount + suffix
    chain = db.Column(db.String(10), nullable=False)           # trc20 / erc20 / bep20 / sol
    address = db.Column(db.String(80), nullable=False)         # 收款地址（admin 主钱包）
    status = db.Column(db.String(20), default='pending', index=True)
    # pending / confirmed / expired / cancelled / pending_review (用户提交 tx hash)
    tx_hash = db.Column(db.String(120))                        # 链上 tx hash（确认后填）
    tx_block_number = db.Column(db.BigInteger)                 # 区块高度
    tx_from_address = db.Column(db.String(80))                 # 付款方地址（防欺诈用）
    tx_received_amount = db.Column(db.Numeric(12, 6))          # 实际收到 amount
    review_note = db.Column(db.Text)                           # 手动审核备注
    created_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)        # 30 分钟过期
    confirmed_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'plan': self.plan,
            'months': self.months,
            'discount_pct': self.discount_pct,
            'base_amount': float(self.base_amount),
            'amount_due': float(self.amount_due),
            'suffix': self.suffix,
            'chain': self.chain,
            'address': self.address,
            'status': self.status,
            'tx_hash': self.tx_hash,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'confirmed_at': self.confirmed_at.isoformat() if self.confirmed_at else None,
        }


class Subscription(db.Model):
    """已开通订阅 — 一个 user 一次只能有一条 active 订阅"""
    __tablename__ = 'subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    plan = db.Column(db.String(20), nullable=False)            # basic / pro / team
    status = db.Column(db.String(20), default='active', index=True)
    # active / cancelled / expired
    invoice_id = db.Column(db.Integer, db.ForeignKey('payment_invoices.id'))
    activated_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    cancelled_at = db.Column(db.DateTime)
    auto_renew = db.Column(db.Boolean, default=False)          # USDT 不能自动续，默认 false
    notes = db.Column(db.Text)

    def to_dict(self):
        return {
            'id': self.id,
            'plan': self.plan,
            'status': self.status,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'days_remaining': max(0, (self.expires_at - db.func.now()).days) if self.expires_at else None,
        }
