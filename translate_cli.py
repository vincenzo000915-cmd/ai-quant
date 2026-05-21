#!/usr/bin/env python3
"""Host-side 候選翻譯器 — 用本機 claude CLI（你的 Claude Pro/Max 訂閱）翻譯候選策略。

跟 app/services/llm_translator.py 走 Anthropic SDK 那條路平行：
  - 容器內：build_prompt_for_candidate(cid) 組 prompt + save_translation_for_candidate(cid, out) 存回
  - 容器外（本機）：claude --print --system-prompt "..." 跑 LLM
  - 兩端透過 docker exec stdin/stdout 串接

用法：
    python3 /opt/quant/translate_cli.py [candidate_id]      # 單一
    python3 /opt/quant/translate_cli.py --pending           # 跑所有 status='pending'
    python3 /opt/quant/translate_cli.py --pending --max 5   # 限制數量
"""
import argparse
import json
import subprocess
import sys
import time


CONTAINER = 'quant-web-1'
CLAUDE_MODEL = 'sonnet'   # 速度 / 訂閱額度友善
CLAUDE_TIMEOUT = 300   # Phase 12.13: 大 prompt 实测 105s，120s 边缘；给 5 min buffer


def _docker_python(code: str, stdin: str | None = None, timeout: int = 60) -> str:
    """在容器內跑 python -c <code>，回傳 stdout（若 rc != 0 抓 stderr 後 raise）"""
    args = ['docker', 'exec', '-i', CONTAINER, 'python', '-c', code]
    r = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f'docker exec python failed (rc={r.returncode}): {r.stderr.strip()}')
    return r.stdout


def list_pending() -> list[dict]:
    code = """
import json
from app import create_app
app = create_app()
with app.app_context():
    from app.models import StrategyCandidate
    items = StrategyCandidate.query.filter_by(status='pending').order_by(StrategyCandidate.id).all()
    print(json.dumps([{'id': c.id, 'name': c.source_name or c.id, 'lang': c.raw_lang} for c in items]))
"""
    return json.loads(_docker_python(code))


def build_prompt(cid: int) -> dict:
    code = f"""
import json
from app import create_app
app = create_app()
with app.app_context():
    from app.services.llm_translator import build_prompt_for_candidate
    print(json.dumps(build_prompt_for_candidate({cid})))
"""
    return json.loads(_docker_python(code))


def claude_translate(prompt_text: str) -> str:
    """呼叫 claude --print，回傳 stdout 原文"""
    args = ['claude', '--print', '--model', CLAUDE_MODEL]
    r = subprocess.run(args, input=prompt_text, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError(f'claude --print failed (rc={r.returncode}): {r.stderr.strip()[:300]}')
    return r.stdout


def save_translation(cid: int, raw_output: str) -> dict:
    # raw_output 透過 stdin 餵進去（避免 shell quoting / 跳脫地獄）
    code = f"""
import sys, json
raw = sys.stdin.read()
from app import create_app
app = create_app()
with app.app_context():
    from app.services.llm_translator import save_translation_for_candidate
    print(json.dumps(save_translation_for_candidate({cid}, raw, model_label='claude-cli-sonnet')))
"""
    return json.loads(_docker_python(code, stdin=raw_output, timeout=90))


def translate_one(cid: int) -> dict:
    print(f'[{cid}] 抓 prompt…')
    bp = build_prompt(cid)
    print(f'[{cid}] {bp["source_name"]} ({bp["raw_lang"]}, prompt {len(bp["prompt"])} chars) → claude…')
    t0 = time.time()
    raw = claude_translate(bp['prompt'])
    dt = time.time() - t0
    print(f'[{cid}] claude 回應 {len(raw)} chars，耗時 {dt:.1f}s。寫回 DB + 沙箱驗證…')
    res = save_translation(cid, raw)
    if res.get('ok'):
        c = res['candidate']
        print(f'[{cid}] ✅ translated → fn={c["signal_fn_name"]} type={c["candidate_type"]} '
              f'tf={c["timeframe"]} category={c["category"]}')
    else:
        print(f'[{cid}] ❌ {res.get("error", "")[:200]}')
    return res


def main():
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument('cid', nargs='?', type=int, help='單一 candidate id')
    grp.add_argument('--pending', action='store_true', help='跑所有 status=pending')
    parser.add_argument('--max', type=int, help='--pending 模式下最多翻幾個')
    args = parser.parse_args()

    if args.cid:
        translate_one(args.cid)
        return 0

    pending = list_pending()
    if args.max:
        pending = pending[: args.max]
    if not pending:
        print('沒有 pending 候選。爬一波先：docker exec -i quant-web-1 python -c "from app import create_app; create_app().app_context().push(); from app.services.crawlers.github import crawl_all; print(crawl_all(max_files_per_repo=5))"')
        return 0

    print(f'共 {len(pending)} 個 pending 待翻譯')
    ok = err = 0
    for p in pending:
        try:
            r = translate_one(p['id'])
            if r.get('ok'):
                ok += 1
            else:
                err += 1
        except Exception as e:
            err += 1
            print(f'[{p["id"]}] EXCEPTION: {type(e).__name__}: {e}')
    print(f'\n=== 完成：{ok} 成功 / {err} 失敗 ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
