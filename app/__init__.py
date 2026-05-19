from flask import Flask
from .extensions import db, socketio, celery_app
from .config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # 初始化擴展
    db.init_app(app)
    socketio.init_app(app)

    # 更新 Celery 配置
    celery_app.conf.update(
        broker_url=config_class.CELERY_BROKER_URL,
        result_backend=config_class.CELERY_RESULT_BACKEND,
    )

    # 註冊路由
    from .routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    # 健康檢查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'quant-trading'}

    # 服務前端靜態檔
    import os
    frontend_build = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend', 'build')
    if os.path.exists(frontend_build):
        from flask import send_from_directory
        app.static_folder = os.path.join(frontend_build, 'static')
        
        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        def serve_frontend(path):
            if path and os.path.exists(os.path.join(frontend_build, path)):
                return send_from_directory(frontend_build, path)
            return send_from_directory(frontend_build, 'index.html')

    # 延遲創建資料表（gunicorn worker fork 後再做）
    with app.app_context():
        try:
            from . import models  # noqa
            db.create_all()
        except Exception:
            pass  # DB 未就緒時跳過，worker 重啟後會再試

    return app
