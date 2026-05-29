"""Phase 15: 守门员富市场感知层 — 汇总当前市场富特征喂配对 (北极星"全面实时多维分析")

蓝图 project-phase15-blueprint。user 点出: 守门员只用 regime 一个粗标签配策略不够,
要拿全市场富指标 (P0 采的 5m/l2/funding/形态动能 + 波动/量/方向/多周期) 才配得准.

perceive_market() 汇总:
- regime (趋势/震荡)            ← regime_detector 纯函数
- direction (上/下/横)          ← 价 vs MA20 + 近期涨跌
- volatility (高/正常/低)       ← ATR/price
- volume (放量/正常/缩量)        ← 当前量 vs 均量
- mtf_aligned (多周期regime一致) ← base TF vs aux 细 TF regime
- price_action (形态/猎杀针/动能)← candle_patterns (P0c)
- funding (费率/拥挤侧)          ← FundingRate (P0b, 可回测)
- orderbook (盘口失衡)           ← l2 (P0b, **仅 live 实时**, 回测无历史)
"""
from __future__ import annotations


def _recent_funding(symbol: str, at_ts: int | None = None) -> dict | None:
    """最近(或某时点前)资金费率 + 拥挤侧。"""
    try:
        from app.models import FundingRate
        q = FundingRate.query.filter_by(symbol=symbol)
        if at_ts:
            q = q.filter(FundingRate.timestamp <= at_ts)
        f = q.order_by(FundingRate.timestamp.desc()).first()
        if not f or f.funding_rate is None:
            return None
        r = f.funding_rate
        crowded = 'long' if r > 0.0001 else ('short' if r < -0.0001 else 'neutral')
        return {'rate': round(r, 6), 'crowded_side': crowded}
    except Exception:
        return None


def perceive_market(symbol: str, base_candles: list, aux_candles: list | None = None,
                    base_tf: str = '15m', include_orderbook: bool = False) -> dict:
    """守门员富市场感知: 当前市场富特征 dict, 喂策略配对。
    include_orderbook=True 才拉实时 l2 (仅 live; 回测无历史 l2)。"""
    from app.services.gatekeeper import regime_from_candles
    from app.services import candle_patterns as cp
    if not base_candles or len(base_candles) < 25:
        return {'ok': False, 'reason': '数据不足'}
    closes = [c['close'] for c in base_candles]

    # regime
    regime = regime_from_candles(base_candles)
    # direction: 价 vs MA20 + 近20根涨跌
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else closes[-1]
    chg = (closes[-1] - closes[-20]) / closes[-20] * 100 if len(closes) >= 20 else 0
    if closes[-1] > ma20 and chg > 0.5:
        direction = 'up'
    elif closes[-1] < ma20 and chg < -0.5:
        direction = 'down'
    else:
        direction = 'flat'
    # volatility: ATR/price
    atr = cp.compute_atr(base_candles)
    atr_now = atr[-1] if atr and atr[-1] else None
    vol_pct = (atr_now / closes[-1] * 100) if atr_now else None
    volatility = ('high' if vol_pct and vol_pct > 1.5 else
                  ('low' if vol_pct and vol_pct < 0.5 else 'normal'))
    # volume: 当前 vs 近20均量
    vols = [c.get('volume', 0) or 0 for c in base_candles]
    avgv = sum(vols[-20:-1]) / 19 if len(vols) >= 20 else (sum(vols) / len(vols) if vols else 1)
    vol_ratio = vols[-1] / avgv if avgv > 0 else 1.0
    volume = 'surge' if vol_ratio > 1.8 else ('dry' if vol_ratio < 0.6 else 'normal')
    # 多周期对齐: base vs aux(更细) regime 一致?
    aux_regime = (regime_from_candles(aux_candles)
                  if aux_candles and len(aux_candles) >= 60 else None)
    mtf_aligned = (aux_regime == regime) if aux_regime and regime != 'unknown' else None
    # 形态/猎杀针/动能 (aux 更细优先)
    pa_src = aux_candles if (aux_candles and len(aux_candles) >= 35) else base_candles
    pa = cp.read_price_action(pa_src)
    price_action = {
        'pattern': (pa.get('pattern') or {}).get('pattern'),
        'pattern_dir': (pa.get('pattern') or {}).get('direction'),
        'hunt': (pa.get('hunt') or {}).get('is_hunt'),
        'momentum': (pa.get('momentum') or {}).get('state'),
    }
    # funding (P0b, 可回测)
    funding = _recent_funding(symbol)
    # 画像需求指标的当前状态 (补齐感知: stochastic/cci/ichimoku/psar/donchian/bollinger/vwap...)
    from app.services.market_indicators import compute_market_indicators
    _indicators = compute_market_indicators(base_candles)
    # orderbook (P0b l2, 仅 live)
    orderbook = None
    if include_orderbook:
        try:
            from app.services.hyperliquid_service import fetch_l2_features
            f = fetch_l2_features(symbol, depth=5)
            if f.get('ok'):
                orderbook = {'imbalance': f['imbalance'], 'spread_bps': f['spread_bps']}
        except Exception:
            orderbook = None

    return {
        'ok': True, 'symbol': symbol, 'regime': regime, 'direction': direction,
        'volatility': volatility, 'vol_pct': round(vol_pct, 3) if vol_pct else None,
        'volume': volume, 'vol_ratio': round(vol_ratio, 2),
        'mtf_aligned': mtf_aligned, 'aux_regime': aux_regime,
        'price_action': price_action, 'funding': funding, 'orderbook': orderbook,
        'indicators': _indicators,
    }
