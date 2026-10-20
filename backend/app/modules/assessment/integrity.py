"""Достоверность результата теста (античит): высокая / средняя / низкая — с причинами.

Сигналы:
* **интерфейс теста** (клиент присылает с каждым ответом): потеря фокуса и переключение вкладки (число и
  время вне вкладки), вставка текста (число вставок и символов). Клиенту доверять нельзя — поэтому сигналы
  клиента только понижают достоверность, но никогда её не повышают; отсутствие сигналов (ответы в обход
  интерфейса, через API) — тоже причина;
* **сервер**: время ответа по часам сервера относительно ожидаемого времени семейства на уровне кандидата и длины
  текста задания (``fast_threshold_s``, Ф3 08.10; раньше — max(5 с, 8 % рекомендуемого времени), что ловило честный
  быстрый проход опытного разработчика). Два порога: «мгновенно» (``instant_threshold_s``) — быстрее, чем текст
  задания можно даже пробежать глазами; «быстро» — быстрее и доли ожидаемого времени семейства на уровне θ, и доли
  времени беглого чтения. Быстрый верный ответ — признак предзнания, быстрый неверный — угадывания. В экспрессе и
  в демо-режиме жюри (soft_fast) быстрые, но не мгновенные верные ответы без других сигналов достоверность не
  понижают: работодатель видит мягкую пометку «стоит уточнить зондом»;
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
  видит; если текст задания скопирован в нейросеть, слово появляется в ответе;
* **оценщик**: утверждения кандидата об оценке собственного ответа (grader.strip_meta).

Психометрический контур (KF2, 20.10): **индекс согласованности ответов person-fit l_z** (Drasgow, Levine, Williams,
1985) — стандартизованное лог-правдоподобие ответов при итоговом θ. Сильно отрицательный l_z — паттерн «провалены
лёгкие, решены трудные», типичный для подсказки на отдельных заданиях. l_z < −2 — +1 балл, l_z < −3 — +2 балла
(person_fit_lz, bank_engine.finish → assess(lz=…)). При подозрении попытка не «аннулируется» и не уходит в повторный
тест: работодателю и кандидату рекомендуется 3-минутная устная защита (interview.service.defense_recommendation).

Баллы риска: ≥ 3 — низкая, 1–2 — средняя, 0 — высокая. Результат виден работодателю в карточке кандидата
и в объяснении подборки; в ранжирование не входит (ложное срабатывание не должно наказывать честного
кандидата — для этого флаг и причины, решение остаётся за человеком). Правила — чистые функции, покрыты
тестами (tests/test_day3a.py, tests/test_integrity_ig.py).

Кому что видно (решение владельца Р27 от 07.10: механизмы кандидату не раскрывать). Перед тестом кандидат видит
общее предупреждение и даёт согласие (IntegrityNotice, версия NOTICE_VERSION); после теста и в профиле — уровень
и общую причину (candidate_view: «поведение во время теста», «признаки использования подсказок»…), без названий
сигналов, порогов и ИИ-метки. Работодатель — подробные причины (summary_for_employer). Механика — жюри (проводник)
и docs/ANTIFRAUD.md, раздел 6. Проверка, что подробности не уходят кандидату и анониму, — tests/test_integrity_r27.py.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Callable

from app.core.fmt import ru_num

log = logging.getLogger("assessment.integrity")

LEVEL_TITLES = {"high": "высокая", "medium": "средняя", "low": "низкая"}
# Порог «быстро» (Ф3, 08.10): ожидаемое время семейства — как в модели времени банка (exp β = 0,45 · рекомендуемого
# времени, pool_from_specs), на уровне кандидата короче в e^(0,3·(θ − b)) раз (|θ − b| ≤ 2: Senior на лёгком задании —
# примерно вдвое быстрее); «быстро» — быстрее 12 % этого времени и половины времени беглого чтения текста задания.
EXPECTED_SHARE_OF_LIMIT = 0.45
SPEED_PER_LOGIT = 0.3
SPEED_CLIP = 2.0
FAST_SHARE_OF_EXPECTED = 0.12
FAST_SHARE_OF_READ = 0.5
# Беглое чтение: условие — 40 символов в секунду, код — 20; варианты ответа сравнивают, а не читают целиком — половина
READ_CPS, CODE_CPS, OPTION_WEIGHT = 40.0, 20.0, 0.5
# «Мгновенно» — быстрее пятой части времени беглого чтения (текст задания не прочитан), от 4 до 10 с
INSTANT_SHARE_OF_READ, INSTANT_MIN_S, INSTANT_MAX_S = 0.2, 4.0, 10.0
FAST_MIN_S = INSTANT_MIN_S
SOFT_FAST_NOTE = "стоит уточнить зондом"
MAX_SIGNAL = 10_000
BASE_KEYS = ("focus_lost", "hidden_ms", "paste", "paste_chars", "copy")
# Новые сигналы интерфейса (И9) — в словаре, только если клиент их прислал (старые клиенты и API не наказываются
# правилами, о которых не знали): полноэкранный режим и динамика набора развёрнутого ответа.
EXT_KEYS = ("fs_exit", "fs_out_ms", "fs_ms", "fs_na", "typed", "inserted", "dropped", "deleted", "keys", "ik_cv",
            "active_ms", "printscreen")  # printscreen — нажатия PrintScreen за задание (D3 п. 3)
PRINTSCREEN_TITLE = "Снимок экрана (PrintScreen)"
MS_KEYS = {"hidden_ms", "fs_out_ms", "fs_ms", "active_ms"}
MAX_KEYS = {"fs_na", "ik_cv"}  # при сложении шагов задания — максимум, а не сумма
FAST_TEXT_CPS = 8.0  # символов в секунду по часам сервера: ≈ 90 слов в минуту без единой паузы на чтение и мысль
FAST_TEXT_MIN = 200  # короче — не проверяем
TYPED_SHARE_MIN = 0.5  # меньше половины длинного ответа набрано с клавиатуры, и это не вставка — текст «появился»
EVEN_RHYTHM_CV = 25  # коэффициент вариации интервалов между нажатиями, ×100: у человека обычно 60–150
EVEN_RHYTHM_KEYS = 100
# Person-fit l_z (KF2): минимум дихотомических ответов и пороги баллов риска
LZ_MIN_ITEMS = 6
LZ_WARN, LZ_ALARM = -2.0, -3.0
LZ_TITLE = "Паттерн ответов не согласуется с уровнем"
LZ_REASON = (f"{LZ_TITLE} (индекс l_z < −2,0): ошибки на базовых заданиях при верных ответах на сложных")



def _n(k: int, one: str, few: str, many: str) -> str:
    """Число со словом в нужной форме: 1 задание, 2 задания, 5 заданий."""
    m10, m100 = k % 10, k % 100
    w = one if m10 == 1 and m100 != 11 else few if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else many
    return f"{k} {w}"

def person_fit_lz(responses: list[tuple[float, float, float]], theta: float) -> float | None:
    """Индекс согласованности ответов person-fit l_z (Drasgow, Levine & Williams, 1985) для 2PL — чистая функция.

    responses — [(a, b, x)], x — дихотомический ответ (0/1; дробный балл округляется по порогу 0,5), theta — оценка
    уровня. l_0 = Σ [x·ln P + (1 − x)·ln(1 − P)], E[l_0] = Σ [P·ln P + (1 − P)·ln(1 − P)],
    Var[l_0] = Σ P(1 − P)·ln²(P / (1 − P)), l_z = (l_0 − E[l_0]) / √Var[l_0]. Около 0 — паттерн согласован с уровнем,
    сильно отрицательный — «провалены лёгкие, решены трудные». None — меньше LZ_MIN_ITEMS ответов или нет дисперсии.
    """
    try:
        th = float(theta)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(th):
        return None
    rows = []
    for r in responses or []:
        try:
            a, b, x = float(r[0]), float(r[1]), float(r[-1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (math.isfinite(a) and math.isfinite(b) and math.isfinite(x)):
            continue
        rows.append((a, b, 1.0 if x >= 0.5 else 0.0))
    if len(rows) < LZ_MIN_ITEMS:
        return None
    l0 = e = var = 0.0
    for a, b, x in rows:
        p = 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, a * (th - b)))))
        p = min(1.0 - 1e-9, max(1e-9, p))
        lp, lq = math.log(p), math.log(1.0 - p)
        l0 += x * lp + (1.0 - x) * lq
        e += p * lp + (1.0 - p) * lq
        var += p * (1.0 - p) * (lp - lq) ** 2
    if var <= 1e-12:
        return None
    return round((l0 - e) / math.sqrt(var), 4)


def lz_points(lz: float | None) -> int:
    """Баллы риска по l_z: < −3 — 2, < −2 — 1, иначе 0."""
    if lz is None:
        return 0
    return 2 if lz < LZ_ALARM else 1 if lz < LZ_WARN else 0


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


def text_size(public: dict | None) -> tuple[int, int]:
    """(символов условия и вариантов с весом, символов кода) открытой части задания — для порога «быстро»."""
    pub = public or {}
    opts = pub.get("options") or []
    steps = pub.get("steps") or []
    text = len(pub.get("stem") or "") + sum(len(s.get("prompt") or "") for s in steps if isinstance(s, dict))
    text += OPTION_WEIGHT * sum(len(o.get("text") or "") + len(o.get("code") or "") for o in opts if isinstance(o, dict))
    return int(text), len(pub.get("code") or "")


def read_s(text_chars: float | None, code_chars: float | None) -> float | None:
    """Время беглого чтения задания, с (None — длина текста неизвестна)."""
    if text_chars is None and code_chars is None:
        return None
    return float(text_chars or 0) / READ_CPS + float(code_chars or 0) / CODE_CPS


def instant_threshold_s(text_chars: float | None = None, code_chars: float | None = None) -> float:
    r = read_s(text_chars, code_chars)
    return INSTANT_MIN_S if r is None else min(INSTANT_MAX_S, max(INSTANT_MIN_S, INSTANT_SHARE_OF_READ * r))


def expected_s(time_limit_s: float, theta: float | None = None, b: float | None = None) -> float:
    """Ожидаемое время ответа на задание семейства для кандидата уровня θ (b — трудность семейства)."""
    base = EXPECTED_SHARE_OF_LIMIT * float(time_limit_s)
    if theta is None or b is None:
        return base
    return base * math.exp(-SPEED_PER_LOGIT * max(-SPEED_CLIP, min(SPEED_CLIP, float(theta) - float(b))))


def fast_threshold_s(time_limit_s: float, *, text_chars: float | None = None, code_chars: float | None = None,
                     theta: float | None = None, b: float | None = None) -> float:
    """Порог «быстро»: быстрее доли ожидаемого времени семейства на уровне кандидата и доли беглого чтения текста,
    но не ниже порога «мгновенно». Без длины текста — только по ожидаемому времени."""
    by_expected = FAST_SHARE_OF_EXPECTED * expected_s(time_limit_s, theta, b)
    r = read_s(text_chars, code_chars)
    t = by_expected if r is None else min(by_expected, FAST_SHARE_OF_READ * r)
    return max(instant_threshold_s(text_chars, code_chars), t)


def is_fast(time_s: float | None, time_limit_s: float, *, text_chars: float | None = None,
            code_chars: float | None = None, theta: float | None = None, b: float | None = None) -> bool:
    if time_s is None:
        return False
    return float(time_s) < fast_threshold_s(time_limit_s, text_chars=text_chars, code_chars=code_chars, theta=theta, b=b)


def is_instant(time_s: float | None, text_chars: float | None = None, code_chars: float | None = None) -> bool:
    return time_s is not None and float(time_s) < instant_threshold_s(text_chars, code_chars)


def _fast(i: dict, theta: float | None) -> bool:
    return is_fast(i.get("time_s"), i["time_limit_s"], text_chars=i.get("text_chars"), code_chars=i.get("code_chars"),
                   theta=theta, b=i.get("b"))


def _instant(i: dict) -> bool:
    return is_instant(i.get("time_s"), i.get("text_chars"), i.get("code_chars"))


def assess(items: list[dict], preknowledge: dict | None = None, extra: dict | None = None, *,
           theta: float | None = None, soft_fast: bool = False, lz: float | None = None) -> dict:
    """items — завершённые задания сессии: {format, canary, time_s, time_limit_s, score (0..1|None), signals,
    injection, meta_claims, ai_mark_hit, fast_text, typing, text_chars, code_chars, b}; extra — сигналы сессии для
    внешних источников (SOURCES); theta — итоговая оценка уровня (для ожидаемого времени семейства); soft_fast —
    экспресс или демо-режим жюри: быстрые (не мгновенные) верные ответы без других сигналов — мягкая пометка без
    понижения достоверности; lz — индекс person-fit l_z по ответам сессии (person_fit_lz, KF2): < −2 — +1 балл,
    < −3 — +2 балла.

    Возвращает {level, title, points, reasons[], signals{...}, sources[]}.
    """
    pk = preknowledge or {}
    done = [i for i in items if i.get("time_s") is not None]
    scored = [i for i in done if not i.get("canary")]
    n = len(scored)
    reasons: list[tuple[int, str, str]] = []  # (баллы, текст для работодателя, вид причины — KIND_TITLES)

    fast_correct = [i for i in scored if _fast(i, theta) and (i.get("score") or 0) >= 0.5]
    instant_correct = [i for i in fast_correct if _instant(i)]
    fast_wrong = [i for i in scored if _fast(i, theta) and i.get("score") is not None and i["score"] < 0.5]
    canary_fast = [i for i in done if i.get("canary") and _fast(i, theta) and (i.get("score") or 0) >= 0.5]

    if pk.get("flagged"):
        reasons.append((3, "Детектор предзнания сработал: канарейки и время ответов похожи на знание ответов "
                           f"заранее (статистика {pk.get('combined', 0):.2f})"
                        + (f"; из оценки исключено ответов: {pk['excluded_answers']}" if pk.get("excluded_answers") else ""),
                        "assist"))
    if canary_fast:
        reasons.append((1, f"Канареечные задания (опубликованные варианты) решены аномально быстро: {len(canary_fast)}",
                        "assist"))
    if n:
        if len(fast_wrong) / n >= 0.3 and len(fast_wrong) >= 3:
            reasons.append((1, f"Много мгновенных неверных ответов ({len(fast_wrong)} из {n}) — похоже на угадывание",
                            "behavior"))

    lz_pts = lz_points(lz)
    if lz_pts:  # KF2: person-fit l_z — ответы не согласуются с уровнем (подсказка на отдельных заданиях)
        reasons.append((lz_pts, LZ_REASON, "assist"))

    with_sig = [i for i in done if i.get("signals") is not None]
    focus_items = [i for i in with_sig if (i["signals"].get("focus_lost") or 0) > 0]
    hidden_s = sum((i["signals"].get("hidden_ms") or 0) for i in with_sig) / 1000.0
    focus_total = sum((i["signals"].get("focus_lost") or 0) for i in with_sig)
    if len(focus_items) >= 5 or hidden_s >= 180:
        reasons.append((2, f"Уход со вкладки теста: {_n(len(focus_items), 'задание', 'задания', 'заданий')}, "
                           f"{_n(focus_total, 'раз', 'раза', 'раз')}, вне вкладки {ru_num(hidden_s / 60, 1)} мин", "behavior"))
    elif len(focus_items) >= 2 or hidden_s >= 30:
        reasons.append((1, f"Уход со вкладки теста: {_n(len(focus_items), 'задание', 'задания', 'заданий')}, "
                           f"{_n(focus_total, 'раз', 'раза', 'раз')}, вне вкладки {hidden_s:.0f} с", "behavior"))
    paste_items = [i for i in with_sig if (i["signals"].get("paste") or 0) > 0
                   and (i["signals"].get("paste_chars") or 0) >= 30]
    paste_chars = sum((i["signals"].get("paste_chars") or 0) for i in paste_items)
    if len(paste_items) >= 2:
        reasons.append((2, f"Вставка готового текста в ответ: {_n(len(paste_items), 'задание', 'задания', 'заданий')}, "
                           f"{_n(paste_chars, 'символ', 'символа', 'символов')}", "assist"))
    elif paste_items:
        reasons.append((1, f"Вставка готового текста в ответ: 1 задание, {_n(paste_chars, 'символ', 'символа', 'символов')}",
                        "assist"))
    inj = [i for i in done if i.get("injection")]
    if inj:  # развёрнутый ответ адресован модели-оценщику (grader.injection_signals) — оценивает эксперт
        reasons.append((2, "В развёрнутом ответе — инструкции для автоматического оценщика "
                           f"({_n(len(inj), 'задание', 'задания', 'заданий')}); ответ передан эксперту", "answer"))
    if done and len(with_sig) < 0.5 * len(done):
        reasons.append((1, "Интерфейс теста не прислал сигналы по большинству заданий — ответы отправлены "
                           "в обход интерфейса (через API)", "behavior"))

    ext_signals: dict = {}
    for name, fn in list(SOURCES):
        try:
            r, sig = fn(done, extra or {})
            r = [_reason(x, name) for x in r or []]
        except Exception:  # noqa: BLE001 — внешний источник не должен ломать итог теста
            log.exception("integrity source %s failed", name)
            continue
        reasons.extend(r)
        ext_signals.update(sig or {})

    soft = _fast_reasons(reasons, fast_correct, instant_correct, n, soft_fast)
    points = sum(p for p, _, _ in reasons)
    level = "low" if points >= 3 else "medium" if points >= 1 else "high"
    ordered = sorted(reasons, key=lambda x: -x[0])
    return {
        "level": level, "title": LEVEL_TITLES[level], "points": points,
        "reasons": [t for _, t, _ in ordered] or
                   ["Сигналов нарушений нет: фокус не терялся, вставок нет, время ответов обычное, канарейки в норме"],
        # вид каждой причины (KIND_TITLES) — для общей формулировки кандидату (candidate_view, Р27)
        "kinds": [k for _, _, k in ordered] or ["none"],
        "signals": {"items": len(done), "scored": n, "fast_correct": len(fast_correct), "fast_wrong": len(fast_wrong),
                    "instant_correct": len(instant_correct), "fast_soft": soft,
                    "canary_fast": len(canary_fast), "focus_lost_items": len(focus_items), "focus_lost_total": focus_total,
                    "hidden_s": round(hidden_s, 1), "paste_items": len(paste_items), "paste_chars": paste_chars,
                    "client_signals_items": len(with_sig), "preknowledge_flagged": bool(pk.get("flagged")),
                    "injection_items": len(inj), "lz": lz, "lz_flag": bool(lz_pts), **ext_signals},
        "sources": [n for n, _ in SOURCES],
    }


def _fast_reasons(reasons: list, fast_correct: list, instant_correct: list, n: int, soft_fast: bool) -> bool:
    """Быстрые верные ответы → причина (добавляется в reasons). Считается последней: мягкий режим (экспресс, жюри)
    действует, только если других сигналов нет. Возвращает True, если пометка мягкая (без баллов)."""
    if not n or not fast_correct:
        return False
    share = len(fast_correct) / n
    if soft_fast and not sum(p for p, _, _ in reasons):
        if len(instant_correct) >= 2:  # мгновенные — текст задания не прочитан: помечаются и в мягком режиме
            reasons.append((2 if len(instant_correct) / n >= 0.25 else 1,
                            f"Мгновенные верные ответы: {len(instant_correct)} из {n}", "assist"))
            return False
        if len(fast_correct) >= 2 or share >= 0.10:
            reasons.append((0, f"Быстрые верные ответы: {len(fast_correct)} из {n} — {SOFT_FAST_NOTE}", "none"))
            return True
        return False
    if share >= 0.25 and len(fast_correct) >= 2:
        reasons.append((2, f"Аномально быстрые верные ответы: {len(fast_correct)} из {n}", "assist"))
    elif len(fast_correct) >= 2 or share >= 0.10:
        reasons.append((1, f"Аномально быстрые верные ответы: {len(fast_correct)} из {n}", "assist"))
    return False


def summary_for_employer(integ: dict | None) -> dict | None:
    """То, что видит работодатель: уровень и подробные причины (без сырых сигналов). Кандидату — candidate_view."""
    if not integ:
        return None
    rs = list(integ.get("reasons") or [])  # по убыванию веса; сверх пяти — одной строкой, чтобы не терялось число
    more = [f"И ещё {_n(len(rs) - 5, 'причина', 'причины', 'причин')} меньшего веса"] if len(rs) > 5 else []
    return {"level": integ.get("level"), "title": integ.get("title") or LEVEL_TITLES.get(integ.get("level", ""), ""),
            "reasons": rs[:5] + more,
            **({"camera": integ["camera"]} if integ.get("camera") else {})}  # итог камеры по согласию (И16)


# ------------------------------------------------------------------ что видит кандидат (решение владельца Р27)
# Механизмы проверки кандидату не раскрываются: ни названий сигналов, ни порогов, ни ИИ-метки. Кандидат видит уровень
# достоверности и общую причину — вид причины (kinds), а подробности (summary_for_employer) — работодатель, жюри
# (проводник) и документация (docs/ANTIFRAUD.md, раздел 6).
NOTICE_VERSION = "2026-10-07"  # версия текста экрана перед тестом и согласия (IntegrityNotice в Assessment.tsx)
KIND_TITLES = {
    "behavior": "Поведение во время теста",
    "assist": "Признаки использования подсказок",
    "answer": "Содержание развёрнутого ответа",
    "camera": "Данные камеры во время теста",
}
CANDIDATE_HIGH = "Замечаний к самостоятельности выполнения нет"
CANDIDATE_NOTE = ("Оценку уровня и грейд пометка не меняет. Работодатель видит её с подробностями; решение по ней "
                  "принимает человек.")
# Результаты, сохранённые до появления kinds (стенд до 07.10): вид причины — по началу текста
_KIND_BY_PREFIX = (
    ("Детектор предзнания", "assist"), ("Канареечные задания", "assist"), ("Аномально быстрые верные", "assist"),
    ("Мгновенные верные", "assist"), ("Быстрые верные", "none"),
    ("Вставка готового текста", "assist"), ("В развёрнутом ответе — невидимая метка", "assist"),
    ("Развёрнутый ответ появился быстрее", "assist"), ("Развёрнутый ответ в основном не набран", "assist"),
    ("Слишком ровный ритм", "assist"), (PRINTSCREEN_TITLE, "behavior"), (LZ_TITLE, "assist"),
    ("В развёрнутом ответе — инструкции", "answer"),
    ("В развёрнутом ответе — утверждения", "answer"), ("Сигналов нарушений нет", "none"), ("И ещё ", "none"),
    ("нет лица в кадре", "camera"), ("в кадре несколько лиц", "camera"), ("камера ", "camera"), ("Камера", "camera"),
)


def _reason(r: tuple, source: str = "") -> tuple[int, str, str]:
    """Причина источника → (баллы, текст, вид). Источники без вида (пары) — вид по имени источника или «поведение»."""
    if len(r) >= 3 and r[2] in KIND_TITLES:
        return int(r[0]), str(r[1]), str(r[2])
    return int(r[0]), str(r[1]), source if source in KIND_TITLES else "behavior"


def reason_kind(text: str) -> str:
    t = (text or "").strip()
    for prefix, kind in _KIND_BY_PREFIX:
        if t.startswith(prefix):
            return kind
    return "behavior"


def _kinds(integ: dict) -> list[str]:
    texts, kinds = list(integ.get("reasons") or []), integ.get("kinds")
    return list(kinds) if isinstance(kinds, list) and len(kinds) == len(texts) else [reason_kind(t) for t in texts]


def candidate_view(integ: dict | None) -> dict | None:
    """То, что видит сам кандидат (после теста, в профиле, в PDF): уровень и общая причина, без технических деталей,
    порогов и названий сигналов."""
    if not integ:
        return None
    level = integ.get("level") if integ.get("level") in LEVEL_TITLES else "high"
    out = {"level": level, "title": LEVEL_TITLES[level]}
    if integ.get("camera"):  # итог камеры по согласию (И16) кандидат видит целиком — это его собственные данные
        out["camera"] = integ["camera"]
    if level == "high":
        return {**out, "reasons": [CANDIDATE_HIGH]}
    order: list[str] = []
    for k in _kinds(integ):  # по убыванию веса: первым — вид самой весомой причины
        if k in KIND_TITLES and k not in order:
            order.append(k)
    return {**out, "reasons": [KIND_TITLES[k] for k in order] or [KIND_TITLES["behavior"]], "note": CANDIDATE_NOTE}


JURY_NOTE = ("Демо-режим жюри: так причины видит работодатель. Кандидат вне демо-режима видит только уровень и общую "
             "причину — механику проверки кандидату не раскрываем.")


def jury_view(integ: dict | None) -> dict | None:
    """Я11 (С3-11): в демо-режиме жюри к итогу теста — подробные причины, как у работодателя (summary_for_employer):
    из уже собранных событий, без новых правил. Кандидату вне демо-режима не отдаётся (Р27, service.finish_session)."""
    emp = summary_for_employer(integ)
    if not emp or emp.get("level") not in ("medium", "low") or not emp.get("reasons"):
        return None
    return {"reasons": emp["reasons"], "note": JURY_NOTE}


def add_reasons(integ: dict, extra: list[tuple], *, kind: str = "camera", **attach: Any) -> dict:
    """Сигналы отдельных модулей (камера по согласию — app/modules/proctor, И16) в общую достоверность: баллы
    складываются, причины добавляются, уровень — по тем же порогам (≥ 3 — низкая, 1–2 — средняя). extra — пары
    (баллы, текст) или тройки (баллы, текст, вид); kind — вид для пар (по умолчанию «камера»). attach — сводки
    модулей для работодателя (camera=…). Как и сигналы интерфейса, только понижают достоверность."""
    out = {**integ, **attach}
    new = sorted((x for x in (_reason(r, kind) for r in extra or []) if x[0] > 0), key=lambda x: -x[0])
    if new:
        base = int(integ.get("points") or 0)
        points = base + sum(p for p, _, _ in new)
        level = "low" if points >= 3 else "medium" if points >= 1 else "high"
        out.update(points=points, level=level, title=LEVEL_TITLES[level],
                   reasons=(list(integ.get("reasons") or []) if base else []) + [t for _, t, _ in new],
                   kinds=(_kinds(integ) if base else []) + [k for _, _, k in new])
    return out


# ------------------------------------------------------------------ источники причин (точка расширения)
# Источник причин — функция (done, extra) → (reasons [(баллы, текст[, вид])], signals {счётчики}). Вид — ключ
# KIND_TITLES (общая причина для кандидата); без вида — по имени источника («camera») или «поведение». done — завершённые
# задания сессии (как в assess), extra — сигналы уровня сессии от внешних модулей (например, extra["camera"] —
# события прокторинга камерой, И16). Источник только добавляет причины: уровень считается по сумме баллов всех
# источников, как и раньше (≥ 3 — низкая, 1–2 — средняя). Ошибка источника не ломает расчёт — он пропускается.
ReasonSource = Callable[[list[dict], dict], tuple[list[tuple], dict]]
SOURCES: list[tuple[str, ReasonSource]] = []


def register_source(name: str, fn: ReasonSource) -> None:
    """Подключить внешний источник причин (повторная регистрация с тем же именем заменяет прежний)."""
    for k, (n, _) in enumerate(SOURCES):
        if n == name:
            SOURCES[k] = (name, fn)
            return
    SOURCES.append((name, fn))


def proctoring_source(done: list[dict], extra: dict) -> tuple[list[tuple[int, str, str]], dict]:
    """Лёгкий прокторинг без камеры (И9): полноэкранный режим, копирование, ИИ-метка, время набора, динамика
    набора, утверждения об оценке в ответе."""
    reasons: list[tuple[int, str, str]] = []
    with_sig = [i for i in done if i.get("signals") is not None]
    fs_items = [i for i in with_sig if "fs_ms" in i["signals"] or "fs_na" in i["signals"]]
    # Я11 (С3-5): задание, где режим недоступен (fs_na, телефон), — не «вне полноэкранного режима»: прежний клиент
    # присылал там всё время задания как fs_out_ms («Выход … 0 раз, вне его 5 мин» на iPhone)
    fs_avail = [i for i in fs_items if not i["signals"].get("fs_na")]
    fs_exits = sum((i["signals"].get("fs_exit") or 0) for i in fs_avail)
    fs_out_s = sum((i["signals"].get("fs_out_ms") or 0) for i in fs_avail) / 1000.0
    fs_never = bool(fs_items) and all((i["signals"].get("fs_ms") or 0) == 0 and not i["signals"].get("fs_na")
                                      for i in fs_items)
    if fs_never:
        reasons.append((1, "Тест пройден без полноэкранного режима, хотя браузер его поддерживает", "behavior"))
    elif fs_exits >= 6 or fs_out_s >= 300:
        reasons.append((2, f"Выход из полноэкранного режима: {_n(fs_exits, 'раз', 'раза', 'раз')}, "
                           f"вне его {fs_out_s / 60:.1f} мин", "behavior"))
    elif fs_exits >= 2 or fs_out_s >= 60:
        reasons.append((1, f"Выход из полноэкранного режима: {_n(fs_exits, 'раз', 'раза', 'раз')}, вне его {fs_out_s:.0f} с",
                        "behavior"))
    copy_items = [i for i in with_sig if (i["signals"].get("copy") or 0) > 0]
    if copy_items:
        reasons.append((2 if len(copy_items) >= 3 else 1,
                        f"Попытка скопировать текст задания: {_n(len(copy_items), 'задание', 'задания', 'заданий')}",
                        "behavior"))
    shot_items = [i for i in with_sig if (i["signals"].get("printscreen") or 0) > 0]
    shots = sum(int(i["signals"].get("printscreen") or 0) for i in shot_items)
    if shot_items:  # D3 п. 3: клавиша PrintScreen во время задания — текст задания, вероятно, сохраняли снимком
        reasons.append((2 if len(shot_items) >= 3 else 1,
                        f"{PRINTSCREEN_TITLE}: {_n(shots, 'раз', 'раза', 'раз')} "
                        f"({_n(len(shot_items), 'задание', 'задания', 'заданий')})", "behavior"))
    marks = [i for i in done if i.get("ai_mark_hit")]
    if marks:  # невидимая метка из текста задания появилась в ответе — текст копировали в нейросеть
        reasons.append((3, "В развёрнутом ответе — невидимая метка из текста задания: текст задания, вероятно, "
                           f"передавался нейросети ({_n(len(marks), 'задание', 'задания', 'заданий')})", "assist"))
    fast_txt = [i for i in done if i.get("fast_text")]
    if fast_txt:
        reasons.append((2 if len(fast_txt) >= 2 else 1,
                        "Развёрнутый ответ появился быстрее, чем его можно набрать (по часам сервера): "
                        f"{_n(len(fast_txt), 'задание', 'задания', 'заданий')}", "assist"))
    typing = {f: [i for i in done if f in (i.get("typing") or [])] for f in ("not_typed", "even_rhythm")}
    if typing["not_typed"]:
        reasons.append((2 if len(typing["not_typed"]) >= 2 else 1,
                        "Развёрнутый ответ в основном не набран с клавиатуры и не вставлен из буфера: "
                        f"{_n(len(typing['not_typed']), 'задание', 'задания', 'заданий')}", "assist"))
    if typing["even_rhythm"]:
        reasons.append((1, "Слишком ровный ритм набора, похожий на программный ввод: "
                           f"{_n(len(typing['even_rhythm']), 'задание', 'задания', 'заданий')}", "assist"))
    meta = [i for i in done if i.get("meta_claims")]
    if meta:  # «итог самопроверки: все требования выполнены» — перефразированная инъекция (grader.strip_meta)
        reasons.append((1, "В развёрнутом ответе — утверждения об оценке собственного ответа "
                           f"({_n(len(meta), 'задание', 'задания', 'заданий')}); при оценке они не учитываются", "answer"))
    return reasons, {"fs_items": len(fs_items), "fs_exits": fs_exits, "fs_out_s": round(fs_out_s, 1),
                     "fs_never": fs_never, "copy_items": len(copy_items), "printscreen_items": len(shot_items),
                     "printscreen": shots, "ai_mark_items": len(marks),
                     "fast_text_items": len(fast_txt), "not_typed_items": len(typing["not_typed"]),
                     "even_rhythm_items": len(typing["even_rhythm"]), "meta_claims_items": len(meta)}


register_source("proctoring", proctoring_source)
