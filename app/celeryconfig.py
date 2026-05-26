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
    },

    # === 短線策略（1h）===
    'run-swing-strategies': {
        'task': 'app.tasks.strategy_tasks.run_strategy_signals_short',
        'schedule': crontab(minute='5'),
    },

    # === 波段/長線策略（4h）===
    'run-long-strategies': {
        'task': 'app.tasks.strategy_tasks.run_strategy_signals',
        'schedule': crontab(minute='15'),
    },

    # === 市場數據獲取 ===
    'fetch-market-data': {
        'task': 'app.tasks.strategy_tasks.fetch_market_data',
        'schedule': crontab(minute='0'),  # 每小時
    },

    # === 持倉價格更新（每5分鐘）===
    'update-positions': {
        'task': 'app.tasks.strategy_tasks.update_positions',
        'schedule': crontab(minute='*/5'),
    },

    # === 止損止盈檢查（每5分鐘）===
    'check-stop-loss': {
        'task': 'app.tasks.strategy_tasks.check_stop_loss',
        'schedule': crontab(minute='*/5'),
    },

    # === Phase 5.3: 策略健康監控（每天 03:00 UTC，自動退役 Sharpe 衰退者）===
    'monitor-strategy-health': {
        'task': 'app.tasks.strategy_tasks.monitor_strategy_health',
        'schedule': crontab(hour='3', minute='0'),
    },

    # === Phase 5.2: 候選池自動回測（每小時 30 分，跑所有 translated 走 walk-forward）===
    'auto-backtest-candidates': {
        'task': 'app.tasks.strategy_tasks.auto_backtest_translated_candidates',
        'schedule': crontab(minute='30'),
    },

    # === Phase 12.17: 爬蟲提速 1次/日 → 4次/日 (00:00 / 06:00 / 12:00 / 18:00 UTC) ===
    'auto-crawl-github': {
        'task': 'app.tasks.strategy_tasks.auto_crawl_github',
        'schedule': crontab(hour='*/6', minute='0'),
    },

    # === Phase 12.17: 翻譯提速 1次/日 → 6次/日 (每 4 小時 30 分) ===
    'auto-translate-pending': {
        'task': 'app.tasks.strategy_tasks.auto_translate_pending',
        'schedule': crontab(hour='*/4', minute='30'),
    },

    # === Phase 6.1: 每 5 分鐘檢查當日虧損 → 觸發 halt ===
    'monitor-daily-loss': {
        'task': 'app.tasks.strategy_tasks.monitor_daily_loss',
        'schedule': crontab(minute='*/5'),
    },

    # === Phase 6.4: 異常檢測（flash crash / 持倉密度）每 5 分鐘 ===
    'monitor-anomalies': {
        'task': 'app.tasks.strategy_tasks.monitor_anomalies',
        'schedule': crontab(minute='*/5'),
    },

    # === Phase 8.2: 對賬本地 vs OKX 持倉，每 5 分鐘 ===
    'reconcile-positions': {
        'task': 'app.tasks.strategy_tasks.reconcile_okx_positions',
        'schedule': crontab(minute='*/5'),
    },

    # === Phase 10.8 + 14k-42: 智能托管 — 每 1 小时（之前 4h 太慢, force_optimize 链路要等 4-8h 才完整）
    'advisor-auto-apply': {
        'task': 'app.tasks.strategy_tasks.auto_apply_advisor',
        'schedule': crontab(minute='10'),
    },

    # === Phase 14k-30 #1: AI 改动 auto-revert — 每 6h ===
    'auto-revert-ai-changes': {
        'task': 'app.tasks.strategy_tasks.auto_revert_ai_changes',
        'schedule': crontab(minute='20', hour='*/6'),
    },

    # === Phase 14k-45 L1: AI 市场分析 brief prewarm — 每 15min ===
    'prewarm-market-brief': {
        'task': 'app.tasks.strategy_tasks.prewarm_market_brief',
        'schedule': crontab(minute='*/15'),
    },

    # === Phase 14k-45 L2: 信号 watcher 检查 — 每 5min ===
    'check-signal-watchers': {
        'task': 'app.tasks.strategy_tasks.check_signal_watchers',
        'schedule': crontab(minute='*/5'),
    },

    # === Phase 10.9: 每週日 04:00 UTC 給所有 running 策略跑參數網格 ===
    'weekly-auto-optimize': {
        'task': 'app.tasks.strategy_tasks.auto_optimize_running_strategies',
        'schedule': crontab(hour='4', minute='0', day_of_week='sun'),
    },

    # === Phase 10.9: 每天 23:00 UTC 推日報 Telegram ===
    'daily-advisor-summary': {
        'task': 'app.tasks.strategy_tasks.daily_advisor_summary',
        'schedule': crontab(hour='23', minute='0'),
    },

    # === Phase 12.11: 每週日 05:00 UTC 復活 retired 策略（行情變了重新試）===
    'weekly-auto-revive': {
        'task': 'app.tasks.strategy_tasks.auto_revive_retired_strategies',
        'schedule': crontab(hour='5', minute='0', day_of_week='sun'),
    },

    # === Phase 12.4: 每 90s 預熱 Dashboard 緩存（保用戶不見 24s 冷啟動）===
    'prewarm-dashboard-cache': {
        'task': 'app.tasks.strategy_tasks.prewarm_dashboard_cache',
        'schedule': 90.0,
    },

    # === Phase 12.14: 每週日 06:00 UTC 清 candidates 表 rejected/error + candidate-stage backtest ===
    'weekly-cleanup-candidates': {
        'task': 'app.tasks.strategy_tasks.cleanup_old_rejected_candidates',
        'schedule': crontab(hour='6', minute='0', day_of_week='sun'),
    },

    # === Phase 12.17: AI 改進提速 1次/週 → 1次/日 (07:00 UTC = 北京 15:00)
    # admin 走 claude_cli 訂閱免費，加速生成候選不燒 API token
    'daily-auto-ai-improve': {
        'task': 'app.tasks.strategy_tasks.auto_ai_improve_strategies',
        'schedule': crontab(hour='7', minute='0'),
    },

    # === Phase 12.24.2: USDT 链上付款监听（每 60s）===
    # 4 链轮询 (TRC/ERC/BEP/SOL) 自动 confirm pending invoices + 开通订阅
    'check-onchain-payments': {
        'task': 'app.tasks.strategy_tasks.check_onchain_payments',
        'schedule': 60.0,   # 每 60s
    },

    # === Phase 12.34: Daily 早报 (08:00 UTC = 北京 16:00)
    'daily-morning-report': {
        'task': 'app.tasks.strategy_tasks.daily_morning_report',
        'schedule': crontab(hour='8', minute='0'),
    },

    # === Phase 12.35: 内部 health monitor (每 5 min)
    # 不依赖 UptimeRobot；自己跑 + Redis 去重 + 异常 Telegram
    'internal-health-monitor': {
        'task': 'app.tasks.strategy_tasks.internal_health_monitor',
        'schedule': 300.0,   # 每 300s = 5 min
    },

    # === Phase 14k-6: HL agent 180 天过期检查 (每天 09:00 UTC = 北京 17:00)
    # iter 所有 HL 绑定 user, <=14 天 → Telegram 警告 (per-user 去重);
    # 已过期 → 自动 set is_active=false + 通知
    'check-hl-agent-expiry': {
        'task': 'app.tasks.strategy_tasks.check_hl_agent_expiry',
        'schedule': crontab(hour='9', minute='0'),
    },

    # === Phase 14k-20: 卡住的 AI 推荐 clone 每 5 min 重试
    'retry-stuck-ai-recommendations': {
        'task': 'app.tasks.strategy_tasks.retry_stuck_ai_recommendations',
        'schedule': 300.0,   # 每 300s = 5 min
    },

    # === Phase 14k-22: AI 量化经理核心 — 每小时跟踪目标进度 + DD 保护 + 资金扩展
    'profit-progress-monitor': {
        'task': 'app.tasks.strategy_tasks.profit_progress_monitor',
        'schedule': crontab(minute='12'),    # 每小时 :12 跑 (避开 :00 :15 :30 :45 拥挤)
    },

    # === Phase 14k-22: AI 周度策略复盘 — 暂停亏损 + 退役死循环 + 补新
    'weekly-strategy-review': {
        'task': 'app.tasks.strategy_tasks.weekly_strategy_review',
        'schedule': crontab(hour='23', minute='0', day_of_week='sun'),
    },
}
