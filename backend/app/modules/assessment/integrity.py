"""Достоверность результата теста (античит): высокая / средняя / низкая — с причинами.

Сигналы:
* **интерфейс теста** (клиент присылает с каждым ответом): потеря фокуса и переключение вкладки (число и
  время вне вкладки), вставка текста (число вставок и символов). Клиенту доверять нельзя — поэтому сигналы
  клиента только понижают достоверность, но никогда её не повышают; отсутствие сигналов (ответы в обход
  интерфейса, через API) — тоже причина;
* **сервер**: время ответа по часам сервера. «Аномально быстро» — быстрее max(5 с, 8 % рекомендуемого
  времени задания); быстрый верный ответ — признак предзнания, быстрый неверный — угадывания;
* **детектор предзнания** (``assessment_bank.psychometrics.CanaryDetector``): канарейки — намеренно
  опубликованные варианты на позициях 2, 6, 10 — и модель времени; при срабатывании θ пересчитывается
  без подозрительных ответов (bank_engine.finish).

Баллы риска: ≥ 3 — низкая, 1–2 — средняя, 0 — высокая. Результат виден работодателю в карточке кандидата
и в объяснении подборки; в ранжирование не входит (ложное срабатывание не должно наказывать честного
кандидата — для этого флаг и причины, решение остаётся за человеком). Правила — чистые функции, покрыты
тестами (tests/test_day3a.py).
"""
from __future__ import annotations

from typing import Any

LEVEL_TITLES = {"high": "высокая", "medium": "средняя", "low": "низкая"}
FAST_SHARE_OF_LIMIT = 0.08
FAST_MIN_S = 5.0
MAX_SIGNAL = 10_000



def _n(k: int, one: str, few: str, many: str) -> str:
    """Число со словом в нужной форме: 1 задание, 2 задания, 5 заданий."""
    m10, m100 = k % 10, k % 100
    w = one if m10 == 1 and m100 != 11 else few if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else many
    return f"{k} {w}"

def clean_signals(raw: Any) -> dict | None:
    """Сигналы клиента → безопасный словарь целых чисел (мусор и отрицательные значения отбрасываются)."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k in ("focus_lost", "hidden_ms", "paste", "paste_chars", "copy"):
        try:
            v = int(raw.get(k, 0) or 0)
        except (TypeError, ValueError):
            v = 0
        out[k] = max(0, min(v, 3_600_000 if k == "hidden_ms" else MAX_SIGNAL))
    return out


def merge_signals(a: dict | None, b: dict | None) -> dict | None:
    if not a:
        return b
    if not b:
        return a
    return {k: int(a.get(k, 0)) + int(b.get(k, 0)) for k in set(a) | set(b)}


def is_fast(time_s: float | None, time_limit_s: float) -> bool:
    if time_s is None:
        return False
    return float(time_s) < max(FAST_MIN_S, FAST_SHARE_OF_LIMIT * float(time_limit_s))


def assess(items: list[dict], preknowledge: dict | None = None) -> dict:
    """items — завершённые задания сессии: {format, canary, time_s, time_limit_s, score (0..1|None), signals}.

    Возвращает {level, title, points, reasons[], signals{...}}.
    """
    pk = preknowledge or {}
    done = [i for i in items if i.get("time_s") is not None]
    scored = [i for i in done if not i.get("canary")]
    n = len(scored)
    reasons: list[tuple[int, str]] = []

    fast_correct = [i for i in scored if is_fast(i["time_s"], i["time_limit_s"]) and (i.get("score") or 0) >= 0.5]
    fast_wrong = [i for i in scored if is_fast(i["time_s"], i["time_limit_s"]) and i.get("score") is not None
                  and i["score"] < 0.5]
    canary_fast = [i for i in done if i.get("canary") and is_fast(i["time_s"], i["time_limit_s"])
                   and (i.get("score") or 0) >= 0.5]

    if pk.get("flagged"):
        reasons.append((3, "Детектор предзнания сработал: канарейки и время ответов похожи на знание ответов "
                           f"заранее (статистика {pk.get('combined', 0):.2f})"
                        + (f"; из оценки исключено ответов: {pk['excluded_answers']}" if pk.get("excluded_answers") else "")))
    if canary_fast:
        reasons.append((1, f"Канареечные задания (опубликованные варианты) решены аномально быстро: {len(canary_fast)}"))
    if n:
        share = len(fast_correct) / n
        if share >= 0.25 and len(fast_correct) >= 2:
            reasons.append((2, f"Аномально быстрые верные ответы: {len(fast_correct)} из {n}"))
        elif len(fast_correct) >= 2 or (share >= 0.10 and fast_correct):
            reasons.append((1, f"Аномально быстрые верные ответы: {len(fast_correct)} из {n}"))
        if len(fast_wrong) / n >= 0.3 and len(fast_wrong) >= 3:
            reasons.append((1, f"Много мгновенных неверных ответов ({len(fast_wrong)} из {n}) — похоже на угадывание"))

    with_sig = [i for i in done if i.get("signals") is not None]
    focus_items = [i for i in with_sig if (i["signals"].get("focus_lost") or 0) > 0]
    hidden_s = sum((i["signals"].get("hidden_ms") or 0) for i in with_sig) / 1000.0
    focus_total = sum((i["signals"].get("focus_lost") or 0) for i in with_sig)
    if len(focus_items) >= 5 or hidden_s >= 180:
        reasons.append((2, f"Уход со вкладки теста: {_n(len(focus_items), 'задание', 'задания', 'заданий')}, "
                           f"{_n(focus_total, 'раз', 'раза', 'раз')}, вне вкладки {hidden_s / 60:.1f} мин"))
    elif len(focus_items) >= 2 or hidden_s >= 30:
        reasons.append((1, f"Уход со вкладки теста: {_n(len(focus_items), 'задание', 'задания', 'заданий')}, "
                           f"{_n(focus_total, 'раз', 'раза', 'раз')}, вне вкладки {hidden_s:.0f} с"))
    paste_items = [i for i in with_sig if (i["signals"].get("paste") or 0) > 0
                   and (i["signals"].get("paste_chars") or 0) >= 30]
    paste_chars = sum((i["signals"].get("paste_chars") or 0) for i in paste_items)
    if len(paste_items) >= 2:
        reasons.append((2, f"Вставка готового текста в ответ: {_n(len(paste_items), 'задание', 'задания', 'заданий')}, "
                           f"{_n(paste_chars, 'символ', 'символа', 'символов')}"))
    elif paste_items:
        reasons.append((1, f"Вставка готового текста в ответ: 1 задание, {_n(paste_chars, 'символ', 'символа', 'символов')}"))
    if done and len(with_sig) < 0.5 * len(done):
        reasons.append((1, "Интерфейс теста не прислал сигналы по большинству заданий — ответы отправлены "
                           "в обход интерфейса (через API)"))

    points = sum(p for p, _ in reasons)
    level = "low" if points >= 3 else "medium" if points >= 1 else "high"
    return {
        "level": level, "title": LEVEL_TITLES[level], "points": points,
        "reasons": [t for _, t in sorted(reasons, key=lambda x: -x[0])] or
                   ["Сигналов нарушений нет: фокус не терялся, вставок нет, время ответов обычное, канарейки в норме"],
        "signals": {"items": len(done), "scored": n, "fast_correct": len(fast_correct), "fast_wrong": len(fast_wrong),
                    "canary_fast": len(canary_fast), "focus_lost_items": len(focus_items), "focus_lost_total": focus_total,
                    "hidden_s": round(hidden_s, 1), "paste_items": len(paste_items), "paste_chars": paste_chars,
                    "client_signals_items": len(with_sig), "preknowledge_flagged": bool(pk.get("flagged"))},
    }


def summary_for_employer(integ: dict | None) -> dict | None:
    """То, что видит работодатель: уровень и причины (без сырых сигналов)."""
    if not integ:
        return None
    return {"level": integ.get("level"), "title": integ.get("title") or LEVEL_TITLES.get(integ.get("level", ""), ""),
            "reasons": list(integ.get("reasons") or [])[:5]}
