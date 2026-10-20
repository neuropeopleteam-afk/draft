"""common.http.principal_retry_amplification_mcq — mcq_concept (Principal): нагрузка на упавшую зависимость от повторов.

Цепочка из d слоёв (шлюз → сервисы → зависимость); слой i при ошибке повторяет вызов до r_i раз (1 + r_i попыток).
Во время полного отказа нижней зависимости повторы перемножаются по слоям. Верхний слой ограничен дедлайном клиента
D: попытка ждёт таймаут t, перед повтором — пауза b, затем 2b, 4b, …; попытки, которые не успевают начаться и
закончиться до дедлайна, не делаются. Внутренние слои успевают все свои попытки. Вопрос: сколько обращений в секунду
получит зависимость при потоке λ запросов клиента. Ответ: λ · k_top · Π_{i≥2}(1 + r_i), где k_top — число попыток
верхнего слоя, укладывающихся в дедлайн. Ловушки: без дедлайна, сумма вместо произведения, только верхний слой,
забыт первый вызов (Π r_i), дедлайн применён ко всем слоям, наибольшее r на всех слоях. ``brute`` — пошаговая
имитация дерева вызовов одного запроса.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import num, numeric_variant
from assessment_bank.gen_utils import plural

FAMILY_ID = "common.http.principal_retry_amplification_mcq"
CONTEXTS = ["оформление заказа", "оплата картой", "поиск рейсов", "выдача ленты", "проверка остатков", "расчёт доставки",
            "подбор тарифа", "авторизация платежа"]
LAYERS = ["шлюз", "сервис заказов", "сервис цен", "сервис остатков", "адаптер"]

MODEL = '''
def k_top(P):
    k, pause, used = 0, P["b"], 0
    for i in range(1 + P["r"][0]):
        need = used + (pause if i > 0 else 0) + P["t"]
        if need > P["D"]:
            break
        if i > 0:
            pause_used = pause
            pause *= 2
        used = need
        k += 1
    return k

def prod(xs):
    out = 1
    for x in xs:
        out *= x
    return out

def answer(P):
    return P["lam"] * k_top(P) * prod(1 + r for r in P["r"][1:])

def brute(P):
    def calls(layer):
        if layer == len(P["r"]):
            return 1
        n = 0
        attempts = k_top(P) if layer == 0 else 1 + P["r"][layer]
        for _ in range(attempts):
            n += calls(layer + 1)
        return n
    return P["lam"] * calls(0)

def traps(P):
    lam, r = P["lam"], P["r"]
    kt = k_top(P)
    return {"no_deadline": lam * prod(1 + x for x in r), "sum": lam * sum(1 + x for x in r),
            "top_only": lam * kt, "no_first": lam * max(kt - 1, 1) * prod(max(x, 1) for x in r[1:]),
            "deadline_all": lam * kt ** len(r), "max_r": lam * (1 + max(r)) ** len(r),
            "inner_only": lam * prod(1 + x for x in r[1:])}

def fmt(x):
    return f"{x:,} в секунду".replace(",", "\\u00a0")
'''


def _sample(rng):
    d = rng.choice([3, 4])
    return {"r": [rng.choice([2, 3, 4, 5])] + [rng.choice([1, 2, 3]) for _ in range(d - 1)],
            "lam": rng.choice([40, 50, 80, 120, 150, 200, 300]), "t": rng.choice([200, 250, 300, 400, 500]),
            "b": rng.choice([50, 100, 150, 200]), "D": rng.choice([800, 1000, 1200, 1500, 2000])}


def _accept(P, ns):
    kt = ns["k_top"](P)
    return 2 <= kt < 1 + P["r"][0]


def _stem(P, ctx):
    d = len(P["r"])
    rows = "\n".join(f"• {LAYERS[i]} — до {r} {plural(r, 'повтора', 'повторов', 'повторов')}"
                     if r > 1 else f"• {LAYERS[i]} — до 1 повтора" for i, r in enumerate(P["r"]))
    return (f"Сценарий «{ctx}»: запрос клиента проходит {d} {plural(d, 'слой', 'слоя', 'слоёв')}, каждый вызывает "
            f"следующий, последний — общую зависимость. При ошибке слой повторяет свой вызов (без бюджета повторов):\n"
            f"{rows}\n\nЗависимость полностью отказала и сразу возвращает ошибку внутренним слоям; поток клиентов — "
            f"{P['lam']} запросов в секунду. У верхнего слоя (шлюза) дедлайн клиента {P['D']} мс: попытка ждёт таймаут "
            f"{P['t']} мс, перед повтором — пауза {P['b']} мс, перед каждым следующим — вдвое больше; попытка, которая "
            f"не успевает закончиться до дедлайна, не начинается. Внутренние слои успевают все свои попытки.\n\n"
            "Сколько обращений в секунду получает упавшая зависимость?")


def _explain(P, a, traps):
    ns = {}
    exec(compile(MODEL, "<m>", "exec"), ns)
    kt = ns["k_top"](P)
    inner = " · ".join(f"(1 + {r})" for r in P["r"][1:])
    return (f"Повторы перемножаются по слоям. Шлюз в дедлайн {P['D']} мс успевает {kt} "
            f"{plural(kt, 'попытку', 'попытки', 'попыток')} из {1 + P['r'][0]}; внутренние слои — все: "
            f"{P['lam']} · {kt} · {inner} = {num(a)} обращений в секунду.")


TRAP_DESC = {"no_deadline": "без дедлайна шлюза", "sum": "попытки слоёв сложены, а не перемножены",
             "top_only": "только повторы шлюза", "no_first": "забыт первый вызов (произведение r_i, а не 1 + r_i)",
             "deadline_all": "дедлайн шлюза применён ко всем слоям", "max_r": "наибольшее r на всех слоях",
             "inner_only": "без повторов шлюза"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.1, abs_min=5, trap_first="no_deadline",
                           trap_desc=TRAP_DESC)
