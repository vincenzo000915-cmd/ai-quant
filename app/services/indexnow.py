"""Phase 12.33: IndexNow 协议 — Bing + Yandex 实时索引

USAGE:
  - Manual: POST /api/admin/indexnow/ping  → 推全 sitemap URL
  - Auto: 内容更新时调 notify_urls([url1, url2, ...]) 立刻通知搜索引擎

不影响 Googlebot（Google 不支持 IndexNow，仍用 sitemap）；但 Bing/Yandex
通常 1-2 分钟内抓取（vs sitemap 几天）。
"""
from __future__ import annotations
import os
import logging
import requests

logger = logging.getLogger(__name__)

INDEXNOW_KEY = '19707f303ca640e08bec1f781a52c9d3'
HOST = 'ai-quant.medias-ai.cloud'
ENDPOINT = 'https://api.indexnow.org/indexnow'

# 全部公开页 — sitemap 同步
PUBLIC_URLS = [
    f'https://{HOST}/',
    f'https://{HOST}/pricing',
    f'https://{HOST}/terms',
    f'https://{HOST}/refund-policy',
    f'https://{HOST}/privacy',
]


def notify_urls(urls: list[str] | None = None) -> dict:
    """ping IndexNow，通知 Bing/Yandex 这些 URL 有更新

    无参数 → 推全 sitemap URL；带参 → 只推指定 URL（增量）。
    返回 {ok, status, count, response}
    """
    target_urls = urls or PUBLIC_URLS
    payload = {
        'host': HOST,
        'key': INDEXNOW_KEY,
        'keyLocation': f'https://{HOST}/{INDEXNOW_KEY}.txt',
        'urlList': target_urls,
    }
    try:
        r = requests.post(ENDPOINT, json=payload, timeout=12,
                          headers={'Content-Type': 'application/json'})
        ok = 200 <= r.status_code < 300
        if ok:
            logger.info(f'[indexnow] notified {len(target_urls)} URLs, status={r.status_code}')
        else:
            logger.warning(f'[indexnow] failed status={r.status_code} body={r.text[:200]}')
        return {
            'ok': ok,
            'status': r.status_code,
            'count': len(target_urls),
            'response': r.text[:500],
        }
    except Exception as e:
        logger.exception('[indexnow] request failed')
        return {'ok': False, 'error': str(e), 'count': len(target_urls)}
