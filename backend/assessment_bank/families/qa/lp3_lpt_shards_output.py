"""qa.ci.lp3_lpt_shards_output — predict_output: сколько шардов CI нужно, чтобы уложиться во время прогона.

Набор тестовых файлов с длительностями; раннер распределяет файлы по шардам жадно «самый длинный — в наименее
загруженный шард» (LPT), файл не делится. Каждый шард тратит фиксированное время на подготовку окружения.
Прогон = подготовка + самая загруженная очередь. Вопрос — минимальное число шардов, при котором прогон не
дольше цели. Ловушки: ceil(сумма / цель) без учёта подготовки и неделимости файлов; не заметить, что самый
длинный файл задаёт нижнюю границу. Ответ — целое число.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.ci.lp3_lpt_shards_output"
SUITES = ["e2e витрины", "интеграционные тесты API", "UI-тесты мобильного приложения", "регресс биллинга",
          "контрактные тесты", "тесты миграций БД"]
PREFIX = ["test_checkout", "test_auth", "test_search", "test_cart", "test_profile", "test_orders", "test_promo",
          "test_delivery", "test_payments", "test_reports", "test_admin", "test_import", "test_export",
          "test_notifications", "test_settings", "test_catalog", "test_reviews", "test_refunds", "test_sso", "test_api"]

CALC = r'''
import re, heapq
setup = target = None
files = []
for l in DATA.splitlines():
    if l.startswith("подготовка шарда"):
        setup = float(l.split(":")[1].split()[0].replace(",", "."))
    elif l.startswith("цель прогона"):
        target = float(l.split(":")[1].split()[0].replace(",", "."))
    elif l.count("|") == 1 and not l.startswith("файл"):
        f, d = [x.strip() for x in l.split("|")]
        files.append(float(d.replace(",", ".")))
def run(k):
    h = [0.0] * k
    for d in sorted(files, reverse=True):
        heapq.heapreplace(h, h[0] + d)
    return setup + max(h)
k = 1
while run(k) > target + 1e-9:
    k += 1
print(k)
'''


def _run(files, k, setup):
    import heapq
    h = [0.0] * k
    for d in sorted(files, reverse=True):
        heapq.heapreplace(h, h[0] + d)
    return setup + max(h)


def _n(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    suite = rng.choice(SUITES)
    for _ in range(4000):
        n = rng.randint(12, 18)
        files = [rng.choice([0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 11, 13]) for _ in range(n)]
        setup = rng.choice([1, 1.5, 2, 3, 4])
        target = rng.choice([8, 10, 12, 15, 20])
        if max(files) + setup > target:
            continue
        k = 1
        while _run(files, k, setup) > target + 1e-9 and k < 40:
            k += 1
        if k >= 40 or k < 3:
            continue
        naive = -(-sum(files) // target)
        naive2 = -(-sum(files) // (target - setup))
        if k in (naive,) or (k == naive2 and rng.random() < 0.6):
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    names = rng.sample(PREFIX, n)
    lines = [f"подготовка шарда: {_n(setup)} мин", f"цель прогона: {_n(target)} мин", "", "файл | мин"]
    for nm, d in zip(names, files):
        lines.append(f"{nm}.py | {_n(d)}")
    block = "\n".join(lines)
    stem = (f"Набор «{suite}» в CI. Раннер раскладывает тестовые файлы по шардам так: файлы по убыванию "
            "длительности, каждый — в шард с наименьшей текущей суммой; файл целиком идёт в один шард. Каждый шард "
            "сначала тратит время на подготовку окружения, шарды работают параллельно, прогон заканчивается вместе с "
            "самым загруженным. Какое наименьшее число шардов нужно, чтобы прогон занимал не больше цели? "
            "Ответ — целое число.")
    expl = (f"Сумма {_n(sum(files))} мин, самый длинный файл {_n(max(files))} мин, подготовка {_n(setup)} мин. "
            f"Раскладка по правилу раннера: при {k - 1} шардах прогон {_n(round(_run(files, k - 1, setup), 2))} мин > "
            f"{_n(target)}, при {k} — {_n(round(_run(files, k, setup), 2))} мин. Оценка ⌈сумма / цель⌉ = {naive} "
            f"не учитывает подготовку и неделимость файлов; ⌈сумма / (цель − подготовка)⌉ = {naive2} — неделимость.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(k), expl=expl, ctx=suite,
                         accept=num_accept(k, ("шардов", "шарда")),
                         params={"files": files, "setup": setup, "target": target})
