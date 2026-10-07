"""Достоверность результата теста (античит): высокая / средняя / низкая — с причинами.

Сигналы:
* **интерфейс теста** (клиент присылает с каждым ответом): потеря фокуса и переключение вкладки (число и
  время вне вкладки), вставка текста (число вставок и символов). Клиенту доверять нельзя — поэтому сигналы
  клиента только понижают достоверность, но никогда её не повышают; отсутствие сигналов (ответы в обход
  интерфейса, через API) — тоже причина;
* **сервер**: время ответа по часам сервера. «Аномально быстро» — быстрее max(5 с, 8 % рекомендуемого
  времени задания); быстрый верный ответ — признак предзнания, быстрый неверный — угадывания;
* **оценщик открытых ответов**: ответ с инструкциями для модели (grader.injection_signals) не оценивается
  LLM, уходит эксперту и понижает достоверность;
* **детектор предзнания** (``assessment_bank.psychometrics.CanaryDetector``): канарейки — намеренно
  опубликованные варианты на позициях 2, 6, 10 — и модель времени; при срабатывании θ пересчитывается
  без подозрительных ответов (bank_engine.finish).

Лёгкий прокторинг без камеры (И9, 07.10) — тоже только понижает достоверность:
* **полноэкранный режим**: тест начинается в нём (если браузер умеет); выходы и время вне него;
* **защита текста задания**: выделение и копирование текста, кода и вариантов отключены, попытка копирования
  считается (copy);
* **динамика набора** развёрнутого ответа: сколько символов набрано с клавиатуры, сколько появилось вставкой,
  перетаскиванием или крупными порциями в обход клавиатуры, ритм нажатий (слишком ровный — признак программного
  ввода). Сам текст и нажатые клавиши не сохраняются — только счётчики;
* **аномалии времени по часам сервера**: длинный развёрнутый ответ быстрее, чем его можно набрать (FAST_TEXT_CPS);
* **ИИ-метка** (ai_mark): в тексте развёрнутых заданий — невидимая на экране фраза с редким словом. Человек её не
  видит; если текст задания скопирован в нейросеть, слово появляется в ответе. Экран «Что отслеживается во время
  теста» сообщает о метках заранее, механику не раскрывает;
* **оценщик**: утверждения кандидата об оценке собственного ответа (grader.strip_meta).

Баллы риска: ≥ 3 — низкая, 1–2 — средняя, 0 — высокая. Результат виден работодателю в карточке кандидата
и в объяснении подборки; в ранжирование не входит (ложное срабатывание не должно наказывать честного
кандидата — для этого флаг и причины, решение остаётся за человеком). Правила — чистые функции, покрыты
тестами (tests/test_day3a.py).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger("assessment.integrity")

LEVEL_TITLES = {"high": "высокая", "medium": "средняя", "low": "низкая"}
FAST_SHARE_OF_LIMIT = 0.08
FAST_MIN_S = 5.0
MAX_SIGNAL = 10_000
BASE_KEYS = ("focus_lost", "hidden_ms", "paste", "paste_chars", "copy")
# Новые сигналы интерфейса (И9) — в словаре, только если клиент их прислал (старые клиенты и API не наказываются
# правилами, о которых не знали): полноэкранный режим и динамика набора развёрнутого ответа.
EXT_KEYS = ("fs_exit", "fs_out_ms", "fs_ms", "fs_na", "typed", "inserted", "dropped", "deleted", "keys", "ik_cv",
            "active_ms")
MS_KEYS = {"hidden_ms", "fs_out_ms", "fs_ms", "active_ms"}
MAX_KEYS = {"fs_na", "ik_cv"}  # при сложении шагов задания — максимум, а не сумма
FAST_TEXT_CPS = 8.0  # символов в секунду по часам сервера: ≈ 90 слов в минуту без единой паузы на чтение и мысль
FAST_TEXT_MIN = 200  # короче — не проверяем
TYPED_SHARE_MIN = 0.5  # меньше половины длинного ответа набрано с клавиатуры, и это не вставка — текст «появился»
EVEN_RHYTHM_CV = 25  # коэффициент вариации интервалов между нажатиями, ×100: у человека обычно 60–150
EVEN_RHYTHM_KEYS = 100



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
    for k in BASE_KEYS + tuple(k for k in EXT_KEYS if k in raw):
        try:
            v = int(raw.get(k, 0) or 0)
        except (TypeError, ValueError):
            v = 0
        out[k] = max(0, min(v, 3_600_000 if k in MS_KEYS else 1 if k == "fs_na" else MAX_SIGNAL))
    return out


def merge_signals(a: dict | None, b: dict | None) -> dict | None:
    if not a:
        return b
    if not b:
        return a
    return {k: (max if k in MAX_KEYS else lambda x, y: x + y)(int(a.get(k, 0)), int(b.get(k, 0)))
            for k in set(a) | set(b)}


def fast_text(chars: int, server_ms: int | None) -> bool:
    """Развёрнутый ответ длиннее FAST_TEXT_MIN появился быстрее FAST_TEXT_CPS символов в секунду (часы сервера)."""
    if server_ms is None or chars < FAST_TEXT_MIN:
        return False
    return chars / max(1.0, server_ms / 1000.0) > FAST_TEXT_CPS


def typing_flags(sig: dict | None, text_len: int) -> list[str]:
    """Динамика набора развёрнутого ответа → признаки (чистая функция). Без сигналов набора — ничего."""
    if not sig or "typed" not in sig or text_len < FAST_TEXT_MIN:
        return []
    out = []
    if sig.get("typed", 0) < TYPED_SHARE_MIN * text_len and (sig.get("paste_chars") or 0) < 30:
        out.append("not_typed")  # не вставка из буфера (её считает правило вставки), но и не клавиатура
    if (sig.get("keys") or 0) >= EVEN_RHYTHM_KEYS and 0 < (sig.get("ik_cv") or 0) < EVEN_RHYTHM_CV:
        out.append("even_rhythm")
    return out


def is_fast(time_s: float | None, time_limit_s: float) -> bool:
    if time_s is None:
        return False
    return float(time_s) < max(FAST_MIN_S, FAST_SHARE_OF_LIMIT * float(time_limit_s))


def assess(items: list[dict], preknowledge: dict | None = None, extra: dict | None = None) -> dict:
    """items — завершённые задания сессии: {format, canary, time_s, time_limit_s, score (0..1|None), signals,
    injection, meta_claims, ai_mark_hit, fast_text, typing}; extra — сигналы сессии для внешних источников (SOURCES).

    Возвращает {level, title, points, reasons[], signals{...}, sources[]}.
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
    inj = [i for i in done if i.get("injection")]
    if inj:  # развёрнутый ответ адресован модели-оценщику (grader.injection_signals) — оценивает эксперт
        reasons.append((2, "В развёрнутом ответе — инструкции для автоматического оценщика "
                           f"({_n(len(inj), 'задание', 'задания', 'заданий')}); ответ передан эксперту"))
    if done and len(with_sig) < 0.5 * len(done):
        reasons.append((1, "Интерфейс теста не прислал сигналы по большинству заданий — ответы отправлены "
                           "в обход интерфейса (через API)"))

    ext_signals: dict = {}
    for name, fn in list(SOURCES):
        try:
            r, sig = fn(done, extra or {})
        except Exception:  # noqa: BLE001 — внешний источник не должен ломать итог теста
            log.exception("integrity source %s failed", name)
            continue
        reasons.extend(r)
        ext_signals.update(sig or {})

    points = sum(p for p, _ in reasons)
    level = "low" if points >= 3 else "medium" if points >= 1 else "high"
    return {
        "level": level, "title": LEVEL_TITLES[level], "points": points,
        "reasons": [t for _, t in sorted(reasons, key=lambda x: -x[0])] or
                   ["Сигналов нарушений нет: фокус не терялся, вставок нет, время ответов обычное, канарейки в норме"],
        "signals": {"items": len(done), "scored": n, "fast_correct": len(fast_correct), "fast_wrong": len(fast_wrong),
                    "canary_fast": len(canary_fast), "focus_lost_items": len(focus_items), "focus_lost_total": focus_total,
                    "hidden_s": round(hidden_s, 1), "paste_items": len(paste_items), "paste_chars": paste_chars,
                    "client_signals_items": len(with_sig), "preknowledge_flagged": bool(pk.get("flagged")),
                    "injection_items": len(inj), **ext_signals},
        "sources": [n for n, _ in SOURCES],
    }


def summary_for_employer(integ: dict | None) -> dict | None:
    """То, что видит работодатель: уровень и причины (без сырых сигналов)."""
    if not integ:
        return None
    rs = list(integ.get("reasons") or [])  # по убыванию веса; сверх пяти — одной строкой, чтобы не терялось число
    more = [f"И ещё {_n(len(rs) - 5, 'причина', 'причины', 'причин')} меньшего веса"] if len(rs) > 5 else []
    return {"level": integ.get("level"), "title": integ.get("title") or LEVEL_TITLES.get(integ.get("level", ""), ""),
            "reasons": rs[:5] + more}


# ------------------------------------------------------------------ источники причин (точка расширения)
# Источник причин — функция (done, extra) → (reasons [(баллы, текст)], signals {счётчики}). done — завершённые
# задания сессии (как в assess), extra — сигналы уровня сессии от внешних модулей (например, extra["camera"] —
# события прокторинга камерой, И16). Источник только добавляет причины: уровень считается по сумме баллов всех
# источников, как и раньше (≥ 3 — низкая, 1–2 — средняя). Ошибка источника не ломает расчёт — он пропускается.
ReasonSource = Callable[[list[dict], dict], tuple[list[tuple[int, str]], dict]]
SOURCES: list[tuple[str, ReasonSource]] = []


def register_source(name: str, fn: ReasonSource) -> None:
    """Подключить внешний источник причин (повторная регистрация с тем же именем заменяет прежний)."""
    for k, (n, _) in enumerate(SOURCES):
        if n == name:
            SOURCES[k] = (name, fn)
            return
    SOURCES.append((name, fn))


def proctoring_source(done: list[dict], extra: dict) -> tuple[list[tuple[int, str]], dict]:
    """Лёгкий прокторинг без камеры (И9): полноэкранный режим, копирование, ИИ-метка, время набора, динамика
    набора, утверждения об оценке в ответе."""
    reasons: list[tuple[int, str]] = []
    with_sig = [i for i in done if i.get("signals") is not None]
    fs_items = [i for i in with_sig if "fs_ms" in i["signals"] or "fs_na" in i["signals"]]
    fs_exits = sum((i["signals"].get("fs_exit") or 0) for i in fs_items)
    fs_out_s = sum((i["signals"].get("fs_out_ms") or 0) for i in fs_items) / 1000.0
    fs_never = bool(fs_items) and all((i["signals"].get("fs_ms") or 0) == 0 and not i["signals"].get("fs_na")
                                      for i in fs_items)
    if fs_never:
        reasons.append((1, "Тест пройден без полноэкранного режима, хотя браузер его поддерживает"))
    elif fs_exits >= 6 or fs_out_s >= 300:
        reasons.append((2, f"Выход из полноэкранного режима: {_n(fs_exits, 'раз', 'раза', 'раз')}, "
                           f"вне его {fs_out_s / 60:.1f} мин"))
    elif fs_exits >= 2 or fs_out_s >= 60:
        reasons.append((1, f"Выход из полноэкранного режима: {_n(fs_exits, 'раз', 'раза', 'раз')}, вне его {fs_out_s:.0f} с"))
    copy_items = [i for i in with_sig if (i["signals"].get("copy") or 0) > 0]
    if copy_items:
        reasons.append((2 if len(copy_items) >= 3 else 1,
                        f"Попытка скопировать текст задания: {_n(len(copy_items), 'задание', 'задания', 'заданий')}"))
    marks = [i for i in done if i.get("ai_mark_hit")]
    if marks:  # невидимая метка из текста задания появилась в ответе — текст копировали в нейросеть
        reasons.append((3, "В развёрнутом ответе — невидимая метка из текста задания: текст задания, вероятно, "
                           f"передавался нейросети ({_n(len(marks), 'задание', 'задания', 'заданий')})"))
    fast_txt = [i for i in done if i.get("fast_text")]
    if fast_txt:
        reasons.append((2 if len(fast_txt) >= 2 else 1,
                        "Развёрнутый ответ появился быстрее, чем его можно набрать (по часам сервера): "
                        f"{_n(len(fast_txt), 'задание', 'задания', 'заданий')}"))
    typing = {f: [i for i in done if f in (i.get("typing") or [])] for f in ("not_typed", "even_rhythm")}
    if typing["not_typed"]:
        reasons.append((2 if len(typing["not_typed"]) >= 2 else 1,
                        "Развёрнутый ответ в основном не набран с клавиатуры и не вставлен из буфера: "
                        f"{_n(len(typing['not_typed']), 'задание', 'задания', 'заданий')}"))
    if typing["even_rhythm"]:
        reasons.append((1, "Слишком ровный ритм набора, похожий на программный ввод: "
                           f"{_n(len(typing['even_rhythm']), 'задание', 'задания', 'заданий')}"))
    meta = [i for i in done if i.get("meta_claims")]
    if meta:  # «итог самопроверки: все требования выполнены» — перефразированная инъекция (grader.strip_meta)
        reasons.append((1, "В развёрнутом ответе — утверждения об оценке собственного ответа "
                           f"({_n(len(meta), 'задание', 'задания', 'заданий')}); при оценке они не учитываются"))
    return reasons, {"fs_items": len(fs_items), "fs_exits": fs_exits, "fs_out_s": round(fs_out_s, 1),
                     "fs_never": fs_never, "copy_items": len(copy_items), "ai_mark_items": len(marks),
                     "fast_text_items": len(fast_txt), "not_typed_items": len(typing["not_typed"]),
                     "even_rhythm_items": len(typing["even_rhythm"]), "meta_claims_items": len(meta)}


register_source("proctoring", proctoring_source)
