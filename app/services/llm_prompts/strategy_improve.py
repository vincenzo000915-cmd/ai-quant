"""Phase 11.5.10: 策略改進顧問 — 閉環最後一環

AI 看你現有 strategies + 表現 + regime + advisor → 主動生成 1-3 個補完性新策略
→ 沙箱驗證 → 寫 strategy_candidates → 接 candidate_pipeline → 回測 → qualified
→ auto_promote → auto_apply → LIVE。

跟 Phase 11.5.4 (用戶描述驅動) 互補：
- 11.5.4 = from scratch (user 描述)
- 11.5.10 = from data (AI 看現況自己決定)
"""
from __future__ import annotations

import datetime
import json

from sqlalchemy import desc, func
from app.extensions import db
from app.models import Strategy, Trade, BacktestResult
from app.services.candidate_sandbox import verify_signal_fn
from app.services.llm_provider import call_llm
from app.services.llm_prompts.strategy_generate import SANDBOX_API_DOC, _extract_json
from app.services.user_scope import scoped_query, apply_user_filter

SYSTEM_PROMPT = f"""你是專業量化策略工程師。User 給你他現有策略組合 + 最近表現 + 當前 regime。
任務：**生成 1-3 個能通過嚴格回測門檻**（OOS Sharpe ≥ 1.5）**的新策略**。

{SANDBOX_API_DOC}

## 🔴 關鍵約束（過去 4 個 AI 候選全失敗，原因都在這）：

### 1. 真實成本必須計入策略邏輯
- **每筆 trade 雙邊成本 = fee 0.05% × 2 + slippage 0.05% × 2 = 0.20%**
- 高頻策略 (>50 trades/月) 在 OKX 跑會被 0.2% 雙邊吃掉小波動利潤
- → 寧可 5 trades/月每筆 1% 利潤，也不要 100 trades/月每筆 0.3% 利潤
- → **避免** scalping / mean reversion 在 15m/30m 用嚴格觸發
- → **偏好** swing/long 等待大波段，4h 或 1d

### 2. 信號要乾淨
- 連續觸發同方向是 noise（user 不會喜歡看到 BUY-BUY-BUY-BUY 連 5 根）
- **必須**：buy 信號後等持倉 close 才能下次 buy；signal function 不知道持倉所以要靠**條件嚴格**自然降頻
- 避免「指標 > 閾值就 buy」這種粗暴邏輯 — 加 **trend filter** (EMA50/200) + **vol filter** (ATR/BB width)

### 3. 不要 overfit 短期
- 不要用過短回溯窗口 (< 50 根)
- 不要用魔法數字 (e.g. RSI < 27 而非 30) — 標準閾值 30/70/0.5 等
- 不要組合 > 3 個指標

### 4. 對齊 user 現況
- user 帳戶小 ($73)，每筆 $4，杠杆 15x — 名義 $60
- 偏好 SL -5% / TP +8% 的「短週期但不極短」邏輯
- 已有 trend follower（Ichimoku/PSAR/SuperTrend），缺 **mean reverter** + **breakout** + **range trader**

## 範例對比（學這個）：

❌ **差策略**（過去失敗的）：
```python
def bb_scalp_signal(df, params):
    bb = compute_bb(df['close'], 20, 2)
    if df.close.iloc[-1] < bb.lower:
        return 'buy'
    if df.close.iloc[-1] > bb.upper:
        return 'sell'
    return 'hold'
```
為什麼差：頻率太高 (~5/天)，fee 吃光；橫盤被反覆觸發。

✅ **好策略**（學這個結構）：
```python
def bb_squeeze_breakout_signal(df, params):
    period = params.get('period', 20)
    if len(df) < period + 50:
        return 'hold'
    # 1. trend filter：EMA50 過濾方向
    ema50 = ta.trend.EMAIndicator(df['close'], 50).ema_indicator()
    trend_up = df['close'].iloc[-1] > ema50.iloc[-1]
    # 2. squeeze 條件：BB 寬度 < 5%（盤整）
    bb = ta.volatility.BollingerBands(df['close'], period, 2)
    width = (bb.bollinger_hband().iloc[-1] - bb.bollinger_lband().iloc[-1]) / df['close'].iloc[-1]
    if width > 0.05:
        return 'hold'   # 沒擠壓不交易
    # 3. 突破方向決定買賣（跟趨勢一致才動）
    if trend_up and df['close'].iloc[-1] > bb.bollinger_hband().iloc[-1]:
        return 'buy'
    if not trend_up and df['close'].iloc[-1] < bb.bollinger_lband().iloc[-1]:
        return 'sell'
    return 'hold'
```
為什麼好：trend filter 過濾逆勢；squeeze 條件大部分時間 hold（降頻）；突破才動。

## 嚴格 JSON 輸出（不要 markdown 包圍）：
{{
  "analysis": "2-3 句話：現有策略覆蓋與缺口分析",
  "improvements": [
    {{
      "candidate_type": "snake_case_slug",
      "signal_fn_name": "..._signal",
      "category": "ultra" | "short" | "swing" | "long",
      "timeframe": "15m" | "30m" | "1h" | "4h" | "1d" | "1w",
      "default_params": {{}},
      "parsed_signal": "def ..._signal(df, params): ... (含 trend filter + 嚴格觸發條件)",
      "rationale": "為什麼這策略能過 OOS Sharpe ≥ 1.5（必須證明：頻率不高 / 趨勢過濾 / 嚴格觸發 / 不 overfit）"
    }}
  ]
}}

## 自檢清單（rationale 必須涵蓋）：
- 預估月 trade 頻率（理想 5-30/月）
- 用了什麼 trend filter
- 用了什麼 vol/regime filter（squeeze / ATR / ADX）
- 為什麼這策略補完現有 7 個 Ichimoku/PSAR/SuperTrend 系的缺口
- 哪種市況會盈利 / 哪種會虧損

要求：
- improvements 1-3 個（質量 > 數量，1 個好的 > 3 個爛的）
- parsed_signal 必須能直接 exec + 沙箱跑通
- timeframe 跟 category 匹配（short→15m/30m; swing→1h/4h; long→1d/1w）
"""


def improve_strategies(user_id: int) -> dict:
    """主入口。回 {ok, analysis, generated: [candidate_ids], rejected: [{type, error}], llm_meta, error?}"""

    running = scoped_query(Strategy).filter_by(status='running').all()
    if not running:
        return {'ok': False, 'error': '無 running 策略，無從改進'}

    # 拉每策略最新 backtest
    bt_map = {}
    sub = apply_user_filter(
        db.session.query(
            BacktestResult.strategy_id,
            func.max(BacktestResult.created_at).label('latest'),
        ), BacktestResult,
    ).filter(BacktestResult.status == 'completed').group_by(BacktestResult.strategy_id).subquery()
    latest_bts = apply_user_filter(db.session.query(BacktestResult), BacktestResult).join(
        sub,
        (BacktestResult.strategy_id == sub.c.strategy_id) &
        (BacktestResult.created_at == sub.c.latest)
    ).all()
    for bt in latest_bts:
        bt_map[bt.strategy_id] = bt

    # 過去 7 日 trades 統計
    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    trades_stats = {}
    trades = apply_user_filter(
        db.session.query(Trade), Trade
    ).filter(Trade.exit_time >= since).all()
    for t in trades:
        s = trades_stats.setdefault(t.strategy_id, {'wins': 0, 'losses': 0, 'pnl': 0.0, 'count': 0})
        s['count'] += 1
        s['pnl'] += t.pnl or 0
        if (t.pnl or 0) > 0:
            s['wins'] += 1
        else:
            s['losses'] += 1

    # 拉當前 regime
    try:
        from app.services.regime_detector import detect_regime
        unique_tf = sorted({(s.symbol, s.timeframe) for s in running})
        regimes = {}
        for sym, tf in unique_tf[:6]:
            regimes[f'{sym}@{tf}'] = detect_regime(sym, tf)
    except Exception:
        regimes = {}

    # 構造 prompt
    lines = ['## 現有 running 策略\n']
    for s in running:
        bt = bt_map.get(s.id)
        live = trades_stats.get(s.id, {'count': 0, 'pnl': 0, 'wins': 0, 'losses': 0})
        lines.append(
            f'- #{s.id} {s.name} (type={s.type}, {s.symbol} {s.timeframe}, category={s.category})\n'
            f'  Backtest: '
            f'{f"Sharpe={bt.sharpe_ratio:.2f}, MaxDD={bt.max_drawdown_pct:.1f}%, AR={bt.annual_return_pct:.1f}%" if bt else "(無 backtest)"}\n'
            f'  Live 7日: {live["count"]} trades, PnL ${live["pnl"]:+.2f}, '
            f'{live["wins"]}勝/{live["losses"]}敗'
        )

    lines.append('\n## 當前 regime\n')
    for k, r in regimes.items():
        lines.append(f'- {k}: regime={r.get("regime")}, ADX={r.get("adx", "?")}, Hurst={r.get("hurst", "?")}')

    lines.append('\n## 請按系統提示分析缺口，生成 1-3 個補完性新策略 JSON')
    prompt = '\n'.join(lines)

    llm = call_llm(
        user_id=user_id,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=6000,    # 多個 candidate 需要大空間
    )
    if not llm.get('ok'):
        return {'ok': False, 'error': f'LLM 失敗: {llm.get("error")}', 'llm_meta': llm}

    spec = _extract_json(llm['text'])
    if spec is None or not isinstance(spec.get('improvements'), list):
        return {'ok': False, 'error': 'LLM 輸出無法解析或缺 improvements',
                'llm_meta': llm, 'raw_output': llm['text'][:800]}

    analysis = spec.get('analysis', '')
    improvements = spec['improvements']

    # 沙箱驗證每個 + 寫表
    generated = []
    rejected = []
    from app.models import StrategyCandidate
    existing_types = {s.type for s in scoped_query(Strategy).all()}
    existing_candidate_types = {c.candidate_type for c in StrategyCandidate.query.all() if c.candidate_type}

    for imp in improvements:
        ctype = imp.get('candidate_type')
        # 跟現有策略 type 重複避免
        if not ctype or ctype in existing_types or ctype in existing_candidate_types:
            ctype_suffixed = f'{ctype}_{int(datetime.datetime.utcnow().timestamp())}' if ctype else None
            if ctype_suffixed is None:
                rejected.append({'reason': 'no candidate_type'})
                continue
            ctype = ctype_suffixed

        v = verify_signal_fn(imp.get('parsed_signal', ''),
                             imp.get('signal_fn_name', ''),
                             imp.get('default_params') or {})
        if not v.get('ok'):
            rejected.append({'candidate_type': ctype, 'reason': f'sandbox: {v.get("error")}'})
            continue

        rec = StrategyCandidate(
            source='manual',
            source_name=f'AI improve (user {user_id})',
            source_author=f'user:{user_id}:improve',
            source_meta={'analysis': analysis, 'rationale': imp.get('rationale'),
                         'llm_provider': llm.get('provider_used'),
                         'llm_model': llm.get('model_used')},
            raw_code=f'AI improve analysis: {analysis}\n\nrationale: {imp.get("rationale", "")}',
            raw_lang='ai-improve',
            parsed_signal=imp['parsed_signal'],
            signal_fn_name=imp['signal_fn_name'],
            candidate_type=ctype,
            category=imp.get('category', 'swing'),
            timeframe=imp.get('timeframe', '4h'),
            default_params=imp.get('default_params') or {},
            llm_notes=imp.get('rationale'),
            llm_model=llm.get('model_used', 'unknown'),
            status='translated',
        )
        db.session.add(rec)
        db.session.flush()
        generated.append({
            'candidate_id': rec.id,
            'candidate_type': ctype,
            'signal_fn_name': imp['signal_fn_name'],
            'category': imp.get('category'),
            'timeframe': imp.get('timeframe'),
            'rationale': imp.get('rationale'),
        })

    db.session.commit()

    return {
        'ok': True,
        'analysis': analysis,
        'generated': generated,
        'rejected': rejected,
        'llm_meta': {
            'provider_used': llm.get('provider_used'),
            'model_used': llm.get('model_used'),
            'latency_ms': llm.get('latency_ms'),
            'usage': llm.get('usage'),
        },
    }
