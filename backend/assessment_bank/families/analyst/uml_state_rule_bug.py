"""analyst.uml.state_rule_bug — find_bug: переход машины состояний нарушает требование.

Машина состояний (текстовая запись UML) и 3–4 требования к жизненному циклу объекта. Один переход
нарушает одно из требований (отмена после сборки, переход в конечное мимо обязательного шага, выход из
конечного состояния…). Нужно указать строку перехода. Один подтип дефекта — переход противоречит
требованию; исправление — верный переход в той же строке. Ключ проверяется исполнением: Python разбирает
показанную запись и проверяет все требования.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._an_utils import py_literal_block
from ._fsm_data import FSM, PARSE, fmt

FAMILY_ID = "analyst.uml.state_rule_bug"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(FSM))
    F = FSM[ctx]
    ri = rng.randrange(len(F["reqs"]))
    text, pred, (ti, mutated) = F["reqs"][ri]
    trans = list(F["transitions"])
    order = list(range(len(trans)))
    rng.shuffle(order)
    good = [trans[i] for i in order]
    bad = [mutated if i == ti else trans[i] for i in order]
    fixed = "\n".join(fmt(t) for t in good)
    buggy = "\n".join(fmt(t) for t in bad)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    reqs = list(F["reqs"])
    rng.shuffle(reqs)
    preds = "\n".join(f"assert {r[1]}, {r[0]!r}" for r in reqs)
    prog = lambda m: (py_literal_block("MODEL", m) + PARSE + "try:\n" +  # noqa: E731
                      "\n".join("    " + l for l in preds.splitlines()) +
                      "\n    print('RESULT: PASS')\nexcept AssertionError:\n    print('RESULT: FAIL')\n")
    checks = [Check(name="buggy_fails", runner="python", program=prog(buggy), expect="fail"),
              Check(name="fixed_passes", runner="python", program=prog(fixed), expect="pass",
                    embeds_display_code=False)]
    req_list = "\n".join(f"{i + 1}. {r[0]}" for i, r in enumerate(reqs))
    stem = (f"Аналитик описал жизненный цикл объекта «{ctx}» машиной состояний (текстовая запись UML; переход "
            f"«А --событие--> Б»; начальное состояние — «{F['initial']}»). Требования:\n{req_list}\n\n"
            f"Одна строка модели нарушает требования. Укажите её номер.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line} ({fmt(mutated)}) нарушает требование «{text}» Верно: "
                                f"{fmt(trans[ti])}."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="transition_violates_rule",
                         language="text", params={"fixed_code": fixed, "req": ri})
