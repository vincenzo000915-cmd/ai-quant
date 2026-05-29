"""Phase 15 P2 硬门验证脚本 — judgment_gate on/off 回测对比 (可复跑)

用途: 在真实 candle 上跑多策略 × {off / entry-only / exit-only / both} 的判断闸对比,
证明 entry_gate/exit_gate 是否净 EV 提升 (回测真理: 拦掉的坏单 > 杀掉的好单, 才上 live)。

跑法: docker exec quant-celery-worker-1 bash -c 'cd /app && PYTHONPATH=/app python /opt/quant/scripts/judgment_gate_hardgate.py'

⚠️ 局限 (诚实记录, 见 commit/memory):
- 5m aux 受 OKX 单拉上限约束 (~2000根=5天) → 只能验证最近数天, 且这段恰是震荡市
  (volatility_breakout 该躺平), 无 #43/#45 那种趋势大赢家 → exit_gate 利润锁 0 触发 (无样本验证)。
- entry_gate 在 7 策略上普遍净正 (无一变差, 含转盈) = 有 edge 证据; 但仍是单一时段/2 symbol,
  上 P3 live 前需更长史 + 含趋势日 (验 exit 利润锁) + 观察期满。
"""
import sys

sys.path.insert(0, '/app')
from app import create_app  # noqa: E402

STRATS = ['volatility_breakout', 'macd', 'supertrend', 'trend_following',
          'bollinger', 'atr_breakout', 'keltner_channel']
SYMBOLS = ('ETH/USDT', 'AVAX/USDT')


def main():
    app = create_app()
    with app.app_context():
        from app.services.exchange_service import fetch_ohlcv
        from app.services.strategy_engine import get_signal
        from app.services.backtest_engine import run_backtest
        from app.services.judgment_gate import make_entry_gate, make_exit_gate

        def to_c(rows):
            return [{'open': r['open'], 'high': r['high'], 'low': r['low'],
                     'close': r['close'], 'volume': r['volume'],
                     'timestamp': r['timestamp']} for r in rows]

        data = {}
        for sym in SYMBOLS:
            base = to_c(fetch_ohlcv(sym, '1h', limit=500))
            aux = to_c(fetch_ohlcv(sym, '5m', limit=2000))
            amin = aux[0]['timestamp']
            base = [c for c in base if c['timestamp'] >= amin]  # 截到 aux 覆盖区
            data[sym] = (base, aux)

        print(f"{'策略':<20}{'OFF':>9}{'entry':>9}{'exit':>9}{'both':>9}{'Δboth':>9}{'否决':>6}{'锁利':>6}")
        tot = {k: 0 for k in ('off', 'entry', 'exit', 'both', 'blk', 'lck')}
        for st in STRATS:
            sig = (lambda s: (lambda df, p: get_signal(s, df, p)))(st)
            agg = {k: 0 for k in ('off', 'entry', 'exit', 'both', 'blk', 'lck')}
            for sym, (base, aux) in data.items():
                kw = dict(timeframe='1h', leverage=15.0, signal_fn=sig,
                          exchange='hyperliquid', symbol=sym,
                          aux_candles=aux, aux_timeframe='5m')
                off = run_backtest(st, {}, base, timeframe='1h', leverage=15.0,
                                   signal_fn=sig, exchange='hyperliquid', symbol=sym)
                en = run_backtest(st, {}, base, entry_gate=make_entry_gate(), **kw)
                ex = run_backtest(st, {}, base, exit_gate=make_exit_gate(), **kw)
                both = run_backtest(st, {}, base, entry_gate=make_entry_gate(),
                                    exit_gate=make_exit_gate(), **kw)
                agg['off'] += off['total_pnl']; agg['entry'] += en['total_pnl']
                agg['exit'] += ex['total_pnl']; agg['both'] += both['total_pnl']
                agg['blk'] += both['entry_gate_blocks']; agg['lck'] += both['exit_gate_locks']
            d = agg['both'] - agg['off']
            print(f"{st:<20}{agg['off']:>9.2f}{agg['entry']:>9.2f}{agg['exit']:>9.2f}"
                  f"{agg['both']:>9.2f}{d:>+9.2f}{agg['blk']:>6}{agg['lck']:>6}")
            for k in tot:
                tot[k] += agg[k]
        print('-' * 86)
        print(f"{'合计':<20}{tot['off']:>9.2f}{tot['entry']:>9.2f}{tot['exit']:>9.2f}"
              f"{tot['both']:>9.2f}{tot['both']-tot['off']:>+9.2f}{tot['blk']:>6}{tot['lck']:>6}")
        print(f"\nentry-only Δ={tot['entry']-tot['off']:+.2f}  "
              f"exit-only Δ={tot['exit']-tot['off']:+.2f}  both Δ={tot['both']-tot['off']:+.2f}")


if __name__ == '__main__':
    main()
