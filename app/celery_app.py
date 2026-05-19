"""Celery 應用入口"""
from app.extensions import celery_app

# 導入任務以註冊
from app.tasks import strategy_tasks  # noqa
from app.tasks import scheduler       # noqa
