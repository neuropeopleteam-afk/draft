"""Приоритизация синтетических находок по готовым баллам CVSS v3.1."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS, SOURCES

FAMILY_ID = "security.triage.cvss_priority_output"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    identifiers = rng.sample(range(10, 999), 4)
    scores = rng.sample([0, 39, 40, 69, 70, 89, 90, 98, 100], 3)
    score_tenths = scores + [scores[0]]
    rows = [(f"F-{identifiers[i]}", score_tenths[i] / 10, rng.choice([0, 1]),
             rng.choice([1, 2, 3])) for i in range(4)]
    rng.shuffle(rows)
    code = f"""findings = {rows!r}

def severity(score):
    if score >= 9.0:
        return 'critical'
    if score >= 7.0:
        return 'high'
    if score >= 4.0:
        return 'medium'
    if score > 0:
        return 'low'
    return 'none'

ordered = sorted(findings, key=lambda r: (-r[1], -r[2], -r[3], r[0]))
for fid, score, exposed, importance in ordered:
    print(fid, severity(score), f'{{score:.1f}}')"""
    ordered = sorted(rows, key=lambda r: (-int(round(r[1] * 10)), -r[2], -r[3], r[0]))
    def reference(score):
        value = int(round(score * 10))
        return next(label for cutoff, label in [(90, "critical"), (70, "high"), (40, "medium"),
                                               (1, "low"), (0, "none")] if value >= cutoff)
    out = "\n".join(f"{fid} {reference(score)} {score:.1f}" for fid, score, _, _ in ordered)
    stem = (f"{ctx.capitalize()}: четыре полностью учебные находки. Баллы CVSS v3.1 Base "
            "уже выданы аналитиком; вычислять вектор не требуется. Формат записи: "
            "(id, балл, доступность извне 0/1, важность актива 1–3). Для этой очереди сначала "
            "сортируют по баллу, при равенстве — по доступности извне, затем важности, "
            "затем id по возрастанию. Это заданная политика, не универсальная оценка риска. "
            "Что выведет код? Учтите границы уровней 4.0, 7.0 и 9.0.")
    return build_variant(
        FAMILY_ID, seed, stem=stem, code=code, context=ctx, verification="execution",
        answer_key=AnswerKey(kind="output", value=out, explanation="Шкала v3.1: 0 — none, "
                            "0.1–3.9 — low, 4.0–6.9 — medium, 7.0–8.9 — high, 9.0–10 — critical. "
                            "Base Score не заменяет контекст риска; порядок здесь явно задан."),
        checks=[Check(name="stdout", runner="python", program=code,
                      expect="stdout_equals", expected_stdout=out)],
        params={"source_urls": [SOURCES["cvss"]], "scores_are_given": True},
    )
