from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from celery import Celery
from celery.signals import task_prerun, task_postrun

db = SQLAlchemy()
socketio = SocketIO(cors_allowed_origins="*")

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


# 為每個 task push Flask app context — 沒有這個 SQLAlchemy.query 會炸
# "Working outside of application context"。
# 用 stack 是因為 celery prefork 子進程可能巢狀重入。
_app_ctx_stack = []


@task_prerun.connect
def _push_app_context(sender=None, task_id=None, task=None, **kwargs):
    from app import create_app
    app = create_app()
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
