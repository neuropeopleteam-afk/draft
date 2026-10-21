"""Объяснимость выдачи подбора для HR и нанимающего менеджера (критерий ТЗ 35 % — обоснованность и объяснимость).

Собирает структурированный блок ``explain`` для каждого кандидата в подборке и в карточке кандидата:
* ``headline`` — главная причина в одну строку без внутреннего жаргона (T0/T1/T2, IRT, θ);
* ``summary`` — связное резюме для HR на 1–2 предложения: почему кандидат на этом месте, чем подтверждён уровень;
* ``why_above_next`` — (P0) объяснение границы с соседом снизу («Почему №1 выше №2»): за счёт какого подтверждённого
  навыка, результата теста или достижения ФСП этот кандидат стоит выше следующего;
* ``offer_forecast`` — прогноз вероятности принятия приглашения (вилка против рыночного коридора категории,
  совпадение формата/города/переезда, покрытие стека, активность) с честной подписью;
* ``grade`` — статус грейда (подтверждён платформой / предварительно / самозаявлено), результат теста, давность
  подтверждения (ширина погрешности вместо снижения балла) и подсказка со шкалой;
* ``core`` — состояние основного языка или определяющего фреймворка роли;
* ``skills_tested`` — какие обязательные и желательные навыки подтверждены тестом или коротким заданием;
* ``skills_fsp`` — достижения, подтверждённые реестром ФСП (с пояснением, что командный результат подтверждает
  дисциплину и роль, а не каждый отдельный технологический тег);
* ``skills_probes`` — результаты коротких заданий работодателей;
* ``gaps`` — чего не хватает из обязательного стека и как это проверить (короткое задание на 15 минут);
* ``breakdown`` — вклад каждого фактора в итоговый балл соответствия из 100 (самоописание T0 = 0,0).
"""
from __future__ import annotations

import re
from typing import Any

from app.modules.catalog.seed_data import tag_title

WEIGHT_LABELS: dict[str, tuple[str, int]] = {
    "test": ("Сила результата теста на грейд", 45),
    "stack_required": ("Обязательные навыки (проверены тестом)", 35),
    "stack_desired": ("Желательные навыки (проверены тестом)", 5),
    "fsp": ("Достижения в реестре ФСП", 10),
    "probe": ("Короткие задания работодателей", 5),
}

GRADE_STATUS_TITLES: dict[str, str] = {
    "confirmed": "Подтверждён на платформе",
    "provisional": "Предварительно (у границы уровня)",
    "unconfirmed": "Самозаявлено (тест не пройден)",
}

RANKING_BASIS_RU = (
    "Категория и фильтр грейда строятся только по подтверждённому результату теста; место внутри категории "
    "определяют результат теста, подтверждённые заданиями навыки, достижения в реестре ФСП и короткие задания "
    "работодателей. Самозаявленные данные анкеты и резюме в расчёт балла и ярусов не входят (вес 0 %)."
)

RANKING_BASIS_V2_RU = (
    "Категория и фильтр грейда — только по результату теста. Стек вакансии — фильтр: показаны кандидаты, у которых "
    "обязательные навыки заявлены или подтверждены тестом (заявленное баллов не даёт). Место внутри категории — только "
    "тест и ФСП: сила результата теста и запас над порогом грейда, достижения ФСП, навыки вакансии, подтверждённые "
    "заданиями, короткие задания работодателей; минус — обязательные навыки, которые тест проверил и не подтвердил. "
    "Самоописание (заявленный стек, грейд, формат, город, вилка) в балл не входит."
)


def formula_v2(weights: dict[str, float] | None = None) -> dict[str, Any]:
    """Формула match-v2 для экрана: веса в процентах (сумма плюсов = 100), минусы отдельно."""
    from app.modules.matching import ltr

    w = weights or ltr.weights()
    plus = [{"key": k, "title": ltr.TITLES[k], "pct": round(w[k] * 100)} for k in ltr.POSITIVE if w.get(k, 0) > 0]
    minus = [{"key": k, "title": ltr.TITLES[k], "pct": round(-w[k] * 100)} for k in ltr.NEGATIVE if w.get(k, 0) < 0]
    meta = ltr.model()["meta"]
    return {"version": ltr.VERSION, "plus": plus, "minus": minus,
            "text": "Место в категории = " + " + ".join(f"{x['title'][:1].lower()}{x['title'][1:]} {x['pct']} %" for x in plus)
                    + "".join(f" − {x['title'][:1].lower()}{x['title'][1:]} {x['pct']} %" for x in minus),
            "trained_on": meta.get("trained_on_ru"), "source": meta.get("source")}


_PCT_RE = re.compile(r"(\d+)\s*%")


def _extract_pct(text: str | None) -> int | None:
    if not text:
        return None
    m = _PCT_RE.search(text)
    return int(m.group(1)) if m else None


def _clean_jargon(text: str | None) -> str:
    """Убирает служебные коды T0/T1/T2 и греческую θ из основного текста для HR."""
    if not text:
        return ""
    s = re.sub(r"\s*\(T[012]\)", "", text)
    s = re.sub(r",\s*θ\s*=\s*[^,.;)]+", "", s)
    s = re.sub(r"\bT1\b", "тест платформы", s)
    s = re.sub(r"\bT2\b", "реестр ФСП", s)
    s = re.sub(r"\bT0\b", "самоописание", s)
    return s.strip()


def _rub(v: int | float | None) -> str:
    if not v:
        return "—"
    return f"{int(round(v)):,}".replace(",", " ") + " ₽"


def compute_offer_forecast(
    card: dict[str, Any],
    req: dict[str, Any],
    comps: dict[str, Any],
    req_confirmed: int,
    req_total: int,
    *,
    accepted_count: int | None = None,
    invited_count: int | None = None,
) -> dict[str, Any]:
    """Оценка факторов принятия приглашения кандидатом.

    Без накопленной статистики реальных принятий (invited_count >= 5) процент не выдумывается
    (возвращается ``status = 'insufficient_data'``, ``probability = None``, ``pct = None``),
    а работодателю показываются только объективные факторы совпадения словами.
    """
    market = card.get("market_range") or {}
    m_lo = market.get("from")
    m_hi = market.get("to")
    m_med = market.get("median") or ((m_lo + m_hi) // 2 if m_lo and m_hi else None)

    s_from = req.get("salary_from")
    s_to = req.get("salary_to") or s_from
    is_net = bool(req.get("salary_net"))
    offer_net = round((s_to or 0) * (1.0 if is_net else 0.87)) if s_to else None

    factors: list[str] = []
    positive_signals = 0
    negative_signals = 0

    # 1. Вилка против рыночных ожиданий категории
    if offer_net and m_med:
        if m_hi and offer_net >= m_hi:
            positive_signals += 2
            factors.append(f"Верх вилки ({_rub(offer_net)} на руки) на уровне верхнего квартиля рынка категории ({_rub(m_hi)})")
        elif offer_net >= m_med:
            positive_signals += 1
            factors.append(f"Вилка ({_rub(offer_net)} на руки) не ниже медианы рынка категории ({_rub(m_med)})")
        elif m_lo and offer_net >= m_lo:
            factors.append(f"Вилка в нижней половине рынка категории ({_rub(m_lo)} – {_rub(m_hi)} на руки)")
        else:
            negative_signals += 2
            factors.append(f"Верх вилки ({_rub(offer_net)} на руки) ниже рыночного диапазона категории (от {_rub(m_lo)} на руки)")
    else:
        factors.append("Зарплатная вилка в потребности не указана (ориентир — рынок категории)")

    # 2. Совпадение формата работы и локации (с различением прямого совпадения города и готовности к переезду)
    cand_fmt = card.get("work_format")
    cand_city = (card.get("city") or "").strip()
    reloc = bool(card.get("relocation"))
    req_fmts = req.get("work_formats") or ([req["work_format"]] if req.get("work_format") else [])
    req_city = (req.get("city") or "").strip()

    if cand_fmt == "remote" and ("remote" in req_fmts or not req_fmts):
        positive_signals += 1
        factors.append("Удалённый формат работы полностью совпадает")
    elif req_city and any(f in ("office", "hybrid") for f in req_fmts):
        if cand_city and cand_city.lower() == req_city.lower():
            positive_signals += 1
            factors.append(f"Город присутствия совпадает ({cand_city})")
        elif reloc:
            factors.append(f"Кандидат в г. {cand_city or 'другом регионе'}, готов к переезду в {req_city} (смягчает несовпадение города, но требует времени на релокацию)")
        else:
            negative_signals += 2
            factors.append(f"Требуется присутствие в г. {req_city}, у кандидата указан {cand_city or 'другой город'} без переезда")
    elif not req_fmts or cand_fmt in req_fmts or cand_fmt == "any":
        positive_signals += 1
        factors.append("Формат работы подходит кандидату")

    # 3. Соответствие стека
    if req_total > 0:
        if req_confirmed == req_total:
            positive_signals += 1
            factors.append(f"Подтверждены все обязательные навыки роли ({req_confirmed} из {req_total})")
        elif req_confirmed > 0:
            factors.append(f"Подтверждено {req_confirmed} из {req_total} обязательных навыков")

    if negative_signals >= 2:
        level = "low"
        qual_title = "Есть расхождения по условиям (оценка по факторам)"
    elif positive_signals >= 2 and negative_signals == 0:
        level = "high"
        qual_title = "Условия совпадают с рынком и профилем (оценка по факторам)"
    else:
        level = "medium"
        qual_title = "Частичное совпадение условий (оценка по факторам)"

    if invited_count is not None and invited_count >= 5 and accepted_count is not None:
        prob = round(max(0.0, min(1.0, accepted_count / invited_count)), 2)
        pct = round(prob * 100)
        return {
            "status": "measured",
            "probability": prob,
            "pct": pct,
            "level": level,
            "title": f"{pct} % (по {invited_count} приглашениям)",
            "factors": factors[:3],
            "note": f"Доля принятых приглашений по фактическим данным ({accepted_count} из {invited_count}).",
        }

    return {
        "status": "insufficient_data",
        "probability": None,
        "pct": None,
        "level": level,
        "title": qual_title,
        "factors": factors[:3],
        "note": "Мало данных о реальных принятиях приглашений для расчёта процента — показаны факторы совпадения вилки, формата и стека.",
    }


def build_why_above_next(
    curr: dict[str, Any],
    nxt: dict[str, Any] | None,
    req: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """«Почему №k выше №(k+1)»: лаконичное объяснение границы с соседом снизу в подборке (P0)."""
    if not nxt:
        return None
    req = req or {}
    c_ref = curr.get("ref") or "Текущий"
    n_ref = nxt.get("ref") or "Следующий"
    c_score = float(curr.get("score") or 0.0)
    n_score = float(nxt.get("score") or 0.0)
    diff100 = round((c_score - n_score) * 100, 1)

    reasons: list[dict[str, str]] = []

    # 1. Статус подтверждения грейда
    c_gs = curr.get("grade_status") or "confirmed"
    n_gs = nxt.get("grade_status") or "confirmed"
    if c_gs != "unconfirmed" and n_gs == "unconfirmed":
        reasons.append({
            "kind": "tier",
            "text": f"грейд подтверждён тестом на платформе (у {n_ref} уровень только самозаявлен)",
        })
    c_contrib = (curr.get("components") or {}).get("contrib")
    n_contrib = (nxt.get("components") or {}).get("contrib")
    if c_contrib is not None and n_contrib is not None:
        return _why_above_v2(curr, nxt, c_ref, n_ref, diff100, reasons, c_contrib, n_contrib)

    # 2. Ядро роли (основной язык / фреймворк)
    c_core = curr.get("core") or {}
    n_core = nxt.get("core") or {}
    if c_core.get("state") in ("confirmed", "declared") and n_core.get("state") == "absent":
        reasons.append({
            "kind": "core",
            "text": f"подтверждено основное ядро роли — {c_core.get('title')} (у {n_ref} смежный стек)",
        })

    # 3. Обязательные навыки (какие именно подтверждены у curr, но отсутствуют у nxt)
    c_exp = curr.get("explain") or build_explain_from_result(curr, req, weights)
    n_exp = nxt.get("explain") or build_explain_from_result(nxt, req, weights)
    c_req_skills = {s["title"]: s.get("score_pct") for s in (c_exp.get("skills_tested") or []) if s.get("required")}
    n_req_skills = {s["title"]: s.get("score_pct") for s in (n_exp.get("skills_tested") or []) if s.get("required")}
    only_in_curr = [t for t in c_req_skills if t not in n_req_skills]
    if only_in_curr:
        names = ", ".join(only_in_curr[:3])
        reasons.append({
            "kind": "skill",
            "text": f"подтверждён обязательный навык {names} ({c_exp.get('required_confirmed', 0)} из {c_exp.get('required_total', 0)} против {n_exp.get('required_confirmed', 0)} у {n_ref})",
        })
    else:
        # Проверим, по какому общему навыку у curr заметно выше процент
        better_skill = None
        for t, c_pct in c_req_skills.items():
            n_pct = n_req_skills.get(t)
            if c_pct is not None and n_pct is not None and c_pct - n_pct >= 10:
                better_skill = (t, c_pct, n_pct)
                break
        if better_skill:
            reasons.append({
                "kind": "skill",
                "text": f"выше результат по обязательному навыку {better_skill[0]} ({better_skill[1]} % против {better_skill[2]} %)",
            })

    # 4. Вклад компонент балла (тест, ФСП, короткие задания)
    c_comps = curr.get("components") or {}
    n_comps = nxt.get("components") or {}
    w_map = dict(weights or {"test": 0.45, "stack_required": 0.35, "stack_desired": 0.05, "fsp": 0.10, "probe": 0.05})
    if not req.get("stack_required"):
        w_map["test"] = w_map.get("test", 0.45) + w_map.get("stack_required", 0.35)

    dt = round(w_map.get("test", 0.45) * (float(c_comps.get("test") or 0) - float(n_comps.get("test") or 0)) * 100, 1)
    if dt >= 0.4:
        reasons.append({
            "kind": "test",
            "text": f"более высокий результат адаптивного теста (+{str(dt).replace('.', ',')} балла)",
        })

    df = round(w_map.get("fsp", 0.10) * (float(c_comps.get("fsp") or 0) - float(n_comps.get("fsp") or 0)) * 100, 1)
    if df >= 0.3:
        reasons.append({
            "kind": "fsp",
            "text": f"подтверждённые достижения в реестре ФСП (+{str(df).replace('.', ',')} балла)",
        })

    dp = round(w_map.get("probe", 0.05) * (float(c_comps.get("probe") or 0) - float(n_comps.get("probe") or 0)) * 100, 1)
    if dp >= 0.3:
        reasons.append({
            "kind": "probe",
            "text": f"выполненное короткое задание работодателя (+{str(dp).replace('.', ',')} балла)",
        })

    if not reasons:
        if diff100 > 0:
            reasons.append({
                "kind": "score",
                "text": f"более высокий суммарный балл подтверждённых навыков (+{str(diff100).replace('.', ',')} из 100)",
            })
        else:
            reasons.append({
                "kind": "tie",
                "text": "равный балл по обязательным требованиям, выше общий рейтинг подтверждённого профиля в категории",
            })

    short_list = "; ".join(r["text"] for r in reasons[:3])
    headline = f"Выше следующего кандидата ({n_ref}) за счёт: {short_list}"
    return {
        "current_ref": c_ref,
        "next_ref": n_ref,
        "score_diff100": diff100,
        "headline": headline,
        "reasons": reasons[:3],
    }


V2_WHY = {
    "test": "сильнее результат теста на грейд",
    "margin": "больше запас над порогом грейда по шкале теста",
    "fsp": "достижения ФСП (реестр и официальные протоколы)",
    "required": "больше обязательных навыков вакансии подтверждено тестом",
    "desired": "подтверждены желательные навыки вакансии",
    "probe": "выполнено короткое задание работодателя",
}


def _why_above_v2(curr: dict, nxt: dict, c_ref: str, n_ref: str, diff100: float, reasons: list,
                  c_contrib: dict, n_contrib: dict) -> dict[str, Any]:
    """match-v2: «почему выше соседа» — точная разность вкладов признаков линейной модели (в баллах из 100)."""
    if (curr.get("category_id") and nxt.get("category_id") and curr.get("category_id") != nxt.get("category_id")
            and (curr.get("card") or {}).get("above") is not True and (nxt.get("card") or {}).get("above") is True):
        reasons.append({"kind": "tier", "text": f"точный уровень вакансии (у {n_ref} — ступенью выше)"})
    diffs = []
    for k, txt in V2_WHY.items():
        d = round(float(c_contrib.get(k) or 0) - float(n_contrib.get(k) or 0), 1)
        if d >= 0.3:
            diffs.append((d, {"kind": k, "text": f"{txt} (+{str(d).replace('.', ',')} балла)", "points100": d}))
    df = round(float(c_contrib.get("failed") or 0) - float(n_contrib.get("failed") or 0), 1)
    if df >= 0.3:
        diffs.append((df, {"kind": "failed", "points100": df,
                           "text": f"у {n_ref} тест проверил и не подтвердил обязательный навык "
                                   f"(−{str(df).replace('.', ',')} балла у него)"}))
    dpv = round(float(c_contrib.get("provisional") or 0) - float(n_contrib.get("provisional") or 0), 1)
    if dpv >= 0.3:
        diffs.append((dpv, {"kind": "provisional", "points100": dpv,
                            "text": f"грейд подтверждён окончательно (у {n_ref} — предварительно, "
                                    f"−{str(dpv).replace('.', ',')} балла)"}))
    reasons += [r for _, r in sorted(diffs, key=lambda x: -x[0])]
    if not reasons:
        reasons.append({"kind": "tie", "text": "равный балл теста и ФСП, выше общий рейтинг подтверждённого профиля"
                                               if diff100 <= 0 else
                                               f"выше суммарный балл теста и ФСП (+{str(diff100).replace('.', ',')} из 100)"})
    short_list = "; ".join(r["text"] for r in reasons[:3])
    return {"current_ref": c_ref, "next_ref": n_ref, "score_diff100": diff100,
            "headline": f"Выше следующего кандидата ({n_ref}) за счёт: {short_list}", "reasons": reasons[:3],
            "exact": True}


def annotate_selection_neighbors(
    results: list[dict[str, Any]],
    req: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Добавляет каждому элементу ``results[i]`` и ``results[i]['explain']`` блок ``why_above_next``."""
    for i, curr in enumerate(results):
        if not curr.get("explain"):
            curr["explain"] = build_explain_from_result(curr, req, weights)
        nxt = results[i + 1] if i + 1 < len(results) else None
        why = build_why_above_next(curr, nxt, req, weights)
        curr["why_above_next"] = why
        curr["explain"]["why_above_next"] = why
    return results


def compute_salary_calibration(
    scored_count_confirmed: int,
    req: dict[str, Any] | None,
    market_range: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Калибровка зарплатной вилки потребности строго по фактическому числу подтверждённых кандидатов в пуле (без выдуманных констант)."""
    if not req or not market_range:
        return None
    m_lo = market_range.get("from")
    m_hi = market_range.get("to")
    m_med = market_range.get("median") or ((m_lo + m_hi) // 2 if m_lo and m_hi else None)
    if not m_lo or not m_hi:
        return None

    actual_confirmed = max(0, int(scored_count_confirmed or 0))
    s_from = req.get("salary_from")
    s_to = req.get("salary_to") or s_from
    is_net = bool(req.get("salary_net"))
    if not s_to:
        return {
            "status": "not_set",
            "market_from": m_lo,
            "market_median": m_med,
            "market_to": m_hi,
            "recommended_to": m_med or m_hi,
            "confirmed_in_pool": actual_confirmed,
            "additional_candidates": 0,
            "text": (
                f"Рыночный ориентир категории на руки: {_rub(m_lo)} – {_rub(m_hi)} (медиана {_rub(m_med)}). "
                f"В подборке сейчас подтверждённых кандидатов: {actual_confirmed}."
            ),
        }

    top_net = round(s_to * (1.0 if is_net else 0.87))
    if actual_confirmed == 0:
        return {
            "status": "below_market" if top_net < m_lo else "below_median" if (m_med and top_net < m_med) else "competitive",
            "current_top": s_to,
            "current_top_net": top_net,
            "recommended_to": (m_med or m_lo) if is_net else int(round((m_med or m_lo) / 0.87, -3)),
            "confirmed_in_pool": 0,
            "additional_candidates": 0,
            "text": f"В выбранной категории сейчас 0 подтверждённых кандидатов (рыночный коридор категории: {_rub(m_lo)} – {_rub(m_hi)} на руки).",
        }

    if top_net < m_lo:
        target_net = m_med or m_lo
        target_offer = target_net if is_net else int(round(target_net / 0.87, -3))
        return {
            "status": "below_market",
            "current_top": s_to,
            "current_top_net": top_net,
            "recommended_to": target_offer,
            "recommended_net": target_net,
            "confirmed_in_pool": actual_confirmed,
            "additional_candidates": actual_confirmed,
            "text": (
                f"Верх вилки ({_rub(top_net)} на руки) ниже нижней границы рынка категории ({_rub(m_lo)} на руки). "
                f"Если поднять вилку до {_rub(target_offer)} — все {actual_confirmed} подтверждённых кандидатов подборки войдут в рыночный коридор категории."
            ),
        }
    if m_med and top_net < m_med:
        target_net = m_med
        target_offer = target_net if is_net else int(round(target_net / 0.87, -3))
        return {
            "status": "below_median",
            "current_top": s_to,
            "current_top_net": top_net,
            "recommended_to": target_offer,
            "recommended_net": target_net,
            "confirmed_in_pool": actual_confirmed,
            "additional_candidates": 0,
            "text": (
                f"Верх вилки ({_rub(top_net)} на руки) в нижней половине рынка категории ({_rub(m_lo)} – {_rub(m_hi)}, медиана {_rub(m_med)}). "
                f"В подборке {actual_confirmed} подтверждённых кандидатов; повышение до медианы ({_rub(target_offer)}) укрепит конкурентность предложения."
            ),
        }
    return {
        "status": "competitive",
        "current_top": s_to,
        "current_top_net": top_net,
        "recommended_to": s_to,
        "confirmed_in_pool": actual_confirmed,
        "additional_candidates": 0,
        "text": f"Ваша вилка ({_rub(top_net)} на руки) находится внутри или выше медианы рынка категории ({_rub(m_lo)} – {_rub(m_hi)} на руки; в подборке {actual_confirmed} подтверждённых кандидатов).",
    }


def build_explain_from_result(
    item: dict[str, Any],
    req: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Собирает блок ``explain`` из элемента ``results[i]`` версии подборки или карточки с полем ``match``."""
    req = req or {}
    card = item.get("card") or item
    score = float(item.get("score") or (item.get("match") or {}).get("score") or 0.0)
    score100 = round(score * 100)
    rank = item.get("rank") or item.get("rank_in_selection")
    comps = item.get("components") or (item.get("match") or {}).get("components") or {}
    reasons = item.get("reasons") or (item.get("match") or {}).get("reasons") or []
    must = item.get("must") or (item.get("match") or {}).get("must") or {}
    core = item.get("core") or (item.get("match") or {}).get("core")
    grade_status = (
        item.get("grade_status")
        or comps.get("grade_status")
        or (card.get("status") or {}).get("status")
        or ("provisional" if (card.get("category") or {}).get("preliminary") else "confirmed")
    )

    test_info = card.get("test") or {}
    fsp_info = card.get("fsp") or {}
    cat_title = (
        (card.get("category") or {}).get("title")
        or (card.get("claimed") or {}).get("title")
        or "Категория не присвоена"
    )

    # 1. Навыки из reasons + card.skills_confirmed
    confirmed_scores: dict[str, int] = {}
    for sk in card.get("skills_confirmed") or []:
        if sk.get("title") and sk.get("score") is not None:
            confirmed_scores[str(sk["title"]).lower()] = round(float(sk["score"]) * 100)

    skills_tested: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    for r in reasons:
        req_str = str(r.get("requirement") or "")
        if not (req_str.startswith("Обязательно: ") or req_str.startswith("Желательно: ")):
            continue
        zone, skill_name = req_str.split(": ", 1)
        is_req = zone == "Обязательно"
        st = r.get("status")
        via = r.get("implied_by") or r.get("implied_via")
        via_title = tag_title(via) if via else None
        reason_text = str(r.get("text") or "")
        pct_val = confirmed_scores.get(skill_name.lower()) or _extract_pct(reason_text)

        if st == "confirmed" or via_title:
            source_label = (
                f"Подтверждено косвенно через {via_title}"
                if via_title
                else "Подтверждено заданием работодателя"
                if "заданием работодателя" in reason_text.lower()
                else "Подтверждено заданиями теста"
            )
            skills_tested.append({
                "title": skill_name,
                "required": is_req,
                "score_pct": pct_val,
                "via": via_title,
                "source": source_label,
                "text": _clean_jargon(reason_text),
            })
        else:
            if st == "mismatch":
                state_code = "low"
                state_title = "Проверялся на платформе, порог пока не набран"
            elif st == "declared":
                state_code = "declared"
                state_title = "Указан кандидатом в анкете, тестом ещё не проверялся"
            else:
                state_code = "untested"
                state_title = "В тесте кандидата этот навык не проверялся"
            gaps.append({
                "title": skill_name,
                "required": is_req,
                "state": state_code,
                "state_title": state_title,
                "text": _clean_jargon(reason_text),
                "action": f"Проверить коротким заданием по навыку «{skill_name}» (10–15 мин)",
            })

    if not skills_tested and card.get("skills_confirmed"):
        for sk in (card.get("skills_confirmed") or [])[:5]:
            skills_tested.append({
                "title": sk.get("title") or sk.get("tag"),
                "required": False,
                "score_pct": round(float(sk.get("score") or 0) * 100),
                "via": None,
                "source": "Подтверждено заданиями теста",
                "text": f"Подтверждено на платформе ({round(float(sk.get('score') or 0) * 100)} %)",
            })

    # 2. Достижения ФСП (реестр) с честным разграничением командного/индивидуального вклада и подсветкой протокола
    from app.modules.fsp.relevance import protocol_highlight

    skills_fsp: list[dict[str, Any]] = []
    # fsp-v3: лучший результат — из причины ранжирования (статус подтверждения и цитата официального протокола)
    fr = next((r for r in reasons if r.get("requirement") == "Достижения ФСП" and r.get("fsp_status")), None)
    if fr and not fsp_info.get("hidden"):
        st = fr["fsp_status"]
        pr = fr.get("protocol") or None
        skills_fsp.append({
            "text": fr.get("text") or "Достижение ФСП", "status": st, "protocol": pr,
            "relevance": None, "focus_title": None, "highlighted_tags": [],
            "source": ("Официальный протокол ФСП, подтверждено ФСП" if st == "verified" and pr else
                       "Найдено в официальном протоколе ФСП, ждёт подтверждения ФСП — учитывается с весом 0,5"
                       if st == "pending_fsp" else
                       "Подтверждено реестром ФСП") + " (подтверждает соревновательную дисциплину и результат; "
                      "конкретный технологический стек проверяется индивидуальным тестом)",
        })
    if not fsp_info.get("hidden"):
        seen_txt = (fr or {}).get("text") or ""
        for ach in [a for a in (fsp_info.get("achievements") or []) if not (a.get("text") and a["text"] in seen_txt)
                    ][:4 - len(skills_fsp)]:
            disc = ach.get("discipline")
            hl = protocol_highlight(disc, req.get("direction")) if disc else {}
            skills_fsp.append({
                "text": ach.get("text") or "Достижение ФСП",
                "relevance": (ach.get("relevance") or {}).get("title") or hl.get("title") or None,
                "focus_title": hl.get("focus_title"),
                "highlighted_tags": hl.get("tags") or [],
                "source": "Подтверждено реестром ФСП (подтверждает соревновательную дисциплину и опыт; конкретный технологический стек проверяется индивидуальным тестом)",
            })

    # 3. Короткие задания работодателей
    skills_probes: list[dict[str, Any]] = []
    for pr in (card.get("probes") or [])[:3]:
        skills_probes.append({
            "title": pr.get("title") or "Задание работодателя",
            "verdict": pr.get("verdict") or "Проверено",
        })

    # 4. Статус грейда, теста и давности подтверждения (P2: старое подтверждение расширяет погрешность, не штрафуя балл)
    fresh = card.get("freshness") or {}
    fresh_note = fresh.get("text")
    if test_info:
        correct = test_info.get("correct")
        answered = test_info.get("answered")
        integ = (test_info.get("integrity") or {}).get("title") or "высокая"
        grade_text = (
            f"Решено {correct} из {answered} заданий · достоверность: {integ.lower()}"
            if correct is not None and answered is not None
            else "Уровень проверен адаптивным тестом"
        )
        if fresh_note:
            grade_text += f" · {fresh_note} (давность учитывается в ширине интервала точности, балл не занижается)"
        theta = test_info.get("theta")
        se = test_info.get("se")
        grade_hint = (
            f"Оценка по шкале адаптивного теста: {theta:+.2f} ± {se:.2f}".replace(".", ",")
            if isinstance(theta, (int, float)) and isinstance(se, (int, float))
            else None
        )
    else:
        grade_text = "Тест по направлению ещё не пройден — уровень указан со слов кандидата (в балл не входит)"
        grade_hint = None

    req_total = int(must.get("required_total") or sum(1 for s in skills_tested + gaps if s["required"]))
    req_missing = int(must.get("missing_total") if must.get("missing_total") is not None else sum(1 for g in gaps if g["required"]))
    req_confirmed = max(0, req_total - req_missing)

    # 5. Заголовок (headline) и связное резюме (summary)
    if grade_status == "confirmed":
        head_grade = f"Грейд {cat_title} подтверждён тестом"
    elif grade_status == "provisional":
        head_grade = f"Категория {cat_title} присвоена предварительно"
    else:
        head_grade = f"Уровень заявлен кандидатом ({cat_title}), тест не пройден"

    if req_total > 0:
        if req_missing == 0:
            head_stack = f"все обязательные навыки подтверждены ({req_confirmed} из {req_total})"
            tier_label = "Полное покрытие обязательных навыков"
        else:
            head_stack = f"подтверждено {req_confirmed} из {req_total} обязательных навыков"
            tier_label = f"Не хватает подтверждения {req_missing} обязат. навыка" if req_missing == 1 else f"Не хватает подтверждения {req_missing} обязат. навыков"
    else:
        head_stack = f"подтверждено навыков: {len(skills_tested)}" if skills_tested else "оценка по профилю теста"
        tier_label = "Ранжирование по силе теста и достижениям"

    headline = f"{head_grade} · {head_stack}"

    summary_parts: list[str] = []
    if rank:
        summary_parts.append(f"Место #{rank} в подборке (соответствие {score100} из 100).")
    else:
        summary_parts.append(f"Итоговое соответствие требованиям — {score100} из 100.")
    if skills_tested:
        top_names = ", ".join(
            f"{s['title']}" + (f" ({s['score_pct']} %)" if s.get("score_pct") else "")
            for s in skills_tested[:4]
        )
        summary_parts.append(f"Проверено на платформе: {top_names}.")
    if skills_fsp:
        summary_parts.append(f"Реестр ФСП: {skills_fsp[0]['text']}.")
    if gaps:
        gap_names = ", ".join(g["title"] for g in gaps if g["required"])[:120]
        if gap_names:
            summary_parts.append(f"Что уточнить коротким заданием: {gap_names}.")

    # 6. Разложение балла (breakdown)
    w_map = dict(
        weights
        or {
            "test": 0.45,
            "stack_required": 0.35,
            "stack_desired": 0.05,
            "fsp": 0.10,
            "probe": 0.05,
        }
    )
    if req_total == 0 and not req.get("stack_required"):
        w_map["test"] = round(w_map.get("test", 0.45) + w_map.get("stack_required", 0.35), 2)
        w_map["stack_required"] = 0.0

    breakdown: list[dict[str, Any]] = []
    if comps.get("contrib") is not None:  # match-v2: вклады линейной модели (тест и ФСП), минусы — отрицательные
        from app.modules.matching import ltr

        w2 = weights if (weights and "margin" in weights) else ltr.weights()
        raw = {**{k: comps.get(k) for k in ltr.FEATURES}, "provisional": comps.get("provisional_flag")}
        for key in ltr.FEATURES:
            if not w2.get(key):
                continue
            breakdown.append({"key": key, "label": ltr.TITLES[key], "weight_pct": round(w2[key] * 100),
                              "raw_pct": round(float(raw.get(key) or 0.0) * 100),
                              "points100": float(comps["contrib"].get(key) or 0.0), "minus": key in ltr.NEGATIVE})
    for key in (() if breakdown else ("test", "stack_required", "stack_desired", "fsp", "probe")):
        label, default_pct = WEIGHT_LABELS[key]
        w = float(w_map.get(key, default_pct / 100.0))
        val = float(comps.get(key) or 0.0)
        pts = round(w * val * 100, 1)
        breakdown.append({
            "key": key,
            "label": label,
            "weight_pct": round(w * 100),
            "raw_pct": round(val * 100),
            "points100": pts,
        })

    core_summary = None
    if core and core.get("title"):
        core_summary = {
            "label": core.get("label") or "Основной навык роли",
            "title": core.get("title"),
            "state": core.get("state"),
            "via": core.get("via"),
            "headline": core.get("headline"),
            "text": _clean_jargon(core.get("text")),
        }

    offer_forecast = compute_offer_forecast(card, req, comps, req_confirmed, req_total)

    return {
        "headline": headline,
        "summary": " ".join(summary_parts),
        "score100": score100,
        "rank": rank,
        "tier_label": tier_label,
        "required_confirmed": req_confirmed,
        "required_total": req_total,
        "t0_in_score": False,
        "ranking_basis_ru": RANKING_BASIS_V2_RU if comps.get("contrib") is not None else RANKING_BASIS_RU,
        "grade": {
            "title": cat_title,
            "status": grade_status,
            "status_title": GRADE_STATUS_TITLES.get(grade_status, "Проверено"),
            "text": grade_text,
            "hint": grade_hint,
        },
        "core": core_summary,
        "skills_tested": skills_tested,
        "skills_fsp": skills_fsp,
        "skills_probes": skills_probes,
        "gaps": gaps,
        "breakdown": breakdown,
        "offer_forecast": offer_forecast,
        "why_above_next": item.get("why_above_next"),
    }
