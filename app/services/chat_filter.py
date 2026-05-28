"""Phase 14k-126 + 14k-126.2 加固: chat 输入/输出过滤 — 红队测试驱动加强.

分层防御:
  1. **输入 normalize** — 去 zero-width / 重音分解 / case fold (绕过 encoding tricks)
  2. **输入 regex 过滤** — 大幅覆盖中英德法俄日韩主要越狱关键词 + hypothetical / research /
    enumeration / social-engineering 框架
  3. **chat_assistant system prompt** — chat AI 自己拒答 (第二道)
  4. **输出 regex 过滤** — LLM 真漏内部细节时拦下 + GENERIC_FALLBACK (第三道)
  5. **extraction throttle** — 24h 内 ≥3 次尝试 → 锁 chat 24h

红队测试目标: ≥95% defense rate on classic attack vectors.
"""
from __future__ import annotations

import re
import unicodedata
import base64


# ---------------------------------------------------------------------------
# Normalize 预处理 — 去掉绕过 trick 的字符
# ---------------------------------------------------------------------------
ZERO_WIDTH_CHARS = '​‌‍⁠﻿'
ZERO_WIDTH_RE = re.compile(f'[{re.escape(ZERO_WIDTH_CHARS)}]')


def _normalize(text: str) -> str:
    """归一化用户输入, 防 encoding trick.

    步骤:
      1. NFKD 分解 (兼容字体, 例 ⅰ → i)
      2. 去 zero-width chars
      3. 折叠多个空格为单空格
      4. 转小写
    """
    if not text:
        return ''
    # Phase 14k-126.2: NFKC (compat decomp + canonical compose) — 处理 ⅰ→i 等 trick,
    # 但保留 CJK 组合字 (NFKD 会拆 시→ㅅㅣ / プ→フ゜ → CJK regex 完全断)
    text = unicodedata.normalize('NFKC', text)
    # 去 zero-width
    text = ZERO_WIDTH_RE.sub('', text)
    # 折叠 spaces/tabs
    text = re.sub(r'\s+', ' ', text)
    return text.lower().strip()


# ---------------------------------------------------------------------------
# 输入端: 大幅扩展越狱 / extraction 关键词
# ---------------------------------------------------------------------------
INPUT_JAILBREAK_PATTERNS = [
    # === 1. 直接 prompt extraction (英文) ===
    r'ignore (?:all |the )?(?:previous|prior|above)',
    r'forget (?:all |the )?(?:previous|prior|above)',
    r'(?:show|tell|give|share|print|reveal|display|expose) (?:me )?(?:your |the )?(?:system )?(?:prompt|instructions?|rules?|guidelines?|constraints?|directives?|role|setup|configuration|safety)',
    r'(?:what (?:is|are) )?(?:your |the )?(?:system )?(?:prompt|instructions?|directives?|guidelines?|constraints?|rules?|safety rules?)',
    r'(?:what (?:are|is)|are) (?:your |the |my )?(?:rules?|prompts?|instructions?|guidelines?|constraints?)',
    r'what (?:are )?you (?:instructed|told|programmed|trained|directed|told to do)',
    r'(?:reveal|expose|disclose|leak|出) your (?:system )?(?:prompt|instructions?|rules?)',
    r'(?:repeat|recite) (?:the )?(?:system )?(?:prompt|message above|instructions)',
    r'(?:what (?:is|are) )?your (?:role|guidelines|purpose|directive|safety rules|constraints)',
    # === 1.5 直接 prompt extraction (中文) ===
    r'(?:忽略|忘记|跳过)(?:之前|上面|以上|前面|所有|全部)',
    r'(?:请)?(?:把|说|告诉|输出|展示|显示|打印|分享|揭示|泄露)(?:我|出来|一下)?(?:你的(?:系统)?|系统)(?:提示|指令|规则|设定|prompt|限制|约束|准则|角色|配置)',
    r'(?:你的|系统)(?:提示词|指令是|prompt 是|提示 是|规则是|设定是|角色是|限制是)',
    r'你(?:被|是被|被人)(?:告诉|教|训练|设定|指示)',
    r'你之前(?:被|收到|接到)',
    r'重复(?:你的|上面的|之前的|系统的)',
    r'你(?:的)?(?:角色|身份|限制|约束|规则|准则|安全(?:规则)?)是什么',
    # === 2. Role-play / persona swap ===
    r'(?:you are now|pretend (?:to be|you are)|act as|role[- ]?play|switch to|enter)',
    r'(?:扮演|假装|你现在是|你不再是|切换到|进入)',
    r'\b(?:DAN|dan|jailbreak|developer mode|god mode|sandbox mode|debug mode|admin mode)\b',
    r'(?:开发者|越狱|上帝|沙盒|调试|管理员)(?:模式)',
    r'(?:unrestricted|no restrictions?|无限制|没有限制|不受限制)',
    # === 3. Hypothetical / 假设型 ===
    r'(?:hypothetically|theoretically|if you (?:could|were|had)|imagine you)',
    r'(?:假设|如果你能|想象|理论上)',
    r'(?:in (?:a |this )?(?:parallel|alternate|fictional|hypothetical))',
    r"(?:let's|let us) (?:play|imagine|pretend)",
    # === 4. Research / 假科学/学术包装 ===
    r'for (?:academic|scientific|research|educational|safety|study|paper)',
    r'(?:i am|i\'m) (?:a |an )?(?:security |academic |ai )?researcher',
    r'我(?:是|为)(?:安全|学术|AI|研究)研究',
    r'(?:research|academic|study|paper|thesis) (?:on|about|into)',
    # === 5. Enumeration / 间接抽取 ===
    r'list (?:all |every )?(?:things?|rules?|constraints?|guidelines?) (?:you (?:can|cannot|are unable|cant)|i shouldnt|are forbidden)',
    r'(?:列出|列举)(?:所有|你不能|你的|每个)',
    r'what\s+(?:\w+\s+)?(?:would|will|do)\s+you\s+(?:refuse|never|not|cannot|cant|won\'?t)(?:\s+to)?\s+(?:do|say|answer|tell|reply|respond)',
    r'(?:write|compose|create) (?:a |an )?(?:poem|song|story|joke|riddle) (?:about|describing|listing) (?:your |the )?(?:rules?|guidelines?|prompt|constraints?|limitations?|instructions?)',
    r'(?:翻译|转换|改写)(?:你的|系统)(?:限制|规则|提示|指令)',
    r'translate (?:your |the )(?:system )?(?:prompt|instructions?|rules?|guidelines?)',
    r'(?:sing|recite|chant)\b.*?(?:your |the )?(?:rules?|guidelines?|prompt|instructions?|constraints?)',
    # === 6. Social engineering / 情感操控 ===
    r'(?:my grandmother|my grandma|my late|deceased)',
    r'(?:my (?:life |daughter |son |kid |child |family )(?:depends|hinges)|life or death)',
    r'(?:i am|i\'m) (?:the )?(?:developer|admin|administrator|owner|maker|creator)',
    r'我(?:是|就是)(?:开发者|管理员|admin|系统管理员|创造者)',
    r'(?:please|i beg|plz),? (?:my|i)',
    r'(?:为了|为此)(?:我的|安全|生命)',
    # === 7. 内部代码/阈值抽取 (我们系统具体的) ===
    r'(?:what|which) (?:threshold|阈值|gate|门槛) (?:determines|decides|controls|gates|算)',
    r'(?:什么|哪个|哪种) (?:sharpe|EV|阈值|门槛|gate)',
    r'(?:which|what) (?:python |internal )?function (?:handles|controls|runs|implements)',
    r'(?:strategy_advisor|advisor_executor|strategy_recommend|strategy_synthesize|strategy_improve|sizing_advisor|chat_assistant|capital_tier_review)\.py',
    # 14k-126.3: 移除 fan_out / promote_candidate / propose_signal_grid / invent_new_strategy
    # 这些是 user-facing 功能名 (advisor 10 actions), 不该当 jailbreak. 内部实现函数才该挡:
    r'(?:_check_promote_gates|build_recommendations|run_auto_apply|_execute_one|recommend_strategies|backtest_all_translated)',
    # 只挡 "how *exactly* does ... work" / "specific|internal|exact (threshold|code|logic)" — 不挡 "how does advisor decide actions" 这种正常问
    r'(?:how|why) (?:exactly|specifically|internally|precisely)\s+(?:does|do) (?:the |your )?(?:advisor|promote|fan_out|invent|grid|gate|守门员)',
    r'(?:internal|specific|exact|precise|raw) (?:threshold|阈值|code|逻辑|logic|implementation|details?|prompt|gate)',
    r'(?:告诉我|描述)(?:advisor|sizing|synth|improve)(?:.py)?(?:里的|内部)?(?:逻辑|代码|实现)',
    # === 8. 跨用户/特权数据抽取 ===
    r'(?:list|show|dump|enumerate) (?:all )?users?',
    r'(?:admin\'?s? |master |other |别的 ?|其他 ?|root )(?:user(?:s)?\'?(?:\s|s)?)?(?:password|api[- ]?key|secret|token|email|info|data|credential)',
    r'what (?:is|are) (?:other |the )?users? (?:doing|running|trading)',
    r'(?:user_id|uid)\s*=\s*\d',
    r'(?:其他|别人|別的) users?',
    r'(?:其他|别的|所有) users? (?:的|的所有|的策略|的密码|的 key)',
    r'(?:select|insert|update|delete|drop)\s+(?:\*|from|into|table)',
    # === 9. 多语言越狱 (德/法/俄/日/韩 主要 keyword) ===
    # 德语
    r'zeige? (?:mir )?dein(?:en|e)? (?:system[- ]?)?prompt',
    r'(?:dein|euer) (?:system|prompt|anweisung)',
    # 法语
    r'montre[zr]? (?:moi |mes )?(?:ton |le )?(?:system[ée] )?prompt',
    r'(?:ton |votre )(?:prompt|instruction|consigne)',
    # 俄语
    r'покажи (?:мне )?(?:свой |твой )?(?:system[ -]?)?промпт',
    r'(?:промпт|инструкци|правил)',
    # 日语
    r'システム(?:プロンプト|指示)',
    r'(?:あなたの|君の) (?:プロンプト|ルール|設定)',
    # 韩语
    r'시스템 (?:프롬프트|지시|규칙)',
    r'(?:너의|당신의) (?:프롬프트|규칙|설정)',
    # === 10. Output / debug / conversation extraction ===
    r'(?:print|show|display) (?:the |this |our )?(?:full |complete |entire )?conversation',
    r'(?:debug|verbose|raw) (?:mode|output|response)',
    r'override (?:safety|safe|guardrails?|rules?)',
    # === 11. Encoding / base64 hints ===
    r'(?:base64|b64|rot13|hex)(?:[- ]?(?:decode|encode))?',
]

INPUT_JAILBREAK_RE = [re.compile(p, re.IGNORECASE) for p in INPUT_JAILBREAK_PATTERNS]

# Base64 自检: 命中长 base64 段 → suspicious (尝试解码看是否含越狱关键词)
BASE64_BLOB_RE = re.compile(r'(?:[A-Za-z0-9+/]{20,}={0,2})')

# friendly refusal
REFUSAL_MESSAGE = (
    '我是你的量化驾驶舱助手 (read-only), 不能分享系统设置或讨论我的角色, '
    '但可以帮你看 strategies / trades / 持仓 / AI 决策。换个问题问我吧 🤖'
)


def _check_base64_blob(text: str) -> bool:
    """检测 base64 编码后含越狱 keyword. 如果解码后包含 'ignore previous' / 'prompt' 等 → 拒."""
    for blob in BASE64_BLOB_RE.findall(text):
        try:
            decoded = base64.b64decode(blob, validate=False).decode('utf-8', errors='ignore').lower()
        except Exception:
            continue
        if any(kw in decoded for kw in ['ignore previous', 'system prompt', 'instructions',
                                        '忽略', '系统提示', '指令', 'dan', 'developer mode']):
            return True
    return False


def check_input(user_message: str) -> tuple[bool, str]:
    """检查 user 输入是否含越狱 / extraction 尝试.

    流程:
      1. 长度/空检查
      2. _normalize (NFKD + zero-width + lower + collapse)
      3. 跑所有 INPUT_JAILBREAK_RE
      4. base64 blob 解码自检

    Returns:
        (allowed, reason_if_blocked)
    """
    if not user_message or not user_message.strip():
        return False, 'empty input'
    if len(user_message) > 2000:
        return False, 'input too long (>2000 chars)'

    normalized = _normalize(user_message)

    for pat, raw in zip(INPUT_JAILBREAK_RE, INPUT_JAILBREAK_PATTERNS):
        if pat.search(normalized):
            return False, f'matched: {raw[:80]}'

    # Phase 14k-126.2: space-stripped second pass — 防 "i gn ore p re vio us" 分字攻击
    # heuristic: 5+ tokens 且 60%+ 是 1-3 字符短 token = 分字攻击嫌疑 (正常句子很少这样)
    tokens = normalized.split()
    if len(tokens) >= 5:
        short_count = sum(1 for t in tokens if 1 <= len(t) <= 3)
        if short_count / len(tokens) > 0.6:
            no_spaces = normalized.replace(' ', '')
            # 用 substring 检查关键 jailbreak words (regex 的空格在 no_spaces 中不存在所以直接 substring)
            JAILBREAK_SUBSTRINGS = [
                'ignoreprevious', 'ignoreabove', 'ignoreprior', 'ignoreall',
                'forgetprevious', 'forgetabove', 'systemprompt',
                'tellmeyourprompt', 'showyourprompt', 'printyourprompt',
                'youarenowdan', 'developermode', 'godmode', 'unrestricted',
                'pretendtobe', 'roleplay',
                '忽略之前', '忽略所有', '系统提示', '告诉我提示', '扮演',
            ]
            for sub in JAILBREAK_SUBSTRINGS:
                if sub in no_spaces:
                    return False, f'matched (space-stripped): {sub}'

    if _check_base64_blob(user_message):
        return False, 'matched: base64-encoded jailbreak'

    return True, ''


# ---------------------------------------------------------------------------
# 输出端: 检查 LLM 回答是否泄漏内部 prompt 片段
# ---------------------------------------------------------------------------
OUTPUT_LEAK_PATTERNS = [
    # 英文 LLM 自暴
    r'my (?:system )?(?:prompt|instructions?|rules?|guidelines?) (?:is|are|says|state|read)',
    r'i (?:am|was) (?:told|instructed|programmed|directed|trained) to',
    r'as an? (?:ai|assistant|llm) (?:i am|trained|developed|designed|built|made|created)',
    r"here (?:is|'s) (?:my|the) (?:system )?(?:prompt|instructions?|rules?|guidelines?)",
    r'(?:per|following|according to) (?:my|the) (?:system |internal )?(?:prompt|instructions?|rules?)',
    r'(?:i (?:was|am) given|i (?:was|am) provided with|i received) (?:the |a |these |my )?(?:prompt|instructions?|guidelines?)',
    # 中文 LLM 自暴
    r'我(?:的|被|是被|收到)(?:告诉|指令|要求|设定为|训练成|提示|限制)',
    r'我的(?:系统)?(?:提示|指令|规则|prompt|限制|约束|准则)是',
    r'原(?:始|本)(?:系统)?提示',
    r'根据(?:我的|系统)?(?:提示|指令|设定)',
    # 内部代码 / 函数名 暴露
    r'(?:advisor_executor|strategy_advisor|build_recommendations|_check_promote_gates|run_auto_apply)',
    r'(?:strategy_synthesize|strategy_improve_v[678]|sizing_advisor|chat_assistant)\.py',
    r'(?:auto_apply_max_running|auto_apply_max_per_day|tier_rank|invent_quota)',
    # 数值阈值暴露
    r'sharpe[\s_]*>=?\s*1\.5(?:\s*and|\s*或|\s*or|\s*,)',
    r'EV[\s_]*>=?\s*0\.[0-9]',
    r'(?:max_running|capital_util)\s*[<>=]+\s*\d',
    r'oos_sharpe[\s_]*>=?\s*[0-9.]',
    # 暴露我们的安全/防御策略
    r'(?:i (?:cannot|will not|won\'t|refuse to) (?:reveal|discuss|share|disclose|talk about))',
    r'(?:my (?:safety|guardrails?|limitations?|restrictions?)|safety rules?|guardrails?) (?:include|are|require)',
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
    """
    if not ai_response:
        return '', []
    normalized = _normalize(ai_response)
    leaked = []
    for pat, raw in zip(OUTPUT_LEAK_RE, OUTPUT_LEAK_PATTERNS):
        if pat.search(normalized):
            leaked.append(raw[:80])
    if leaked:
        return GENERIC_FALLBACK, leaked
    return ai_response, []
