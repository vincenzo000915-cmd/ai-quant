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
任務：**強制輸出 3 個不同 timeframe 的新策略 candidates** — short / swing / long 各一個，互補多 TF 覆蓋。

## 🎯 多 TF 強制需求（v4 核心）

User 現有 7 個 running 策略**全是 4h swing**。多 TF 覆蓋是當前最大缺口。
每次輸出必須包含三類：

1. **short 類**（15m / 30m 二選一）→ category="short"
2. **swing 類**（1h / 4h 二選一）→ category="swing"
3. **long 類**（1d / 1w 二選一）→ category="long"

如果你覺得某 TF 找不到能過門檻的策略，**不要硬湊**，但 rationale 要說明為什麼當前
regime 下這個 TF 暫不適合（如「15m 在當前盤整 fee 必爆」等）。寧可 2 個好的也不要
3 個爛的。

## 🎯 各 TF 對應的回測門檻（針性化，不再一刀切 Sharpe ≥1.5）

| TF      | OOS Sharpe | Profit Factor | Trades / 90d | AR (annual) |
|---------|-----------|---------------|--------------|-------------|
| 15m/30m | ≥ 1.5     | **≥ 1.8** ⚠   | ≥ 60         | ≥ 10%       |
| 1h      | ≥ 1.5     | ≥ 1.5         | ≥ 40         | ≥ 8%        |
| 4h      | ≥ 1.5     | ≥ 1.5         | ≥ 30         | ≥ 8%        |
| 1d      | ≥ 1.5     | **≥ 1.4** ⚠   | ≥ 12 (1年回测) | ≥ 6%        |
| 1w      | ≥ 1.5     | ≥ 1.3         | ≥ 8 (3年回测)  | ≥ 5%        |

⚠ short tier 高 PF：手續費 0.2% 雙邊吃單頻策略 — PF 必須夠高才能扣 fee 後盈利
⚠ long tier 低 PF + 低 trades：1d/1w 樣本天然少，PF 1.4 + 12 trades/年合理

{SANDBOX_API_DOC}

## 🔴 關鍵約束（過去候選失敗模式 — 必學）：

### 1. 真實成本必須計入策略邏輯
- **每筆 trade 雙邊成本 = fee 0.05% × 2 + slippage 0.05% × 2 = 0.20%**
- 高頻策略 (>50 trades/月) 在 OKX 跑會被 0.2% 雙邊吃掉小波動利潤
- → 短 TF (15m/30m) 必須**每筆 ≥ 0.6% 利潤**才能扣 fee 後賺 PF > 1.8
- → swing (1h/4h) 每筆 ≥ 1% 利潤
- → long (1d/1w) 每筆 ≥ 3% 利潤
- 不同 TF 要用**完全不同**邏輯：short = breakout/momentum；swing = trend；long = regime-shift

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
- **TF 多樣性是當前頭等缺口** — 7 個 running 全 4h，要補 short + long 兩端

### 🚨 5. 頻率自估必須留 50% buffer（#44 案例教訓）
- 上一個 AI candidate #44 rsi_dip_recovery 預估「4-7 次/月」實際只有 **2 次/月**
- LLM 預估頻率系統性偏高 — **3 層 filter 串聯（如 ADX + EMA + RSI）通常只有 10-20% candles 通過**，比直覺低很多
- → 自估頻率時除以 2-3 作為 buffer；如果預估「5 次/月」實際可能「2 次/月」
- → **90 天回測必須有 ≥ 30 個 trades 才統計顯著**（不然 Sharpe 沒意義）
- → 寧可用 2 層 filter 多 trades，不要 3 層 filter 樣本不夠

### 🚨 6. profit_factor 1.5 是地板（#44 PF=1.07 失敗）
- profit_factor = win_pnl_sum / |loss_pnl_sum|，這是「賺得比輸得多多少倍」
- < 1.5 = 幾乎打平，加上未來市場噪音就是虧錢
- > 2.0 = 健康策略
- → 不要追求高勝率低盈虧比（如 win_rate 70% 但 avg_win = avg_loss），這在 fee 環境下會虧
- → 偏好 win_rate 40-55% + avg_win = 2× avg_loss（順勢突破特性）

### 🚨 7. AR < 5%/年的策略不要交（#44 AR=0.37% 浪費 slot）
- 真實 OKX 一年下來打平甚至虧手續費的策略**不該佔 capital slot**
- → 自評 AR 預估：90 天 trade × 平均賺 % / 投入 = ?
- → 太低就減少 filter / 換更敏感觸發 / 換不同 regime

### 🚨 8. 多 symbol 提升 sample size
- 同 strategy_type 在 BTC/ETH/SOL/AVAX 都跑可以提升 trade 樣本 4×
- → 自評時提一句「這策略適合 fan-out 哪些 symbol」（不只 single symbol 跑）

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

❌ **#44 案例**（半失敗 — Sharpe 0.55, PF 1.07, AR 0.37%）：
```python
# RSI dip + EMA200 trend + ADX<30 三層 filter
# 預估 5-9 次/月 → 實際 2 次/月，樣本不夠，PF 接近 1
```
為什麼半失敗：3 層 filter 串聯導致觸發太稀 + sample 不足 + win/loss 比平。

✅ **好策略**（學這個結構）：
```python
def bb_squeeze_breakout_signal(df, params):
    period = params.get('period', 20)
    if len(df) < period + 50:
        return 'hold'
    # 1. trend filter：EMA50 過濾方向（**只用 2 層 filter**）
    ema50 = ta.trend.EMAIndicator(df['close'], 50).ema_indicator()
    trend_up = df['close'].iloc[-1] > ema50.iloc[-1]
    # 2. squeeze 條件：BB 寬度 < 5%（盤整）— 觸發稀但不過稀
    bb = ta.volatility.BollingerBands(df['close'], period, 2)
    width = (bb.bollinger_hband().iloc[-1] - bb.bollinger_lband().iloc[-1]) / df['close'].iloc[-1]
    if width > 0.05:
        return 'hold'
    # 3. 突破方向決定買賣（跟趨勢一致）
    if trend_up and df['close'].iloc[-1] > bb.bollinger_hband().iloc[-1]:
        return 'buy'
    if not trend_up and df['close'].iloc[-1] < bb.bollinger_lband().iloc[-1]:
        return 'sell'
    return 'hold'
```
為什麼好：2 層 filter 不過稀；squeeze 等盤整突破有 momentum；trade pf 通常 2+。

## 嚴格 JSON 輸出（不要 markdown 包圍）：
{{
  "analysis": "2-3 句話：現有策略覆蓋與缺口分析（強調 TF 多樣性缺口）",
  "improvements": [
    {{
      "candidate_type": "snake_case_slug",
      "signal_fn_name": "..._signal",
      "category": "short" | "swing" | "long",
      "timeframe": "15m | 30m (short) / 1h | 4h (swing) / 1d | 1w (long)",
      "default_params": {{}},
      "parsed_signal": "def ..._signal(df, params): ... (含 trend filter + 嚴格觸發條件)",
      "rationale": "為什麼這策略能過該 TF 對應門檻（必須證明：頻率合理 / 趨勢過濾 / 不 overfit / 補哪個 TF 缺口）",
      "self_estimate": {{
        "trades_per_month": "整數 — 月觸發次數估計（已留 50% buffer）",
        "trades_in_90d_backtest": "整數 — short ≥60 / swing ≥30 / long ≥3 (1d) 才合格",
        "expected_profit_factor": "浮點數 — short ≥1.8 / swing ≥1.5 / long ≥1.4",
        "expected_annual_return_pct": "浮點數 — short ≥10 / swing ≥8 / long ≥6",
        "filter_layers": "整數 — 過濾器層數，建議 ≤ 2",
        "fan_out_symbols": "list — 適合擴展的 symbol 例如 [BTC,ETH,SOL]"
      }}
    }}
  ]
}}

**輸出順序強制**：improvements 必須包含至少 1 個 short + 1 個 swing + 1 個 long（除非
某 TF 找不到能過門檻的，明確說明跳過原因）。

## 自檢清單（rationale 必須涵蓋）：
- 預估月 trade 頻率（理想 10-30/月）+ 90 天 sample ≥ 30
- 用了什麼 trend filter
- 用了什麼 vol/regime filter（squeeze / ATR / ADX）
- 為什麼這策略補完現有 7 個 Ichimoku/PSAR/SuperTrend 系的缺口
- 哪種市況會盈利 / 哪種會虧損
- 預估 profit_factor / AR — 必須過門檻

要求：
- improvements 1-3 個（質量 > 數量，1 個好的 > 3 個爛的）
- parsed_signal 必須能直接 exec + 沙箱跑通
- timeframe 跟 category 匹配（short→15m/30m; swing→1h/4h; long→1d/1w）
- **self_estimate 必填且符合門檻**（自評不過直接重設計，不要交沒信心的）
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
