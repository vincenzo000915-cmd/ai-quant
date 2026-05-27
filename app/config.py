import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'quant-secret-key-change-me')

    # Phase 11.1: JWT — fallback 到 SECRET_KEY 但鼓勵單獨設
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = 60 * 60 * 24 * 30  # 30 天
    JWT_TOKEN_LOCATION = ['headers']
    JWT_HEADER_NAME = 'Authorization'
    JWT_HEADER_TYPE = 'Bearer'

    # Database
    DB_HOST = os.getenv('DB_HOST', 'postgres')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME', 'quant')
    DB_USER = os.getenv('DB_USER', 'quant')
    DB_PASS = os.getenv('DB_PASS', 'quant_pass')
    SQLALCHEMY_DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Phase 12.36 + 14k-75: 连接池调优 — 14k-74 worker concurrency 4→8 后需更大 pool
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,           # 14k-75: 8 worker × 1.2 ≈ 10 常驻 (从 5 提升)
        'max_overflow': 10,        # 高峰 +10 (总 20)
        'pool_recycle': 1800,
        'pool_pre_ping': True,
        'pool_timeout': 20,
        # 14k-75: Postgres 服务端自动 kill idle in transaction > 5min
        # (LLM call 平均 30s-3min, 5min 是安全阈值, 太长就是 bug)
        'connect_args': {
            'options': '-c idle_in_transaction_session_timeout=300000',   # 5 分钟 (毫秒)
            'connect_timeout': 10,
        },
    }

    # Redis
    REDIS_HOST = os.getenv('REDIS_HOST', 'redis')
    REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'

    # Celery
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL

    # Exchange (OKX)
    EXCHANGE_NAME = os.getenv('EXCHANGE_NAME', 'okx')
    EXCHANGE_API_KEY = os.getenv('EXCHANGE_API_KEY', '')
    EXCHANGE_SECRET = os.getenv('EXCHANGE_SECRET', '')
    EXCHANGE_PASSPHRASE = os.getenv('EXCHANGE_PASSPHRASE', '')
    EXCHANGE_TESTNET = os.getenv('EXCHANGE_TESTNET', 'true') == 'true'

    # Trading params
    DEFAULT_SYMBOL = 'BTC/USDT'
    DEFAULT_TIMEFRAME = '4h'
    KLINE_LIMIT = 500  # 最多保留K線數量

    # Risk control
    MAX_DAILY_LOSS = float(os.getenv('MAX_DAILY_LOSS', '10'))  # 百分比
    MAX_POSITIONS = int(os.getenv('MAX_POSITIONS', '3'))
    MAX_POSITION_SIZE = float(os.getenv('MAX_POSITION_SIZE', '20'))  # 單筆上限百分比
    STOP_LOSS_PERCENT = float(os.getenv('STOP_LOSS_PERCENT', '5'))
    TAKE_PROFIT_PERCENT = float(os.getenv('TAKE_PROFIT_PERCENT', '15'))
    CONSECUTIVE_LOSS_LIMIT = int(os.getenv('CONSECUTIVE_LOSS_LIMIT', '3'))

    # Notification
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
