"""common.db.principal_quorum_latency_mcq — mcq_concept (Principal): кворум записи и чтения в реплицированном хранилище.

N реплик в разных зонах, координатор знает RTT до каждой. Запись подтверждается после W ответов, чтение собирает R
ответов; чтение видит последнюю подтверждённую запись, если кворумы пересекаются: R + W > N. Ограничения: W ≥ 2
(подтверждённая запись переживает потерю узла) и задержка чтения (R-й по скорости ответ) не больше бюджета. Вопрос:
наименьшая задержка записи (W-й по скорости ответ). Ловушки: W = 1, без бюджета чтения, R + W ≥ N (на единицу
меньше), «все реплики», большинство без учёта бюджета, сумма задержек записи и чтения, следующий допустимый W.
``brute`` перебирает все пары (W, R) — независимо от формулы R = N − W + 1.
"""
from __future__ import annotations

from assessment_bank.families._w2010_kit import numeric_variant
from assessment_bank.gen_utils import plural

FAMILY_ID = "common.db.principal_quorum_latency_mcq"
CONTEXTS = ["хранилище корзин", "хранилище сессий", "хранилище профилей", "журнал платежей",
            "хранилище счётчиков лайков", "хранилище настроек", "каталог товаров", "хранилище статусов заказов"]
ZONES = ["та же зона", "соседняя зона", "второй ЦОД в городе", "другой регион", "дальний регион", "резервный ЦОД",
         "третий ЦОД"]

MODEL = '''
def kth(P, k):
    return sorted(P["rtt"])[k - 1]

def feasible(P, w, r):
    return w >= 2 and r + w > len(P["rtt"]) and kth(P, r) <= P["B"]

def answer(P):
    n = len(P["rtt"])
    ws = [w for w in range(2, n + 1) if feasible(P, w, n - w + 1)]
    return kth(P, min(ws)) if ws else None

def brute(P):
    n = len(P["rtt"])
    best = None
    for w in range(1, n + 1):
        for r in range(1, n + 1):
            if feasible(P, w, r):
                lat = kth(P, w)
                best = lat if best is None or lat < best else best
    return best

def traps(P):
    n = len(P["rtt"])
    a = answer(P)
    ws = [w for w in range(2, n + 1) if feasible(P, w, n - w + 1)]
    off = [w for w in range(2, n + 1) if n - w >= 1 and kth(P, n - w) <= P["B"]]
    w0 = min(ws) if ws else n
    nxt = [w for w in ws if kth(P, w) > a]
    return {"w1": kth(P, 1), "no_read_budget": kth(P, 2), "off_by_one": kth(P, min(off)) if off else None,
            "all": kth(P, n), "majority": kth(P, n // 2 + 1), "sum": a + kth(P, n - w0 + 1),
            "next_w": kth(P, min(nxt)) if nxt else None}

def fmt(x):
    return f"{x} мс"
'''


def _sample(rng):
    n = rng.choice([3, 5, 5, 7])
    rtt = sorted(rng.sample([1, 2, 3, 4, 6], 2) + rng.sample(range(8, 40), max(1, n // 2 - 1))
                 + rng.sample(range(45, 140), n - 2 - max(1, n // 2 - 1)))
    return {"rtt": rtt, "B": rng.choice(rtt[1:]) + rng.choice([0, 1, 3])}


def _accept(P, ns):
    return ns["answer"](P) is not None


def _stem(P, ctx):
    n = len(P["rtt"])
    rows = "\n".join(f"• реплика {i + 1} ({ZONES[min(i, len(ZONES) - 1)]}) — {t} мс" for i, t in enumerate(P["rtt"]))
    return (f"{ctx[0].upper() + ctx[1:]} — {n} {plural(n, 'реплика', 'реплики', 'реплик')} без лидера. Координатор "
            f"подтверждает запись после W ответов, чтение собирает R ответов и берёт самую свежую версию. RTT от "
            f"координатора (обработка на реплике входит в RTT):\n{rows}\n\nТребования: чтение сразу после "
            f"подтверждённой записи видит её (кворумы записи и чтения пересекаются); подтверждённая запись переживает "
            f"потерю любого одного узла (W ≥ 2); задержка чтения — не больше {P['B']} мс. Ответы реплик приходят "
            f"параллельно. Какая наименьшая задержка записи достижима?")


def _explain(P, a, traps):
    n = len(P["rtt"])
    ws = [w for w in range(2, n + 1) if n - w + 1 >= 1 and sorted(P["rtt"])[n - w] <= P["B"]]
    w = min(ws)
    return (f"Кворумы пересекаются при R + W > N, то есть R = N − W + 1. Задержка записи — W-й по скорости ответ, "
            f"чтения — R-й. При W = {w}, R = {n - w + 1}: чтение {sorted(P['rtt'])[n - w]} мс ≤ {P['B']} мс, запись "
            f"{a} мс; меньший W (с W ≥ 2) требует большего R, и чтение выходит за бюджет.")


TRAP_DESC = {"w1": "W = 1 — подтверждённая запись теряется вместе с узлом", "no_read_budget": "W = 2 без бюджета чтения",
             "off_by_one": "R + W ≥ N — кворумы могут не пересекаться", "all": "ожидание всех реплик",
             "majority": "большинство без учёта бюджета чтения", "sum": "сложены задержки записи и чтения",
             "next_w": "не наименьший допустимый W"}


def generate(seed: int):
    return numeric_variant(FAMILY_ID, seed, contexts=CONTEXTS, sample=_sample, model=MODEL, stem=_stem,
                           explain=_explain, accept=_accept, rel=0.08, abs_min=2, trap_first="off_by_one",
                           trap_desc=TRAP_DESC)
