"""Извлечение структурированных полей из текста резюме (после вырезания ПДн).

Детерминированный путь (словари и регулярные выражения) работает всегда; LLM — необязательное
уточнение по тексту, где ФИО и контакты уже заменены плейсхолдерами. Все извлечённые факты имеют
уровень доказанности T0 (самоописание) и не влияют на категорию и ранжирование — только на фильтры.
"""
from __future__ import annotations

from datetime import date
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from app.modules.catalog.dictionary import (
    DIRECTION_KEYWORDS,
    GRADE_KEYWORDS,
    ROLE_TITLES,
    ROLES,
    SOFT_SKILL_TITLES,
    SOFT_SKILLS,
    find_keys,
    find_stack,
)
from app.modules.catalog.seed_data import STACK, tag_direction
from app.modules.llm.client import chat_json

_RANGE = re.compile(
    r"(?:(\d{1,2})[./]|(?:янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек)\w*\.?\s*)?((?:19|20)\d{2})\s*"
    r"(?:г\.?\s*)?[-–—]\s*(?:(?:\d{1,2})[./]|(?:янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек)\w*\.?\s*)?"
    r"((?:19|20)\d{2}|по\s+настоящее\s+время|настоящее\s+время|н\.\s?в\.|сейчас|present|now|текущ\w*)",
    re.I,
)
_EXPLICIT = re.compile(r"(?:опыт\s+(?:работы|разработки|в\s+ит)?[^\d\n]{0,25})(\d{1,2}(?:[.,]\d)?)\s*(?:\+\s*)?(?:год|лет|года)",
                       re.I)
_YEARS_MONTHS = re.compile(r"(\d{1,2})\s*(?:год|лет|года)\s*(\d{1,2})\s*месяц", re.I)


def pdf_to_text(data: bytes) -> tuple[str, int]:
    """Разбор в текущем процессе (без тайм-аута) — для скриптов и тестов. В API — pdf_to_text_safe."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text() or "") for p in reader.pages[:20]]
    return "\n".join(pages), len(reader.pages)


class PdfError(Exception):
    def __init__(self, code: str, pages: int | None = None):
        super().__init__(code)
        self.code, self.pages = code, pages


_WORKER = Path(__file__).with_name("pdf_worker.py")


def _limits(memory_mb: int, cpu_s: int):
    import resource  # импорт в родителе: в дочернем процессе после fork — только системные вызовы

    def apply() -> None:  # выполняется в дочернем процессе до запуска Python
        lim = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))

    return apply


def pdf_to_text_safe(data: bytes, max_pages: int = 20, timeout_s: float = 10.0, memory_mb: int = 512) -> tuple[str, int]:
    """Разбор PDF в отдельном процессе: тайм-аут, лимит памяти и CPU, отказ при > max_pages страниц до разбора.

    Ошибки — PdfError с кодом: too_many_pages | timeout | unreadable. Воркер API не блокируется и не падает
    от «тяжёлого» или вредоносного PDF: процесс разбора убивается по тайм-ауту.
    """
    try:
        res = subprocess.run([sys.executable, "-I", str(_WORKER), str(max_pages)], input=data, capture_output=True,
                             timeout=timeout_s, preexec_fn=_limits(memory_mb, int(timeout_s) + 2),
                             env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
    except subprocess.TimeoutExpired:
        raise PdfError("timeout") from None
    try:
        out = json.loads(res.stdout.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError, UnicodeDecodeError):
        raise PdfError("unreadable") from None  # процесс убит по лимиту памяти/CPU или упал
    if out.get("error"):
        raise PdfError(out["error"], out.get("pages"))
    return out.get("text") or "", int(out.get("pages") or 0)


def experience_years(text: str, today: date | None = None) -> float | None:
    today = today or date.today()
    m = _YEARS_MONTHS.search(text)
    if m:
        return round(int(m.group(1)) + int(m.group(2)) / 12, 1)
    m = _EXPLICIT.search(text)
    if m:
        return float(m.group(1).replace(",", "."))
    intervals = []
    for r in _RANGE.finditer(text):
        start = int(r.group(2))
        end_raw = r.group(3)
        end = int(end_raw) if end_raw[:2].isdigit() else today.year + (today.month - 1) / 12
        if 1980 <= start <= today.year and start <= end <= today.year + 1:
            intervals.append((start + (int(r.group(1)) - 1) / 12 if r.group(1) else start, end))
    if not intervals:
        return None
    # Объединяем пересечения, суммируем
    intervals.sort()
    total, cur_s, cur_e = 0.0, *intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return round(min(total, 45.0), 1) if total > 0 else None


def extract_rules(text: str) -> dict:
    tags = find_stack(text)
    stack = [{"tag": t, "title": STACK[t][0]} for t, _ in sorted(tags.items(), key=lambda kv: kv[1])]
    roles = [{"id": r, "title": ROLE_TITLES[r]} for r in find_keys(text, ROLES)]
    soft = [{"id": s, "title": SOFT_SKILL_TITLES[s]} for s in find_keys(text, SOFT_SKILLS)]
    votes = {d: 3 * n for d, n in find_keys(text, DIRECTION_KEYWORDS).items()}
    for t in tags:
        d = tag_direction(t)
        if d:
            votes[d] = votes.get(d, 0) + 1
    gk = find_keys(text, GRADE_KEYWORDS)
    exp = experience_years(text)
    # Стаж надёжнее ключевых слов («наставник стажёров» ≠ junior); слова — только если стаж не найден
    if exp is not None:
        grade_hint = "junior" if exp < 1.5 else "middle" if exp < 4.5 else "senior"
    else:
        grade_hint = max(gk, key=gk.get) if gk else None
    return {
        "stack": stack,
        "roles": roles,
        "soft_skills": soft,
        "experience_years": exp,
        "direction_hint": max(votes, key=votes.get) if votes else None,
        "grade_hint": grade_hint,
        "method": "rules",
    }


LLM_SYSTEM = (
    "Ты извлекаешь факты из резюме ИТ-специалиста. ФИО и контакты уже вырезаны. Верни только JSON: "
    '{"stack": [id], "roles": [id], "soft_skills": [id], "experience_years": число или null}. '
    "Стек — только из списка: {tags}. Роли — только из: {roles}. Софт-скиллы — только из: {soft}. "
    "Не выдумывай: указывай только то, что явно есть в тексте."
)


def extract(text_redacted: str, use_llm: bool = True) -> dict:
    out = extract_rules(text_redacted)
    if not use_llm:
        return out
    prompt = (LLM_SYSTEM.replace("{tags}", ", ".join(STACK)).replace("{roles}", ", ".join(ROLES))
              .replace("{soft}", ", ".join(SOFT_SKILLS)))
    res = chat_json(prompt, text_redacted[:8000])
    if not res.ok or not isinstance(res.data, dict):
        out["llm"] = {"used": False, "reason": res.error}
        return out
    d = res.data
    have = {s["tag"] for s in out["stack"]}
    for t in d.get("stack") or []:
        if t in STACK and t not in have:
            out["stack"].append({"tag": t, "title": STACK[t][0], "by": "llm"})
            have.add(t)
    have_r = {r["id"] for r in out["roles"]}
    for r in d.get("roles") or []:
        if r in ROLE_TITLES and r not in have_r:
            out["roles"].append({"id": r, "title": ROLE_TITLES[r], "by": "llm"})
    have_s = {s["id"] for s in out["soft_skills"]}
    for s in d.get("soft_skills") or []:
        if s in SOFT_SKILL_TITLES and s not in have_s:
            out["soft_skills"].append({"id": s, "title": SOFT_SKILL_TITLES[s], "by": "llm"})
    if out["experience_years"] is None and isinstance(d.get("experience_years"), (int, float)):
        out["experience_years"] = float(d["experience_years"])
    out["method"] = "llm+rules"
    out["llm"] = {"used": True, "latency_ms": res.latency_ms}
    return out
