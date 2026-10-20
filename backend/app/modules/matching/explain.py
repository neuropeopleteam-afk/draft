"""Объяснимость выдачи подбора для HR и нанимающего менеджера (критерий ТЗ 35 % — обоснованность и объяснимость).

Собирает структурированный блок ``explain`` для каждого кандидата в подборке и в карточке кандидата:
* ``headline`` — главная причина в одну строку без внутреннего жаргона (T0/T1/T2, IRT, θ);
* ``summary`` — связное резюме для HR на 1–2 предложения: почему кандидат на этом месте, чем подтверждён уровень;
* ``grade`` — статус грейда (подтверждён платформой / предварительно / самозаявлено), результат теста и подсказка со шкалой;
* ``core`` — состояние основного языка или определяющего фреймворка роли;
* ``skills_tested`` — какие обязательные и желательные навыки подтверждены тестом или коротким заданием (включая косвенное подтверждение через фреймворк);
* ``skills_fsp`` — достижения, подтверждённые реестром Федерации спортивного программирования;
* ``skills_probes`` — результаты коротких заданий работодателей;
* ``gaps`` — чего не хватает из обязательного стека и как это проверить (короткое задание на 15 минут);
* ``breakdown`` — вклад каждого фактора в итоговый балл соответствия из 100.

Работает как по живому ``Bundle`` во время расчёта подборки, так и по уже сохранённому элементу ``results[i]``
из ``SelectionVersion`` (обратная совместимость со всеми сохранёнными версиями подборок).
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

_PCT_RE = re.compile(r"(\d+)\s*%")


def _extract_pct(text: str | None) -> int | None:
    if not text:
        return None
    m = _PCT_RE.search(text)
    return int(m.group(1)) if m else None


def _clean_jargon(text: str | None) -> str:
    """Убирает служебные коды T0/T1/T2 и греческую θ из основного текста для HR (оставляя понятные русские формулировки)."""
    if not text:
        return ""
    s = re.sub(r"\s*\(T[012]\)", "", text)
    s = re.sub(r",\s*θ\s*=\s*[^,.;)]+", "", s)
    s = re.sub(r"\bT1\b", "тест платформы", s)
    s = re.sub(r"\bT2\b", "реестр ФСП", s)
    s = re.sub(r"\bT0\b", "самоописание", s)
    return s.strip()


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
        raw_text = str(r.get("text") or "")
        pct_val = confirmed_scores.get(skill_name.lower()) or _extract_pct(raw_text)

        if st == "confirmed" or via_title:
            source_label = (
                f"Подтверждено косвенно через {via_title}"
                if via_title
                else "Подтверждено заданием работодателя"
                if "заданием работодателя" in raw_text.lower()
                else "Подтверждено заданиями теста"
            )
            skills_tested.append({
                "title": skill_name,
                "required": is_req,
                "score_pct": pct_val,
                "via": via_title,
                "source": source_label,
                "text": _clean_jargon(raw_text),
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
                "text": _clean_jargon(raw_text),
                "action": f"Проверить коротким заданием по навыку «{skill_name}» (10–15 мин)",
            })

    # Если в потребности не было стек-тегов, но у кандидата есть подтверждённые навыки из теста
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

    # 2. Достижения ФСП (реестр)
    skills_fsp: list[dict[str, Any]] = []
    if not fsp_info.get("hidden"):
        for ach in (fsp_info.get("achievements") or [])[:4]:
            skills_fsp.append({
                "text": ach.get("text") or "Достижение ФСП",
                "relevance": (ach.get("relevance") or {}).get("title"),
                "source": "Подтверждено реестром ФСП",
            })

    # 3. Короткие задания работодателей
    skills_probes: list[dict[str, Any]] = []
    for pr in (card.get("probes") or [])[:3]:
        skills_probes.append({
            "title": pr.get("title") or "Задание работодателя",
            "verdict": pr.get("verdict") or "Проверено",
        })

    # 4. Статус грейда и теста
    if test_info:
        correct = test_info.get("correct")
        answered = test_info.get("answered")
        integ = (test_info.get("integrity") or {}).get("title") or "высокая"
        grade_text = (
            f"Решено {correct} из {answered} заданий · достоверность: {integ.lower()}"
            if correct is not None and answered is not None
            else "Уровень проверен адаптивным тестом"
        )
        theta = test_info.get("theta")
        se = test_info.get("se")
        grade_hint = (
            f"Оценка по шкале адаптивного теста: {theta:+.2f} ± {se:.2f}".replace(".", ",")
            if isinstance(theta, (int, float)) and isinstance(se, (int, float))
            else None
        )
    else:
        grade_text = "Тест по направлению ещё не пройден — уровень указан со слов кандидата"
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
    for key in ("test", "stack_required", "stack_desired", "fsp", "probe"):
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

    return {
        "headline": headline,
        "summary": " ".join(summary_parts),
        "score100": score100,
        "rank": rank,
        "tier_label": tier_label,
        "required_confirmed": req_confirmed,
        "required_total": req_total,
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
    }
