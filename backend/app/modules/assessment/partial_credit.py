"""Частичный балл 0–4 у развёрнутых ответов (флаг ASSESSMENT_PARTIAL_CREDIT_ENABLED, по умолчанию выкл.).

Оценщик (grader.grade_open; с GRADING_EVIDENCE — цитаты-доказательства по пунктам и скептик) возвращает, как и
раньше, оценки пунктов рубрики и взвешенную оценку 0..1. Балл 0–4 считает код: ``points = round(4 · оценка)`` —
тот же вызов модели, без нового запроса и без изменения промпта. С флагом балл входит в θ по модели частичного балла
(GPCM, ``assessment_bank.psychometrics.gpcm``): балл 3 из 4 говорит о способности больше, чем «засчитано», а 1 из 4 —
больше, чем «не засчитано». Без флага оценка 0..1 входит в 2PL как раньше.

Рубрики — из банка (у каждого варианта open_answer и open_book_3step есть рубрика с пунктами и эталонами сильного,
среднего и слабого ответа). Если рубрики у варианта нет, с флагом используется общий шаблон ``generic_rubric``
(правильность, полнота, обоснование) — без него ответ ушёл бы эксперту (``no_rubric``).

Шкала баллов (для экрана эксперта и документации):
* 0 — ответа по существу нет или он неверен;
* 1 — отдельные верные элементы, главное упущено;
* 2 — основная идея верна, существенные пробелы;
* 3 — верно и почти полно, мелкие пробелы;
* 4 — полный ответ по всем пунктам рубрики.
"""
from __future__ import annotations

from assessment_bank.psychometrics.gpcm import K, TEXT_FORMATS as _BANK_TEXT_FORMATS, points as _points, text_parts as _bank_text_parts

TEXT_FORMATS = tuple(dict.fromkeys((*_BANK_TEXT_FORMATS, "incident_sim")))


def text_parts(fmt: str, n_parts: int = 1) -> list[int]:
    if fmt == "incident_sim":
        return [2] if n_parts >= 3 else ([n_parts - 1] if n_parts > 0 else [])
    return _bank_text_parts(fmt, n_parts)

MODEL = "GPCM 0–4"
SCALE_RU = {
    0: "ответа по существу нет или он неверен",
    1: "отдельные верные элементы, главное упущено",
    2: "основная идея верна, существенные пробелы",
    3: "верно и почти полно, мелкие пробелы",
    4: "полный ответ по всем пунктам рубрики",
}

__all__ = ["K", "MODEL", "SCALE_RU", "TEXT_FORMATS", "enabled", "generic_rubric", "points", "session_summary",
           "text_parts"]


def enabled() -> bool:
    from app.core.config import get_settings

    return bool(get_settings().assessment_partial_credit_enabled)


def points(score: float | None) -> int | None:
    """Балл 0–4 из взвешенной оценки пунктов рубрики 0..1 (None — оценки нет: ждёт эксперта)."""
    return _points(score, K)


def generic_rubric(stem: str = "", step_prompt: str | None = None) -> dict:
    """Общий шаблон рубрики по критериям ответа — для варианта без рубрики в банке (только при флаге)."""
    task = (step_prompt or stem or "").strip().splitlines()[0][:200] if (step_prompt or stem) else "задание"
    return {
        "criteria": [
            {"id": "correct", "weight": 0.4,
             "description": "Правильность: ответ по существу решает поставленную задачу, без фактических ошибок"},
            {"id": "complete", "weight": 0.35,
             "description": "Полнота: учтены все требования условия, важные случаи и ограничения"},
            {"id": "reasoning", "weight": 0.25,
             "description": "Обоснование: решения объяснены, названы компромиссы и почему выбран этот вариант"},
        ],
        "strong": f"Полный и верный ответ на «{task}»: все требования условия, важные случаи, решения обоснованы.",
        "medium": "Основная идея верна, но часть требований или случаев упущена, обоснование краткое.",
        "weak": "Общие слова или неверное решение; требования условия не разобраны.",
        "scoring_notes": "Общий шаблон: у варианта нет своей рубрики в банке. Оценивайте по существу ответа.",
        "generic": True,
    }


def session_summary(items: list[dict]) -> dict:
    """Сводка для details результата: баллы 0–4 развёрнутых частей сессии (без текста ответов)."""
    out = []
    for it in items:
        if it.get("canary") or it.get("format") not in TEXT_FORMATS:
            continue
        for j in text_parts(it["format"], len(it.get("x") or [])):
            v = (it.get("x") or [None])[j]
            out.append({"format": it["format"], "part": j, "points": points(v)})
    dist = [0] * (K + 1)
    for r in out:
        if r["points"] is not None:
            dist[r["points"]] += 1
    return {"model": MODEL, "parts": out, "distribution": dist}
