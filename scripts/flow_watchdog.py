#!/usr/bin/env python3
"""Phase 12.46: AI + 自动化流程 watchdog

每 30min host cron 跑，覆盖：
  - Celery beat 心跳（task-meta keys 增长）
  - 各 signal cycle 是否按时跑（15m/1h/4h）
  - Translate pipeline 健康（pending 不堆积、最近有 translated）
  - Daily AI improve cron 是否按时（24h 内 done event）
  - LLM call errors 频率（worker log grep）
  - PG connection count
  - Active positions reconcile 及时
  - OKX API 通

设计原则：
  - 检测优先于自动修：任何 unsafe 修改（重启 worker / 改 timeout）都人审
  - 安全自动修：触发 translate / 触发 AI improve（纯异步调用）
  - 任何 FAIL → Telegram 立即推
  - dedup: 同 check 30min 不重复 Telegram
  - 报告写 /var/log/quant/flow_watchdog.log

用法:
  python3 /opt/quant/scripts/flow_watchdog.py         # 检测 + 自动修（默认）
  python3 /opt/quant/scripts/flow_watchdog.py --dry-run  # 不发 Telegram + 不 autofix
  python3 /opt/quant/scripts/flow_watchdog.py --check NAME  # 只跑一个

cron:
  */30 * * * * root /usr/bin/python3 /opt/quant/scripts/flow_watchdog.py >> /var/log/quant/flow_watchdog_cron.log 2>&1
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

LOG_DIR = Path('/var/log/quant')
TG_TOKEN = os.environ.get('TG_TOKEN', '8987521221:AAHRYteR9sYCC7j7t7uT1GMbl3pmTXmMVhw')
TG_CHAT = os.environ.get('TG_CHAT', '844917210')
API_TOKEN = os.environ.get('API_AUTH_TOKEN', 'MycRdx7-yRb5u5vasVydoVpkpgJaxq14anw7mrNrCd4')
DEDUP_WINDOW_SEC = 1800

OK = 'OK'
WARN = 'WARN'
FAIL = 'FAIL'

# Phase 14k-33: 给每个内部 check_name 一个人看得懂的中文显示名
CHECK_LABELS = {
    'celery_beat_heartbeat': 'Celery 调度器心跳 / Scheduler Heartbeat',
    'signal_cycle_health':   '回测信号循环 / Signal Cycle',
    'ai_improve_recent':     '每日 AI 策略改进 / Daily AI Improve',
    'translate_pipeline':    '策略翻译队列 / Translate Queue',
    'llm_errors_1h':         '近 1 小时 LLM 错误 / LLM Errors (1h)',
    'pg_connection_pool':    '数据库连接数 / DB Connections',
    'exchange_connectivity':      '交易所余额 / Exchange Balance',
    'reconcile_health':      '当前持仓状态 / Position Status',
    'running_strategies':    '运行中策略数 / Running Strategies',
    # Phase 14k-45 L1/L2/L3 新增
    'market_brief_recent':   'AI 市场分析活跃 / Market Brief Active',
    'signal_watchers':       '信号 watcher 健康 / Signal Watchers',
    'dynamic_synth_recent':  'AI 策略合成活跃 / Dynamic Synthesis',
}


def t0(): return time.time()
def ms(t): return int((time.time() - t) * 1000)


def run_cmd(cmd, timeout=10) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'
    except FileNotFoundError as e:
        return 127, '', f'not found: {e}'


def psql(sql: str) -> tuple[int, str]:
    return tuple(run_cmd(
        ['docker', 'exec', 'quant-postgres-1', 'psql', '-U', 'quant', '-d', 'quant',
         '-t', '-A', '-c', sql], timeout=10,
    )[:2])


# === DETECTION ===

def check_celery_beat_heartbeat() -> dict:
    """1. Celery worker 响应 ping (替代 task-meta 计数 - 有 TTL 过期 false positive 问题)
    inspect ping 直接验 worker process alive + 接受任务"""
    t = t0()
    rc, out, err = run_cmd(
        ['docker', 'exec', 'quant-celery-worker-1', 'celery',
         '-A', 'app.tasks.strategy_tasks', 'inspect', 'ping', '-t', '5'],
        timeout=15,
    )
    if rc != 0 or 'pong' not in (out + err).lower():
        return {'status': FAIL, 'detail': f'Celery worker 无响应（可能挂了）: {(err or out)[:120]}', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': 'worker 在线', 'latency_ms': ms(t)}


def check_signal_cycle_15m() -> dict:
    """2. 15m signal cycle proxy — backtest_results 2h 内有新增 (auto_backtest :30 hourly)"""
    t = t0()
    rc, out = psql("""
        SELECT COUNT(*), COALESCE(MAX(created_at)::text, 'never')
        FROM backtest_results
        WHERE created_at > NOW() - INTERVAL '2 hours'
    """)
    if rc != 0:
        return {'status': WARN, 'detail': 'pg query fail', 'latency_ms': ms(t)}
    try:
        count, last = out.strip().split('|', 1)
        count = int(count)
    except Exception as e:
        return {'status': WARN, 'detail': f'parse error: {e}', 'latency_ms': ms(t)}
    if count == 0:
        return {'status': WARN, 'detail': '近 2 小时无新回测（自动回测定时任务可能挂或候选池为空）', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'近 2 小时完成 {count} 次回测，最近 {last[:19]}', 'latency_ms': ms(t)}


def check_ai_improve_recent() -> dict:
    """3. Daily AI improve cron 25h 内有 done 或 skipped event.

    Phase 14k-35 修: actor 从 'auto:%ai_improve%' 放宽 — Phase 14 后 task actor 改成
    'auto:daily_recommend' 没含 ai_improve 子串, 导致一直 false positive.
    改用 event_type IN (那些 event 本身就是 ai_improve namespace).
    """
    t = t0()
    rc, out = psql("""
        SELECT COALESCE(MAX(created_at)::text, 'never'),
               COUNT(*) FILTER (WHERE event_type='auto_ai_improve_done'),
               COUNT(*) FILTER (WHERE event_type='auto_ai_improve_skipped'),
               COUNT(*) FILTER (WHERE event_type='auto_ai_improve_error')
        FROM audit_log
        WHERE event_type IN ('auto_ai_improve_done', 'auto_ai_improve_skipped', 'auto_ai_improve_error')
          AND created_at > NOW() - INTERVAL '25 hours'
    """)
    if rc != 0:
        return {'status': WARN, 'detail': 'pg query fail', 'latency_ms': ms(t)}
    try:
        last, done, skipped, errored = out.strip().split('|')
        done, skipped, errored = int(done), int(skipped), int(errored)
    except:
        return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}
    total = done + skipped + errored
    last_human = '从未运行过' if last == 'never' else f'上次 {last[:19]}'
    if total == 0:
        return {'status': FAIL, 'detail': f'已 25 小时没有运行（每日定时任务可能挂了，{last_human}）', 'latency_ms': ms(t)}
    if errored > 0 or (skipped > 0 and done == 0):
        return {'status': WARN, 'detail': f'近 25 小时：完成 {done} 次 / 跳过 {skipped} 次 / 失败 {errored} 次（没产出新候选）', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'近 25 小时：完成 {done} 次 / 跳过 {skipped} 次 / 失败 {errored} 次', 'latency_ms': ms(t)}


def check_translate_pipeline() -> dict:
    """4. Translate 流健康度 (Phase 14k-35 重写, 之前 'pending' status 不存在永远 OK).

    candidates 真实生命周期: translated → backtesting → qualified → promoted (或 dismissed/error)
    检测:
      - WARN: backtesting 状态卡住 > 6h (回测 task 挂了)
      - WARN: 24h 内无新 translated (translate cron 可能挂)
      - 都没问题 → OK
    """
    t = t0()
    # 14k-51: 加 stale_qualified / archived 分级 (qualified pool 应该看真能 promote 的)
    rc, out = psql("""
        SELECT
          (SELECT COUNT(*) FROM strategy_candidates WHERE status='backtesting' AND updated_at < NOW() - INTERVAL '6 hours'),
          (SELECT COUNT(*) FROM strategy_candidates WHERE status='translated' AND created_at > NOW() - INTERVAL '24 hours'),
          (SELECT COUNT(*) FROM strategy_candidates WHERE status='error' AND created_at > NOW() - INTERVAL '24 hours'),
          (SELECT COUNT(*) FROM strategy_candidates WHERE status='qualified'),
          (SELECT COUNT(*) FROM strategy_candidates WHERE status='stale_qualified'),
          (SELECT COUNT(*) FROM strategy_candidates WHERE status='archived')
    """)
    if rc != 0:
        return {'status': WARN, 'detail': '数据库查询失败', 'latency_ms': ms(t)}
    try:
        parts = [int(x) for x in out.strip().split('|')]
        stuck_bt, new_translated_24h, errored_24h, qualified_pool, stale_pool, archived_pool = parts
    except Exception as e:
        return {'status': WARN, 'detail': f'解析失败: {e}', 'latency_ms': ms(t)}
    if stuck_bt > 5:
        return {'status': WARN, 'detail': f'有 {stuck_bt} 个候选卡在回测超过 6 小时（回测 task 可能挂）', 'latency_ms': ms(t),
                'autofix_hint': '重启 celery-worker 释放卡住的回测'}
    # 14k-51: 看真能 promote 的池 (qualified), stale/archived 不算
    if new_translated_24h == 0 and qualified_pool < 5:
        return {'status': WARN,
                'detail': f'近 24h 无新翻译 + 真 promote-eligible 池薄 (qualified={qualified_pool}, stale={stale_pool}, archived={archived_pool})',
                'latency_ms': ms(t)}
    return {'status': OK,
            'detail': f'24h 翻译 {new_translated_24h} / 卡 backtesting {stuck_bt} / err {errored_24h} / qualified {qualified_pool} / stale {stale_pool} / archived {archived_pool}',
            'latency_ms': ms(t)}


def check_llm_errors_recent() -> dict:
    """5. Worker log 最近 1h 内 LLM call timeout / parse fail 次数"""
    t = t0()
    rc, out, _ = run_cmd(
        ['docker', 'logs', '--since', '60m', 'quant-celery-worker-1'],
        timeout=10,
    )
    if rc != 0:
        return {'status': WARN, 'detail': 'docker logs fail', 'latency_ms': ms(t)}
    timeouts = out.count('TimeoutExpired')
    parse_fails = out.count('LLM 输出无法解析')
    if timeouts >= 3:
        return {'status': FAIL, 'detail': f'近 1 小时 LLM 超时 {timeouts} 次 / 解析失败 {parse_fails} 次（超时偏多）', 'latency_ms': ms(t),
                'autofix_hint': '考虑调大 CLAUDE_CLI_TIMEOUT'}
    if timeouts > 0 or parse_fails > 0:
        return {'status': WARN, 'detail': f'近 1 小时 LLM 超时 {timeouts} 次 / 解析失败 {parse_fails} 次', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': '近 1 小时无 LLM 错误', 'latency_ms': ms(t)}


def check_pg_pool() -> dict:
    """6. PG connection count（防坑 18 复发）"""
    t = t0()
    rc, out = psql("SELECT count(*) FROM pg_stat_activity")
    if rc != 0:
        return {'status': WARN, 'detail': 'pg query fail', 'latency_ms': ms(t)}
    try: count = int(out.strip())
    except: return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}
    if count > 80:
        return {'status': FAIL, 'detail': f'数据库连接数 {count}（已超 80，逼近 100 上限）', 'latency_ms': ms(t),
                'autofix_hint': '重启 celery-worker 释放空闲连接'}
    if count > 50:
        return {'status': WARN, 'detail': f'数据库连接数 {count}（超过 50）', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'数据库连接数 {count}', 'latency_ms': ms(t)}


def check_exchange_connectivity() -> dict:
    """7. 交易所 /api/account 通 + 总余额 > 0.

    Phase 14k-35: schema 变了 (14k-11 多交易所重构后), balances 是 {exchange_name: total}
    不再是 {coin: detail}. 用 top-level data.balance 总余额判定.
    """
    t = t0()
    try:
        req = urllib.request.Request('http://localhost:5005/api/account',
                                      headers={'Authorization': f'Bearer {API_TOKEN}'})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        return {'status': FAIL, 'detail': f'账户接口请求失败（{type(e).__name__}）', 'latency_ms': ms(t)}
    accounts = data.get('accounts') or []
    total = float(data.get('balance') or 0)
    if not accounts:
        return {'status': WARN, 'detail': '接口通了但未绑定任何交易所', 'latency_ms': ms(t)}
    if total <= 0:
        # bound 但没钱 — WARN (可能用户没充值)
        names = ', '.join(a.get('label', '?') for a in accounts)
        return {'status': WARN, 'detail': f'已绑 {names} 但总余额为 0（请检查交易所是否有资金）', 'latency_ms': ms(t)}
    names = ' + '.join(f'{a.get("label", "?")} ${float(a.get("equity") or 0):.2f}' for a in accounts)
    return {'status': OK, 'detail': f'总余额 ${total:.2f}（{names}）', 'latency_ms': ms(t)}


def check_reconcile_recent() -> dict:
    """8. open positions snapshot（reconcile/update_positions 静默，无可靠时间戳）"""
    t = t0()
    rc, out = psql("""
        SELECT COUNT(*), COALESCE(MAX(opened_at)::text, 'none')
        FROM positions WHERE status='open'
    """)
    if rc != 0:
        return {'status': WARN, 'detail': 'pg query fail', 'latency_ms': ms(t)}
    try:
        count, last = out.strip().split('|', 1)
        count = int(count)
    except Exception as e:
        return {'status': WARN, 'detail': f'parse: {e}', 'latency_ms': ms(t)}
    last_human = '无' if last == 'none' else last[:19]
    return {'status': OK, 'detail': f'{count} 个持仓中，最近开仓 {last_human}', 'latency_ms': ms(t)}


def check_running_strategies() -> dict:
    """9. running 策略数 > 0 + 14k-52 stopped 池健康 (老 stopped 没堆积)"""
    t = t0()
    rc, out = psql("""
        SELECT
          (SELECT COUNT(*) FROM strategies WHERE status='running'),
          (SELECT COUNT(*) FROM strategies WHERE status='stopped'),
          (SELECT COUNT(*) FROM strategies WHERE status='stopped' AND created_at < NOW() - INTERVAL '7 days'),
          (SELECT COUNT(*) FROM strategies WHERE status='retired')
    """)
    if rc != 0: return {'status': WARN, 'detail': 'pg fail', 'latency_ms': ms(t)}
    try:
        running, stopped, stopped_old, retired = [int(x) for x in out.strip().split('|')]
    except Exception as e:
        return {'status': WARN, 'detail': f'parse: {e}', 'latency_ms': ms(t)}
    if running == 0:
        return {'status': WARN, 'detail': '没有运行中的策略（可能被手动停了）', 'latency_ms': ms(t)}
    # 14k-52: 老 stopped > 20 → cleanup task 该跑了
    if stopped_old > 20:
        return {'status': WARN,
                'detail': f'{running} 运行 / {stopped} stopped (其中 {stopped_old} > 7d 等 cleanup) / {retired} retired',
                'latency_ms': ms(t),
                'autofix_hint': '手动跑 cleanup_stale_candidates 释放 dedup slot'}
    return {'status': OK,
            'detail': f'{running} 运行 / {stopped} stopped (老 {stopped_old}) / {retired} retired',
            'latency_ms': ms(t)}


# Phase 14k-45 L1: AI 市场分析活跃
def check_market_brief_recent() -> dict:
    """近 30min 内有 market_brief_prewarmed audit (确保 prewarm task 在跑)."""
    t = t0()
    rc, out = psql("""
        SELECT COUNT(*), COALESCE(MAX(created_at)::text, 'none')
        FROM audit_log WHERE event_type='market_brief_prewarmed' AND created_at > NOW() - INTERVAL '30 minutes'
    """)
    if rc != 0: return {'status': WARN, 'detail': '数据库查询失败', 'latency_ms': ms(t)}
    try:
        count, last = out.strip().split('|', 1)
        count = int(count)
    except Exception as e:
        return {'status': WARN, 'detail': f'解析失败: {e}', 'latency_ms': ms(t)}
    if count == 0:
        return {'status': FAIL, 'detail': '近 30 分钟没有 AI 市场分析活动（prewarm task 可能挂了）',
                'latency_ms': ms(t), 'autofix_hint': '重启 celery-worker/beat'}
    return {'status': OK, 'detail': f'近 30 分钟 prewarm 跑了 {count} 次, 最近 {last[:19]}', 'latency_ms': ms(t)}


# Phase 14k-45 L2: 信号 watcher 健康
def check_signal_watchers() -> dict:
    """active watcher 数 + 是否有卡死 (已过期但还 active)."""
    t = t0()
    rc, out = psql("""
        SELECT
          (SELECT COUNT(*) FROM signal_watchers WHERE status='active'),
          (SELECT COUNT(*) FROM signal_watchers WHERE status='active' AND expires_at < NOW()),
          (SELECT COUNT(*) FROM signal_watchers WHERE status='triggered' AND triggered_at > NOW() - INTERVAL '24 hours')
    """)
    if rc != 0: return {'status': WARN, 'detail': '数据库查询失败', 'latency_ms': ms(t)}
    try:
        active, stuck, triggered_24h = [int(x) for x in out.strip().split('|')]
    except Exception as e:
        return {'status': WARN, 'detail': f'解析失败: {e}', 'latency_ms': ms(t)}
    if stuck > 0:
        return {'status': WARN, 'detail': f'{stuck} 个 watcher 已过期但状态仍 active (expire task 没跑)',
                'latency_ms': ms(t), 'autofix_hint': '查 check_signal_watchers task'}
    return {'status': OK,
            'detail': f'{active} 个 active / 近 24 小时触发 {triggered_24h} 次',
            'latency_ms': ms(t)}


# Phase 14k-45 L3: 动态策略合成活跃
def check_dynamic_synth_recent() -> dict:
    """近 24h 是否有 synth candidate 创建 (synthesize_dynamic_strategy 跑了吗)."""
    t = t0()
    rc, out = psql("""
        SELECT COUNT(*) FROM strategy_candidates
        WHERE source='synth' AND created_at > NOW() - INTERVAL '24 hours'
    """)
    if rc != 0: return {'status': WARN, 'detail': '数据库查询失败', 'latency_ms': ms(t)}
    try: count = int(out.strip())
    except: return {'status': WARN, 'detail': f'解析失败: {out}', 'latency_ms': ms(t)}
    # synth 不是强制定时, advisor 决定何时触发. 0 是正常
    return {'status': OK, 'detail': f'近 24 小时 AI 合成了 {count} 个候选', 'latency_ms': ms(t)}


CHECKS = [
    ('celery_beat_heartbeat', check_celery_beat_heartbeat),
    ('signal_cycle_health',   check_signal_cycle_15m),
    ('ai_improve_recent',     check_ai_improve_recent),
    ('translate_pipeline',    check_translate_pipeline),
    ('llm_errors_1h',         check_llm_errors_recent),
    ('pg_connection_pool',    check_pg_pool),
    ('exchange_connectivity',      check_exchange_connectivity),
    ('reconcile_health',      check_reconcile_recent),
    ('running_strategies',    check_running_strategies),
    # Phase 14k-45 新增 3 个 check
    ('market_brief_recent',   check_market_brief_recent),
    ('signal_watchers',       check_signal_watchers),
    ('dynamic_synth_recent',  check_dynamic_synth_recent),
]


# === AUTOFIX (limited, safe) ===

def autofix_translate_pipeline() -> tuple[bool, str]:
    """触发 host translate_cli.py 跑一次（安全 — 只 LLM 调用）"""
    rc, out, err = run_cmd(['/opt/quant/translate_pending_cron.sh'], timeout=180)
    if rc != 0:
        return False, f'translate script fail: {err[:120]}'
    return True, f'translate triggered, output: {out[:120]}'


def autofix_ai_improve_trigger() -> tuple[bool, str]:
    """异步调用 /api/strategies/ai-improve POST 触发一次 (safe，背景跑)"""
    try:
        req = urllib.request.Request(
            'http://localhost:5005/api/strategies/ai-improve',
            data=b'{}', method='POST',
            headers={
                'Authorization': f'Bearer {API_TOKEN}',
                'Content-Type': 'application/json',
            },
        )
        # 不等待响应（LLM 调用慢）— 1s timeout 强制断开
        try:
            urllib.request.urlopen(req, timeout=1)
        except (urllib.error.URLError, TimeoutError):
            pass  # 预期；后台 async 跑
        return True, 'AI improve POST 已触发（异步）'
    except Exception as e:
        return False, f'trigger fail: {type(e).__name__}: {e}'


AUTOFIX_MAP = {
    'translate_pipeline': autofix_translate_pipeline,
    # ai_improve_recent: 不自动触发 — LLM call 慢 + 可能浪费 token，让我（claude）人审
}


# === Telegram + Dedup ===

def _dedup_path(): return LOG_DIR / 'flow_watchdog_dedup.json'

def load_dedup():
    p = _dedup_path()
    if not p.exists(): return {}
    try: return json.loads(p.read_text())
    except: return {}

def save_dedup(d): _dedup_path().write_text(json.dumps(d))

def should_alert(name: str) -> bool:
    d = load_dedup()
    now = time.time()
    last = d.get(name, 0)
    if now - last < DEDUP_WINDOW_SEC: return False
    d[name] = now
    save_dedup(d)
    return True

def send_telegram(text: str) -> bool:
    try:
        data = urllib.parse.urlencode({
            'chat_id': TG_CHAT, 'parse_mode': 'HTML',
            'text': text[:4096],
        }).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=data, method='POST',
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


# === Main ===

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--check', help='跑单个 check')
    parser.add_argument('--no-autofix', action='store_true')
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    selected = CHECKS
    if args.check:
        selected = [(n, fn) for n, fn in CHECKS if n == args.check]
        if not selected:
            print(f'unknown check: {args.check}', file=sys.stderr)
            return 2

    report = {
        'checked_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'host': socket.gethostname(),
        'results': {}, 'autofixes': {},
        'summary': {'OK': 0, 'WARN': 0, 'FAIL': 0},
    }
    for name, fn in selected:
        try: res = fn()
        except Exception as e:
            res = {'status': FAIL, 'detail': f'check 抛错: {type(e).__name__}: {e}', 'latency_ms': 0}
        report['results'][name] = res
        report['summary'][res['status']] += 1

    # Auto-fix attempts
    if not args.dry_run and not args.no_autofix:
        for name, res in report['results'].items():
            if res['status'] != FAIL: continue
            fix_fn = AUTOFIX_MAP.get(name)
            if not fix_fn: continue
            try:
                ok, msg = fix_fn()
                report['autofixes'][name] = {'ok': ok, 'msg': msg}
            except Exception as e:
                report['autofixes'][name] = {'ok': False, 'msg': f'autofix raised: {e}'}

    # write json
    (LOG_DIR / 'flow_watchdog_latest.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (LOG_DIR / f'flow_watchdog_{datetime.datetime.utcnow():%Y%m%d}.jsonl').open('a').write(
        json.dumps(report, ensure_ascii=False) + '\n'
    )

    # Telegram if new FAILs
    if not args.dry_run:
        new_fails = []
        for n, r in report['results'].items():
            if r['status'] == FAIL and should_alert(n):
                new_fails.append(n)
        if new_fails:
            lines = []
            for n in new_fails:
                r = report['results'][n]
                af = report['autofixes'].get(n)
                label = CHECK_LABELS.get(n, n)
                line = f'• <b>{label}</b>: {r["detail"]}'
                if af:
                    line += f'\n  🔧 自动修复: {"✅ 成功" if af["ok"] else "❌ 失败"}（{af["msg"]}）'
                elif r.get('autofix_hint'):
                    line += f'\n  💡 处理建议: {r["autofix_hint"]}'
                lines.append(line)
            text = '🚨 <b>系统监控异常 / System Health Alert</b>\n\n' + '\n\n'.join(lines)
            send_telegram(text)

    # stdout
    s = report['summary']
    print(f'=== flow_watchdog {report["checked_at"]} ===')
    print(f'OK={s["OK"]} WARN={s["WARN"]} FAIL={s["FAIL"]}')
    for name, res in report['results'].items():
        icon = {'OK': '✓', 'WARN': '⚠', 'FAIL': '✗'}[res['status']]
        print(f'  {icon} {name:25s} {res["detail"]}  ({res["latency_ms"]}ms)')
    for name, af in report['autofixes'].items():
        print(f'  🔧 autofix {name}: {"OK" if af["ok"] else "FAIL"}: {af["msg"]}')

    return 2 if s['FAIL'] > 0 else (1 if s['WARN'] > 0 else 0)


if __name__ == '__main__':
    sys.exit(main())
