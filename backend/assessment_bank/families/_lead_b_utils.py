"""Общие помощники семейств уровней Lead и Principal (волна 7): qa, security, mobile, analyst.

Только для генераторов ``<направление>/lead_*.py`` и ``<направление>/principal_*.py`` этого потока.

* ``module_choose_fix`` — choose_fix на большом фрагменте: кандидату показан модуль целиком с дефектной функцией,
  варианты — замены этой функции; каждая замена исполняется в составе модуля на одних и тех же сценариях
  (верная проходит все, остальные падают хотя бы на одном), дефектный модуль тоже падает.
* ``open_variant`` — open_answer по теме из словаря ``TOPICS`` с рубрикой из трёх критериев и эталонами; замечания
  для оценщика требуют дословных цитат из ответа на каждый засчитанный критерий (модуль доказательной оценки).
* ``computed_mcq`` — mcq_concept, где ключ считает программа по тем же числам, что показаны кандидату.
* ``design_review_variant`` — open_answer «ревью дизайн-документа»: выдержка документа, в которую вставлены k
  проблем из пула темы (остальные места — верные строки); критерии рубрики — найденные проблемы и приоритизация.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from assessment_bank.families.data_ml._dm_utils import balanced_options, check_lengths  # noqa: F401
from assessment_bank.gen_utils import build_variant, js_harness, para, py_harness, rubric_from
from assessment_bank.schema import AnswerKey, Check

EVIDENCE_NOTES = ("Оценка по критериям рубрики, каждый — по шкале 0–4 (частичный балл): 0 — нет или неверно "
                  "(опасно); 1 — названо общими словами без связи с ситуацией; 2 — верно, но без чисел и деталей "
                  "условия; 3 — верно и применено к ситуации с обоснованием; 4 — как 3, плюс компромиссы и способ "
                  "проверки. Балл задания — взвешенная сумма по критериям, делённая на 4. Эталоны — ориентиры "
                  "уровня, а не требуемая формулировка. Каждый балл выше нуля подтверждается дословной цитатой из "
                  "ответа (одна-две фразы на критерий). Равноценные решения с обоснованием компромисса засчитываются.")


def ru_num(x: float | int) -> str:
    """Число по-русски: пробел между тысячами, десятичная запятая; целое без дробной части."""
    if isinstance(x, int) or float(x).is_integer():
        return f"{int(x):,}".replace(",", " ")
    return f"{x:,.2f}".replace(",", " ").replace(".", ",").rstrip("0").rstrip(",")


def pct(x: float, nd: int = 1) -> str:
    """Доля → «12,5 %» (x — доля от 0 до 1)."""
    s = f"{100 * x:.{nd}f}".replace(".", ",")
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return s + " %"


def module_choose_fix(fid: str, seed: int, rng, *, stem: str, module: str, buggy_fn: str, correct_fn: str,
                      distractors: Sequence[str], tests: str, context: str, defect: str, why: str,
                      label: str, runner: str = "python", params: dict[str, Any] | None = None,
                      language: str | None = None, prelude: str = ""):
    """choose_fix: ``module`` содержит метку ``{FN}``, на её место встаёт функция (дефектная или вариант)."""
    if "{FN}" not in module:
        raise ValueError("в модуле нет места {FN} для функции")
    harness: Callable[..., str]
    if runner == "python":
        harness = py_harness
    elif runner == "node":
        harness = lambda code, body: js_harness(code, body, prelude)  # noqa: E731
    else:
        raise ValueError(runner)
    texts = [correct_fn, *distractors]
    if len(set(texts)) != len(texts) or buggy_fn in texts:
        raise ValueError("варианты замены совпадают между собой или с дефектной функцией")
    opts, key = balanced_options(fid, seed, rng, (label, correct_fn), [(label, d) for d in distractors])
    code = module.replace("{FN}", buggy_fn)
    checks = [Check(name="buggy_fails", runner=runner, program=harness(code, tests), expect="fail")]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner=runner,
                            program=harness(module.replace("{FN}", o.code), tests),
                            expect="pass" if o.id == key else "fail", embeds_display_code=False))
    return build_variant(fid, seed, stem=stem, code=code, options=opts,
                         answer_key=AnswerKey(kind="option", value=key, explanation=why),
                         context=context, verification="execution", checks=checks, defect_type=defect,
                         params=params or {}, language=language,
                         display_code_note="Каждый вариант исполняется на месте дефектной функции в составе "
                                           "показанного модуля на одних и тех же сценариях.")


def open_variant(fid: str, seed: int, *, topic: str, spec: dict[str, Any], vals: dict[str, Any], context: str,
                 length: str = "10–18 предложений", extra_notes: str = ""):
    """open_answer по теме ``spec`` (text, criteria [(id, описание, вес)], strong, medium, weak) и числам ``vals``."""
    stem = spec["text"].format(**vals) + f" Ответ — {length}."
    rub = {"criteria": [(n, d.format(**vals), w) for n, d, w in spec["criteria"]],
           "strong": spec["strong"].format(**vals), "medium": spec["medium"].format(**vals),
           "weak": spec["weak"].format(**vals),
           "notes": (EVIDENCE_NOTES + (" " + extra_notes if extra_notes else "")).strip()}
    ak = AnswerKey(kind="rubric", value="rubric",
                   explanation="Открытый ответ оценивается по рубрике (сильный/средний/слабый) с цитатами из ответа.")
    return build_variant(fid, seed, stem=stem, answer_key=ak, rubric=rubric_from(rub), context=context,
                         verification="rubric_only", language="text", params={"topic": topic})


def computed_mcq(fid: str, seed: int, rng, *, stem: str, correct: str, distractors: Sequence[str], program: str,
                 why: str, context: str, code: str | None = None, params: dict[str, Any] | None = None,
                 language: str | None = None, note: str = "Программа считает ответ по тем же числам, что "
                                                         "показаны кандидату.", max_ratio: float = 1.35):
    """mcq_concept с ключом исполнением: ``program`` печатает текст верного варианта."""
    check_lengths([correct, *distractors], max_ratio=max_ratio)
    opts, key = balanced_options(fid, seed, rng, (correct, None), [(d, None) for d in distractors])
    checks = [Check(name="compute", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=correct, embeds_display_code=False)]
    return build_variant(fid, seed, stem=stem, code=code, options=opts,
                         answer_key=AnswerKey(kind="option", value=key, explanation=para(why)),
                         context=context, verification="execution", checks=checks, params=params or {},
                         language=language, display_code_note=note)


def design_review_variant(fid: str, seed: int, rng, *, context: str, intro: str, doc_title: str,
                          lines: Sequence[str], issues: dict[str, dict[str, str | None]], vals: dict[str, Any],
                          k: int = 3, length: str = "10–16 предложений", extra_notes: str = "",
                          priority_crit: str = "Расставляет приоритет замечаний по риску для требований и "
                                               "предлагает порядок исправления и способ проверки"):
    """Ревью дизайн-документа.

    ``lines`` — строки документа; строка ``@<id>@`` — место проблемы ``<id>`` из ``issues``. У проблемы: ``good`` —
    верная строка (или None — строки нет), ``bad`` — строка с проблемой, ``crit`` — что должен найти кандидат,
    ``fix`` — фрагмент сильного ответа, ``hint`` — фрагмент среднего ответа. В вариант вставляются k проблем.
    """
    planted = sorted(rng.sample(sorted(issues), k))
    doc: list[str] = []
    for ln in lines:
        if ln.startswith("@") and ln.endswith("@"):
            iid = ln.strip("@")
            text = issues[iid]["bad"] if iid in planted else issues[iid]["good"]
            if text:
                doc.append(str(text).format(**vals))
        else:
            doc.append(ln.format(**vals))
    code = "\n".join(doc)
    for iid in planted:
        bad = str(issues[iid]["bad"]).format(**vals)
        if bad not in doc:
            raise ValueError(f"строка проблемы {iid} не попала в документ")
    w_issue = round(0.75 / k, 6)
    crit = [(iid, "Находит проблему: " + str(issues[iid]["crit"]).format(**vals), w_issue) for iid in planted]
    crit.append(("priorities", priority_crit, round(1 - w_issue * k, 6)))
    strong = " ".join(f"({i}) {str(issues[iid]['fix']).format(**vals)}" for i, iid in enumerate(planted, 1))
    strong = ("Замечания по документу: " + strong + " Приоритет — по риску для требований: сначала то, что "
              "ведёт к потере данных, денег или нарушению обещаний клиентам, затем — к стоимости и скорости; для "
              "каждого исправления — проверка (тест, нагрузочный прогон или наблюдение после выкатки).")
    medium = ("В документе есть риски: " + str(issues[planted[0]]["hint"]).format(**vals) + " Ещё стоит добавить "
              "больше тестов и мониторинга.")
    weak = "Документ выглядит хорошо, решение типовое; можно начинать разработку, детали уточнятся по ходу."
    good_ids = [iid for iid in sorted(issues) if iid not in planted]
    notes = (EVIDENCE_NOTES + " Вставленные проблемы — по критериям рубрики; остальные разделы документа верны "
             f"(темы: {', '.join(good_ids)}) — замечания к ним не засчитываются, но и не снижают балл, если не "
             "предлагают опасного решения. Ссылки на пункты документа желательны, но цитата из ответа обязательна."
             + (" " + extra_notes if extra_notes else ""))
    stem = (f"{intro} Ниже — выдержка из дизайн-документа «{doc_title}». Проведите ревью как ведущий инженер: "
            f"найдите проблемы, которые помешают выполнить требования, сошлитесь на пункты документа, оцените риск и "
            f"предложите исправления и способ проверки. Ответ — {length}.")
    rub = {"criteria": crit, "strong": strong, "medium": medium, "weak": weak, "notes": notes}
    ak = AnswerKey(kind="rubric", value="rubric",
                   explanation="Ревью оценивается по рубрике: найденные вставленные проблемы и приоритизация, "
                               "каждый критерий 0–4 с цитатами из ответа.")
    return build_variant(fid, seed, stem=stem, code=code, answer_key=ak, rubric=rubric_from(rub), context=context,
                         verification="rubric_only", language="text", params={"planted": planted})
