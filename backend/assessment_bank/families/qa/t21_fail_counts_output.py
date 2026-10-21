"""qa.flaky.t21_fail_counts_output — predict_output (набор t21, порог Junior): подсчёт в словаре и sorted с ключом.

Лог перезапусков: строки «тест:статус». Программа разбирает их split, считает падения каждого теста в словаре
(get с умолчанием) и печатает тесты по убыванию числа падений, при равенстве — по алфавиту (ключ-кортеж
`(-count, name)`). Ловушки: тесты без падений в словарь не попадают; порядок при равных счётчиках задаёт второй элемент
ключа, а не порядок в логе. Ключ — независимый подсчёт и упорядочивание в генераторе; проверка — исполнение кода.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.flaky.t21_fail_counts_output"

CTX = [("перезапуски ночного UI-регресса", ["login", "cart", "pay", "search", "profile", "logout"]),
       ("ретраи API-тестов в CI", ["orders", "refund", "auth", "stock", "invoice", "webhook"]),
       ("повторные прогоны мобильных e2e", ["onboarding", "feed", "chat", "upload", "settings", "push"]),
       ("перезапуски контрактных тестов", ["billing", "users", "catalog", "delivery", "promo", "reviews"])]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, pool = rng.choice(CTX)
    var = rng.choice(["fails", "counter", "flaky"])
    for _ in range(300):
        names = rng.sample(pool, rng.randint(4, 5))
        n = rng.randint(6, 8)
        log = [(rng.choice(names), rng.choice(["fail", "fail", "pass"])) for _ in range(n)]
        cnt: dict[str, int] = {}
        for nm, st in log:
            if st == "fail":
                cnt[nm] = cnt.get(nm, 0) + 1
        vals = list(cnt.values())
        only_pass = {nm for nm, _ in log} - set(cnt)
        # нужны: хотя бы одна пара с равным счётчиком, разные счётчики и тест только с pass
        if len(cnt) >= 3 and len(set(vals)) >= 2 and len(vals) > len(set(vals)) and only_pass:
            # равные счётчики должны идти в логе НЕ по алфавиту хотя бы для одной пары
            first_seen = {}
            for nm, st in log:
                if st == "fail" and nm not in first_seen:
                    first_seen[nm] = len(first_seen)
            tie_unsorted = any(cnt[a] == cnt[b] and first_seen[a] < first_seen[b] and a > b
                               for a in cnt for b in cnt if a != b)
            if tie_unsorted:
                break
    else:
        raise RuntimeError("t21_fail_counts: не собрался лог")
    entries = [f"{nm}:{st}" for nm, st in log]
    code = (f"log = {entries}\n"
            f"{var} = {{}}\n"
            "for entry in log:\n"
            "    name, status = entry.split(\":\")\n"
            "    if status == \"fail\":\n"
            f"        {var}[name] = {var}.get(name, 0) + 1\n"
            f"for name in sorted({var}, key=lambda n: (-{var}[n], n)):\n"
            f"    print(name, {var}[name])")
    order = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))
    out = "\n".join(f"{nm} {c}" for nm, c in order)
    expl = ("Падения по тестам: " + ", ".join(f"{nm} — {c}" for nm, c in cnt.items())
            + f"; {', '.join(sorted(only_pass))} "
            + ("только проходил — в словаре его нет" if len(only_pass) == 1 else "только проходили — в словаре их нет")
            + ". Ключ (-счётчик, имя): сначала "
              "больше падений, при равенстве — по алфавиту: " + ", ".join(f"{nm} {c}" for nm, c in order)
            + ". Ловушка — порядок при равных счётчиках задаёт имя, а не порядок появления в логе.")
    stem = (f"Анализ нестабильных тестов ({ctx}): программа считает, сколько раз падал каждый тест, и печатает "
            "сводку.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"log": entries}, language="python")
