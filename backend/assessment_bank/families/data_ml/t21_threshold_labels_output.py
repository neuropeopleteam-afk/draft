"""data_ml.metrics.t21_threshold_labels_output — predict_output (набор t21, порог Стажёра): перевод вероятностей
модели в метки 0/1 по порогу через if / else.

Программа проходит по оценкам модели и добавляет 1, если оценка проходит порог, иначе 0; печатает список меток
и их сумму (сколько объектов отмечено положительными). Ловушки чтения: оценка, равная порогу (`>=` включает
её, `>` — нет; в каждом варианте есть хотя бы одна такая оценка), и порядок меток совпадает с порядком оценок.
Ключ — независимый расчёт в генераторе на целых сотых; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.metrics.t21_threshold_labels_output"

CTX = [("антифрод платежей", "подозрительная операция"), ("прогноз оттока абонентов", "абонент уйдёт"),
       ("модерация объявлений", "объявление на проверку"), ("кредитный скоринг", "риск дефолта"),
       ("детектор спама", "письмо — спам"), ("прогноз брака на линии", "деталь с браком")]
NAMES = [("scores", "labels"), ("probs", "preds"), ("p", "flags"), ("risk", "marks")]


def _lit(k: int) -> str:
    """Литерал вероятности из целых сотых: 40 → 0.4, 65 → 0.65."""
    return repr(k / 100)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pos_name = rng.choice(CTX)
    sv, lv = rng.choice(NAMES)
    op = rng.choice([">=", ">"])
    for _ in range(300):
        thr = rng.choice([30, 40, 50, 60, 70])
        n = rng.randint(5, 7)
        ks = [rng.randrange(5, 100, 5) for _ in range(n)]
        n_eq = rng.choice([1, 1, 2])
        for i in rng.sample(range(n), n_eq):
            ks[i] = thr
        labels = [1 if (k >= thr if op == ">=" else k > thr) else 0 for k in ks]
        if 1 <= sum(labels) <= n - 1:
            break
    else:
        raise RuntimeError("t21_threshold_labels: не собрались оценки")
    lits = [_lit(k) for k in ks]
    code = (f"{sv} = [{', '.join(lits)}]\n"
            f"{lv} = []\n"
            f"for s in {sv}:\n"
            f"    if s {op} {_lit(thr)}:\n"
            f"        {lv}.append(1)\n"
            "    else:\n"
            f"        {lv}.append(0)\n"
            f"print({lv}, sum({lv}))")
    out = f"{labels} {sum(labels)}"
    eq = [lits[i] for i in range(n) if ks[i] == thr]
    eq_rule = ("«>=» включает равенство — оценка, равная порогу, получает 1" if op == ">=" else
               "«>» строгое — оценка, равная порогу, получает 0")
    expl = (f"Порог {_lit(thr)}, сравнение «{op}»: {eq_rule} (здесь это {', '.join(eq)}). Метки по порядку "
            f"оценок: {labels}, их сумма — {sum(labels)}. Вывод: «{out}».")
    stem = (f"Задача «{ctx}»: модель выдаёт вероятность класса «{pos_name}», программа переводит вероятности "
            f"в метки по порогу.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"op": op, "threshold": thr, "scores": ks}, language="python")
