"""backend.kafka.consumer_group_mcq — mcq_concept: партиции, consumer groups и простаивающие потребители.

Один подтип: в топике P партиций, в «нашей» группе C > P потребителей, топик читают ещё G − 1 групп.
Вопрос: сколько потребителей нашей группы простаивает и сколько раз будет обработано одно сообщение.
Ловушки: партиция в группе достаётся ровно одному потребителю (лишние простаивают), а каждая группа
получает все сообщения. Ключ проверяется исполнением модели: назначение партиций по алгоритму
RangeAssignor Kafka (сортировка участников, P // C подряд + по одной первым P % C) и доставка
каждого сообщения всем группам.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, plural
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.kafka.consumer_group_mcq"

# (контекст, топик, наша группа, другие группы)
CONTEXTS = [("платежи", "payments", "billing", ["antifraud", "analytics", "audit"]),
            ("заказы", "orders", "warehouse", ["notifications", "analytics", "crm"]),
            ("клики", "clicks", "recommender", ["dwh", "ab-tests", "monitoring"]),
            ("логи доступа", "access-log", "siem", ["archive", "metrics", "alerts"]),
            ("события доставки", "delivery-events", "tracking", ["sms", "dwh", "support"])]

SIM = """P, GROUPS = {P}, {groups!r}
OUR = {our!r}


def range_assign(members, partitions):
    members = sorted(members)
    per, extra = divmod(partitions, len(members))
    out, start = {{}}, 0
    for i, m in enumerate(members):
        n = per + (1 if i < extra else 0)
        out[m] = list(range(start, start + n))
        start += n
    return out


assign = {{g: range_assign([f"{{g}}-{{i}}" for i in range(n)], P) for g, n in GROUPS.items()}}
idle = sum(1 for parts in assign[OUR].values() if not parts)
deliveries = 0
msg_partition = 0  # любое сообщение лежит ровно в одной партиции
for g, a in assign.items():
    owners = [m for m, parts in a.items() if msg_partition in parts]
    assert len(owners) <= 1  # в группе партицию читает не больше одного потребителя
    deliveries += len(owners)
OPTIONS = {options!r}
print(next(k for k, v in OPTIONS.items() if v == (idle, deliveries)))
"""


def _times(n: int) -> str:
    return f"{n} раза" if n in (2, 3, 4) else f"{n} раз"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, topic, our, others = rng.choice(CONTEXTS)
    P = rng.randint(2, 8)
    C = P + rng.randint(1, 4)
    n_other = rng.randint(1, 3)
    other = rng.sample(others, n_other)
    groups = {our: C}
    for g in other:
        groups[g] = rng.randint(1, P + 2)
    G = len(groups)
    idle = C - P
    pairs = [(idle, G), (0, G), (idle, 1), (0, 1)]
    text = lambda p: f"Простаивают {p[0]}; каждое сообщение обрабатывается {_times(p[1])}"
    opts, key = make_options(rng, (text(pairs[0]), None), [(text(p), None) for p in pairs[1:]])
    mapping = {o.id: pairs[[text(p) for p in pairs].index(o.text)] for o in opts}
    program = SIM.format(P=P, groups=groups, our=our, options=mapping)
    checks = [Check(name="simulate", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=key, embeds_display_code=False)]
    others_txt = ", ".join(f"`{g}` ({n} экз.)" for g, n in groups.items() if g != our)
    stem = (f"Kafka, {ctx}: топик `{topic}` с {P} партициями. Группа потребителей `{our}` запущена в {C} "
            f"экземплярах; топик также читают группы {others_txt}. Все экземпляры работают, ребалансировка "
            f"завершена. Сколько экземпляров группы `{our}` простаивают без партиций и сколько раз всего "
            f"(по всем группам) будет обработано одно сообщение топика?")
    why = (f"В группе каждую партицию читает ровно один потребитель: {P} {plural(P, "партиция", "партиции", "партиций")} на {C} {plural(C, "экземпляр", "экземпляра", "экземпляров")} — "
           f"{idle} без партиций. Группы независимы: каждая получает все сообщения, поэтому сообщение "
           f"обработают {G} {plural(G, "группа", "группы", "групп")} — по одному разу в каждой. Масштабировать группу выше числа партиций "
           f"бесполезно.")
    ak = AnswerKey(kind="option", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Показанного кода нет; исполняется модель назначения партиций "
                                           "(RangeAssignor) и доставки по группам.",
                         params={"P": P, "C": C, "G": G})
