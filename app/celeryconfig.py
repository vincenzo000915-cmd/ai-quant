from celery.schedules import crontab

# ===== Celery Beat Schedule（定時任務） =====
# 15m 極短策略：每 15 分鐘執行一次信號檢查
# 1h 短線策略：每小時執行一次信號檢查
# 4h 波段/長線策略：每小時檢查（他們只在 new 4h candle 時才觸發）
# 持倉更新和風控在每個檢查週期都跑

beat_schedule = {
    # === 極短策略（15m）===
    'run-short-term-strategies': {
        'task': 'app.tasks.strategy_tasks.run_strategy_signals_ultra',
        'schedule': crontab(minute='*/15'),
        'options': {'queue': 'default'},
    },

    # === 短線策略（1h）===
    'run-swing-strategies': {
        'task': 'app.tasks.strategy_tasks.run_strategy_signals_short',
        'schedule': crontab(minute='5'),
        'options': {'queue': 'default'},
    },

    # === 波段/長線策略（4h）===
    'run-long-strategies': {
        'task': 'app.tasks.strategy_tasks.run_strategy_signals',
        'schedule': crontab(minute='15'),
        'options': {'queue': 'default'},
    },

    # === 市場數據獲取 ===
    'fetch-market-data': {
        'task': 'app.tasks.strategy_tasks.fetch_market_data',
        'schedule': crontab(minute='0'),  # 每小時
        'options': {'queue': 'default'},
    },

    # === 持倉價格更新（每5分鐘）===
    'update-positions': {
        'task': 'app.tasks.strategy_tasks.update_positions',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'default'},
    },

    # === 止損止盈檢查（每5分鐘）===
    'check-stop-loss': {
        'task': 'app.tasks.strategy_tasks.check_stop_loss',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'default'},
    },

    # === Phase 5.3: 策略健康監控（每天 03:00 UTC，自動退役 Sharpe 衰退者）===
    'monitor-strategy-health': {
        'task': 'app.tasks.strategy_tasks.monitor_strategy_health',
        'schedule': crontab(hour='3', minute='0'),
        'options': {'queue': 'default'},
    },

    # === Phase 5.2: 候選池自動回測（每小時 30 分，跑所有 translated 走 walk-forward）===
    'auto-backtest-candidates': {
        'task': 'app.tasks.strategy_tasks.auto_backtest_translated_candidates',
        'schedule': crontab(minute='30'),
        'options': {'queue': 'default'},
    },

    # === Phase 5.1: 每日爬蟲（02:00 UTC，先爬再翻譯）===
    'auto-crawl-github': {
        'task': 'app.tasks.strategy_tasks.auto_crawl_github',
        'schedule': crontab(hour='2', minute='0'),
        'options': {'queue': 'default'},
    },

    # === Phase 5.1: 每天 02:30 翻譯 pending（需要 ANTHROPIC_API_KEY，沒 key 自動跳過）===
    'auto-translate-pending': {
        'task': 'app.tasks.strategy_tasks.auto_translate_pending',
        'schedule': crontab(hour='2', minute='30'),
        'options': {'queue': 'default'},
    },

    # === Phase 6.1: 每 5 分鐘檢查當日虧損 → 觸發 halt ===
    'monitor-daily-loss': {
        'task': 'app.tasks.strategy_tasks.monitor_daily_loss',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'default'},
    },

    # === Phase 6.4: 異常檢測（flash crash / 持倉密度）每 5 分鐘 ===
    'monitor-anomalies': {
        'task': 'app.tasks.strategy_tasks.monitor_anomalies',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'default'},
    },

    # === Phase 8.2: 對賬本地 vs OKX 持倉，每 5 分鐘 ===
    'reconcile-positions': {
        'task': 'app.tasks.strategy_tasks.reconcile_okx_positions',
        'schedule': crontab(minute='*/5'),
        'options': {'queue': 'default'},
    },
}
