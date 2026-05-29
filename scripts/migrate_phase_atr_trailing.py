"""Phase 14k-158 C: positions 表加 peak_price 列 (移动止盈棘轮基准)

跑法 (container 内):
    docker exec quant-web-1 python /opt/quant/scripts/migrate_phase_atr_trailing.py

做什么:
- ALTER positions ADD COLUMN IF NOT EXISTS peak_price DOUBLE PRECISION (nullable)
  · 移动止盈状态: 持仓期最有利价 (long=最高/short=最低), trailing_sl() 棘轮基准.
  · NULL = 非 atr 仓/未初始化 → trailing 不生效, flat_pct 仓完全不受影响.

idempotent: 可重跑 (IF NOT EXISTS). 无数据回填 (现存持仓非 atr, 留 NULL 即可).
"""
import sys

sys.path.insert(0, '/app')

from sqlalchemy import text

from app import create_app
from app.extensions import db


def run():
    db.session.execute(text(
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS peak_price DOUBLE PRECISION"
    ))
    db.session.commit()
    # 验证
    col = db.session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='positions' AND column_name='peak_price'"
    )).fetchone()
    print(f"✓ positions.peak_price 列: {'存在' if col else '缺失!'}")


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        run()
