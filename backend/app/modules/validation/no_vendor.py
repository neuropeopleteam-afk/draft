"""Ответы /api/validation/* для экрана — без названий моделей и поставщиков (правило владельца; решение штаба 21.10).

Полные идентификаторы остаются в файлах данных и в docs/ репозитория (воспроизводимость). На экран ответ проходит через
``scrub``: идентификаторы и ключи моделей (``anthropic/claude-…``, ``yandex``, ``sonnet``) заменяются ролями
(«модель стенда», «российская модель», «открытая модель на нашем сервере») или буквами («модель А», «модель Б», …) —
одинаково в ключах словарей и в значениях, чтобы связи внутри ответа не рвались; свободный текст — заменой названий.
Политика ПДн (core/legal) сюда не относится: там раскрытие обработчика по закону.
"""
from __future__ import annotations

import re

VENDOR = re.compile(r"claude|sonnet|fable|anthropic|openai|\bgpt|gemini|yandex|deepseek|grok|kimi|openrouter|qwen|moonshot|x-ai|\bgoogle\b(?! play)",
                    re.I)
LETTERS = "АБВГДЕЖИКЛМНПРСТУФХЦ"

_ROLES = [(re.compile(r"sonnet", re.I), "модель стенда"), (re.compile(r"fable", re.I), "вторая модель оценщика"),
          (re.compile(r"yandex", re.I), "российская модель"), (re.compile(r"gpt-oss", re.I), "открытая модель-эталон"),
          (re.compile(r"qwen|llm-local", re.I), "открытая модель на нашем сервере")]
_TOKEN = re.compile(r"^[\w.\-/:@]+$")  # идентификатор или ключ (без пробелов и «=»)  # идентификатор или ключ (без пробелов)

_SUBS = [
    (r"кросс-вендорн\w*", "из моделей разных компаний"),
    (r"OpenRouter \(зарубежный провайдер\)", "зарубежный провайдер"),
    (r"Yandex AI Studio", "российское облако"), (r"OpenAI-совместим\w* API", "стандартный API"),
    (r"«только YandexGPT»|\"только YandexGPT\"", "«только российская модель»"),
    (r"YandexGPT[\s\d.]*\d|YandexGPT|\bYandex\b", "российская модель"),
    (r"модели семейства Claude", "модели того же семейства"),
    (r"Claude Fable\s*[\d.]+|\bFable\s*[\d.]+", "вторая модель"),
    (r"Claude(?: Sonnet| Opus| Haiku)?[\s\d.]*\d|\bSonnet\b(?:[\s\d.]*\d)?|\bClaude\b", "модель стенда"),
    (r"gpt-oss-120b", "открытая модель-эталон"),
    (r"\b(?:Anthropic|OpenAI|Google|xAI|Moonshot|Alibaba|Zhipu|DeepSeek)\s*\+\s*(?:Anthropic|OpenAI|Google|xAI|Moonshot|Alibaba|Zhipu|DeepSeek)",
     "две компании"),
    (r"\b(?:Anthropic|OpenAI|xAI|Moonshot|Alibaba|Zhipu)\b", "другая компания"), (r"\bGoogle\b(?! Play)", "другая компания"),
    (r"\bQwen[\w.\-]*(?:\s+(?:[A-Z]?\d[\w.\-]*|Q4_K_M))*", "открытая модель"),
    (r"\b(?:DeepSeek|Grok|Kimi|Gemini|GLM|GPT)[\w.\-]*(?:\s+(?:[A-Z]?\d[\w.\-]*|Flash|Pro|Mini))*", "модель другой компании"),
    (r"\b(?:anthropic|openai|google|x-ai|moonshotai|deepseek|qwen|z-ai|yandex)/[\w.\-@:]+", "модель"),
    (r"OpenRouter", "зарубежный провайдер"),
]


_COMPANY = re.compile(r"^(?:anthropic|openai|google|x-ai|xai|moonshot(?:ai)?|deepseek|alibaba|qwen|yandex|zhipu|z-ai)$", re.I)


_CODES = [(re.compile(r"sonnet", re.I), "stand"), (re.compile(r"fable", re.I), "second"),
          (re.compile(r"yandex", re.I), "ru"), (re.compile(r"gpt-oss", re.I), "ref_open"),
          (re.compile(r"qwen|llm-local", re.I), "local")]
_LAT = "abcdefghijklmnopqrstuvwxyz"


class _Alias:
    """Идентификаторы и ключи (без пробелов) → нейтральные латинские коды, одинаково в ключах и значениях
    (контракт API — латиница): stand, ru, local, ref_open, second, model_a…, company_a…; подписи по-русски даёт фронтенд
    (noVendor.ts makeModelAlias) или замена текста (text())."""

    def __init__(self) -> None:
        self.seen: dict[str, str] = {}
        self.n_model = 0
        self.n_company = 0

    def token(self, s: str) -> str:
        base, sep, variant = s.partition("@")
        key = base.lower()
        if key not in self.seen:
            code = next((c for rx, c in _CODES if rx.search(base)), None)
            if code is None and _COMPANY.match(base):
                code = f"company_{_LAT[self.n_company % 26]}"
                self.n_company += 1
            if code is None:
                code = f"model_{_LAT[self.n_model % 26]}"
                self.n_model += 1
            self.seen[key] = code
        v = variant if variant and not VENDOR.search(variant) else ""
        return self.seen[key] + (f"@{v}" if v else "")


_PRE = [(r"режим\w* LLM_CHAIN=yandex|LLM_CHAIN=yandex", "режим «только российская модель»"),
        (r"\byandexgpt[\w.\-/]*(?:\s+[\d.]*\d)?", "российская модель")]
# последняя страховка: любое оставшееся слово с названием модели/компании → «модель»
_FALLBACK = re.compile(r"[\w.\-/:@=]*(?:claude|sonnet|fable|anthropic|openai|\bgpt|gemini|yandex|deepseek|grok|kimi|openrouter|qwen|"
                       r"moonshot|x-ai)[\w.\-/:@=]*", re.I)


def text(s: str) -> str:
    for pat, rep in _PRE + _SUBS:
        s = re.sub(pat, rep, s, flags=re.I) if pat in dict(_PRE) else re.sub(pat, rep, s)
    return _FALLBACK.sub("модель", s)


def scrub(obj, _a: _Alias | None = None):
    """Глубокая замена: строки-идентификаторы и ключи — роль/буква (согласованно), свободный текст — замена названий."""
    a = _a or _Alias()
    if isinstance(obj, dict):
        return {(a.token(k) if isinstance(k, str) and VENDOR.search(k) and _TOKEN.match(k) else k): scrub(v, a)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, a) for v in obj]
    if isinstance(obj, str) and VENDOR.search(obj):
        return a.token(obj) if _TOKEN.match(obj.strip()) else text(obj)
    return obj
