"""data_ml.metrics.t21_precision_at_k_ties_output — predict_output (набор t21, порог Senior): precision@k двух
ранжирований при равных скорах — устойчивая сортировка, reverse=True и срез [::-1].

Модель ранжирования выдала скоры документам, часть скоров совпадает, причём группа равных пересекает границу top-k.
Программа строит два ранжирования и для каждого печатает top-k и precision@k дробью «hits/k». Первое —
``sorted(..., key=lambda r: -r[1])`` или ``sorted(..., key=lambda r: r[1], reverse=True)``: обе устойчивы, равные
скоры остаются в исходном порядке (reverse=True НЕ разворачивает порядок равных). Второе — сортировка по возрастанию
и срез ``[::-1]``: он разворачивает весь список, в том числе порядок равных. Ловушки: считать reverse=True равным
«отсортировать и развернуть»; считать, что равные скоры упорядочатся по id. Ключ — независимая модель (вставки по
явному правилу сравнения: равный элемент встаёт после ранее вставленных равных) в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.metrics.t21_precision_at_k_ties_output"

CTX = [("поиск по каталогу товаров", "s", "items"),
       ("рекомендации статей в ленте", "a", "feed"),
       ("подбор вакансий кандидату", "v", "jobs"),
       ("поиск по базе знаний поддержки", "d", "docs"),
       ("рекомендации треков", "t", "tracks")]
LEVELS = [55, 60, 65, 70, 75, 80, 85, 90, 95]
NAMES = [("v1", "v2"), ("rank_a", "rank_b"), ("old", "new"), ("order1", "order2")]


def _stable_desc(items):
    """Устойчивая сортировка по убыванию скора: элемент вставляется перед первым СТРОГО меньшим."""
    res = []
    for it in items:
        pos = len(res)
        for j, other in enumerate(res):
            if other[1] < it[1]:
                pos = j
                break
        res.insert(pos, it)
    return res


def _stable_asc(items):
    """Устойчивая сортировка по возрастанию скора: элемент вставляется перед первым СТРОГО большим."""
    res = []
    for it in items:
        pos = len(res)
        for j, other in enumerate(res):
            if other[1] > it[1]:
                pos = j
                break
        res.insert(pos, it)
    return res


def _sc(v: int) -> str:
    return repr(v / 100)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pfx, var = rng.choice(CTX)
    want_diff_hits = rng.random() < 0.7
    for _ in range(2000):
        n = rng.randint(6, 8)
        k = rng.randint(2, 4)
        n_lev = rng.randint(3, 4)
        levels = rng.sample(LEVELS, n_lev)
        items_sc = [rng.choice(levels) for _ in range(n)]
        if len(set(items_sc)) < 3:
            continue
        ids = [f"{pfx}{x}" for x in rng.sample(range(10, 99), n)]
        items = list(zip(ids, items_sc))
        desc = _stable_desc(items)
        # группа равных скоров пересекает границу top-k и не вся лежит внутри top-k
        if desc[k - 1][1] != desc[k][1]:
            continue
        flipped = list(reversed(_stable_asc(items)))
        top1 = [d for d, _ in desc[:k]]
        top2 = [d for d, _ in flipped[:k]]
        if top1 == top2:
            continue
        n_rel = rng.randint(2, 4)
        rel = rng.sample(ids, n_rel)
        h1 = sum(1 for d in top1 if d in rel)
        h2 = sum(1 for d in top2 if d in rel)
        if (h1 != h2) != want_diff_hits:
            continue
        # равные скоры не должны случайно идти в порядке возрастания id (иначе ловушка «по id» не видна)
        tie_ids = [d for d, s in items if s == desc[k - 1][1]]
        if tie_ids == sorted(tie_ids):
            continue
        break
    else:
        raise RuntimeError("t21_precision_at_k_ties: не собрались скоры")
    use_reverse = rng.random() < 0.6
    first_stable = rng.random() < 0.5
    n1, n2 = rng.choice(NAMES)
    stable_expr = (f"sorted({var}, key=lambda r: r[1], reverse=True)" if use_reverse
                   else f"sorted({var}, key=lambda r: -r[1])")
    flip_expr = f"sorted({var}, key=lambda r: r[1])[::-1]"
    e1, e2 = (stable_expr, flip_expr) if first_stable else (flip_expr, stable_expr)
    rel_shown = list(rel)
    rng.shuffle(rel_shown)
    lit = "[" + ", ".join(f'("{d}", {_sc(s)})' for d, s in items) + "]"
    rel_lit = "{" + ", ".join(f'"{d}"' for d in rel_shown) + "}"
    code = (f"{var} = {lit}\n"
            f"relevant = {rel_lit}\n"
            f"k = {k}\n"
            "\n"
            "def precision_at_k(order):\n"
            "    top = [doc for doc, _ in order[:k]]\n"
            "    hits = sum(doc in relevant for doc in top)\n"
            '    return " ".join(top) + f" {hits}/{k}"\n'
            "\n"
            f"{n1} = {e1}\n"
            f"{n2} = {e2}\n"
            f"print(precision_at_k({n1}))\n"
            f"print(precision_at_k({n2}))")
    line_st = " ".join(top1) + f" {h1}/{k}"
    line_fl = " ".join(top2) + f" {h2}/{k}"
    out = f"{line_st}\n{line_fl}" if first_stable else f"{line_fl}\n{line_st}"
    tie = desc[k - 1][1]
    tie_ids = [d for d, s in items if s == tie]
    how = ("reverse=True сортирует по убыванию, но сортировка остаётся устойчивой — равные НЕ переставляются"
           if use_reverse else "ключ -r[1] сортирует по убыванию; сортировка устойчива")
    expl = (f"Скор {_sc(tie)} у {len(tie_ids)} документов ({', '.join(tie_ids)} — в исходном порядке), и эта группа "
            f"пересекает границу top-{k}. {stable_expr}: {how}, поэтому порядок "
            f"{' '.join(d for d, _ in desc)} — top-{k}: {' '.join(top1)}, релевантных {h1} → «{line_st}». "
            f"{flip_expr}: по возрастанию равные тоже идут в исходном порядке, а срез [::-1] разворачивает весь "
            f"список вместе с порядком равных: {' '.join(d for d, _ in flipped)} — top-{k}: {' '.join(top2)}, "
            f"релевантных {h2} → «{line_fl}». Ловушка — считать reverse=True тем же, что сортировка и разворот, "
            f"или упорядочивать равные по id.")
    stem = (f"Офлайн-оценка ранжирования ({ctx}): программа упорядочивает выдачу по скору модели двумя способами и "
            f"для каждого печатает top-{k} и precision@{k}.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"items": [list(x) for x in items], "relevant": rel_shown, "k": k,
                                  "reverse_kw": use_reverse, "stable_first": first_stable},
                          language="python")
