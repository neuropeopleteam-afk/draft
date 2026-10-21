"""devops.release.t21_ref_slices_output — predict_output (набор t21, порог Стажёра): срезы строки и len в Python.

Шаг CI разбирает имя ветки релиза вида `release/2.14-rc1` срезами: начало, середина и хвост строки, плюс длина.
Ловушки чтения: правая граница среза не входит, индексы считаются с нуля, отрицательный индекс отсчитывается с конца;
границы срезов в вариантах сдвинуты на символ (захватывают `/` или `-` либо нет). Ключ — независимый расчёт в
генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.release.t21_ref_slices_output"

CTX = [("сборка биллинга", "billing"), ("релиз каталога", "catalog"), ("выкладка платёжного шлюза", "payments"),
       ("сборка поиска", "search"), ("релиз личного кабинета", "cabinet"), ("выкладка CRM", "crm"),
       ("релиз сервиса уведомлений", "notify")]
PREFIX = ["release", "hotfix", "rc", "deploy", "ship"]
SUFFIX = ["rc1", "rc2", "beta", "lts", "fix", "hf3", "canary"]
VARS = ["ref", "branch", "tag", "name"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, _svc = rng.choice(CTX)
    var = rng.choice(VARS)
    prefix = rng.choice(PREFIX)
    ver = f"{rng.randint(1, 4)}.{rng.randint(0, 19)}"
    suffix = rng.choice(SUFFIX)
    ref = f"{prefix}/{ver}-{suffix}"
    lp, lv, ls = len(prefix), len(ver), len(suffix)
    a = lp + rng.choice([0, 1])                      # конец «головы»: без «/» или с ним
    s2 = lp + 1 + rng.choice([0, 0, -1])             # начало версии (или на символ раньше — с «/»)
    e2 = lp + 1 + lv + rng.choice([0, 0, 1])         # конец версии (или с «-»)
    c = ls + rng.choice([0, 1])                      # хвост: суффикс или с «-»
    exprs = [f"{var}[:{a}]", f"{var}[{s2}:{e2}]", f"{var}[-{c}:]"]
    vals = [ref[:a], ref[s2:e2], ref[-c:]]
    order = [0, 1, 2]
    rng.shuffle(order)
    with_len = rng.random() < 0.6
    lines = [f'{var} = "{ref}"']
    out_lines = []
    for i in order:
        lines.append(f"print({exprs[i]})")
        out_lines.append(vals[i])
    if with_len:
        lines.append(f"print(len({var}))")
        out_lines.append(str(len(ref)))
    code = "\n".join(lines)
    out = "\n".join(out_lines)
    parts = [f"{exprs[i]} → «{vals[i]}»" for i in order]
    if with_len:
        parts.append(f"len({var}) = {len(ref)}")
    expl = (f"Индексы считаются с нуля, правая граница среза не входит, отрицательная — от конца строки. "
            f"В «{ref}» символ «/» стоит под индексом {lp}, «-» — под индексом {lp + 1 + lv}. "
            + "; ".join(parts) + ".")
    stem = (f"Шаг CI ({ctx}) разбирает имя ветки релиза срезами строки перед тем, как проставить версию "
            f"образа.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"ref": ref, "slices": [a, s2, e2, c]}, language="python")
