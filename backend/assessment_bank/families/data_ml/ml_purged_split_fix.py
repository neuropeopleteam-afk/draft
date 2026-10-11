"""data_ml.ml.purged_split_fix — choose_fix: разбиение временного ряда с горизонтом цели (разрыв перед тестом).

Порог Middle/Senior. Цель строки t считается по следующим H периодам (t+1 … t+H). Показанная функция «скользящего
начала» обучает на всех строках до начала теста — цели последних H строк обучения захватывают период теста
(утечка цели). Варианты замены (состав фиксирован, один подтип):
* верный — обучение `range(0, start - H)`: цель последней строки обучения заканчивается до начала теста;
* разрыв H − 1 (`start - H + 1`) — строка start − H видит первый период теста;
* разрыв 1 — достаточно только при H = 1;
* разрыв H, но в обучение добавлены строки после теста (`i >= end + H`) — обучение на будущем.
Проверка исполнением: для нескольких (n, k, H) — цели обучения не доходят до теста, обучение только в прошлом и
использует всю допустимую историю, тестовые блоки идут подряд.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import fix_options_variant

FAMILY_ID = "data_ml.ml.purged_split_fix"

# (контекст, что считается целью, единица периода)
CONTEXTS = [("прогноз продаж магазина", "сумма продаж за следующие {h} дней", "день"),
            ("отток абонентов", "факт ухода в следующие {h} недель", "неделя"),
            ("кредитный скоринг", "просрочка в следующие {h} месяцев", "месяц"),
            ("прогноз нагрузки колл-центра", "число звонков за следующие {h} часов", "час"),
            ("спрос на такси", "число заказов за следующие {h} часов", "час"),
            ("прогноз поломок станков", "поломка в следующие {h} смен", "смена")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, target_tpl, unit = rng.choice(CONTEXTS)
    h = rng.randint(3, 14)
    fn = rng.choice(["time_splits", "walk_forward", "make_folds", "rolling_origin"])
    nv, kv, hv = rng.choice([("n_rows", "n_folds", "horizon"), ("n", "k", "h"), ("size", "folds", "gap")])
    tr, te = rng.choice([("train", "test"), ("tr_idx", "te_idx"), ("fit_rows", "eval_rows")])

    def func(train_expr: str) -> str:
        return (f"def {fn}({nv}, {kv}, {hv}):\n    fold = {nv} // ({kv} + 1)\n    out = []\n"
                f"    for k_ in range(1, {kv} + 1):\n        start, end = k_ * fold, (k_ + 1) * fold\n"
                f"        {tr} = {train_expr}\n        {te} = list(range(start, end))\n"
                f"        out.append(({tr}, {te}))\n    return out\n")

    buggy = func("list(range(0, start))")
    correct = func(f"list(range(0, start - {hv}))")
    distractors = [func(f"list(range(0, start - {hv} + 1))"),
                   func("list(range(0, start - 1))"),
                   func(f"[i for i in range({nv}) if i < start - {hv} or i >= end + {hv}]")]
    k1 = rng.randint(3, 5)
    combos = [((k1 + 1) * (h + rng.randint(5, 30)), k1, h), (3 * rng.randint(20, 60), 2, rng.randint(2, 6))]
    test = (f"for n_, k2, h2 in {combos!r}:\n"
            f"    folds = {fn}(n_, k2, h2)\n"
            f"    assert len(folds) == k2\n"
            f"    prev_end = None\n"
            f"    for tr_, te_ in folds:\n"
            f"        assert tr_ and te_\n"
            f"        assert max(tr_) + h2 < min(te_), 'цель обучения заходит в тест'\n"
            f"        assert tr_ == list(range(0, min(te_) - h2)), 'не вся допустимая история'\n"
            f"        assert te_ == list(range(te_[0], te_[-1] + 1))\n"
            f"        assert prev_end is None or te_[0] == prev_end + 1\n"
            f"        prev_end = te_[-1]\n")
    target = target_tpl.format(h=h)
    stem = (f"ML ({ctx}). Цель строки t — {target}, то есть периоды t+1 … t+{h} (единица — {unit}). "
            f"`{fn}` строит валидацию со скользящим началом: обучение только на прошлом, тестовые блоки подряд, "
            f"история до теста используется вся, сколько допустимо. На валидации модель заметно лучше, чем потом "
            f"на новых данных. Какая замена функции исправляет разбиение?")
    why = (f"Цель последних {h} строк перед тестом считается по периодам, которые уже входят в тест, — в обучение "
           f"попадает информация о тестовом периоде (утечка цели). Строку t можно брать в обучение, только если "
           f"t + {h} < start, то есть `range(0, start - {hv})`. Разрыв на одну строку меньше или в один период "
           f"оставляет перекрытие, а строки после теста — обучение на будущем.")
    return fix_options_variant(FAMILY_ID, seed, rng, stem=stem, buggy=buggy, correct=correct,
                               distractors=distractors, test=test, context=ctx, defect="label_horizon_leak",
                               why=why, params={"horizon": h, "combos": combos})
