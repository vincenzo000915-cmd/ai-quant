"""GitHub 策略爬蟲 — Phase 4.2

從幾個知名量化策略 repo 拉策略源碼，寫入 strategy_candidates 表（status='pending'）。
不做翻譯 — 那是 candidate_pipeline 的事。

預設 repo 清單在 DEFAULT_REPOS，可在 API / CLI 呼叫時覆寫。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from app.extensions import db
from app.models import StrategyCandidate


CACHE_DIR = Path('/tmp/quant_crawler/github')

# 預設 repo 清單。kind 決定怎麼 walk + 怎麼挑檔案。
DEFAULT_REPOS = [
    {
        'kind': 'freqtrade',
        'url': 'https://github.com/freqtrade/freqtrade-strategies.git',
        'branch': 'main',
        'walk_subdirs': ['user_data/strategies'],   # 只看這幾個資料夾
        'license_hint': 'GPLv3',
    },
    {
        'kind': 'freqtrade',
        'url': 'https://github.com/iterativv/NostalgiaForInfinity.git',
        'branch': 'main',
        'walk_subdirs': ['.'],
        'license_hint': 'GPLv3',
    },
]


# freqtrade strategy 偵測：找繼承 IStrategy 的 class
_FREQTRADE_CLASS_RE = re.compile(r'class\s+([A-Za-z_]\w*)\s*\([^)]*IStrategy[^)]*\)\s*:')
# jesse strategy 偵測：找繼承 Strategy 的 class（從 jesse import）
_JESSE_IMPORT_RE = re.compile(r'from\s+jesse\.strategies\s+import\s+Strategy')
_JESSE_CLASS_RE = re.compile(r'class\s+([A-Za-z_]\w*)\s*\([^)]*Strategy[^)]*\)\s*:')


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    """執行命令，失敗就丟 RuntimeError"""
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f'cmd {cmd!r} failed (rc={res.returncode}): {res.stderr.strip()}')
    return res.stdout


def _clone_or_update(url: str, branch: str = 'main') -> Path:
    """淺 clone 或更新到最新。回傳本地路徑。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[^a-zA-Z0-9_-]', '_', url.split('/')[-1].replace('.git', ''))
    local = CACHE_DIR / name
    if local.exists():
        try:
            _run(['git', '-C', str(local), 'fetch', '--depth=1', 'origin', branch], timeout=180)
            _run(['git', '-C', str(local), 'reset', '--hard', f'origin/{branch}'], timeout=30)
        except RuntimeError:
            # fetch 失敗時重 clone
            _run(['rm', '-rf', str(local)])
            _run(['git', 'clone', '--depth=1', '--branch', branch, url, str(local)], timeout=300)
    else:
        _run(['git', 'clone', '--depth=1', '--branch', branch, url, str(local)], timeout=300)
    return local


def _detect_strategies(repo_dir: Path, kind: str, subdirs: list[str]) -> list[dict]:
    """掃 repo 找符合 kind 的策略檔。回傳 [{relpath, class_name, content}]"""
    found = []
    bases = [repo_dir / s for s in subdirs] if subdirs and subdirs != ['.'] else [repo_dir]
    for base in bases:
        if not base.exists() or not base.is_dir():
            continue
        for path in base.rglob('*.py'):
            try:
                txt = path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            if len(txt) > 200_000:
                continue   # 太大跳過
            class_name = None
            if kind == 'freqtrade':
                m = _FREQTRADE_CLASS_RE.search(txt)
                if not m:
                    continue
                class_name = m.group(1)
            elif kind == 'jesse':
                if not _JESSE_IMPORT_RE.search(txt):
                    continue
                m = _JESSE_CLASS_RE.search(txt)
                if not m:
                    continue
                class_name = m.group(1)
            else:
                # generic：任何 .py 都收
                class_name = path.stem

            found.append({
                'relpath': str(path.relative_to(repo_dir)),
                'class_name': class_name,
                'content': txt,
            })
    return found


def _source_url(repo_url: str, branch: str, relpath: str) -> str:
    """構造 GitHub blob URL — 用 (source, source_url) 做唯一性檢查"""
    base = repo_url.rstrip('/').removesuffix('.git')
    return f'{base}/blob/{branch}/{relpath}'


def crawl_repo(repo_cfg: dict, max_files: int | None = None) -> dict:
    """爬單一 repo。回傳 {'inserted', 'skipped', 'errors', 'detected'}"""
    url = repo_cfg['url']
    branch = repo_cfg.get('branch', 'main')
    kind = repo_cfg.get('kind', 'freqtrade')
    subdirs = repo_cfg.get('walk_subdirs', ['.'])
    license_hint = repo_cfg.get('license_hint', '')

    local = _clone_or_update(url, branch)
    files = _detect_strategies(local, kind, subdirs)
    if max_files:
        files = files[:max_files]

    inserted = skipped = errors = 0
    for f in files:
        s_url = _source_url(url, branch, f['relpath'])
        existing = StrategyCandidate.query.filter_by(source='github', source_url=s_url).first()
        if existing:
            skipped += 1
            continue
        try:
            c = StrategyCandidate(
                source='github',
                source_url=s_url,
                source_name=f['class_name'],
                source_author=url.split('/')[-2] if '/' in url else 'unknown',
                source_meta={
                    'kind': kind,
                    'license_hint': license_hint,
                    'repo_url': url,
                    'branch': branch,
                    'relpath': f['relpath'],
                },
                raw_code=f['content'],
                raw_lang='python',
                status='pending',
            )
            db.session.add(c)
            db.session.commit()
            inserted += 1
        except Exception:
            db.session.rollback()
            errors += 1

    return {
        'repo': url,
        'detected': len(files),
        'inserted': inserted,
        'skipped': skipped,
        'errors': errors,
    }


def crawl_all(repos: list[dict] | None = None, max_files_per_repo: int | None = None) -> dict:
    """爬所有預設 repo（或自訂清單）。回傳每 repo 的統計。"""
    repos = repos or DEFAULT_REPOS
    results = []
    for cfg in repos:
        try:
            results.append(crawl_repo(cfg, max_files=max_files_per_repo))
        except Exception as e:
            results.append({'repo': cfg.get('url'), 'error': f'{type(e).__name__}: {e}'})
    totals = {
        'inserted': sum(r.get('inserted', 0) for r in results),
        'skipped': sum(r.get('skipped', 0) for r in results),
        'errors': sum(r.get('errors', 0) for r in results),
        'detected': sum(r.get('detected', 0) for r in results),
    }
    return {'repos': results, 'totals': totals}
