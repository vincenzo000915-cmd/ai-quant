"""CLI: 跑 GitHub 爬蟲，把策略源碼塞進 strategy_candidates 表。

usage:
    docker exec -i quant-web-1 python seed_github_candidates.py
    docker exec -i quant-web-1 python seed_github_candidates.py --max 5  # 每 repo 最多 5 個

預設 repo 清單見 app/services/crawlers/github.py DEFAULT_REPOS。
"""
import sys
import argparse

from app import create_app
from app.services.crawlers.github import crawl_all


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max', type=int, default=None,
                        help='每個 repo 最多收幾個策略（給快速 smoke test 用）')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        result = crawl_all(max_files_per_repo=args.max)
        print('=== Per-repo ===')
        for r in result['repos']:
            print(f'  {r.get("repo")}: detected={r.get("detected", 0)} '
                  f'inserted={r.get("inserted", 0)} skipped={r.get("skipped", 0)} '
                  f'errors={r.get("errors", 0)}')
            if r.get('error'):
                print(f'    ERROR: {r["error"]}')
        print('=== Totals ===')
        for k, v in result['totals'].items():
            print(f'  {k}: {v}')
        return 0


if __name__ == '__main__':
    sys.exit(main())
