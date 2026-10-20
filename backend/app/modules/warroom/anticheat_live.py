"""Режим Б «Боевого ИИ-Полигона»: живая проверка текста ответа и телеметрии настоящим античитом бэкенда.

Прогоняет переданный ответ кандидата, телеметрию ввода/экрана, события камеры и матрицу ответов
через реальные функции модулей:
- `app.modules.assessment.grader` (`inspect` от А6 с фолбэком на `injection_signals` и `strip_meta`);
- `app.modules.assessment.integrity` (`person_fit_lz`, `proctoring_source`);
- `app.modules.proctor.rules` (`aggregate`);
- `app.modules.interview.service` (`defense_recommendation`, `integrity_passport`).

Все 21 сигнал сгруппированы по 5 контурам (18 сигналов без камеры + 3 сигнала камеры по согласию),
формулировки — по-русски, без жаргона в основных заголовках (технические детали — в поле `how_it_works`).
"""
from __future__ import annotations

import math
from typing import Any

from app.modules.assessment import grader, integrity
from app.modules.interview import service as interview_service
from app.modules.proctor import rules as proctor_rules

CONTOURS_SPEC: list[dict[str, Any]] = [
    {
        "n": 1,
        "id": "prior",
        "name": "Самостоятельность и темп ответов",
        "color": "#f59e0b",
        "description": "Сверка времени чтения и решения заданий по часам сервера, контрольные задания-канарейки.",
    },
    {
        "n": 2,
        "id": "fit",
        "name": "Согласованность ответов с уровнем",
        "color": "#a78bfa",
        "description": "Проверка естественности паттерна ответов: ошибки на базовых вопросах при мгновенном решении сложных.",
    },
    {
        "n": 3,
        "id": "origin",
        "name": "Происхождение и чистота текста ответа",
        "color": "#f43f5e",
        "description": "Скрытые текстовые маркеры условия, динамика клавиатурного набора, вставки и фильтр манипуляций оценщиком.",
    },
    {
        "n": 4,
        "id": "screen",
        "name": "Рабочее окно и среда прохождения",
        "color": "#22d3ee",
        "description": "Переключения вкладок, полноэкранный режим, копирование условия, снимки экрана и обход интерфейса.",
    },
    {
        "n": 5,
        "id": "live",
        "name": "Камера по согласию и устная защита",
        "color": "#34d399",
        "description": "Локальная проверка кадра в браузере (наличие лица, отсутствие второго человека) и 3-минутная устная защита.",
    },
]

# Реальный каталог из 21 сигнала в 5 контурах (согласовано с А6 и docs/ANTIFRAUD.md §6.5)
SIGNALS_SPEC: list[dict[str, Any]] = [
    # Контур 1: Самостоятельность и темп ответов (5 сигналов)
    {
        "n": 1,
        "c": 1,
        "code": "canary_fast",
        "name": "Контрольные задания решены аномально быстро",
        "pts": 1,
        "how_it_works": "Сравнение времени ответа на контрольных позициях (2, 6, 10) с медианой кандидата.",
    },
    {
        "n": 2,
        "c": 1,
        "code": "preknowledge_flagged",
        "name": "Признак знакомства со слитыми заданиями",
        "pts": 3,
        "how_it_works": "Детектор предзнания по совокупности контрольных вариантов и модели времени ответа.",
    },
    {
        "n": 3,
        "c": 1,
        "code": "fast_correct",
        "name": "Аномально быстрые верные ответы",
        "pts": 2,
        "how_it_works": "Ответ дан быстрее 12 % ожидаемого времени для уровня сложности и быстрее половины времени беглого чтения.",
    },
    {
        "n": 4,
        "c": 1,
        "code": "instant_correct",
        "name": "Мгновенные верные ответы без чтения условия",
        "pts": 2,
        "how_it_works": "Ответ отправлен быстрее пятой части времени, необходимого для прочтения текста задания.",
    },
    {
        "n": 5,
        "c": 1,
        "code": "fast_wrong",
        "name": "Серия мгновенных неверных ответов (угадывание)",
        "pts": 1,
        "how_it_works": "Не менее 30 % заданий (от 3 штук) отвечены неверно без прочтения условия.",
    },
    # Контур 2: Согласованность ответов с уровнем (1 сигнал)
    {
        "n": 6,
        "c": 2,
        "code": "person_fit_lz",
        "name": "Несогласованность ответов со сложностью заданий",
        "pts": 2,
        "how_it_works": "Стандартизованное лог-правдоподобие матрицы ответов (индекс согласованности Drasgow l_z < −2,0 / −3,0).",
    },
    # Контур 3: Происхождение и чистота текста ответа (7 сигналов)
    {
        "n": 7,
        "c": 3,
        "code": "ai_mark_hit",
        "name": "Скрытое контрольное слово из условия в ответе",
        "pts": 3,
        "how_it_works": "Невидимая на экране фраза в условии задания появляется в ответе при слепом копировании текста в нейросеть.",
    },
    {
        "n": 8,
        "c": 3,
        "code": "injection",
        "name": "Попытка перехвата инструкций проверяющей модели",
        "pts": 2,
        "how_it_works": "Фильтр нормализации и деобфускации обнаружил команды управления оценщиком или вложенный JSON-вердикт.",
    },
    {
        "n": 9,
        "c": 3,
        "code": "meta_claims",
        "name": "Самооценка и служебные приписки для проверяющего",
        "pts": 1,
        "how_it_works": "Детектор strip_meta вырезал утверждения кандидата о том, что ответ уже проверен и заслуживает высшего балла.",
    },
    {
        "n": 10,
        "c": 3,
        "code": "paste",
        "name": "Вставка готового фрагмента текста из буфера",
        "pts": 2,
        "how_it_works": "Зафиксирована вставка крупного текста или кода в поле развёрнутого ответа.",
    },
    {
        "n": 11,
        "c": 3,
        "code": "not_typed",
        "name": "Длинный ответ появился без клавиатурного набора",
        "pts": 2,
        "how_it_works": "Менее 50 % символов ответа длиннее 200 знаков введено нажатиями клавиш.",
    },
    {
        "n": 12,
        "c": 3,
        "code": "even_rhythm",
        "name": "Механически ровный ритм печати (автотайпер)",
        "pts": 1,
        "how_it_works": "Коэффициент вариации пауз между нажатиями клавиш ниже 0,25 на серии от 100 нажатий.",
    },
    {
        "n": 13,
        "c": 3,
        "code": "fast_text",
        "name": "Скорость появления текста выше физического предела",
        "pts": 2,
        "how_it_works": "Развёрнутый ответ появился со скоростью свыше 8 символов в секунду по часам сервера.",
    },
    # Контур 4: Рабочее окно и среда прохождения (5 сигналов)
    {
        "n": 14,
        "c": 4,
        "code": "focus_lost",
        "name": "Переключение на другие вкладки или окна",
        "pts": 2,
        "how_it_works": "Потеря фокуса окна теста на 2+ заданиях или суммарное отсутствие свыше 30 секунд.",
    },
    {
        "n": 15,
        "c": 4,
        "code": "fs_exit",
        "name": "Выход из полноэкранного режима во время теста",
        "pts": 1,
        "how_it_works": "Сворачивание полноэкранного окна на десктопе или прохождение без полноэкранного режима.",
    },
    {
        "n": 16,
        "c": 4,
        "code": "copy",
        "name": "Попытка скопировать условие или код задания",
        "pts": 1,
        "how_it_works": "Перехват события копирования текста формулировки задания в буфер обмена.",
    },
    {
        "n": 17,
        "c": 4,
        "code": "printscreen",
        "name": "Снимок экрана во время выполнения задания",
        "pts": 1,
        "how_it_works": "Фиксация системных комбинаций создания скриншота (PrintScreen, Win+Shift+S, Cmd+Shift+3/4/5).",
    },
    {
        "n": 18,
        "c": 4,
        "code": "api_bypass",
        "name": "Отправка ответов в обход штатного интерфейса",
        "pts": 1,
        "how_it_works": "Отсутствие клиентской телеметрии по большинству заданий сессии.",
    },
    # Контур 5: Камера по согласию (3 сигнала)
    {
        "n": 19,
        "c": 5,
        "code": "no_face",
        "name": "Отсутствие лица в кадре во время решения",
        "pts": 1,
        "how_it_works": "Локальный детектор в браузере зафиксировал отсутствие человека перед камерой дольше порога.",
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


def _fallback_grader_inspect(text: str) -> dict[str, Any]:
    """Совместимая обёртка над `grader.py`, если `grader.inspect` из ветки А6 ещё не влита."""
    fn = getattr(grader, "inspect", None)
    if callable(fn):
        return fn(text)

    raw = text or ""
    deobf_fn = getattr(grader, "_deobfuscate", None)
    normalized = deobf_fn(raw) if callable(deobf_fn) else raw
    inj = list(grader.injection_signals(raw))
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
        "signal_titles": [f"Перехвачен шаблон манипуляции: {s}" for s in inj],
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
                "details": inj or ["Прямых команд оценщику не обнаружено"],
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


def inspect_anticheat_live(payload: dict[str, Any]) -> dict[str, Any]:
    """Выполняет живую проверку ответа и телеметрии через настоящие модули античита бэкенда."""
    answer_text = str(payload.get("answer_text") or "")
    canary_word = str(payload.get("canary_word") or "Бергамот").strip()
    telemetry = payload.get("telemetry") if isinstance(payload.get("telemetry"), dict) else {}
    attack_preset = str(payload.get("attack_preset") or "")

    # 1. Реальная проверка текста оценщиком (grader.inspect / injection_signals / strip_meta)
    grader_report = _fallback_grader_inspect(answer_text)

    # 2. Проверка стеганографической метки в ответе
    has_zw = any(ch in answer_text for ch in ("\u2063", "\u200b", "\u200c", "\u200d", "\u2060"))
    has_canary_word = bool(canary_word and canary_word.lower() in answer_text.lower())
    ai_mark_hit = bool(has_zw or has_canary_word or telemetry.get("ai_mark_hit"))

    # 3. Клавиатурная динамика и телеметрия интерфейса
    key_intervals = [float(x) for x in (telemetry.get("key_intervals_ms") or []) if isinstance(x, (int, float))]
    cv_val = _compute_cv(key_intervals) if key_intervals else float(telemetry.get("ik_cv_float") or 0.68)
    ik_cv_int = int(round(cv_val * 100)) if key_intervals else int(telemetry.get("ik_cv", 68))

    paste_count = int(telemetry.get("paste") or 0)
    paste_chars = int(telemetry.get("paste_chars") or 0)
    copy_count = int(telemetry.get("copy") or 0)
    focus_lost = int(telemetry.get("focus_lost") or 0)
    hidden_ms = int(telemetry.get("hidden_ms") or 0)
    fs_exit = int(telemetry.get("fs_exit") or 0)
    fs_out_ms = int(telemetry.get("fs_out_ms") or 0)
    printscreen = int(telemetry.get("printscreen") or 0)
    typed_chars = int(telemetry.get("typed") if telemetry.get("typed") is not None else len(answer_text))
    active_ms = int(telemetry.get("active_ms") or 25_000)
    api_bypass = bool(telemetry.get("api_bypass"))

    even_rhythm = bool((len(key_intervals) >= 12 and cv_val < 0.25) or ik_cv_int < 25 or telemetry.get("even_rhythm"))
    not_typed = bool((len(answer_text) >= 200 and typed_chars < len(answer_text) * 0.5 and paste_count == 0) or telemetry.get("not_typed"))
    fast_text = bool((len(answer_text) >= 200 and active_ms > 0 and (len(answer_text) / (active_ms / 1000.0)) > 8.0) or telemetry.get("fast_text"))

    # 4. Реальный вызов `integrity.proctoring_source` на сформированном задании
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
    proc_reasons, proc_signals = integrity.proctoring_source([done_item], {})

    # 5. Реальный расчёт индекса согласованности `integrity.person_fit_lz`
    lz_items = payload.get("lz_items") if isinstance(payload.get("lz_items"), list) else None
    check_lz = bool(payload.get("check_lz") or attack_preset == "leak" or lz_items is not None)
    used_lz_items = lz_items or DEFAULT_LZ_ITEMS
    lz_tuples = [(float(it["a"]), float(it["b"]), float(it["x"])) for it in used_lz_items]
    lz_theta = float(payload.get("lz_theta") or 1.2)
    lz_val = integrity.person_fit_lz(lz_tuples, lz_theta) if check_lz else None

    # 6. Реальный расчёт событий камеры через `proctor.rules.aggregate`
    cam_events = payload.get("camera_events") if isinstance(payload.get("camera_events"), list) else []
    cam_mode = "camera" if cam_events else "none"
    cam_agg = proctor_rules.aggregate(
        cam_mode,
        [{"position": 1, "time_s": 60.0, "canary": False}],
        cam_events,
        observed={"1": {"ms": 58_000, "frames": 80, "face": 70}},
        windows=[{"from": 1, "to": None, "mid": False}],
    )

    # 7. Собираем список сработавших сигналов из 21 и причины
    triggered_numbers: set[int] = set()
    events_log: list[dict[str, Any]] = []

    def _hit(nums: list[int], msg: str, severe: bool = False) -> None:
        for n in nums:
            triggered_numbers.add(n)
        events_log.append({"signals": nums, "text": msg, "severe": severe})

    if bool(telemetry.get("canary_fast")) or attack_preset == "leak":
        _hit([1, 3], "Контрольные задания на позициях 2, 6, 10 решены за 3–6 с при медиане 74 с")
    if bool(telemetry.get("preknowledge_flagged")) or attack_preset == "leak":
        _hit([2, 4], "Детектор предзнания зафиксировал совпадение ответов со слитым набором и мгновенные ответы без чтения условия", severe=True)
    if bool(telemetry.get("fast_wrong")):
        _hit([5], "Серия мгновенных неверных ответов без прочтения условия")

    if lz_val is not None and lz_val < -2.0:
        _hit([6], f"Паттерн ответов не согласуется с уровнем (индекс согласованности {str(round(lz_val, 2)).replace('-', '−').replace('.', ',')}): ошибки на базовых заданиях при верных ответах на сложных", severe=lz_val < -3.0)

    if ai_mark_hit:
        _hit([7], f"В тексте ответа обнаружено скрытое контрольное слово из условия («{canary_word}»)", severe=True)
    if grader_report["signals"]:
        _hit([8], f"Фильтр оценщика перехватил промпт-инъекцию: {', '.join(grader_report['signals'][:3])}", severe=True)
    if grader_report["meta_removed"]:
        _hit([9], f"Вырезаны служебные приписки и самооценка из ответа ({len(grader_report['meta_removed'])} шт.)")
    if paste_count > 0 or paste_chars > 0:
        _hit([10], f"Вставка готового текста из буфера обмена ({paste_chars or len(answer_text)} знаков)")
    if not_typed:
        _hit([11], "Длинный ответ появился в поле ввода без набора с клавиатуры")
    if even_rhythm:
        _hit([12], f"Механически ровный ритм печати (коэффициент вариации интервалов {str(cv_val).replace('.', ',')} < 0,25)")
    if fast_text:
        _hit([13], "Развёрнутый ответ появился со скоростью выше 8 знаков в секунду по часам сервера")
    if focus_lost > 0 or hidden_ms >= 5_000:
        _hit([14], f"Потеря фокуса окна теста ({round(hidden_ms / 1000.0, 1)} с вне вкладки)")
    if fs_exit > 0 or fs_out_ms > 0:
        _hit([15], f"Выход из полноэкранного режима во время выполнения задания ({fs_exit} раз)")
    if copy_count > 0:
        _hit([16], "Перехвачена попытка скопировать текст условия задания")
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

    # 8. Считаем суммарные баллы риска и формируем паспорт честности через `interview.service`
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
            "focus_lost_items": focus_lost,
            "hidden_s": round(hidden_ms / 1000.0, 1),
            "paste_items": paste_count,
            "printscreen": printscreen,
            "copy_items": copy_count,
            "not_typed_items": 1 if not_typed else 0,
            "even_rhythm_items": 1 if even_rhythm else 0,
            "fast_text_items": 1 if fast_text else 0,
            "fs_exits": fs_exit,
        },
    }
    rec_defense, rec_why, _ = interview_service.defense_recommendation(integ_dict)
    if grader_report["signals"] or risk_points >= 2:
        rec_defense = True
        if not rec_why:
            rec_why = "Зафиксированы признаки несамостоятельного выполнения или манипуляции оценщиком"
    passport = interview_service.integrity_passport(integ_dict, None, detailed=True)

    return {
        "total_signals_catalog": len(SIGNALS_SPEC),
        "triggered_count": len(triggered_numbers),
        "triggered_numbers": sorted(triggered_numbers),
        "risk_points": risk_points,
        "integrity_level": level_key,
        "integrity_title": level_title,
        "defense_recommended": bool(rec_defense),
        "defense_why": rec_why,
        "grader_inspect": grader_report,
        "canary_detected": ai_mark_hit,
        "canary_word": canary_word if ai_mark_hit else None,
        "keystroke_cv": cv_val,
        "person_fit_lz": lz_val,
        "lz_items": used_lz_items if check_lz else [],
        "events_log": events_log,
        "passport": passport,
    }
