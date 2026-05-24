#!/usr/bin/env python3
"""Phase 12.45: Daily AI improve cron review — 跑在 daily-ai-improve 之后

逻辑:
  1. 查最近 1h 内 auto:daily_ai_improve_v6 / v7 / v8 audit_log 事件
  2. 拉它产出的 qualified candidates (created_at 在 cron 时间附近)
  3. 对比 self_estimate vs actual_metrics (从 candidate.source_meta 读)
  4. 计算频率误差比 + Sharpe/PF 准度
  5. 写日志 + 发 Telegram

跑法:
  crontab: `35 7 * * * /usr/bin/python3 /opt/quant/scripts/review_daily_ai_improve.py >> /var/log/quant/ai_improve_review.log 2>&1`

  手动: `python3 /opt/quant/scripts/review_daily_ai_improve.py`
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

LOG_DIR = Path('/var/log/quant')
TG_TOKEN = os.environ.get('TG_TOKEN', '8987521221:AAHRYteR9sYCC7j7t7uT1GMbl3pmTXmMVhw')
TG_CHAT = os.environ.get('TG_CHAT', '844917210')


def psql(sql: str) -> list[list[str]]:
    """run psql -t -A, return list of rows (each is list of fields by |)"""
    p = subprocess.run(
        ['docker', 'exec', 'quant-postgres-1', 'psql', '-U', 'quant', '-d', 'quant',
         '-t', '-A', '-c', sql],
        capture_output=True, text=True, timeout=15,
    )
    if p.returncode != 0:
        raise RuntimeError(f'psql failed: {p.stderr[:200]}')
    rows = []
    for line in p.stdout.strip().splitlines():
        if line.strip():
            rows.append(line.split('|'))
    return rows


def send_tg(text: str) -> bool:
    try:
        data = urllib.parse.urlencode({
            'chat_id': TG_CHAT,
            'parse_mode': 'Markdown',
            'text': text[:4096],
        }).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=data, method='POST',
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f'TG fail: {e}', file=sys.stderr)
        return False


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.utcnow()
    log_lines = [f'=== Daily AI improve review at {now.isoformat()}Z ===']

    # 1. 最近 2h 内 auto AI improve audit log event
    audit_rows = psql("""
        SELECT actor, event_type, context::text, created_at
        FROM audit_log
        WHERE actor LIKE 'auto:%ai_improve%'
          AND created_at > NOW() - INTERVAL '2 hours'
        ORDER BY created_at DESC
        LIMIT 3
    """)
    if not audit_rows:
        msg = '*🤖 Daily AI improve review*\n\n⚠ 最近 2h 无 auto AI improve event — cron 可能没跑 or 还没完成'
        log_lines.append(msg)
        send_tg(msg)
        (LOG_DIR / 'ai_improve_review.log').open('a').write('\n'.join(log_lines) + '\n')
        return 1

    log_lines.append(f'Found {len(audit_rows)} audit events:')
    for r in audit_rows:
        log_lines.append(f'  {r[3]}: {r[0]} / {r[1]}')

    # 2. 拉最近 2h 内 qualified candidates (AI v6/v7/v8 出的)
    # 注：strategy_candidates 没 symbol 列，存在 source_meta jsonb (Phase 12.39)
    cand_rows = psql("""
        SELECT id, candidate_type, timeframe, category, status,
               source_name, source_meta::text, created_at,
               backtest_result_id
        FROM strategy_candidates
        WHERE source_name LIKE '%AI improve%'
          AND created_at > NOW() - INTERVAL '2 hours'
        ORDER BY created_at DESC
        LIMIT 10
    """)

    candidates = []
    for row in cand_rows:
        try:
            meta = json.loads(row[6] or '{}')
        except Exception:
            meta = {}
        est = meta.get('self_estimate', {}) or {}
        actual = meta.get('actual_metrics', {}) or {}
        rp = meta.get('risk_params', {}) or {}
        tp = meta.get('trade_patterns', {}) or {}
        candidates.append({
            'id': int(row[0]),
            'type': row[1],
            'symbol': meta.get('symbol') or '?',
            'timeframe': row[2],
            'category': row[3],
            'status': row[4],
            'created_at': row[7],
            'estimate': est,
            'actual': actual,
            'risk_params': rp,
            'trade_patterns': tp,
        })

    # 3. 统计:
    n_total = len(candidates)
    n_qualified = sum(1 for c in candidates if c['status'] == 'qualified')
    n_translated = sum(1 for c in candidates if c['status'] == 'translated')

    # 频率准度对比
    freq_diffs = []
    sharpe_diffs = []
    for c in candidates:
        est_tr = c['estimate'].get('expected_oos_trades')
        act_tr = c['actual'].get('oos_trades')
        if est_tr and act_tr:
            try:
                ratio = float(act_tr) / float(est_tr)
                freq_diffs.append({'cid': c['id'], 'type': c['type'], 'est': est_tr, 'act': act_tr, 'ratio': ratio})
            except Exception:
                pass
        est_sh = c['estimate'].get('expected_oos_sharpe')
        act_sh = c['actual'].get('oos_sharpe')
        if est_sh is not None and act_sh is not None:
            try:
                sharpe_diffs.append({'cid': c['id'], 'est': float(est_sh), 'act': float(act_sh)})
            except Exception:
                pass

    # 4. 拼 Telegram 报告
    lines = ['*🤖 Daily AI improve v8 review*', '']
    lines.append(f'📊 *本次 cron 产出*:')
    lines.append(f'  - candidates 总: {n_total}')
    lines.append(f'  - qualified (过自测): {n_qualified}')
    lines.append(f'  - translated (未过): {n_translated}')

    if n_qualified > 0:
        lines.append('')
        lines.append('🚀 *Qualified 候选* (已写入 AiPickPanel):')
        for c in candidates:
            if c['status'] != 'qualified':
                continue
            a = c['actual']
            rp = c['risk_params']
            lines.append(
                f'  • `{c["type"]}` ({c["symbol"]} {c["timeframe"]}/{c["category"]})'
            )
            lines.append(
                f'    OOS: Sharpe={a.get("oos_sharpe")} PF={a.get("oos_pf")} '
                f'trades={a.get("oos_trades")} AR={a.get("oos_ar_pct")}%'
            )
            lines.append(
                f'    risk: lev={rp.get("leverage")}x SL={rp.get("stop_loss_pct")}% '
                f'TP={rp.get("take_profit_pct")}% pos=${rp.get("position_size_usdt")}'
            )

    # 频率准度 ratio
    if freq_diffs:
        lines.append('')
        lines.append('🎯 *频率估算准度* (v8.1 prompt 的关键 metric):')
        for f in freq_diffs[:6]:
            ratio = f['ratio']
            if ratio < 0.5:
                tag = '❌ 严重低估'
            elif ratio < 0.7:
                tag = '⚠ 偏低估'
            elif ratio > 1.5:
                tag = '⚠ 偏高估'
            else:
                tag = '✅ 准确'
            lines.append(
                f'  • #{f["cid"]} `{f["type"]}`: 估 {f["est"]} → 实 {f["act"]} '
                f'(ratio={ratio:.2f} {tag})'
            )

        # 平均比 + verdict
        avg_ratio = sum(f['ratio'] for f in freq_diffs) / len(freq_diffs)
        if avg_ratio < 0.5:
            verdict = f'❌ 平均 ratio={avg_ratio:.2f} — v8.1 prompt 仍系统低估 → 需进一步修'
        elif avg_ratio < 0.8:
            verdict = f'🟡 平均 ratio={avg_ratio:.2f} — v8.1 prompt 改善但未完全'
        else:
            verdict = f'✅ 平均 ratio={avg_ratio:.2f} — v8.1 prompt 频率校准生效'
        lines.append('')
        lines.append(verdict)

    if n_total == 0:
        lines.append('')
        lines.append('⚠ 0 candidates produced — 可能 LLM no_edge_today 或 LLM call 失败')

    text = '\n'.join(lines)
    print(text)

    if send_tg(text):
        log_lines.append('Telegram sent ✓')
    else:
        log_lines.append('Telegram send FAIL')

    log_lines.append(text)
    (LOG_DIR / 'ai_improve_review.log').open('a').write('\n'.join(log_lines) + '\n\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
