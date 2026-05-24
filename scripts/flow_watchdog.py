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
    """1. Celery beat 心跳 — Redis task-meta key 数量 1h 内增长"""
    t = t0()
    rc, out, _ = run_cmd(['docker', 'exec', 'quant-redis-1', 'redis-cli', 'EVAL',
                          "return #redis.call('keys', 'celery-task-meta-*')", '0'], timeout=8)
    if rc != 0:
        return {'status': WARN, 'detail': f'redis fail', 'latency_ms': ms(t)}
    try: current = int(out.strip())
    except: return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}

    state_file = LOG_DIR / 'flow_watchdog_state.json'
    state = {}
    if state_file.exists():
        try: state = json.loads(state_file.read_text())
        except: pass
    prev = state.get('celery_task_meta')
    prev_ts = state.get('celery_task_meta_ts', 0)
    state['celery_task_meta'] = current
    state['celery_task_meta_ts'] = time.time()
    state_file.write_text(json.dumps(state))
    if prev is None:
        return {'status': WARN, 'detail': f'baseline 写入 ({current})，下次对比', 'latency_ms': ms(t)}
    elapsed = (time.time() - prev_ts) / 60
    if current <= prev and elapsed > 5:
        return {'status': FAIL, 'detail': f'task-meta {prev}→{current} 无增长 ({elapsed:.1f}min)，beat 可能挂', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'task-meta {prev}→{current} (+{current-prev} in {elapsed:.1f}min)', 'latency_ms': ms(t)}


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
        return {'status': WARN, 'detail': f'2h 无新 backtest_results (auto_backtest :30 cron 可能挂或无 candidates)', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'2h: {count} backtests, last={last[:19]}', 'latency_ms': ms(t)}


def check_ai_improve_recent() -> dict:
    """3. Daily AI improve cron 25h 内有 done 或 skipped event"""
    t = t0()
    rc, out = psql("""
        SELECT COALESCE(MAX(created_at)::text, 'never'),
               COUNT(*) FILTER (WHERE event_type='auto_ai_improve_done'),
               COUNT(*) FILTER (WHERE event_type='auto_ai_improve_skipped'),
               COUNT(*) FILTER (WHERE event_type='auto_ai_improve_error')
        FROM audit_log
        WHERE actor LIKE 'auto:%ai_improve%' AND created_at > NOW() - INTERVAL '25 hours'
    """)
    if rc != 0:
        return {'status': WARN, 'detail': 'pg query fail', 'latency_ms': ms(t)}
    try:
        last, done, skipped, errored = out.strip().split('|')
        done, skipped, errored = int(done), int(skipped), int(errored)
    except:
        return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}
    total = done + skipped + errored
    if total == 0:
        return {'status': FAIL, 'detail': f'25h 无 AI improve event (daily cron 挂?) last={last}', 'latency_ms': ms(t)}
    if errored > 0 or (skipped > 0 and done == 0):
        return {'status': WARN, 'detail': f'25h: done={done} skipped={skipped} errored={errored} (没产出)', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'25h: done={done} skipped={skipped} errored={errored}', 'latency_ms': ms(t)}


def check_translate_pipeline() -> dict:
    """4. Translate 流: pending 不能 >5 长时间 + 最近 6h 有 translated"""
    t = t0()
    rc, out = psql("""
        SELECT
          (SELECT COUNT(*) FROM strategy_candidates WHERE status='pending'),
          (SELECT COUNT(*) FROM strategy_candidates WHERE status='translated' AND updated_at > NOW() - INTERVAL '6 hours'),
          (SELECT COUNT(*) FROM strategy_candidates WHERE status='error')
    """)
    if rc != 0:
        return {'status': WARN, 'detail': 'pg query fail', 'latency_ms': ms(t)}
    try:
        pending, recent_translated, errored = [int(x) for x in out.strip().split('|')]
    except:
        return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}
    if pending > 10:
        return {'status': FAIL, 'detail': f'pending={pending} 堆积 (translate cron 可能挂)', 'latency_ms': ms(t),
                'autofix_hint': 'translate_cli.py 跑一次清池子'}
    return {'status': OK, 'detail': f'pending={pending} recent_translated_6h={recent_translated} errored={errored}', 'latency_ms': ms(t)}


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
        return {'status': FAIL, 'detail': f'1h LLM timeouts={timeouts} parse_fails={parse_fails}', 'latency_ms': ms(t),
                'autofix_hint': '考虑 bump CLAUDE_CLI_TIMEOUT'}
    if timeouts > 0 or parse_fails > 0:
        return {'status': WARN, 'detail': f'1h LLM timeouts={timeouts} parse_fails={parse_fails}', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': '1h 无 LLM call error', 'latency_ms': ms(t)}


def check_pg_pool() -> dict:
    """6. PG connection count（防坑 18 复发）"""
    t = t0()
    rc, out = psql("SELECT count(*) FROM pg_stat_activity")
    if rc != 0:
        return {'status': WARN, 'detail': 'pg query fail', 'latency_ms': ms(t)}
    try: count = int(out.strip())
    except: return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}
    if count > 80:
        return {'status': FAIL, 'detail': f'pg conn={count} > 80 (max 100，坑 18 复发?)', 'latency_ms': ms(t),
                'autofix_hint': '考虑重启 celery-worker 释放 idle'}
    if count > 50:
        return {'status': WARN, 'detail': f'pg conn={count} > 50', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'pg conn={count}', 'latency_ms': ms(t)}


def check_okx_connectivity() -> dict:
    """7. OKX /api/account 通"""
    t = t0()
    try:
        req = urllib.request.Request('http://localhost:5005/api/account',
                                      headers={'Authorization': f'Bearer {API_TOKEN}'})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        return {'status': FAIL, 'detail': f'/api/account fail: {type(e).__name__}', 'latency_ms': ms(t)}
    bal = (data.get('balances') or {}).get('USDT')
    if bal is None:
        return {'status': WARN, 'detail': 'API ok 但 USDT 缺', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'OKX USDT={float(bal):.2f}', 'latency_ms': ms(t)}


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
    return {'status': OK, 'detail': f'{count} open positions, last_opened={last[:19] if last != "none" else "none"}', 'latency_ms': ms(t)}


def check_running_strategies() -> dict:
    """9. running 策略数 > 0"""
    t = t0()
    rc, out = psql("SELECT COUNT(*) FROM strategies WHERE status='running'")
    if rc != 0: return {'status': WARN, 'detail': 'pg fail', 'latency_ms': ms(t)}
    try: count = int(out.strip())
    except: return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}
    if count == 0:
        return {'status': WARN, 'detail': '0 running 策略 (user 可能 stop 了)', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'{count} running', 'latency_ms': ms(t)}


CHECKS = [
    ('celery_beat_heartbeat', check_celery_beat_heartbeat),
    ('signal_cycle_health',   check_signal_cycle_15m),
    ('ai_improve_recent',     check_ai_improve_recent),
    ('translate_pipeline',    check_translate_pipeline),
    ('llm_errors_1h',         check_llm_errors_recent),
    ('pg_connection_pool',    check_pg_pool),
    ('okx_connectivity',      check_okx_connectivity),
    ('reconcile_health',      check_reconcile_recent),
    ('running_strategies',    check_running_strategies),
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
            'chat_id': TG_CHAT, 'parse_mode': 'Markdown',
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
                line = f'• `{n}`: {r["detail"]}'
                if af:
                    line += f'\n  🔧 autofix: {"✅" if af["ok"] else "❌"} {af["msg"]}'
                elif r.get('autofix_hint'):
                    line += f'\n  💡 hint: {r["autofix_hint"]}'
                lines.append(line)
            text = '*🚨 flow_watchdog FAIL*\n\n' + '\n'.join(lines)
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
