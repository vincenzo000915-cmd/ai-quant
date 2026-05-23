from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from celery import Celery
from celery.signals import task_prerun, task_postrun
import redis

db = SQLAlchemy()
socketio = SocketIO(cors_allowed_origins="*")

# Phase 12.35: 共享 Redis client (broker 是 db 0，我们用 db 1 隔开应用状态)
redis_client = redis.Redis(host='redis', port=6379, db=1, decode_responses=True)

def make_celery(app_name=None):
    c = Celery(
        app_name or 'quant_tasks',
        broker='redis://redis:6379/0',
        backend='redis://redis:6379/0',
        # 顯式列出 submodule 才會註冊 @celery_app.task 裝飾器；只寫 'app.tasks' (package)
        # 不會自動 import 子模組，導致 worker [tasks] 列表為空、所有 task 都跑不了。
        include=['app.tasks.strategy_tasks', 'app.tasks.scheduler']
    )
    # 引入 beat schedule
    c.config_from_object('app.celeryconfig')
    return c

celery_app = make_celery()


# Phase 12.36: 修连接池泄漏 — cache app 一次，每个 task 不再 create_app
# 之前 _push_app_context 每个 task 都 create_app() 创新 SQLAlchemy engine + 新 pool
# → idle connection 累积爆炸 (worker process 82+ idle, max_connections=100)
_app_ctx_stack = []
_cached_app = None


def _get_cached_app():
    """Lazy cache Flask app per worker process — 只 create 一次，复用 engine + pool"""
    global _cached_app
    if _cached_app is None:
        from app import create_app
        _cached_app = create_app()
    return _cached_app


@task_prerun.connect
def _push_app_context(sender=None, task_id=None, task=None, **kwargs):
    app = _get_cached_app()
    ctx = app.app_context()
    ctx.push()
    _app_ctx_stack.append(ctx)


@task_postrun.connect
def _pop_app_context(sender=None, task_id=None, task=None, **kwargs):
    if _app_ctx_stack:
        ctx = _app_ctx_stack.pop()
        try:
            ctx.pop()
        except Exception:
            pass
