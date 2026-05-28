"""Phase 14k-126: chat 输入/输出过滤 — 防 prompt extraction 攻击.

输入端 (pre-LLM): 识别越狱 / prompt 泄漏尝试, 直接拒答 + 计 extraction_attempt audit
输出端 (post-LLM): 二次扫 LLM 回答是否漏内部 prompt 片段, 漏就遮蔽 + 记录

设计原则: 多层防御, 任一层放过都还有下一层兜底
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# 输入端: 越狱 / extraction 关键词
# ---------------------------------------------------------------------------
# 这些短语命中视为攻击意图 (lower-case match)
INPUT_JAILBREAK_PATTERNS = [
    # 直接 prompt extraction
    r'ignore (?:all |the )?(?:previous|prior|above)',
    r'forget (?:all |the )?(?:previous|prior|above)',
    r'忽略(?:之前|上面|以上|前面)',
    r'忘记(?:之前|上面|以上|前面)',
    r'print (?:your |the )?(?:system )?(?:prompt|instructions?|rules?)',
    r'show me (?:your |the )?(?:system )?(?:prompt|instructions|rules)',
    r'reveal (?:your |the )?(?:system )?(?:prompt|instructions?|rules?)',
    r'(?:what is|tell me) your (?:system )?(?:prompt|instructions|role)',
    r'(?:把|说出|告诉我)(?:你的|系统)(?:提示|指令|规则|设定|prompt)',
    r'(?:你的|系统)(?:提示词|指令是|prompt 是)',
    r'你(?:被|被告诉|被设定)',
    r'你之前(?:被|收到)',
    r'repeat (?:the )?(?:system )?(?:prompt|message above|instructions)',
    r'重复(?:你的|上面的|之前的)',
    # Role-play / persona swap
    r'(?:you are now|pretend (?:to be|you are)|act as|role[- ]?play)',
    r'(?:扮演|假装|你现在是|你不再是)',
    r'\b(?:DAN|jailbreak|developer mode)\b',
    r'(?:开发者|越狱)模式',
    # Output the conversation / debug mode
    r'(?:print|show) (?:the |this )?conversation',
    r'(?:debug|developer|admin) mode',
    r'system (?:override|prompt) (?:is|was)',
    # 让 AI 暴露规则 / 阈值
    r'(?:what (?:is|are) the )?(?:thresholds?|gates?|阈值|门槛)',  # 暧昧, 配合上下文
    r'(?:函数名|代码逻辑|内部 prompt|源代码)',
]

INPUT_JAILBREAK_RE = [re.compile(p, re.IGNORECASE) for p in INPUT_JAILBREAK_PATTERNS]

# friendly refusal (避免暴露具体过滤逻辑)
REFUSAL_MESSAGE = (
    '我是你的量化驾驶舱助手 (read-only), 不能分享系统设置或讨论我的角色, '
    '但可以帮你看 strategies / trades / 持仓 / AI 决策。换个问题问我吧 🤖'
)


def check_input(user_message: str) -> tuple[bool, str]:
    """检查 user 输入是否含越狱 / extraction 尝试.

    Returns:
        (allowed, reason_if_blocked)
        allowed=True 表示可以送 LLM
        allowed=False 表示拦下, reason_if_blocked 是 matched pattern (audit 用)
    """
    if not user_message or not user_message.strip():
        return False, 'empty input'
    if len(user_message) > 2000:
        return False, 'input too long (>2000 chars)'
    text = user_message.lower()
    for pat, raw in zip(INPUT_JAILBREAK_RE, INPUT_JAILBREAK_PATTERNS):
        if pat.search(text):
            return False, f'matched: {raw[:60]}'
    return True, ''


# ---------------------------------------------------------------------------
# 输出端: 检查 LLM 回答是否泄漏内部 prompt 片段
# ---------------------------------------------------------------------------
# 这些短语在 LLM 回答里出现 = 可能漏 system prompt
OUTPUT_LEAK_PATTERNS = [
    # 英文 LLM 自暴
    r'my (?:system )?(?:prompt|instructions?) (?:is|are|says)',
    r'i (?:am|was) (?:told|instructed|programmed) to',
    r'as an? (?:ai|assistant) (?:i am|trained|developed)',
    r"here (?:is|'s) (?:my|the) (?:system )?(?:prompt|instructions?|rules?)",
    # 中文 LLM 自暴
    r'我(?:的|被|是被)(?:告诉|指令|要求|设定为|训练成)',
    r'我的(?:系统)?(?:提示|指令|规则|prompt)是',
    r'原(?:始|本)(?:系统)?提示',
    # 内部代码 / 函数名暴露 (我们系统具体的)
    r'(?:advisor_executor|strategy_advisor|build_recommendations|_check_promote_gates)',
    r'(?:strategy_synthesize|strategy_improve_v[678]|sizing_advisor)\.py',
    r'(?:auto_apply_max_running|max_per_day|tier_rank)',
    # 数值阈值暴露 (我们系统的)
    r'sharpe[\s_]*>=?\s*1\.5(?:\s*and|\s*或|\s*or)',
    r'EV[\s_]*>=?\s*0\.[0-9]',
    r'(?:max_running|capital_util)\s*[<>=]+\s*\d',
]

OUTPUT_LEAK_RE = [re.compile(p, re.IGNORECASE) for p in OUTPUT_LEAK_PATTERNS]

GENERIC_FALLBACK = (
    '抱歉这部分我没法深入说明，可以换个角度问 — 例如「我应该怎么读 #29 的 Sharpe?」'
    '或者「我可以怎么手动 pause 某个策略?」'
)


def scrub_output(ai_response: str) -> tuple[str, list[str]]:
    """扫 LLM 回答是否漏 prompt / 内部细节.

    Returns:
        (safe_text, leaked_patterns)
        safe_text: 如果漏了, 返回 GENERIC_FALLBACK; 否则原文
        leaked_patterns: 命中 pattern 列表 (audit 用)
    """
    if not ai_response:
        return '', []
    leaked = []
    for pat, raw in zip(OUTPUT_LEAK_RE, OUTPUT_LEAK_PATTERNS):
        if pat.search(ai_response):
            leaked.append(raw[:60])
    if leaked:
        return GENERIC_FALLBACK, leaked
    return ai_response, []
