from celery.schedules import crontab

# ===== Phase 14k-80: 防过时任务堆积 =====
# User 洞察: 交易市场即时性强, 过时 task 堆积重跑没意义
# 1. worker_prefetch_multiplier=1 — worker 不本地缓存 task, 不跑就还在 broker, 真过期自然丢
# 2. task_acks_late=False — worker 拿到 task 立即 ack (crash 不重派)
# 3. beat 每个 task 加 'options': {'expires': N} — broker 自动丢过期 task
worker_prefetch_multiplier = 1
task_acks_late = False
task_reject_on_worker_lost = False  # worker 死掉不重派给别人

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
        'options': {'expires': 600},   # 14k-80: 10min 内没跑就丢, 下次 15min 周期会再派
    },

    # === 短線策略（1h）===
    'run-swing-strategies': {
        'task': 'app.tasks.strategy_tasks.run_strategy_signals_short',
        'schedule': crontab(minute='5'),
        'options': {'expires': 1800},   # 14k-80: 30min, 下次 1h 再派
    },

    # === 波段/長線策略（4h）===
    'run-long-strategies': {
        'task': 'app.tasks.strategy_tasks.run_strategy_signals',
        'schedule': crontab(minute='15'),
        'options': {'expires': 1800},   # 14k-80: 30min, 4h 周期容忍
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
        'options': {'expires': 180},   # 14k-80: 3min 没跑就丢, 价格已过时
    },

    # === 止損止盈檢查（每5分鐘）===
    'check-stop-loss': {
        'task': 'app.tasks.strategy_tasks.check_stop_loss',
        'schedule': crontab(minute='*/5'),
        'options': {'expires': 180},   # 14k-80: 3min 没跑就丢, 价格过时止损失效
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
        'options': {'expires': 180},   # 14k-80
    },

    # === Phase 6.4: 異常檢測（flash crash / 持倉密度）每 5 分鐘 ===
    'monitor-anomalies': {
        'task': 'app.tasks.strategy_tasks.monitor_anomalies',
        'schedule': crontab(minute='*/5'),
        'options': {'expires': 180},   # 14k-80
    },

    # === Phase 8.2: 對賬本地 vs OKX 持倉，每 5 分鐘 ===
    'reconcile-positions': {
        'task': 'app.tasks.strategy_tasks.reconcile_okx_positions',
        'schedule': crontab(minute='*/5'),
        'options': {'expires': 180},   # 14k-80
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

    # === Phase 14k-45 L1: AI 市场分析 brief prewarm ===
    # Phase 14k-79 临时禁用: claude CLI 单次 ~3min × 7 symbol = 21min, lock TTL 14min 失效, CPU 雪崩
    # advisor _get_market_brief 调 analyze_market 时按需懒加载即可 (cache 30min TTL 仍生效)
    # 修完 LLM 调用瓶颈 (e.g. concurrent semaphore / shorter prompt / async batch) 再恢复
    # 'prewarm-market-brief': {
    #     'task': 'app.tasks.strategy_tasks.prewarm_market_brief',
    #     'schedule': crontab(minute='*/15'),
    # },

    # === Phase 14k-45 L2: 信号 watcher 检查 — 每 5min ===
    'check-signal-watchers': {
        'task': 'app.tasks.strategy_tasks.check_signal_watchers',
        'schedule': crontab(minute='*/5'),
        'options': {'expires': 180},   # 14k-80
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
        'options': {'expires': 60},   # 14k-80: 60s 没跑就丢, 下一轮重派
    },

    # === Phase 12.14: 每週日 06:00 UTC 清 candidates 表 rejected/error + candidate-stage backtest ===
    'weekly-cleanup-candidates': {
        'task': 'app.tasks.strategy_tasks.cleanup_old_rejected_candidates',
        'schedule': crontab(hour='6', minute='0', day_of_week='sun'),
    },

    # === Phase 14k-51: 每日 06:30 阶梯归档死池, 防止 qualified 累积拖后 AI ===
    'daily-cleanup-stale-candidates': {
        'task': 'app.tasks.strategy_tasks.cleanup_stale_candidates',
        'schedule': crontab(hour='6', minute='30'),
    },

    # === Phase 12.17: AI 改進提速 1次/週 → 1次/日 (07:00 UTC = 北京 15:00)
    # admin 走 claude_cli 訂閱免費，加速生成候選不燒 API token
    'daily-auto-ai-improve': {
        'task': 'app.tasks.strategy_tasks.auto_ai_improve_strategies',
        'schedule': crontab(hour='7', minute='0'),
    },

    # === Phase 12.24.2: USDT 链上付款监听 ===
    # 14k-80: 60s → 5min (公链 RPC 经常 429, 单次跑 8-12s, 60s 一定堆积)
    # 用户付款后等 5min 入账可接受, 不该烧 worker 资源
    'check-onchain-payments': {
        'task': 'app.tasks.strategy_tasks.check_onchain_payments',
        'schedule': 300.0,   # 14k-80: 60s → 5min
        'options': {'expires': 240},   # 4min 没跑就丢
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
        'options': {'expires': 180},   # 14k-80
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
        'options': {'expires': 180},   # 14k-80
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
