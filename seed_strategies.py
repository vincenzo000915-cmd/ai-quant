"""注入8個策略到資料庫"""
import sys
sys.path.insert(0, '/opt/quant')
from app import create_app
from app.extensions import db
from app.models import Strategy

app = create_app()
with app.app_context():
    strategies = [
        {
            'name': '均線交叉策略',
            'type': 'ma_crossover',
            'params': {'fast': 5, 'slow': 20},
            'symbol': 'BTC/USDT',
            'timeframe': '4h',
            'max_positions': 1,
            'max_daily_loss': 10,
        },
        {
            'name': 'RSI反轉策略',
            'type': 'rsi',
            'params': {'period': 14, 'oversold': 30, 'overbought': 70},
            'symbol': 'BTC/USDT',
            'timeframe': '4h',
            'max_positions': 1,
            'max_daily_loss': 10,
        },
        {
            'name': '布林帶突破策略',
            'type': 'bollinger',
            'params': {'period': 20, 'std': 2},
            'symbol': 'BTC/USDT',
            'timeframe': '4h',
            'max_positions': 1,
            'max_daily_loss': 10,
        },
        {
            'name': 'MACD策略',
            'type': 'macd',
            'params': {'fast': 12, 'slow': 26, 'signal': 9},
            'symbol': 'BTC/USDT',
            'timeframe': '4h',
            'max_positions': 1,
            'max_daily_loss': 10,
        },
        {
            'name': '趨勢跟蹤(ADX+EMA)',
            'type': 'trend_following',
            'params': {'adx_period': 14, 'adx_threshold': 25, 'ema_fast': 20, 'ema_slow': 50},
            'symbol': 'BTC/USDT',
            'timeframe': '4h',
            'max_positions': 1,
            'max_daily_loss': 10,
        },
        {
            'name': '波動率突破(Donchian)',
            'type': 'volatility_breakout',
            'params': {'channel_period': 20, 'breakout_pct': 0.5},
            'symbol': 'BTC/USDT',
            'timeframe': '4h',
            'max_positions': 1,
            'max_daily_loss': 10,
        },
        {
            'name': '均值回歸(布林+RSI)',
            'type': 'mean_reversion',
            'params': {'bb_period': 20, 'bb_std': 2, 'rsi_period': 14, 'rsi_low': 30, 'rsi_high': 70},
            'symbol': 'BTC/USDT',
            'timeframe': '4h',
            'max_positions': 1,
            'max_daily_loss': 10,
        },
        {
            'name': 'SuperTrend策略',
            'type': 'supertrend',
            'params': {'period': 10, 'multiplier': 3},
            'symbol': 'BTC/USDT',
            'timeframe': '4h',
            'max_positions': 1,
            'max_daily_loss': 10,
        },
    ]

    for s in strategies:
        existing = Strategy.query.filter_by(name=s['name']).first()
        if existing:
            print(f'⏭️  {s["name"]} 已存在')
            continue
        strategy = Strategy(**s)
        db.session.add(strategy)
        db.session.commit()
        print(f'✅  {s["name"]} 已新增')

    total = Strategy.query.count()
    print(f'\n📊 資料庫中共 {total} 個策略')
