"""候選策略 pipeline orchestrator — Phase 4

把單一 StrategyCandidate 推一步：translate → sandbox verify → 標記狀態。
（自動回測在 Phase 4.4 的 backtest_pipeline 處理。）
"""
from __future__ import annotations

from app.extensions import db
from app.models import StrategyCandidate
from app.services.candidate_sandbox import verify_signal_fn
from app.services.llm_translator import translate, LLMTranslatorError


def translate_and_verify(candidate_id: int) -> dict:
    """LLM 翻譯 + 沙箱驗證一個 candidate。回傳更新後的 dict。

    狀態流轉：pending → translating → translated（成功）/ error（失敗）
    """
    c = StrategyCandidate.query.get(candidate_id)
    if c is None:
        return {'ok': False, 'error': f'candidate {candidate_id} not found'}

    if not c.raw_code or not c.raw_code.strip():
        c.status = 'error'
        c.error_log = 'raw_code is empty'
        db.session.commit()
        return {'ok': False, 'error': 'raw_code empty', 'candidate': c.to_dict()}

    c.status = 'translating'
    c.error_log = None
    db.session.commit()

    # ---- LLM 翻譯 ----
    try:
        parsed = translate(
            raw_code=c.raw_code,
            raw_lang=c.raw_lang or 'python',
            source_name=c.source_name or 'unknown',
            source_author=c.source_author or 'unknown',
            source_url=c.source_url or '',
        )
    except LLMTranslatorError as e:
        c.status = 'error'
        c.error_log = f'translate: {e}'
        db.session.commit()
        return {'ok': False, 'error': str(e), 'candidate': c.to_dict()}
    except Exception as e:
        c.status = 'error'
        c.error_log = f'translate unexpected: {type(e).__name__}: {e}'
        db.session.commit()
        return {'ok': False, 'error': f'{type(e).__name__}: {e}', 'candidate': c.to_dict()}

    # ---- 沙箱驗證 ----
    verify = verify_signal_fn(
        source=parsed['signal_fn_source'],
        fn_name=parsed['signal_fn_name'],
        default_params=parsed.get('default_params') or {},
    )
    if not verify['ok']:
        c.status = 'error'
        c.parsed_signal = parsed['signal_fn_source']   # 留住翻譯產物方便事後 debug
        c.signal_fn_name = parsed['signal_fn_name']
        c.candidate_type = parsed['candidate_type']
        c.category = parsed['category']
        c.timeframe = parsed['timeframe']
        c.default_params = parsed['default_params']
        c.llm_notes = parsed['notes']
        c.llm_model = parsed['model']
        c.error_log = f'sandbox: {verify["error"]}'
        db.session.commit()
        return {'ok': False, 'error': f'sandbox: {verify["error"]}', 'verify': verify, 'candidate': c.to_dict()}

    # ---- 成功 ----
    c.parsed_signal = parsed['signal_fn_source']
    c.signal_fn_name = parsed['signal_fn_name']
    c.candidate_type = parsed['candidate_type']
    c.category = parsed['category']
    c.timeframe = parsed['timeframe']
    c.default_params = parsed['default_params']
    c.llm_notes = parsed['notes']
    c.llm_model = parsed['model']
    c.status = 'translated'
    c.error_log = None
    db.session.commit()

    return {
        'ok': True,
        'candidate': c.to_dict(include_code=True),
        'verify': verify,
        'usage': parsed.get('usage'),
    }
