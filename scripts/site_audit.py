#!/usr/bin/env python3
"""Phase 12.42 全站健康审计 — 纯基础设施层（不依赖 v6/v7 AI improve 内部 logic）。

设计：
  - 14 检查类别，每个 OK/WARN/FAIL + detail + latency
  - 不依赖 Celery（如 Celery 挂了，本脚本仍能跑 + 告警）
  - 不依赖 web 模块（直接 docker exec / curl localhost）
  - 不依赖 third-party 外部监控
  - FAIL → Telegram + dedup（30min 窗口同 check 不重复刷）
  - 报告写 /var/log/quant/audit_latest.json + 历史 jsonl
  - 用 audit_log event 抽象任务执行检查（v7 内部改变不会破脚本）

用法：
  python3 /opt/quant/scripts/site_audit.py                 # 跑全部 + 写报告
  python3 /opt/quant/scripts/site_audit.py --dry-run       # 不发 Telegram
  python3 /opt/quant/scripts/site_audit.py --quiet         # 只 JSON output
  python3 /opt/quant/scripts/site_audit.py --check celery_worker_ping   # 单跑某 check

未来加 host cron（user 同意后）:
  */15 * * * * /usr/bin/python3 /opt/quant/scripts/site_audit.py >> /var/log/quant/audit_cron.log 2>&1
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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# === 配置 ===
LOG_DIR = Path('/var/log/quant')
PROD_URL = 'https://ai-quant.medias-ai.cloud'
WEB_LOCAL = 'http://localhost:5005'
DOMAIN = 'ai-quant.medias-ai.cloud'
TG_TOKEN = os.environ.get('TG_TOKEN', '8987521221:AAHRYteR9sYCC7j7t7uT1GMbl3pmTXmMVhw')
TG_CHAT = os.environ.get('TG_CHAT', '844917210')
API_TOKEN = os.environ.get('API_AUTH_TOKEN', 'MycRdx7-yRb5u5vasVydoVpkpgJaxq14anw7mrNrCd4')
DEDUP_WINDOW_SEC = 1800   # 30 min 同 check 同状态不重复 Telegram

# Severity
OK = 'OK'
WARN = 'WARN'
FAIL = 'FAIL'


# === 工具函数 ===

def t0() -> float:
    return time.time()


def ms(t: float) -> int:
    return int((time.time() - t) * 1000)


def run_cmd(cmd, timeout: int = 10) -> tuple[int, str, str]:
    """run command, return (returncode, stdout, stderr)"""
    try:
        p = subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'
    except FileNotFoundError as e:
        return 127, '', f'not found: {e}'


def psql_query(sql: str, timeout: int = 10) -> tuple[int, str]:
    """run psql -t -A in postgres container"""
    rc, out, err = run_cmd(
        ['docker', 'exec', 'quant-postgres-1', 'psql', '-U', 'quant', '-d', 'quant',
         '-t', '-A', '-c', sql],
        timeout=timeout,
    )
    return rc, (out if rc == 0 else err)


def http_get_json(url: str, headers: dict | None = None, timeout: int = 10) -> tuple[bool, dict | str]:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode('utf-8', errors='replace')
            try:
                return True, json.loads(body)
            except json.JSONDecodeError:
                return False, f'json decode fail: {body[:100]}'
    except urllib.error.HTTPError as e:
        return False, f'HTTP {e.code}'
    except Exception as e:
        return False, f'{type(e).__name__}: {str(e)[:120]}'


# === 检查函数 (14 个) ===

def check_docker_containers() -> dict:
    """1. 5 个关键容器 Up"""
    t = t0()
    expected = ['quant-web-1', 'quant-celery-worker-1', 'quant-celery-beat-1',
                'quant-postgres-1', 'quant-redis-1']
    rc, out, err = run_cmd(['docker', 'ps', '--format', '{{.Names}}\t{{.Status}}'])
    if rc != 0:
        return {'status': FAIL, 'detail': f'docker ps: {err}', 'latency_ms': ms(t)}
    running = {}
    for line in out.splitlines():
        if '\t' in line:
            name, status = line.split('\t', 1)
            running[name] = status
    missing = [c for c in expected if c not in running or 'Up' not in running.get(c, '')]
    if missing:
        return {'status': FAIL, 'detail': f'容器 down: {missing}', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'5/5 容器 Up', 'latency_ms': ms(t)}


def check_postgres_health() -> dict:
    """2. Postgres 通 + 连接数 < max"""
    t = t0()
    rc, out = psql_query("SELECT 1, count(*) FROM pg_stat_activity")
    if rc != 0:
        return {'status': FAIL, 'detail': f'psql fail: {out[:100]}', 'latency_ms': ms(t)}
    try:
        _, conn = out.strip().split('|')
        conn = int(conn)
    except Exception:
        return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}
    if conn > 80:
        return {'status': FAIL, 'detail': f'连接数 {conn} > 80 (max 100，坑18 复发?)', 'latency_ms': ms(t)}
    if conn > 50:
        return {'status': WARN, 'detail': f'连接数 {conn} > 50', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'pg up, conn={conn}', 'latency_ms': ms(t)}


def check_redis_health() -> dict:
    """3. Redis PING"""
    t = t0()
    rc, out, _ = run_cmd(['docker', 'exec', 'quant-redis-1', 'redis-cli', 'PING'], timeout=5)
    if rc != 0 or 'PONG' not in out:
        return {'status': FAIL, 'detail': f'redis no pong: {out}', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': 'PONG', 'latency_ms': ms(t)}


def check_web_local() -> dict:
    """4. Web /health/business OK + 0 issues"""
    t = t0()
    ok, body = http_get_json(f'{WEB_LOCAL}/health/business', timeout=8)
    if not ok:
        return {'status': FAIL, 'detail': f'web local: {body}', 'latency_ms': ms(t)}
    status = body.get('status')
    issues = body.get('issues') or []
    if status != 'healthy':
        return {'status': FAIL, 'detail': f'{status}: {issues}', 'latency_ms': ms(t)}
    if issues:
        return {'status': WARN, 'detail': f'healthy but {len(issues)} issues: {issues[:3]}', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': 'healthy, 0 issues', 'latency_ms': ms(t)}


def check_web_prod() -> dict:
    """5. Production HTTPS 可达 (本机出网到自己域名)"""
    t = t0()
    try:
        req = urllib.request.Request(PROD_URL, headers={'User-Agent': 'site-audit/1.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            code = r.status
            body_len = len(r.read())
    except Exception as e:
        return {'status': FAIL, 'detail': f'prod: {type(e).__name__}: {str(e)[:100]}', 'latency_ms': ms(t)}
    if code != 200:
        return {'status': FAIL, 'detail': f'HTTP {code}', 'latency_ms': ms(t)}
    if body_len < 2000:
        return {'status': WARN, 'detail': f'HTTP 200 但 body {body_len}b 偏小', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'HTTP 200 / {body_len}b', 'latency_ms': ms(t)}


def check_ssl_cert() -> dict:
    """6. SSL 证书过期天数 (< 30 WARN, < 7 FAIL)"""
    t = t0()
    cmd = f'echo | openssl s_client -servername {DOMAIN} -connect {DOMAIN}:443 2>/dev/null | openssl x509 -noout -enddate'
    rc, out, _ = run_cmd(cmd, timeout=10)
    if rc != 0 or '=' not in out:
        return {'status': WARN, 'detail': f'openssl 取证书失败', 'latency_ms': ms(t)}
    try:
        date_str = out.split('=', 1)[1].strip()
        exp = datetime.datetime.strptime(date_str, '%b %d %H:%M:%S %Y GMT')
        days_left = (exp - datetime.datetime.utcnow()).days
    except Exception as e:
        return {'status': WARN, 'detail': f'parse: {e}', 'latency_ms': ms(t)}
    if days_left < 7:
        return {'status': FAIL, 'detail': f'证书 {days_left} 天后过期 ({date_str})', 'latency_ms': ms(t)}
    if days_left < 30:
        return {'status': WARN, 'detail': f'证书 {days_left} 天后过期 — 该 renew', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'证书 {days_left} 天后过期', 'latency_ms': ms(t)}


def check_disk_space() -> dict:
    """7. 根分区 used %"""
    t = t0()
    rc, out, _ = run_cmd(['df', '-h', '/'])
    if rc != 0:
        return {'status': WARN, 'detail': 'df failed', 'latency_ms': ms(t)}
    lines = out.splitlines()
    if len(lines) < 2:
        return {'status': WARN, 'detail': 'df parse', 'latency_ms': ms(t)}
    parts = lines[1].split()
    try:
        use = int(parts[4].rstrip('%'))
    except Exception:
        return {'status': WARN, 'detail': f'parse: {lines[1]}', 'latency_ms': ms(t)}
    if use > 90:
        return {'status': FAIL, 'detail': f'磁盘 {use}% used (avail={parts[3]})', 'latency_ms': ms(t)}
    if use > 80:
        return {'status': WARN, 'detail': f'磁盘 {use}%', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'磁盘 {use}% used (avail={parts[3]})', 'latency_ms': ms(t)}


def check_ram_load() -> dict:
    """8. RAM % + load1m"""
    t = t0()
    rc, out, _ = run_cmd(['free', '-m'])
    if rc != 0:
        return {'status': WARN, 'detail': 'free failed', 'latency_ms': ms(t)}
    try:
        mem_line = out.splitlines()[1].split()
        total, used = int(mem_line[1]), int(mem_line[2])
        pct = used * 100 // total
    except Exception:
        return {'status': WARN, 'detail': 'parse', 'latency_ms': ms(t)}
    load_1m = None
    try:
        load_1m = float(Path('/proc/loadavg').read_text().split()[0])
    except Exception:
        pass
    if pct > 92:
        return {'status': FAIL, 'detail': f'RAM {pct}% (used {used}/{total}MB) load1m={load_1m}', 'latency_ms': ms(t)}
    if pct > 80:
        return {'status': WARN, 'detail': f'RAM {pct}% load1m={load_1m}', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'RAM {pct}% load1m={load_1m}', 'latency_ms': ms(t)}


def check_celery_worker_ping() -> dict:
    """9. Celery worker 响应 ping"""
    t = t0()
    rc, out, err = run_cmd(
        ['docker', 'exec', 'quant-celery-worker-1', 'celery',
         '-A', 'app.tasks.strategy_tasks', 'inspect', 'ping', '-t', '5'],
        timeout=15,
    )
    if rc != 0 or 'pong' not in (out + err).lower():
        return {'status': FAIL, 'detail': f'worker no pong: {(err or out)[:200]}', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': 'pong', 'latency_ms': ms(t)}


def check_celery_beat_alive() -> dict:
    """10. Celery beat 调度活着 — Redis celery-task-meta keys 增长 + 历次基线对比

    每次跑保存当前 task-meta key count 到 audit_baseline.json。下次跑比较：
      - 数字增长 → beat 正在派发任务 → OK
      - 没增长 → beat 可能挂了 → FAIL
      - 首跑无基线 → 写入基线后 WARN
    """
    t = t0()
    rc, out, _ = run_cmd(
        ['docker', 'exec', 'quant-redis-1', 'redis-cli', 'EVAL',
         "return #redis.call('keys', 'celery-task-meta-*')", '0'],
        timeout=8,
    )
    if rc != 0:
        return {'status': WARN, 'detail': f'redis EVAL fail: {out[:100]}', 'latency_ms': ms(t)}
    try:
        current = int(out.strip())
    except Exception:
        return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}

    baseline_file = LOG_DIR / 'audit_baseline.json'
    baseline = {}
    if baseline_file.exists():
        try:
            baseline = json.loads(baseline_file.read_text())
        except Exception:
            baseline = {}
    prev = baseline.get('celery_task_meta_count')
    prev_ts = baseline.get('celery_task_meta_ts', 0)
    now_ts = time.time()
    # 写新 baseline
    baseline['celery_task_meta_count'] = current
    baseline['celery_task_meta_ts'] = now_ts
    baseline_file.write_text(json.dumps(baseline))

    if prev is None:
        return {'status': WARN, 'detail': f'首次跑无基线 (current={current})，下次起对比', 'latency_ms': ms(t)}
    elapsed_min = (now_ts - prev_ts) / 60
    # 容忍：< 5min 跑（手动重跑）不算 FAIL
    if elapsed_min < 3:
        return {'status': OK, 'detail': f'task-meta={current} (上次{elapsed_min:.1f}min前={prev}，间隔过短)', 'latency_ms': ms(t)}
    if current <= prev:
        # 注意 TTL 也会让 key 减少（自然过期）。但如果 beat 在跑，新增应快于过期
        # 没增长 → 几乎确定 beat 挂
        return {'status': FAIL, 'detail': f'task-meta {prev}→{current} 无增长 ({elapsed_min:.1f}min)，beat 挂?', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'task-meta {prev}→{current} (+{current-prev} 个 in {elapsed_min:.1f}min)', 'latency_ms': ms(t)}


def check_okx_connectivity() -> dict:
    """11. OKX API 通 — /api/account 返 USDT balance (balances dict 是 symbol→float)"""
    t = t0()
    ok, body = http_get_json(
        f'{WEB_LOCAL}/api/account',
        headers={'Authorization': f'Bearer {API_TOKEN}'},
        timeout=20,
    )
    if not ok:
        return {'status': FAIL, 'detail': f'OKX/account: {body}', 'latency_ms': ms(t)}
    balances = body.get('balances') or {}
    usdt = balances.get('USDT')
    if usdt is None:
        return {'status': WARN, 'detail': 'OKX up 但 USDT 字段缺', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'OKX ok USDT={float(usdt):.2f} equity={float(body.get("equity", 0)):.2f}', 'latency_ms': ms(t)}


def check_telegram_bot() -> dict:
    """12. Telegram bot getMe"""
    t = t0()
    ok, body = http_get_json(f'https://api.telegram.org/bot{TG_TOKEN}/getMe', timeout=8)
    if not ok:
        return {'status': WARN, 'detail': f'tg: {body}', 'latency_ms': ms(t)}
    if not body.get('ok'):
        return {'status': FAIL, 'detail': f'tg getMe: {body}', 'latency_ms': ms(t)}
    name = body.get('result', {}).get('username', '?')
    return {'status': OK, 'detail': f'bot=@{name}', 'latency_ms': ms(t)}


def check_recent_critical_events() -> dict:
    """13. 关键事件最近活跃度 — translate / backtest / ai_improve 24h 内"""
    t = t0()
    rc, out = psql_query("""
        SELECT
          (SELECT count(*) FROM audit_log WHERE event_type='candidate_translate' AND created_at > NOW() - INTERVAL '24 hours'),
          (SELECT count(*) FROM backtest_results WHERE created_at > NOW() - INTERVAL '24 hours'),
          (SELECT count(*) FROM audit_log WHERE event_type LIKE 'auto_ai_improve%' AND created_at > NOW() - INTERVAL '48 hours')
    """)
    if rc != 0:
        return {'status': WARN, 'detail': 'query fail', 'latency_ms': ms(t)}
    try:
        translate24, backtest24, aiimprove48 = (int(x) for x in out.strip().split('|'))
    except Exception:
        return {'status': WARN, 'detail': f'parse: {out}', 'latency_ms': ms(t)}
    notes = [f'translate24={translate24}', f'backtest24={backtest24}', f'aiimprove48={aiimprove48}']
    # AI improve daily 跑 — 48h 无说明 cron 出问题
    if aiimprove48 == 0:
        return {'status': FAIL, 'detail': f'48h 无 AI improve event (daily cron 挂了?) | {notes}', 'latency_ms': ms(t)}
    # backtest 24h 0 个不算 FAIL（可能没新候选），但 WARN
    if backtest24 == 0:
        return {'status': WARN, 'detail': f'24h 无 backtest (没新候选?) | {notes}', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': ' '.join(notes), 'latency_ms': ms(t)}


def check_translate_cron() -> dict:
    """14. host translate cron — 检查 host cron log 最近 mtime"""
    t = t0()
    log_candidates = [
        Path('/var/log/quant_translate.log'),    # actual location (see /etc/cron.d/...)
        Path('/var/log/quant/translate_pending_cron.log'),
        Path('/opt/quant/logs/translate_pending_cron.log'),
        Path('/tmp/translate_pending_cron.log'),
    ]
    found = None
    for f in log_candidates:
        if f.exists():
            found = f
            break
    if not found:
        return {'status': WARN, 'detail': f'translate cron log 文件不存在 ({log_candidates})', 'latency_ms': ms(t)}
    mtime = found.stat().st_mtime
    age_min = (time.time() - mtime) / 60
    if age_min > 60 * 5:    # 4h cron 留 5h 余量
        return {'status': FAIL, 'detail': f'translate cron log {age_min:.0f}min 没更新 (4h cron 可能挂了): {found}', 'latency_ms': ms(t)}
    return {'status': OK, 'detail': f'cron log {age_min:.0f}min 前更新: {found.name}', 'latency_ms': ms(t)}


CHECKS: list[tuple[str, callable]] = [
    ('docker_containers',     check_docker_containers),
    ('postgres_health',       check_postgres_health),
    ('redis_health',          check_redis_health),
    ('web_local',             check_web_local),
    ('web_production',        check_web_prod),
    ('ssl_cert',              check_ssl_cert),
    ('disk_space',            check_disk_space),
    ('ram_load',              check_ram_load),
    ('celery_worker_ping',    check_celery_worker_ping),
    ('celery_beat_alive',     check_celery_beat_alive),
    ('okx_connectivity',      check_okx_connectivity),
    ('telegram_bot',          check_telegram_bot),
    ('recent_critical_events',check_recent_critical_events),
    ('translate_cron',        check_translate_cron),
]


# === Dedup ===

def _dedup_path() -> Path:
    return LOG_DIR / 'audit_alert_dedup.json'


def load_dedup() -> dict:
    p = _dedup_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_dedup(d: dict):
    _dedup_path().write_text(json.dumps(d))


def should_alert(check_name: str, status: str) -> bool:
    """FAIL 才 alert；同 check 在 dedup 窗口内不重复发"""
    if status != FAIL:
        return False
    d = load_dedup()
    now = time.time()
    last = d.get(check_name, 0)
    if now - last < DEDUP_WINDOW_SEC:
        return False
    d[check_name] = now
    save_dedup(d)
    return True


def send_telegram(text: str) -> bool:
    try:
        data = urllib.parse.urlencode({
            'chat_id': TG_CHAT,
            'parse_mode': 'Markdown',
            'text': text[:4096],
        }).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=data,
            method='POST',
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


# === Main ===

def main() -> int:
    parser = argparse.ArgumentParser(description='Phase 12.42 site audit')
    parser.add_argument('--dry-run', action='store_true', help='不发 Telegram')
    parser.add_argument('--quiet', action='store_true', help='只 JSON output (machine-readable)')
    parser.add_argument('--check', help='只跑某单个 check')
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    selected = CHECKS
    if args.check:
        selected = [(n, fn) for n, fn in CHECKS if n == args.check]
        if not selected:
            print(f'unknown check: {args.check}; valid: {[n for n, _ in CHECKS]}', file=sys.stderr)
            return 2

    report = {
        'checked_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'host': socket.gethostname(),
        'results': {},
        'summary': {'OK': 0, 'WARN': 0, 'FAIL': 0},
    }
    for name, fn in selected:
        try:
            res = fn()
        except Exception as e:
            res = {'status': FAIL, 'detail': f'check 抛错: {type(e).__name__}: {e}', 'latency_ms': 0}
        report['results'][name] = res
        report['summary'][res['status']] += 1

    # write JSON
    (LOG_DIR / 'audit_latest.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    history = LOG_DIR / f'audit_{datetime.datetime.utcnow():%Y%m%d}.jsonl'
    with history.open('a') as f:
        f.write(json.dumps(report, ensure_ascii=False) + '\n')

    # Telegram alert if any new FAIL
    if not args.dry_run:
        new_fails = []
        for n, res in report['results'].items():
            if should_alert(n, res['status']):
                new_fails.append(n)
        if new_fails:
            lines = [f'• `{n}`: {report["results"][n]["detail"]}' for n in new_fails]
            warns = [f'• `{n}`: {res["detail"]}'
                     for n, res in report['results'].items() if res['status'] == WARN]
            text = '*🚨 site_audit FAIL*\n\n' + '\n'.join(lines)
            if warns:
                text += '\n\n_⚠ WARN_:\n' + '\n'.join(warns[:5])
            send_telegram(text)

    # stdout
    if args.quiet:
        print(json.dumps(report, ensure_ascii=False))
    else:
        s = report['summary']
        print(f"=== site_audit {report['checked_at']} ===")
        print(f"OK={s['OK']} WARN={s['WARN']} FAIL={s['FAIL']}")
        for name, res in report['results'].items():
            icon = {'OK': '✓', 'WARN': '⚠', 'FAIL': '✗'}[res['status']]
            print(f"  {icon} {name:25s} {res['detail']}  ({res['latency_ms']}ms)")

    if report['summary']['FAIL'] > 0:
        return 2
    if report['summary']['WARN'] > 0:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
