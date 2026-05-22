from flask import Flask
from flask_jwt_extended import JWTManager
from .extensions import db, socketio, celery_app
from .config import Config

jwt = JWTManager()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # 初始化擴展
    db.init_app(app)
    socketio.init_app(app)
    jwt.init_app(app)

    # 更新 Celery 配置
    celery_app.conf.update(
        broker_url=config_class.CELERY_BROKER_URL,
        result_backend=config_class.CELERY_RESULT_BACKEND,
    )

    # Phase 8.1: 鉴权 — 所有 mutating 請求要 Bearer token
    from .services.auth import auth_guard
    app.before_request(auth_guard)

    # 註冊路由
    from .routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    # 健康檢查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'quant-trading'}

    # Phase 12.34: 业务健康 (UptimeRobot keyword check 用)
    @app.route('/health/business')
    def health_business():
        """返回 24h 关键 cron 是否健康。UptimeRobot 配 keyword='healthy'
        来检查实际业务运转，不只是 web 还在。
        """
        import datetime
        from app.models import StrategyCandidate, Trade, Strategy
        from app.extensions import db
        now = datetime.datetime.utcnow()
        h24_ago = now - datetime.timedelta(hours=24)
        h48_ago = now - datetime.timedelta(hours=48)
        issues = []

        # 1. 最近 24h 有 translate / AI improve 产出
        latest_translate = db.session.query(StrategyCandidate).filter(
            StrategyCandidate.status == 'translated',
            StrategyCandidate.updated_at >= h48_ago,
        ).order_by(StrategyCandidate.updated_at.desc()).first()
        translate_ok = latest_translate is not None and (now - latest_translate.updated_at).total_seconds() < 18 * 3600
        if not translate_ok:
            issues.append(f'48h 内无成功 translate')

        # 2. 检查 pending 堆积（> 30 视为告警）
        pending_count = db.session.query(StrategyCandidate).filter_by(status='pending').count()
        if pending_count > 30:
            issues.append(f'{pending_count} pending 候选堆积')

        # 3. 检查 running 策略数（< 3 视为告警）
        running_count = db.session.query(Strategy).filter_by(status='running').count()
        if running_count < 3:
            issues.append(f'仅 {running_count} 策略 running')

        # 4. system halted ?
        from app.services.config_service import get_config
        cfg = get_config()
        if cfg.get('halted'):
            issues.append(f'system halted: {cfg.get("halt_reason", "?")}')

        return {
            'status': 'healthy' if not issues else 'degraded',
            'service': 'quant-trading',
            'checks': {
                'translate_recent': translate_ok,
                'pending_count': pending_count,
                'running_strategies': running_count,
                'halted': bool(cfg.get('halted')),
            },
            'issues': issues,
            'checked_at': now.isoformat(),
        }

    # Phase 12.28: SEO — sitemap.xml + robots.txt（高优先级，必须在 catch-all 之前）
    @app.route('/robots.txt')
    def robots_txt():
        from flask import Response
        content = (
            'User-agent: *\n'
            'Allow: /\n'
            'Allow: /pricing\n'
            'Allow: /terms\n'
            'Allow: /refund-policy\n'
            'Allow: /privacy\n'
            'Disallow: /api/\n'
            'Disallow: /dashboard\n'
            'Disallow: /strategies\n'
            'Disallow: /candidates\n'
            'Disallow: /trades\n'
            'Disallow: /audit\n'
            'Disallow: /settings\n'
            'Disallow: /checkout\n'
            'Disallow: /login\n'
            '\n'
            'Sitemap: https://ai-quant.medias-ai.cloud/sitemap.xml\n'
        )
        return Response(content, mimetype='text/plain')

    @app.route('/sitemap.xml')
    def sitemap_xml():
        from flask import Response
        import datetime
        today = datetime.date.today().isoformat()
        urls = [
            ('https://ai-quant.medias-ai.cloud/',              '1.0', 'daily'),
            ('https://ai-quant.medias-ai.cloud/pricing',       '0.9', 'weekly'),
            ('https://ai-quant.medias-ai.cloud/terms',         '0.5', 'monthly'),
            ('https://ai-quant.medias-ai.cloud/refund-policy', '0.5', 'monthly'),
            ('https://ai-quant.medias-ai.cloud/privacy',       '0.5', 'monthly'),
        ]
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        for url, prio, freq in urls:
            xml += '  <url>\n'
            xml += f'    <loc>{url}</loc>\n'
            xml += f'    <lastmod>{today}</lastmod>\n'
            xml += f'    <changefreq>{freq}</changefreq>\n'
            xml += f'    <priority>{prio}</priority>\n'
            xml += '  </url>\n'
        xml += '</urlset>\n'
        return Response(xml, mimetype='application/xml')

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
