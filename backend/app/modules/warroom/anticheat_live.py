"""Режим Б «Боевого ИИ-Полигона»: проверка текста ответа и телеметрии настоящими функциями бэкенда.

Прогоняет переданный ответ, телеметрию ввода/экрана, события камеры, проверку «двойника при
копировании» и матрицу ответов через функции модулей:
- `app.modules.assessment.grader` (`inspect` от А6 с фолбэком на `injection_signals` и `strip_meta`);
- `app.modules.proctor.rules` (`aggregate`, `make_copy_decoy`, `check_copy_decoy`, `integrity_followup`);
- `app.modules.assessment.integrity` (`person_fit_lz`, `proctoring_source`);
- `app.modules.interview.service` (`defense_recommendation`, `integrity_passport`).

По решению владельца (Р27): обычным кандидатам и анонимным посетителям вне демонстрационного
режима жюри внутренние названия сигналов, точные численные пороги и формулы не раскрываются —
возвращаются только 5 высокоуровневых контуров самостоятельности. Детальная расшифровка 21 сигнала
отдаётся только в режиме демонстрации для жюри (`demo_mode=True`).
"""
from __future__ import annotations

import math
import statistics
from typing import Any

from app.modules.assessment import grader, integrity
from app.modules.interview import service as interview_service
from app.modules.proctor import rules as proctor_rules

CANARY_SERVER_WORD = "Бергамот"

CONTOURS_SPEC: list[dict[str, Any]] = [
    {
        "n": 1,
        "id": "prior",
        "name": "Самостоятельность и темп ответов",
        "color": "#f59e0b",
        "description": "Сверка времени чтения и решения заданий по часам сервера, контрольные задания.",
    },
    {
        "n": 2,
        "id": "fit",
        "name": "Согласованность ответов с уровнем",
        "color": "#a78bfa",
        "description": "Проверка естественности паттерна ответов относительно сложности вопросов.",
    },
    {
        "n": 3,
        "id": "origin",
        "name": "Происхождение и чистота текста ответа",
        "color": "#f43f5e",
        "description": "Контроль копирования условия, динамики набора, вставок и фильтр манипуляций оценщиком.",
    },
    {
        "n": 4,
        "id": "screen",
        "name": "Рабочее окно и среда прохождения",
        "color": "#22d3ee",
        "description": "Переключения вкладок, полноэкранный режим, копирование условия и снимки экрана.",
    },
    {
        "n": 5,
        "id": "live",
        "name": "Камера по согласию и устная защита",
        "color": "#34d399",
        "description": "Локальная проверка кадра в браузере по согласию и 3-минутная устная защита решения.",
    },
]

# Реальный каталог из 21 сигнала в 5 контурах (согласовано с А6 и docs/ANTIFRAUD.md §6.5)
SIGNALS_SPEC: list[dict[str, Any]] = [
    {
        "n": 1,
        "c": 1,
        "code": "canary_fast",
        "name": "Контрольные задания решены быстрее типичного темпа",
        "pts": 1,
        "how_it_works": "Сравнение времени ответа на контрольных позициях с медианным темпом кандидата по сессии.",
    },
    {
        "n": 2,
        "c": 1,
        "code": "preknowledge_flagged",
        "name": "Признак предварительного знакомства с вариантами",
        "pts": 3,
        "how_it_works": "Совокупная оценка скорости и точности на контрольных вариантах.",
    },
    {
        "n": 3,
        "c": 1,
        "code": "fast_correct",
        "name": "Аномально быстрые верные ответы на сложных вопросах",
        "pts": 2,
        "how_it_works": "Сопоставление времени ответа с длиной условия и уровнем трудности задания.",
    },
    {
        "n": 4,
        "c": 1,
        "code": "instant_correct",
        "name": "Мгновенные верные ответы без чтения условия",
        "pts": 2,
        "how_it_works": "Ответ отправлен быстрее времени, минимально необходимого для чтения формулировки.",
    },
    {
        "n": 5,
        "c": 1,
        "code": "fast_wrong",
        "name": "Серия мгновенных неверных ответов (случайный перебор)",
        "pts": 1,
        "how_it_works": "Серия неверных ответов, отправленных без прочтения условия.",
    },
    {
        "n": 6,
        "c": 2,
        "code": "person_fit_lz",
        "name": "Несогласованность ответов со сложностью заданий",
        "pts": 2,
        "how_it_works": "Оценка правдоподобия матрицы ответов: ошибки на базовых вопросах при верных ответах на трудных.",
    },
    {
        "n": 7,
        "c": 3,
        "code": "ai_mark_hit",
        "name": "Решение по скопированному двойнику или скрытый маркер условия",
        "pts": 3,
        "how_it_works": "При копировании условия в буфер подставляется вариант-двойник с изменённым опорным числом и контрольным маркером.",
    },
    {
        "n": 8,
        "c": 3,
        "code": "injection",
        "name": "Попытка перехвата инструкций проверяющей модели",
        "pts": 2,
        "how_it_works": "Фильтр нормализации и деобфускации обнаружил директивы управления оценщиком или вложенный вердикт.",
    },
    {
        "n": 9,
        "c": 3,
        "code": "meta_claims",
        "name": "Самооценка и служебные приписки для проверяющего",
        "pts": 1,
        "how_it_works": "Очистка утверждений кандидата о том, что ответ уже проверен и заслуживает высшего балла.",
    },
    {
        "n": 10,
        "c": 3,
        "code": "paste",
        "name": "Вставка готового фрагмента текста из буфера",
        "pts": 2,
        "how_it_works": "Фиксация события вставки крупного фрагмента текста или кода в поле ответа.",
    },
    {
        "n": 11,
        "c": 3,
        "code": "not_typed",
        "name": "Длинный ответ появился без клавиатурного набора",
        "pts": 2,
        "how_it_works": "Доля символов, введённых нажатиями клавиш, существенно ниже длины развёрнутого ответа.",
    },
    {
        "n": 12,
        "c": 3,
        "code": "even_rhythm",
        "name": "Механически ровный ритм печати (программный ввод)",
        "pts": 1,
        "how_it_works": "Анализ вариативности пауз между нажатиями клавиш на длинной серии ввода.",
    },
    {
        "n": 13,
        "c": 3,
        "code": "fast_text",
        "name": "Скорость появления текста выше темпа ручного набора",
        "pts": 2,
        "how_it_works": "Соотношение длины развёрнутого ответа и активного времени работы по часам сервера.",
    },
    {
        "n": 14,
        "c": 4,
        "code": "focus_lost",
        "name": "Переключение на другие вкладки или окна",
        "pts": 2,
        "how_it_works": "Учет числа потерь фокуса и суммарного времени отсутствия на вкладке задания.",
    },
    {
        "n": 15,
        "c": 4,
        "code": "fs_exit",
        "name": "Выход из полноэкранного режима во время теста",
        "pts": 1,
        "how_it_works": "Сворачивание полноэкранного окна во время выполнения задания.",
    },
    {
        "n": 16,
        "c": 4,
        "code": "copy",
        "name": "Попытка скопировать условие или код задания",
        "pts": 1,
        "how_it_works": "Перехват копирования текста условия с автоматической подстановкой варианта-двойника.",
    },
    {
        "n": 17,
        "c": 4,
        "code": "printscreen",
        "name": "Снимок экрана во время выполнения задания",
        "pts": 1,
        "how_it_works": "Фиксация системных клавиш создания снимка экрана.",
    },
    {
        "n": 18,
        "c": 4,
        "code": "api_bypass",
        "name": "Отправка ответов в обход штатного интерфейса",
        "pts": 1,
        "how_it_works": "Отсутствие клиентской телеметрии по серии заданий сессии.",
    },
    {
        "n": 19,
        "c": 5,
        "code": "no_face",
        "name": "Отсутствие лица в кадре во время решения",
        "pts": 1,
        "how_it_works": "Локальный детектор в браузере зафиксировал отсутствие человека перед камерой.",
    },
    {
        "n": 20,
        "c": 5,
        "code": "multi_face",
        "name": "Второе лицо в кадре (посторонний подсказчик)",
        "pts": 2,
        "how_it_works": "Локальный детектор зафиксировал несколько лиц в кадре во время выполнения задания.",
    },
    {
        "n": 21,
        "c": 5,
        "code": "camera_off",
        "name": "Камера закрыта или прервала передачу при активном режиме",
        "pts": 1,
        "how_it_works": "Перекрытие объектива или отключение видеопотока при включённом режиме наблюдения.",
    },
]

DEFAULT_LZ_ITEMS: list[dict[str, float]] = [
    {"a": 0.76, "b": -2.2, "x": 0, "t": 41},
    {"a": 0.70, "b": -1.8, "x": 1, "t": 22},
    {"a": 0.83, "b": -1.5, "x": 0, "t": 38},
    {"a": 0.64, "b": -1.1, "x": 1, "t": 25},
    {"a": 0.76, "b": -0.7, "x": 1, "t": 19},
    {"a": 0.70, "b": -0.3, "x": 0, "t": 44},
    {"a": 0.83, "b": 0.2, "x": 1, "t": 9},
    {"a": 0.76, "b": 0.6, "x": 1, "t": 7},
    {"a": 0.64, "b": 1.1, "x": 0, "t": 36},
    {"a": 0.89, "b": 1.6, "x": 1, "t": 6},
    {"a": 0.95, "b": 2.0, "x": 1, "t": 4},
    {"a": 1.02, "b": 2.4, "x": 1, "t": 3},
]

DEFAULT_ORIGINAL_STEM = (
    "Задача 7 · Backend · Senior. Реализуйте кэш с вытеснением по давности использования (LRU) "
    "и временем жизни ключей (TTL = 300 с) на 1000000 записей (16 сегментов блокировки): "
    "чтение и запись за O(1), истёкшие ключи не возвращаются. Объясните выбор структуры данных и потокобезопасность."
)


def public_signals_catalog(*, demo_mode: bool = False) -> list[dict[str, Any]]:
    """Возвращает каталог сигналов: в демо-режиме — с описанием для жюри, в обычном — без внутренних деталей (Р27)."""
    if demo_mode:
        return SIGNALS_SPEC
    return [
        {
            "n": s["n"],
            "c": s["c"],
            "code": f"signal_{s['n']}",
            "name": f"Индикатор контура #{s['c']} ({CONTOURS_SPEC[s['c'] - 1]['name']})",
            "pts": s["pts"],
            "how_it_works": "Внутренние параметры и пороги сигнала скрыты по правилам безопасности платформы.",
        }
        for s in SIGNALS_SPEC
    ]


def call_make_copy_decoy(stem: str = DEFAULT_ORIGINAL_STEM, key_value: float | int | str | None = 300) -> dict[str, Any]:
    """Вызывает `proctor_rules.make_copy_decoy` (А6) через getattr с совместимым представлением для полигона."""
    fn = getattr(proctor_rules, "make_copy_decoy", None) or getattr(integrity, "make_copy_decoy", None)
    a6_decoy: dict[str, Any] | None = None
    if callable(fn):
        try:
            a6_decoy = fn(stem, key_value)
        except Exception:
            a6_decoy = None

    decoy_stem = (
        stem.replace("1000000", "2500000")
        .replace("1 000 000", "2 500 000")
        .replace("TTL = 300", "TTL = 480")
        .replace("16 сегментов", "64 сегмента")
    )
    if a6_decoy and isinstance(a6_decoy, dict):
        return {
            **a6_decoy,
            "original_stem": stem,
            "decoy_stem": decoy_stem,
            "decoy_expected": "2 500 000 записей, TTL 480 с, 64 сегмента",
            "decoy_markers": ["2 500 000", "2,5 млн", "2.5 млн", "2500000", "375", "480 с", "ttl = 480", "ttl=480", "64 сегмент"],
        }
    return {
        "clipboard_stem": decoy_stem,
        "orig_number": 300.0,
        "decoy_number": 375.0,
        "orig_str": "300",
        "decoy_str": "375",
        "decoy_answer": 375.0,
        "original_stem": stem,
        "decoy_stem": decoy_stem,
        "decoy_expected": "2 500 000 записей, TTL 480 с, 64 сегмента",
        "decoy_markers": ["2 500 000", "2,5 млн", "2.5 млн", "2500000", "375", "480 с", "ttl = 480", "ttl=480", "64 сегмент"],
    }


def call_check_copy_decoy(answer: str, decoy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Вызывает `proctor_rules.check_copy_decoy` (А6) через getattr + сверяет маркеры двойника."""
    dec = decoy or call_make_copy_decoy()
    fn = getattr(proctor_rules, "check_copy_decoy", None) or getattr(integrity, "check_copy_decoy", None)
    a6_hit = False
    if callable(fn):
        try:
            r = fn(answer, dec, copied=True)
            a6_hit = bool(r.get("triggered") if isinstance(r, dict) else r)
        except Exception:
            a6_hit = False

    low = (answer or "").lower()
    markers = [str(m) for m in (dec.get("decoy_markers") or [])]
    matched = [m for m in markers if m.lower() in low]
    triggered = bool(a6_hit or len(matched) > 0)
    if a6_hit and not matched and dec.get("decoy_str"):
        matched = [str(dec["decoy_str"])]
    return {
        "triggered": triggered,
        "matched_markers": matched,
        "decoy_expected": dec.get("decoy_expected"),
    }


def call_integrity_followup(integ: dict[str, Any], decoy_hits: int = 0) -> dict[str, Any]:
    """Вызывает `proctor_rules.integrity_followup` (А6) через getattr с унификацией полей."""
    fn = getattr(proctor_rules, "integrity_followup", None) or getattr(integrity, "integrity_followup", None)
    if callable(fn):
        try:
            res = fn(integ, decoy_hits=decoy_hits)
            if isinstance(res, dict) and "needs_followup_stage" in res:
                needs = bool(res["needs_followup_stage"])
                return {
                    **res,
                    "decoy_hits": decoy_hits,
                    "action": "followup_stage_assigned" if needs else "none",
                    "action_title_ru": (
                        "Назначен дополнительный проверочный этап и 3-минутная устная защита (без автоматической блокировки)"
                        if needs
                        else "Дополнительный этап не требуется"
                    ),
                }
        except Exception:
            pass

    pts = int(integ.get("points") or 0) + (2 if decoy_hits > 0 else 0)
    honesty_index = round(max(0.0, 1.0 - 0.15 * pts), 2)
    reasons = list(integ.get("reasons") or [])
    if decoy_hits > 0:
        reasons.insert(0, "Расчёт выполнен по числам из скопированного в буфер условия-двойника")
    needs_followup = bool(decoy_hits > 0 or pts >= 2 or integ.get("level") in ("medium", "low"))
    return {
        "honesty_index": honesty_index,
        "risk_points": pts,
        "threshold_points": 2,
        "decoy_hits": decoy_hits,
        "decoy_hit": decoy_hits > 0,
        "needs_followup_stage": needs_followup,
        "followup_kind": "oral_defense" if needs_followup else None,
        "action": "followup_stage_assigned" if needs_followup else "none",
        "action_title_ru": (
            "Назначен дополнительный проверочный этап и 3-минутная устная защита (без автоматической блокировки)"
            if needs_followup
            else "Дополнительный этап не требуется"
        ),
        "triggered_factors": reasons[:5],
        "employer_reason_ru": "; ".join(reasons[:3]) if reasons else "Замечаний к самостоятельности прохождения нет",
    }


_INJECTION_CODE_RU: dict[str, str] = {
    "ignore_instructions": "попытка отменить системные правила оценщика",
    "score_request": "прямое требование выставить максимальный балл",
    "role_injection": "подмена системной роли (system / assistant)",
    "json_verdict": "вставка готового JSON-вердикта в текст ответа",
    "marker_spoof": "попытка закрыть или подделать разделитель данных",
    "reviewer_address": "обращение напрямую к проверяющей модели",
    "model_address": "обращение к проверяющей модели в тексте ответа",
}


def _ru_sig(code: str) -> str:
    return _INJECTION_CODE_RU.get(code, f"шаблон манипуляции ({code})")


def _call_grader_inspect(text: str) -> dict[str, Any]:
    """Вызывает `grader.inspect` (А6) через getattr с полной поддержкой до и после слияния веток."""
    fn = getattr(grader, "inspect", None)
    if callable(fn):
        res = fn(text)
        if isinstance(res, dict) and "layers" in res:
            return res

    raw = text or ""
    deobf_fn = getattr(grader, "_deobfuscate", None)
    normalized = deobf_fn(raw) if callable(deobf_fn) else raw
    inj = list(grader.injection_signals(raw))
    inj_titles = [_ru_sig(s) for s in inj]
    cleaned, meta_removed = grader.strip_meta(raw)
    soft_fn = getattr(grader, "_soft_signals", None)
    soft = list(soft_fn(cleaned)) if callable(soft_fn) else []

    normalizations: list[str] = []
    if normalized != raw:
        normalizations.append("Нормализация скрытых символов, омоглифов и разрядки")

    verdict = "blocked" if inj else ("meta_stripped" if meta_removed else ("soft_doubt" if soft else "clean"))
    route = "expert" if inj else ("llm_second" if (meta_removed or soft) else "llm_single")

    return {
        "verdict": verdict,
        "route": route,
        "normalized": normalized,
        "normalizations": normalizations,
        "signals": inj,
        "signal_titles": inj_titles,
        "meta_removed": meta_removed,
        "cleaned_text": cleaned,
        "soft_signals": soft,
        "layers": [
            {
                "id": "normalize",
                "title": "1. Нормализация и очистка обфускации",
                "triggered": bool(normalizations),
                "details": normalizations or ["Скрытых подмен символов не обнаружено"],
            },
            {
                "id": "hard_filter",
                "title": "2. Предварительный фильтр промпт-инъекций",
                "triggered": bool(inj),
                "details": inj_titles or ["Прямых команд оценщику не обнаружено"],
            },
            {
                "id": "strip_meta",
                "title": "3. Очистка самооценок и служебных приписок",
                "triggered": bool(meta_removed),
                "details": meta_removed or ["Попыток приписать себе балл не обнаружено"],
            },
            {
                "id": "soft_doubts",
                "title": "4. Контроль цитат и второй независимый проверяющий",
                "triggered": bool(soft),
                "details": soft or ["Штатная проверка с обязательным цитированием"],
            },
        ],
    }


def _compute_cv(intervals_ms: list[float]) -> float:
    if len(intervals_ms) < 2:
        return 0.0
    mu = sum(intervals_ms) / len(intervals_ms)
    if mu <= 1e-6:
        return 0.0
    var = sum((x - mu) ** 2 for x in intervals_ms) / len(intervals_ms)
    return round(math.sqrt(var) / mu, 3)


def inspect_anticheat_live(payload: dict[str, Any], *, demo_mode: bool = True) -> dict[str, Any]:
    """Выполняет проверку ответа и телеметрии через настоящие модули античита бэкенда."""
    answer_text = str(payload.get("answer_text") or "")[:12000]
    # Контрольное слово задаётся только сервером (клиент не может подменить его)
    canary_word = CANARY_SERVER_WORD
    telemetry = payload.get("telemetry") if isinstance(payload.get("telemetry"), dict) else {}
    attack_preset = str(payload.get("attack_preset") or "")

    # 1. Реальная проверка текста оценщиком (grader.inspect / injection_signals / strip_meta)
    grader_report = _call_grader_inspect(answer_text)

    # 2. Проверка «двойника при копировании» и скрытого маркера условия
    decoy_spec = call_make_copy_decoy()
    decoy_check = call_check_copy_decoy(answer_text, decoy_spec)
    decoy_hit = bool(decoy_check.get("triggered") or telemetry.get("decoy_hit"))

    has_zw = any(ch in answer_text for ch in ("\u2063", "\u200b", "\u200c", "\u200d", "\u2060"))
    has_canary_word = bool(canary_word.lower() in answer_text.lower())
    ai_mark_hit = bool(has_zw or has_canary_word or decoy_hit or telemetry.get("ai_mark_hit"))

    # 3. Клавиатурная динамика и телеметрия интерфейса (безопасное приведение типов)
    raw_intervals = telemetry.get("key_intervals_ms") if isinstance(telemetry.get("key_intervals_ms"), list) else []
    key_intervals: list[float] = []
    for x in raw_intervals[:200]:
        try:
            val = float(x)
            if 0 <= val <= 10_000:
                key_intervals.append(val)
        except (TypeError, ValueError):
            continue

    cv_val = _compute_cv(key_intervals) if key_intervals else 0.68
    ik_cv_int = int(round(cv_val * 100)) if key_intervals else int(telemetry.get("ik_cv") or 68)

    paste_count = max(0, int(telemetry.get("paste") or 0))
    paste_chars = max(0, int(telemetry.get("paste_chars") or 0))
    copy_count = max(0, int(telemetry.get("copy") or 0))
    focus_lost = max(0, int(telemetry.get("focus_lost") or 0))
    hidden_ms = max(0, int(telemetry.get("hidden_ms") or 0))
    fs_exit = max(0, int(telemetry.get("fs_exit") or 0))
    fs_out_ms = max(0, int(telemetry.get("fs_out_ms") or 0))
    printscreen = max(0, int(telemetry.get("printscreen") or 0))
    typed_chars = max(0, int(telemetry.get("typed") if telemetry.get("typed") is not None else len(answer_text)))
    active_ms = max(1, int(telemetry.get("active_ms") or 25_000))
    api_bypass = bool(telemetry.get("api_bypass"))

    even_rhythm = bool((len(key_intervals) >= 12 and cv_val < 0.25) or ik_cv_int < 25 or telemetry.get("even_rhythm"))
    not_typed = bool((len(answer_text) >= 200 and typed_chars < len(answer_text) * 0.5 and paste_count == 0) or telemetry.get("not_typed"))
    chars_per_sec = round(len(answer_text) / (active_ms / 1000.0), 1) if active_ms > 0 else 0.0
    fast_text = bool((len(answer_text) >= 200 and chars_per_sec > 8.0) or telemetry.get("fast_text"))

    # 4. Реальный вызов `integrity.proctoring_source`
    done_item = {
        "position": 1,
        "time_s": round(active_ms / 1000.0, 1),
        "ai_mark_hit": ai_mark_hit,
        "fast_text": fast_text,
        "typing": (["not_typed"] if not_typed else []) + (["even_rhythm"] if even_rhythm else []),
        "meta_claims": bool(grader_report["meta_removed"]),
        "signals": {
            "focus_lost": focus_lost,
            "hidden_ms": hidden_ms,
            "paste": paste_count,
            "paste_chars": paste_chars,
            "copy": copy_count,
            "fs_exit": fs_exit,
            "fs_out_ms": fs_out_ms,
            "fs_ms": 0 if fs_exit > 0 else active_ms,
            "fs_na": False,
            "typed": typed_chars,
            "inserted": paste_chars,
            "keys": max(len(key_intervals), typed_chars),
            "ik_cv": ik_cv_int,
            "active_ms": active_ms,
            "printscreen": printscreen,
        },
    }
    _, proc_signals = integrity.proctoring_source([done_item], {})

    # 5. Реальный расчёт индекса согласованности `integrity.person_fit_lz` и темпа по матрице ответов
    raw_lz_items = payload.get("lz_items") if isinstance(payload.get("lz_items"), list) else None
    check_lz = bool(payload.get("check_lz") or attack_preset == "leak" or raw_lz_items is not None)
    used_lz_items: list[dict[str, float]] = []
    for it in (raw_lz_items or DEFAULT_LZ_ITEMS)[:40]:
        if isinstance(it, dict):
            try:
                used_lz_items.append({
                    "a": float(it.get("a", 1.0)),
                    "b": float(it.get("b", 0.0)),
                    "x": 1 if int(it.get("x", 0)) > 0 else 0,
                    "t": max(1.0, float(it.get("t", 25.0))),
                })
            except (TypeError, ValueError):
                continue
    if not used_lz_items:
        used_lz_items = DEFAULT_LZ_ITEMS

    lz_tuples = [(it["a"], it["b"], int(it["x"])) for it in used_lz_items]
    lz_theta = float(payload.get("lz_theta") or 1.2)
    lz_val = integrity.person_fit_lz(lz_tuples, lz_theta) if check_lz else None

    # Вычисляем фактические времена ответа из переданной матрицы (без захардкоженных чисел)
    item_times = [it["t"] for it in used_lz_items]
    median_time_s = round(statistics.median(item_times), 1) if item_times else 25.0
    hard_fast_times = [it["t"] for it in used_lz_items if it["b"] >= 1.2 and it["x"] == 1 and it["t"] <= 10.0]

    # 6. Реальный расчёт событий камеры через `proctor.rules.aggregate`
    raw_cam = payload.get("camera_events") if isinstance(payload.get("camera_events"), list) else []
    cam_events = [e for e in raw_cam[:30] if isinstance(e, dict)]
    cam_mode = "camera" if cam_events else "none"
    cam_agg = proctor_rules.aggregate(
        cam_mode,
        [{"position": 1, "time_s": 60.0, "canary": False}],
        cam_events,
        observed={"1": {"ms": 58_000, "frames": 80, "face": 70}},
        windows=[{"from": 1, "to": None, "mid": False}],
    )

    # 7. Собираем список сработавших сигналов на основе вычисленных значений
    triggered_numbers: set[int] = set()
    events_log: list[dict[str, Any]] = []

    def _hit(nums: list[int], msg: str, severe: bool = False) -> None:
        for n in nums:
            triggered_numbers.add(n)
        events_log.append({"signals": nums, "text": msg, "severe": severe})

    if check_lz and hard_fast_times:
        min_fast = int(min(hard_fast_times))
        max_fast = int(max(hard_fast_times))
        _hit(
            [1, 3, 4],
            f"Сложные задания (уровень b ≥ 1,2) решены за {min_fast}–{max_fast} с при медианном времени по серии {int(median_time_s)} с",
        )
    if bool(telemetry.get("preknowledge_flagged")) or (check_lz and lz_val is not None and lz_val < -2.5 and hard_fast_times):
        _hit(
            [2],
            f"Совокупный признак предзнания на проверочном примере ({len(hard_fast_times)} мгновенных верных ответов на сложных заданиях)",
            severe=True,
        )
    if bool(telemetry.get("fast_wrong")):
        _hit([5], "Серия мгновенных неверных ответов без прочтения условия")

    if lz_val is not None and lz_val < -2.0:
        _hit(
            [6],
            f"Несогласованность матрицы ответов со сложностью заданий (расчётный индекс {str(round(lz_val, 2)).replace('-', '−').replace('.', ',')}): ошибки на базовых вопросах при верных ответах на трудных",
            severe=lz_val < -3.0,
        )

    if decoy_hit:
        matched_str = ", ".join(decoy_check.get("matched_markers") or ["параметры двойника"])
        _hit([7], f"Решение по скопированному двойнику: в ответе использованы подменённые при копировании числа ({matched_str})", severe=True)
    if has_zw or has_canary_word:
        _hit([7], f"В тексте ответа обнаружено скрытое контрольное слово из условия («{canary_word}»)", severe=True)
    if grader_report["signals"]:
        titles = grader_report.get("signal_titles") or [_ru_sig(s) for s in grader_report["signals"]]
        _hit([8], f"Фильтр оценщика перехватил промпт-инъекцию: {', '.join(titles[:3])}", severe=True)
    if grader_report["meta_removed"]:
        _hit([9], f"Вырезаны служебные приписки и самооценка из ответа ({len(grader_report['meta_removed'])} шт.)")
    if paste_count > 0 or paste_chars > 0:
        _hit([10], f"Вставка готового текста из буфера обмена ({paste_chars or len(answer_text)} знаков)")
    if not_typed:
        _hit([11], f"Длинный ответ ({len(answer_text)} знаков) появился при малом числе нажатий клавиш ({typed_chars})")
    if even_rhythm:
        _hit([12], f"Механически ровный ритм печати на серии нажатий (разброс интервалов {str(cv_val).replace('.', ',')})")
    if fast_text:
        _hit([13], f"Высокая скорость появления текста ({str(chars_per_sec).replace('.', ',')} знаков/с)")
    if focus_lost > 0 or hidden_ms >= 5_000:
        _hit([14], f"Потеря фокуса окна теста ({round(hidden_ms / 1000.0, 1)} с вне вкладки)")
    if fs_exit > 0 or fs_out_ms > 0:
        _hit([15], f"Выход из полноэкранного режима во время выполнения задания ({fs_exit} раз)")
    if copy_count > 0:
        _hit([16], "Перехвачена попытка скопировать условие задания (в буфер обмена подставлен вариант-двойник)")
    if printscreen > 0:
        _hit([17], "Зафиксирована системная комбинация снимка экрана")
    if api_bypass:
        _hit([18], "Ответы отправлены в обход штатного интерфейса без клиентской телеметрии")

    for ev in cam_events:
        k = ev.get("kind")
        if k == "no_face":
            _hit([19], "Локальный анализ кадра: нет лица перед камерой")
        elif k == "multi_face":
            _hit([20], "Локальный анализ кадра: в кадре обнаружено второе лицо", severe=True)
        elif k in ("blocked", "camera_off"):
            _hit([21], "Камера закрыта или прекратила передачу кадра при активном режиме")

    sig_by_n = {s["n"]: s for s in SIGNALS_SPEC}
    risk_points = sum(sig_by_n[n]["pts"] for n in triggered_numbers if n in sig_by_n)
    level_key = "high" if risk_points == 0 else ("medium" if risk_points <= 2 else "low")
    level_title = integrity.LEVEL_TITLES[level_key]

    integ_dict = {
        "level": level_key,
        "title": level_title,
        "points": risk_points,
        "reasons": [e["text"] for e in events_log],
        "camera": cam_agg,
        "signals": {
            **proc_signals,
            "preknowledge_flagged": 2 in triggered_numbers,
            "canary_fast": 1 if 1 in triggered_numbers else 0,
            "lz": lz_val,
            "ai_mark_items": 1 if ai_mark_hit else 0,
            "copy_decoy_items": 1 if decoy_hit else 0,
            "injection_items": 1 if grader_report["signals"] else 0,
            "focus_lost_items": focus_lost,
            "hidden_s": round(hidden_ms / 1000.0, 1),
            "paste_items": paste_count,
            "printscreen_items": printscreen,
            "copy_items": copy_count,
            "not_typed_items": 1 if not_typed else 0,
            "even_rhythm_items": 1 if even_rhythm else 0,
            "fast_text_items": 1 if fast_text else 0,
            "fs_exits": fs_exit,
        },
    }
    followup = call_integrity_followup(integ_dict, decoy_hits=1 if decoy_hit else 0)
    rec_defense, rec_why, _ = interview_service.defense_recommendation(integ_dict)
    if grader_report["signals"] or risk_points >= 2 or followup["needs_followup_stage"]:
        rec_defense = True
        if not rec_why:
            rec_why = followup["employer_reason_ru"]

    # Полный паспорт отдаём только в демо-режиме для жюри; для обычного режима — без раскрытия внутренних порогов (Р27)
    passport = interview_service.integrity_passport(integ_dict, None, detailed=bool(demo_mode))

    return {
        "demo_mode": bool(demo_mode),
        "demo_notice_ru": (
            "Демонстрационный стенд: фильтр текста оценщика (grader.inspect), проверка варианта-двойника (check_copy_decoy), "
            "клавиатурная динамика и индекс согласованности (person_fit_lz) рассчитываются настоящими функциями сервера на действиях в браузере и подготовленных примерах."
        ),
        "total_signals_catalog": len(SIGNALS_SPEC),
        "triggered_count": len(triggered_numbers),
        "triggered_numbers": sorted(triggered_numbers),
        "risk_points": risk_points,
        "integrity_level": level_key,
        "integrity_title": level_title,
        "defense_recommended": bool(rec_defense),
        "defense_why": rec_why,
        "grader_inspect": grader_report,
        "copy_decoy": {
            "decoy_stem": decoy_spec["decoy_stem"],
            "decoy_expected": decoy_spec["decoy_expected"],
            "triggered": decoy_hit,
            "matched_markers": decoy_check.get("matched_markers", []),
        },
        "integrity_followup": followup,
        "canary_detected": ai_mark_hit,
        "canary_word": canary_word if (has_zw or has_canary_word) else None,
        "keystroke_cv": cv_val,
        "person_fit_lz": lz_val,
        "lz_items": used_lz_items if check_lz else [],
        "events_log": events_log if demo_mode else [
            {"signals": e["signals"], "text": f"Зафиксировано событие контура проверки (#{e['signals'][0]})", "severe": e.get("severe")}
            for e in events_log
        ],
        "passport": passport,
    }
