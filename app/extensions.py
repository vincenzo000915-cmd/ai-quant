from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from celery import Celery

db = SQLAlchemy()
socketio = SocketIO(cors_allowed_origins="*")

def make_celery(app_name=None):
    c = Celery(
        app_name or 'quant_tasks',
        broker='redis://redis:6379/0',
        backend='redis://redis:6379/0',
        include=['app.tasks']
    )
    # 引入 beat schedule
    c.config_from_object('app.celeryconfig')
    return c

celery_app = make_celery()
