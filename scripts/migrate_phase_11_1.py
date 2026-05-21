"""Phase 11.1.2: SaaS 多租戶 migration

跑法（在 container 內）：
    docker exec quant-web-1 python /opt/quant/scripts/migrate_phase_11_1.py

或 host 端 + 環境變數設密碼：
    docker exec -e ADMIN_INITIAL_PASSWORD='your_pw' quant-web-1 python /opt/quant/scripts/migrate_phase_11_1.py

做什麼：
1. 在 users 表 seed admin user (id=1, email=$ADMIN_INITIAL_EMAIL or vincenzo000915@gmail.com)
   - 密碼來自 env ADMIN_INITIAL_PASSWORD，沒設就生成隨機 16 字元並印到 stdout
2. ALTER 7 業務表加 user_id INTEGER (nullable, FK→users.id) + index
   - strategies / positions / orders / trades / backtest_results / param_optimizations / audit_log
3. UPDATE 所有現有 row → user_id=1 (admin)
   - 例外：backtest_results 中 strategy_id IS NULL 的（候選池 stage）留 NULL = system resource

idempotent：可重跑。所有 ALTER 用 IF NOT EXISTS，UPDATE 用 WHERE user_id IS NULL。

不做的事（留給 11.1.3）：
- ORM 加 user_id 字段
- API endpoint 加 user filter
- ALTER user_id SET NOT NULL（等所有 INSERT path 都帶了 user_id 再鎖）
"""
import os
import secrets
import sys

sys.path.insert(0, '/app')

from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import User
from app.services.auth_user import hash_password

ADMIN_EMAIL = os.environ.get('ADMIN_INITIAL_EMAIL', 'vincenzo000915@gmail.com').lower()

BUSINESS_TABLES = [
    'strategies',
    'positions',
    'orders',
    'trades',
    'backtest_results',
    'param_optimizations',
    'audit_log',
]


def seed_admin(password: str) -> User:
    """確保 user_id=1 是 admin。idempotent。"""
    u = User.query.get(1)
    if u:
        print(f'  → user_id=1 已存在: email={u.email} role={u.role}; 不動')
        return u
    # id=1 可能空著（test 過後清表），直接 INSERT
    db.session.execute(text(
        "INSERT INTO users (id, email, password_hash, role, subscription_tier, is_active, created_at) "
        "VALUES (1, :email, :pw, 'admin', 'pro', TRUE, NOW())"
    ), {'email': ADMIN_EMAIL, 'pw': hash_password(password)})
    # bump sequence 避免之後 INSERT 撞 id=1
    db.session.execute(text(
        "SELECT setval('users_id_seq', GREATEST((SELECT MAX(id) FROM users), 1))"
    ))
    db.session.commit()
    print(f'  → admin user 建立: id=1 email={ADMIN_EMAIL} role=admin tier=pro')
    return User.query.get(1)


def add_user_id_columns() -> None:
    """ALTER 7 業務表加 user_id (nullable, FK→users.id) + index. Idempotent."""
    for tbl in BUSINESS_TABLES:
        db.session.execute(text(
            f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)"
        ))
        db.session.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_{tbl}_user_id ON {tbl}(user_id)"
        ))
        print(f'  → {tbl}.user_id column + ix_{tbl}_user_id OK')
    db.session.commit()


def backfill_user_id() -> None:
    """所有現有 row → user_id=1 (admin)。

    backtest_results: 若 strategy_id 不為 NULL → 跟 strategy 同 user；
    若 strategy_id IS NULL → 留 NULL (候選池 backtest = system resource)
    """
    for tbl in ['strategies', 'positions', 'orders', 'trades', 'param_optimizations', 'audit_log']:
        r = db.session.execute(text(f"UPDATE {tbl} SET user_id=1 WHERE user_id IS NULL"))
        print(f'  → {tbl}: {r.rowcount} row → user_id=1')

    # backtest_results: 有 strategy_id 的跟 strategy 同 user_id
    r = db.session.execute(text(
        "UPDATE backtest_results br SET user_id = s.user_id "
        "FROM strategies s WHERE br.strategy_id = s.id AND br.user_id IS NULL"
    ))
    print(f'  → backtest_results (有 strategy_id): {r.rowcount} row → user_id=strategy.user_id')

    # 留 NULL 的是 candidate-stage backtest (system resource)
    cnt = db.session.execute(text(
        "SELECT COUNT(*) FROM backtest_results WHERE strategy_id IS NULL AND user_id IS NULL"
    )).scalar()
    print(f'  → backtest_results (candidate-stage): {cnt} row 留 NULL (system resource)')

    db.session.commit()


def main() -> None:
    password = os.environ.get('ADMIN_INITIAL_PASSWORD')
    generated = False
    if not password:
        password = secrets.token_urlsafe(16)
        generated = True

    app = create_app()
    with app.app_context():
        print('=' * 60)
        print('Phase 11.1.2: SaaS 多租户 migration')
        print('=' * 60)
        print(f'admin email: {ADMIN_EMAIL}')
        if generated:
            print('')
            print('⚠️  ADMIN_INITIAL_PASSWORD 未設 — 生成臨時密碼:')
            print(f'   {password}')
            print('⚠️  請登入後立刻改密碼（Phase 11.1.5 frontend 出來後可改）')
            print('')

        print('Step 1: seed admin user')
        seed_admin(password)
        print()
        print('Step 2: ALTER 7 business tables — add user_id column + index')
        add_user_id_columns()
        print()
        print('Step 3: backfill user_id → 1 for existing rows')
        backfill_user_id()
        print()
        print('=' * 60)
        print('完成。下一步 Phase 11.1.3 — ORM + routes user scoping')
        print('=' * 60)


if __name__ == '__main__':
    main()
