"""mobile.offline.t21_upload_budget_output — predict_output (набор t21, порог Стажёра): отбор фото из
офлайн-очереди в рамках лимита трафика — цикл с суммой и if.

Программа на JavaScript (логика React Native-приложения) проходит по размерам фото в офлайн-очереди и берёт фото,
если вместе с уже отобранными оно укладывается в лимит. Ловушки чтения: крупное фото пропускается, но цикл
не останавливается — следующие маленькие фото ещё помещаются; граница `<=` (ровно в лимит — помещается).
Ключ — независимый подсчёт в генераторе; проверка — исполнение показанного кода в песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.offline.t21_upload_budget_output"

CTX = [("фото к отзыву о товаре", "photosKb"), ("снимки акта приёмки на складе", "shotsKb"),
       ("вложения в чате поддержки", "filesKb"), ("фото показаний счётчиков", "imagesKb"),
       ("чеки для авансового отчёта", "receiptsKb")]


def _pick(sizes: list[int], limit: int) -> tuple[int, int, list[int]]:
    used = cnt = 0
    taken = []
    for kb in sizes:
        if used + kb <= limit:
            used += kb
            cnt += 1
            taken.append(kb)
    return cnt, used, taken


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, arr = rng.choice(CTX)
    limit = rng.choice([500, 600, 700, 800, 900, 1000])
    for _ in range(500):
        n = rng.randint(5, 6)
        sizes = [rng.randrange(40, limit * 3 // 4, 10) for _ in range(n)]
        cnt, used, _taken = _pick(sizes, limit)
        # ловушка должна сработать: после первого пропуска что-то ещё помещается; пропусков не больше двух
        first_skip = None
        used_run = 0
        for i, kb in enumerate(sizes):
            if used_run + kb <= limit:
                used_run += kb
            elif first_skip is None:
                first_skip = i
        if first_skip is None:
            continue
        later_fit = False
        used_run = 0
        for i, kb in enumerate(sizes):
            if used_run + kb <= limit:
                used_run += kb
                if i > first_skip:
                    later_fit = True
        if not later_fit or not 1 <= n - cnt <= 2 or len(set(sizes)) != n:
            continue
        break
    else:
        raise RuntimeError("t21_upload_budget: не собрался список размеров")
    lim_name = rng.choice(["LIMIT_KB", "BUDGET_KB", "MAX_KB"])
    code = (f"const {arr} = [{', '.join(map(str, sizes))}];\n"
            f"const {lim_name} = {limit};\n"
            "let usedKb = 0, sent = 0;\n"
            f"for (const kb of {arr}) {{\n"
            f"  if (usedKb + kb <= {lim_name}) {{ usedKb += kb; sent++; }}\n"
            "}\n"
            "console.log(sent, usedKb);")
    out = f"{cnt} {used}"
    run, steps = 0, []
    for kb in sizes:
        if run + kb <= limit:
            run += kb
            steps.append(f"{kb} → {run}")
        else:
            steps.append(f"{kb} — пропуск ({run} + {kb} > {limit})")
    expl = (f"Цикл проходит все {n} фото: {'; '.join(steps)}. Пропущенное фото не останавливает цикл — "
            f"следующие, меньшие, ещё помещаются в лимит. Отобрано {cnt}, сумма {used} КБ: «{out}».")
    stem = (f"Офлайн-очередь React Native-приложения ({ctx}): при подключении через мобильную сеть программа "
            f"отбирает фото для отправки в рамках лимита трафика {limit} КБ.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"sizes": sizes, "limit": limit}, language="javascript")
