"""qa.gen.t21_generator_exhaustion_output — predict_output (набор t21, порог Senior): тестовые случаи из
генератора — частичный расход в any()/all(), zip по короткому и повторный проход по исчерпанному генератору.

Генератор выдаёт тестовые случаи и записывает каждый выданный в список `ran` (сколько случаев реально прогнано).
Один и тот же объект генератора последовательно отдают any()/all() (останавливаются на первом решающем элементе —
остальное остаётся в генераторе), zip() с коротким списком меток и list()/sum(). Ловушки: any/all расходуют
генератор частично; zip(g, labels) при исчерпании меток уже ВЗЯЛ из генератора ещё один случай и выбросил его, а
zip(labels, g) — нет; повторный проход по исчерпанному генератору пуст. После каждого шага печатается результат и
len(ran). Отличие от семейств с gen.send (backend/data_eng/devops): здесь нет send, ловушка — общий итератор и его
исчерпание. Ключ — независимая модель указателя в генераторе; проверка — исполнение показанного кода в песочнице
Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.gen.t21_generator_exhaustion_output"

CTX = [("параметризованные тесты формы входа", "cases", "ran"),
       ("прогон граничных значений поля суммы", "values", "done"),
       ("тесты пагинации API", "pages", "seen"),
       ("регресс по списку заказов", "orders", "checked"),
       ("проверки длины пароля", "lengths", "tried")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, gname, rv = rng.choice(CTX)
    for _ in range(500):
        n = rng.randint(5, 7)
        data = rng.sample(range(0, 40), n)
        mode = rng.choice(["any", "all"])
        thr = rng.randint(5, 35)
        # any(x > thr) останавливается на первом True; all(x < thr2) — на первом False
        if mode == "any":
            pred_src, pred = f"x > {thr}", (lambda x, t=thr: x > t)
        else:
            pred_src, pred = f"x < {thr}", (lambda x, t=thr: x < t)
        stop = next((i for i, x in enumerate(data) if (pred(x) if mode == "any" else not pred(x))), None)
        if stop is None or stop == 0 or stop >= n - 3:
            continue
        k_lab = rng.randint(1, 2)
        g_first = rng.random() < 0.6
        rest = n - (stop + 1)
        if rest <= k_lab:
            continue
        break
    else:
        raise RuntimeError("t21_generator_exhaustion: не собран вариант")
    labels = rng.sample(["a", "b", "c", "x", "y"], k_lab)
    final = rng.choice(["list", "sum", "next"])
    # модель: указатель pos — сколько элементов уже выдал генератор
    outs, notes = [], []
    pos = stop + 1
    res1 = (mode == "any")  # any нашёл True / all нашёл False
    outs.append(f"{res1} {pos}")
    notes.append(f"{mode}() берёт элементы до первого решающего ({data[stop]} на позиции {stop + 1}) и "
                 f"останавливается — выдано {pos}")
    take = data[pos:pos + k_lab]
    pairs = list(zip(take, labels)) if g_first else list(zip(labels, take))
    if g_first:
        consumed = k_lab + 1  # ещё один элемент взят и выброшен
        lost = data[pos + k_lab]
        notes.append(f"zip(g, labels): после {k_lab} пар zip берёт из генератора ещё {lost}, видит конец меток и "
                     f"выбрасывает {lost} — выдано {pos + consumed}")
    else:
        consumed = k_lab
        notes.append(f"zip(labels, g): метки кончаются первыми, генератор больше не трогается — выдано "
                     f"{pos + consumed}")
    pos += consumed
    outs.append(f"{pairs!r} {pos}")
    left = data[pos:]
    outs.append(f"{left!r} {n}")
    notes.append(f"list(g) забирает остаток {left!r} — выдано {n}")
    if final == "list":
        outs.append(f"[] {n}")
        notes.append("повторный list(g) пуст: генератор исчерпан")
    elif final == "sum":
        outs.append(f"0 {n}")
        notes.append("sum по исчерпанному генератору — 0")
    else:
        outs.append(f"None {n}")
        notes.append("next(g, None) у исчерпанного генератора возвращает None")
    zip_src = "zip(g, labels)" if g_first else "zip(labels, g)"
    final_src = {"list": "list(g)", "sum": "sum(1 for _ in g)", "next": "next(g, None)"}[final]
    code = "\n".join([
        f"{rv} = []",
        f"def {gname}(items):",
        "    for x in items:",
        f"        {rv}.append(x)",
        "        yield x",
        "",
        f"g = {gname}({data!r})",
        f"labels = {labels!r}",
        f"print({mode}({pred_src} for x in g), len({rv}))",
        f"print(list({zip_src}), len({rv}))",
        f"print(list(g), len({rv}))",
        f"print({final_src}, len({rv}))",
    ])
    out = "\n".join(outs)
    expl = ("Все шаги работают с ОДНИМ объектом генератора g, а len(" + rv + ") показывает, сколько случаев он уже "
            "выдал. " + "; ".join(notes) + ". Вывод по строкам: " + " / ".join(f"«{o}»" for o in outs) + ".")
    stem = (f"Автотесты ({ctx}): тестовые случаи выдаёт генератор, а программа считает, сколько случаев прогнано "
            f"на каждом шаге.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"data": data, "mode": mode, "thr": thr, "labels": labels, "g_first": g_first,
                                  "final": final}, language="python")
