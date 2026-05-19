"""Wave 1 — 補完經典策略庫（12 個新策略 × 4 個類別）"""
import sys
sys.path.insert(0, '/app')
from app import create_app
from app.extensions import db
from app.models import Strategy

WAVE1 = [
    # === ULTRA 15m（極短）===
    {'name': 'VWAP 回歸',          'type': 'vwap_reversion',   'category': 'ultra', 'timeframe': '15m',
     'params': {'period': 20, 'deviation_pct': 1.0}},
    {'name': 'Keltner 通道',       'type': 'keltner_channel',  'category': 'ultra', 'timeframe': '15m',
     'params': {'ema_period': 20, 'atr_period': 10, 'multiplier': 2}},
    {'name': 'Stochastic 反轉',    'type': 'stochastic',       'category': 'ultra', 'timeframe': '15m',
     'params': {'k_period': 14, 'd_period': 3, 'oversold': 20, 'overbought': 80}},

    # === SHORT 1h（短線）===
    {'name': 'CCI 反轉',           'type': 'cci_reversal',     'category': 'short', 'timeframe': '1h',
     'params': {'period': 20, 'threshold': 100}},
    {'name': 'ATR 通道突破',       'type': 'atr_breakout',     'category': 'short', 'timeframe': '1h',
     'params': {'ema_period': 20, 'atr_period': 14, 'multiplier': 1.5}},
    {'name': 'Heikin Ashi 趨勢',   'type': 'heikin_ashi',      'category': 'short', 'timeframe': '1h',
     'params': {'confirm_bars': 3}},

    # === SWING 4h（波段）===
    {'name': 'Ichimoku 雲帶',      'type': 'ichimoku',         'category': 'swing', 'timeframe': '4h',
     'params': {'tenkan': 9, 'kijun': 26, 'senkou_b': 52}},
    {'name': 'TEMA 三重 EMA',      'type': 'tema',             'category': 'swing', 'timeframe': '4h',
     'params': {'fast': 10, 'slow': 30}},
    {'name': 'Parabolic SAR',      'type': 'psar',             'category': 'swing', 'timeframe': '4h',
     'params': {'step': 0.02, 'max_step': 0.2}},

    # === LONG 4h（長線）===
    {'name': '黃金交叉 50/200',    'type': 'golden_cross',     'category': 'long',  'timeframe': '4h',
     'params': {'fast': 50, 'slow': 200}},
    {'name': 'MACD + 200MA 趨勢',  'type': 'macd_trend_filter','category': 'long',  'timeframe': '4h',
     'params': {'fast': 12, 'slow': 26, 'signal': 9, 'ma': 200}},
    {'name': '週樞軸點突破',       'type': 'weekly_pivot',     'category': 'long',  'timeframe': '4h',
     'params': {'lookback': 42}},
]

if __name__ == '__main__':
    app = create_app()
    added = 0
    skipped = 0
    with app.app_context():
        for s in WAVE1:
            existing = Strategy.query.filter_by(name=s['name']).first()
            if existing:
                print(f'⏭️  {s["name"]} 已存在 (id={existing.id})')
                skipped += 1
                continue
            strategy = Strategy(
                name=s['name'],
                type=s['type'],
                category=s['category'],
                params=s['params'],
                symbol='BTC/USDT',
                timeframe=s['timeframe'],
                status='stopped',     # 先停著 → 回測完評估後再決定啟用
                max_positions=1,
                max_daily_loss=10,
            )
            db.session.add(strategy)
            db.session.commit()
            print(f'✅ {s["name"]} 已新增 (id={strategy.id}, type={s["type"]}, {s["timeframe"]})')
            added += 1

        total = Strategy.query.count()
        print(f'\n📊 Wave 1 完成：新增 {added} 個，跳過 {skipped} 個。DB 共 {total} 個策略。')
