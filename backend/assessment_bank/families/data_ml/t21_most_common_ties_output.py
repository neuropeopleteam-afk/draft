"""data_ml.data.t21_most_common_ties_output — predict_output (набор t21, порог Senior): collections.Counter по
меткам классов и top-k при равных частотах — порядок первого появления метки.

Программа считает метки разметки (Counter(первая_партия) + update(вторая), сумма двух Counter или цикл
`c[y] += 1`), иногда вычитает отбракованные метки (`c.subtract([...])`), берёт top-k одним из трёх способов —
`c.most_common(k)`, `sorted(c.items(), key=lambda kv: -kv[1])[:k]` или `sorted(c.items(), key=lambda kv: kv[1],
reverse=True)[:k]` — и печатает top-k и долю самого частого класса в процентах `n * 100 // total`. Что проследить:
порядок ключей Counter — порядок ПЕРВОГО появления метки (метки второй партии — после меток первой); все три способа
устойчивы: равные частоты остаются в порядке ключей (reverse=True не разворачивает равных, most_common — тоже);
subtract меняет только счётчик, место ключа сохраняется; группа равных пересекает границу k или делит первое место;
доля — целочисленное деление вниз. Ключ — независимая модель (явное правило «частота по убыванию, при равенстве —
индекс первого появления») в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_ml.data.t21_most_common_ties_output"

# (контекст, условие, метки, имена партий)
CTX = [("обращения в поддержку",
        "Перед обучением классификатора обращений инженер проверяет баланс классов в свежей разметке: программа "
        "считает метки и берёт самые частые для отчёта.",
        ["refund", "delivery", "login", "payment", "other"], ("day1", "day2")),
       ("модерация отзывов",
        "Команда модерации собирает разметку отзывов для дообучения фильтра: программа считает метки и выбирает "
        "самые частые классы для отчёта.",
        ["spam", "ok", "toxic", "ads", "offtop"], ("batch_a", "batch_b")),
       ("классификатор изображений",
        "Перед сборкой обучающей выборки для классификатора изображений программа считает метки разметчиков и "
        "выбирает частые классы.",
        ["cat", "dog", "fox", "owl", "bird"], ("part1", "part2")),
       ("антифрод",
        "Аналитик антифрода оценивает дисбаланс классов перед обучением модели: программа считает метки транзакций и "
        "берёт самые частые.",
        ["legit", "fraud", "review", "refund", "test"], ("week1", "week2")),
       ("интенты чат-бота",
        "Перед дообучением чат-бота команда смотрит, какие интенты чаще всего встречаются в разметке диалогов: "
        "программа считает метки и выбирает самые частые.",
        ["greet", "price", "order", "cancel", "human"], ("old", "new"))]
RANK_FORMS = ["most_common", "most_common", "neg_key", "reverse"]


def _rank(labels_order: list[str], cnt: dict[str, int], k: int) -> list[str]:
    """Независимая модель: частота по убыванию, при равенстве — раньше появившаяся метка (явное правило)."""
    pos = {lab: i for i, lab in enumerate(labels_order)}
    return sorted(labels_order, key=lambda lab: (-cnt[lab], pos[lab]))[:k]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, stem, pool, (b1n, b2n) = rng.choice(CTX)
    k = rng.choice([2, 3])
    build = rng.choice(["update", "update", "plus", "loop"])
    rank_form = rng.choice(RANK_FORMS)
    use_sub = rng.random() < 0.4
    top_tie = rng.random() < 0.5
    for _ in range(3000):
        m = rng.randint(4, 5)
        chosen = rng.sample(pool, m)
        # итоговые счётчики (после subtract) с ничьей: на первом месте или на границе k
        if top_tie:
            hi = rng.randint(3, 4)
            final = [hi, hi] + [rng.randint(1, hi - 1) for _ in range(m - 2)]
        else:
            a = rng.randint(3, 5)
            b = rng.randint(2, a - 1)
            final = ([a] if k == 2 else [a, rng.randint(b + 1, a)]) + [b, b]
            final += [rng.randint(1, b) for _ in range(m - len(final))]
        rng.shuffle(final)
        cnt = dict(zip(chosen, final))
        # subtract: отбракованные метки есть в потоке и вычитаются (место ключа сохраняется)
        sub = []
        pre = dict(cnt)
        if use_sub:
            x = rng.choice(chosen)
            d = rng.choice([1, 1, 2])
            pre[x] += d
            sub = [x] * d
        stream = [c for c in chosen for _j in range(pre[c])]
        rng.shuffle(stream)
        n_all = len(stream)
        if not 9 <= n_all <= 15:
            continue
        classes = list(dict.fromkeys(stream))     # порядок первого появления
        ranked = _rank(classes, cnt, m)
        vals = [cnt[c] for c in ranked]
        # ничья должна решать: на первом месте или на границе top-k
        tie_top = vals[0] == vals[1]
        tie_edge = len(vals) > k and vals[k - 1] == vals[k]
        if top_tie and not tie_top or not top_tie and not tie_edge:
            continue
        grp_v = vals[0] if top_tie else vals[k - 1]
        grp = [c for c in classes if cnt[c] == grp_v]
        if grp == sorted(grp) and rng.random() < 0.85:   # алфавитный порядок ничьей не должен совпадать с ответом
            continue
        if sub and sub[0] not in grp and rng.random() < 0.6:  # чаще вычитаем из группы ничьей
            continue
        # разрез на две партии: хотя бы одна метка впервые появляется во второй
        last_first = stream.index(classes[-1])
        if last_first < 3:
            continue
        cut = rng.randint(3, last_first)
        if n_all - cut < 3:
            continue
        break
    else:
        raise RuntimeError("t21_most_common_ties: не собрались метки")
    b1, b2 = stream[:cut], stream[cut:]
    top = _rank(classes, cnt, k)
    total = sum(cnt.values())
    lead = top[0]
    share = cnt[lead] * 100 // total

    def lst(xs):
        return "[" + ", ".join(f'"{x}"' for x in xs) + "]"

    lines = ["from collections import Counter"]
    if build == "update":
        lines += [f"c = Counter({lst(b1)})", f"c.update({lst(b2)})"]
    elif build == "plus":
        lines += [f"{b1n} = {lst(b1)}", f"{b2n} = {lst(b2)}", f"c = Counter({b1n}) + Counter({b2n})"]
    else:
        lines += [f"labels = {lst(stream)}", "c = Counter()", "for y in labels:", "    c[y] += 1"]
    if sub:
        lines.append(f"c.subtract({lst(sub)})")
    if rank_form == "most_common":
        lines.append(f"top = c.most_common({k})")
    elif rank_form == "neg_key":
        lines.append(f"top = sorted(c.items(), key=lambda kv: -kv[1])[:{k}]")
    else:
        lines.append(f"top = sorted(c.items(), key=lambda kv: kv[1], reverse=True)[:{k}]")
    joined = rng.random() < 0.55
    if joined:
        lines.append('print(" ".join(f"{name}:{n}" for name, n in top))')
        out_top = [" ".join(f"{t}:{cnt[t]}" for t in top)]
    else:
        lines += ["for name, n in top:", "    print(name, n)"]
        out_top = [f"{t} {cnt[t]}" for t in top]
    lines += ["label, n = top[0]", "total = sum(c.values())", "print(label, n * 100 // total)"]
    code = "\n".join(lines)
    out = "\n".join(out_top + [f"{lead} {share}"])

    form_txt = {"most_common": f"most_common({k})",
                "neg_key": "sorted(..., key=lambda kv: -kv[1])",
                "reverse": "sorted(..., key=lambda kv: kv[1], reverse=True)"}[rank_form]
    order_txt = ", ".join(f"{c}={cnt[c]}" for c in classes)
    src_txt = {"update": "Counter(первая партия), затем update — новые метки второй партии встают после меток первой",
               "plus": f"Counter({b1n}) + Counter({b2n}) — ключи {b1n}, затем новые ключи {b2n}",
               "loop": "цикл c[y] += 1 — ключ появляется при первой встрече метки"}[build]
    sub_txt = (f" subtract({lst(sub)}) уменьшает счётчик {sub[0]} на {len(sub)}, но место ключа не меняет." if sub
               else "")
    full = _rank(classes, cnt, len(classes))
    fv = [cnt[c] for c in full]
    ties = []
    if fv[0] == fv[1]:
        ties.append(f"на первом месте {', '.join(c for c in classes if cnt[c] == fv[0])} по {fv[0]}")
    if len(fv) > k and fv[k - 1] == fv[k] and fv[k - 1] != fv[0]:
        ties.append(f"на границе top-{k} {', '.join(c for c in classes if cnt[c] == fv[k - 1])} по {fv[k - 1]}")
    tie_txt = "ничьи (" + "; ".join(ties) + ") решаются порядком первого появления"
    note = {"most_common": "most_common при равных частотах сохраняет порядок ключей",
            "neg_key": "сортировка по -частоте устойчива — равные остаются в порядке ключей",
            "reverse": "reverse=True сохраняет устойчивость и не разворачивает равных"}[rank_form]
    expl = (f"Порядок ключей Counter — порядок первого появления меток ({src_txt}).{sub_txt} Итоговые счётчики "
            f"по порядку ключей: {order_txt}; всего {total}. {form_txt} упорядочивает по убыванию частоты устойчиво: "
            f"{tie_txt}, а не алфавитом ({note}). top-{k}: "
            f"{', '.join(f'{t}:{cnt[t]}' for t in top)}. Доля лидера: {cnt[lead]} * 100 // {total} = {share} "
            f"(деление вниз). Вывод:\n{out}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"stream": stream, "cut": cut, "sub": sub, "k": k, "build": build,
                                  "rank_form": rank_form, "top_tie": top_tie}, language="python")
