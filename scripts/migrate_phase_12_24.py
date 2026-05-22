"""Phase 12.24: payment_invoices + subscriptions 表 migration

Idempotent — 可重复跑。
"""
import sys
sys.path.insert(0, '/app')

from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    # 直接 create_all（SQLAlchemy 检测已存在表会跳过）
    print('Running db.create_all() ...')
    db.create_all()
    print('Done. Tables now in DB:')
    rows = db.session.execute(db.text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename IN ('payment_invoices', 'subscriptions') ORDER BY tablename"
    )).fetchall()
    for r in rows:
        print(f'  ✓ {r[0]}')

    # 验证 schema
    for table in ('payment_invoices', 'subscriptions'):
        cols = db.session.execute(db.text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name=:t ORDER BY ordinal_position"
        ), {'t': table}).fetchall()
        print(f'\n  {table} columns ({len(cols)}):')
        for c in cols:
            print(f'    {c[0]:30s} {c[1]}')

print('\nDone.')
