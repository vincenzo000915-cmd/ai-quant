"""Phase 15 学习飞轮迁移: 建 gatekeeper_decisions 表。
用法: docker exec quant-web-1 python /opt/quant/scripts/migrate_phase15_gatekeeper_learning.py
SQLAlchemy create_all 检测已存在表会跳过, 只建新表。"""
from app import create_app
from app.models import db, GatekeeperDecision

app = create_app()
with app.app_context():
    print('Running db.create_all() for gatekeeper_decisions ...')
    db.create_all()
    # 确认表存在
    n = GatekeeperDecision.query.count()
    print(f'OK — gatekeeper_decisions 表就绪, 现有 {n} 条记录。')
