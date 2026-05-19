"""Celery Beat 定時排程"""
from celery.schedules import crontab
from app.extensions import celery_app
from app.tasks.strategy_tasks import (
    fetch_market_data,
    run_strategy_signals,
    update_positions,
    check_stop_loss,
)


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """註冊定時任務"""

    # 每小時獲取K線數據
    sender.add_periodic_task(
        3600.0,
        fetch_market_data.s(),
        name='fetch-market-data-hourly',
    )

    # 每5分鐘計算策略信號
    sender.add_periodic_task(
        300.0,
        run_strategy_signals.s(),
        name='run-strategy-signals-5min',
    )

    # 每30秒更新持倉價格
    sender.add_periodic_task(
        30.0,
        update_positions.s(),
        name='update-positions-30s',
    )

    # 每分鐘檢查止損止盈
    sender.add_periodic_task(
        60.0,
        check_stop_loss.s(),
        name='check-stop-loss-1min',
    )
