"""Phase 14k-109: 单一漏斗 backtest_writer — 所有产 walk-forward backtest 结果的路径都过这扇门.

背景:
  历史上 backtest 数据进 BacktestResult 表分散在多处 (routes._run_strategy_backtest /
  param_optimizer / candidate_pipeline / 各种 ad-hoc). 而 candidate.backtest_result_id
  这个 "AI 看的真值字段" 只有 candidate_pipeline:280 那一处会回填. 结果:
    - param_optimizer 跑完写 param_optimizations.candidate_results JSON, 不写 BacktestResult,
      不回填 candidate -> AI 永远以为 "未跑过真回测", 反复重派 signal_grid 烧 worker
    - 28 个 promoted candidate backtest_result_id NULL (历史残余)
    - 用户洞察: 以后 AI 合成 / 新策略类型只要绕过这扇门, 同样会变 phantom

规约 (单一入口):
  从此, 任何路径产 walk-forward 结果 + 要让数据成为系统 "真值", 都必须调
  record_backtest_from_wf() 或 record_backtest_from_opt_combo(). 不准 inline new BacktestResult().
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from app.extensions import db
from app.models import BacktestResult, Strategy, StrategyCandidate


def _maybe_link_candidate(strategy: Strategy, bt_id: int) -> bool:
    """若 strategy 是 promoted candidate, 回填 candidate.backtest_result_id.

    返回 True 表示回填了 (caller 可 log), False 表示无 candidate 或已链接.
    """
    if not strategy.candidate_id:
        return False
    cand = StrategyCandidate.query.get(strategy.candidate_id)
    if not cand:
        return False
    # 覆盖式回填 — 拿最新的 backtest 作为 candidate 真值 (老的可能是文献 Sharpe / 过期)
    cand.backtest_result_id = bt_id
    return True


def record_backtest_from_wf(
    strategy: Strategy,
    wf_result: dict,
    *,
    source: str,
    params: Optional[dict] = None,
) -> int:
    """从 run_walkforward_backtest 的完整 wf dict 写一笔 BacktestResult.

    wf_result 结构对齐 backtest_engine.run_walkforward_backtest:
      {full: {...}, in_sample: {...}, out_sample: {...}, split_ts, decay_pct, ...}

    Args:
        strategy: 已 commit 的 Strategy 实例
        wf_result: walk-forward 结果 dict
        source: 来源标签 (写进 walkforward_json.source 便于排查) — 'param_opt' / 'manual' / 'risk_opt' / 'synth'
        params: 实际使用的参数快照. None = 用 strategy.params

    Returns:
        新建的 BacktestResult.id
    """
    full = wf_result.get('full') or {}
    oos = wf_result.get('out_sample') or {}

    # 14k-109: OOS 是真值 (in_sample 容易 overfit). sharpe / annual_return 走 OOS,
    # trades / pnl 走 full 因为这是 user 看到的实际累积数字
    bt = BacktestResult(
        strategy_id=strategy.id,
        user_id=strategy.user_id,
        strategy_type=strategy.type,
        params_snapshot=params if params is not None else (strategy.params or {}),
        symbol=strategy.symbol,
        timeframe=strategy.timeframe,
        leverage=15.0,
        position_size_usdt=10.0,
        stop_loss_pct=5.0,
        take_profit_pct=8.0,
        initial_capital=full.get('initial_capital') or 100.0,
        period_start=full.get('period_start'),
        period_end=full.get('period_end'),
        candle_count=full.get('candle_count'),
        total_trades=int(full.get('total_trades') or 0),
        winning_trades=int(full.get('winning_trades') or 0),
        losing_trades=int(full.get('losing_trades') or 0),
        win_rate=float(full.get('win_rate') or 0),
        total_pnl=float(full.get('total_pnl') or 0),
        avg_pnl=float(full.get('avg_pnl') or 0),
        max_drawdown_pct=float(oos.get('max_drawdown_pct') or full.get('max_drawdown_pct') or 0),
        sharpe_ratio=float(oos.get('sharpe_ratio') or 0),
        annual_return_pct=float(oos.get('annual_return_pct') or 0),
        status='completed',
        walkforward_json={**wf_result, 'source': source},
    )
    db.session.add(bt)
    db.session.flush()
    _maybe_link_candidate(strategy, bt.id)
    return bt.id


def record_backtest_from_opt_combo(
    strategy: Strategy,
    combo: dict,
    *,
    source: str,
    opt_id: Optional[int] = None,
) -> Optional[int]:
    """从 param_optimization.candidate_results 单条 combo 写一笔 BacktestResult.

    combo 结构 (param_optimizer 产):
      {params, is_trades, oos_trades, full_trades, is_sharpe, oos_sharpe, full_sharpe,
       is_maxdd, oos_maxdd, is_ar, oos_ar, full_pnl, decay_pct}

    OOS 没交易 (oos_trades=0) 返回 None — 数据没意义不写.
    """
    oos_trades = int(combo.get('oos_trades') or 0)
    if oos_trades < 1:
        return None

    is_trades = int(combo.get('is_trades') or 0)
    full_trades = int(combo.get('full_trades') or (is_trades + oos_trades))
    full_pnl = float(combo.get('full_pnl') or 0)

    bt = BacktestResult(
        strategy_id=strategy.id,
        user_id=strategy.user_id,
        strategy_type=strategy.type,
        params_snapshot=combo.get('params') or (strategy.params or {}),
        symbol=strategy.symbol,
        timeframe=strategy.timeframe,
        initial_capital=100.0,   # param_optimizer 默认
        total_trades=full_trades,
        total_pnl=full_pnl,
        avg_pnl=(full_pnl / full_trades) if full_trades else 0,
        sharpe_ratio=float(combo.get('oos_sharpe') or 0),
        annual_return_pct=float(combo.get('oos_ar') or 0),
        max_drawdown_pct=float(combo.get('oos_maxdd') or 0),
        status='completed',
        walkforward_json={
            'in_sample': {
                'total_trades': is_trades,
                'sharpe_ratio': float(combo.get('is_sharpe') or 0),
                'max_drawdown_pct': float(combo.get('is_maxdd') or 0),
                'annual_return_pct': float(combo.get('is_ar') or 0),
            },
            'out_sample': {
                'total_trades': oos_trades,
                'sharpe_ratio': float(combo.get('oos_sharpe') or 0),
                'max_drawdown_pct': float(combo.get('oos_maxdd') or 0),
                'annual_return_pct': float(combo.get('oos_ar') or 0),
                'total_pnl': full_pnl,
                'initial_capital': 100.0,
            },
            'decay_pct': float(combo.get('decay_pct') or 0),
            'source': source,
            'opt_id': opt_id,
        },
    )
    db.session.add(bt)
    db.session.flush()
    _maybe_link_candidate(strategy, bt.id)
    return bt.id
