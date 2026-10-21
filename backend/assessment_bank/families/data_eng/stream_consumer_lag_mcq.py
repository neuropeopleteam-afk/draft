"""data_eng.stream.consumer_lag_mcq — mcq_concept: отставание группы Kafka и время, за которое она догонит поток.

Показан вывод `kafka-consumer-groups --describe` без колонки LAG: для каждой партиции CURRENT-OFFSET (зафиксированный
offset группы — следующий к чтению) и LOG-END-OFFSET. Отставание партиции — LOG-END-OFFSET − CURRENT-OFFSET
(документация Apache Kafka, «Consumer groups», kafka-consumer-groups.sh). Каждую партицию читает свой экземпляр;
продюсер пишет p сообщений/с в каждую партицию, экземпляр обрабатывает c > p сообщений/с, поэтому отставание партиции
сокращается на (c − p) в секунду, и группа догоняет поток, когда догонит самая отстающая партиция:
t = max(lag_i) / (c − p). Дистракторы — фиксированный состав типовых ошибок: сумма отставаний на (c − p) («один
поток»), max(lag_i) / c (входящий поток не учтён), среднее отставание на (c − p). Ключ — исполнение модели над
показанной таблицей в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, pick_ranked, plural
from assessment_bank.schema import AnswerKey, Check

from ..devops._yaml_model import program

FAMILY_ID = "data_eng.stream.consumer_lag_mcq"

CTX = [("события заказов", "orders-events", "dwh-loader"), ("клики на сайте", "clicks", "sessionizer"),
       ("логи платёжного шлюза", "payments-log", "siem-export"), ("телеметрия курьеров", "courier-gps", "eta-model"),
       ("изменения цен", "price-updates", "search-indexer"), ("CDC таблицы клиентов", "cdc.customers", "lake-sink")]

MODEL = '''
rows = [line.split() for line in TABLE.splitlines()[1:]]
lags = [int(r[4]) - int(r[3]) for r in rows]          # LOG-END-OFFSET − CURRENT-OFFSET
net = CONSUME - PRODUCE                                 # на сколько в секунду сокращается отставание партиции
minutes = max(lags) / net / 60                          # группа догонит, когда догонит худшая партиция
print(f"{minutes:.1f}".replace(".", ",") + " мин")
'''


_LAG_ERR = {"sum": "сумма отставаний, как будто одна партиция", "group_rate": "скорость c − p на всю группу, а не на "
            "каждую партицию", "seconds": "секунды вместо минут", "no_produce": "деление на скорость обработки — "
            "входящий поток забыт", "avg": "среднее отставание вместо худшей партиции", "c_plus_p": "деление на c + p",
            "hours": "часы вместо минут"}


def _fmt(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + " мин"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, topic, group = rng.choice(CTX)
    n_below = rng.randrange(4)  # ранг ключа среди вариантов — равномерный (аудит 21.10: ключ всегда был медианой)
    for _ in range(5000):
        P = rng.randint(3, 6)
        produce = rng.choice([20, 40, 50, 80, 100, 150])
        consume = produce + rng.choice([30, 50, 60, 100, 120, 200])
        net = consume - produce
        base = rng.randint(120_000, 2_400_000)
        cur = [base + rng.randint(0, 900_000) for _ in range(P)]
        # одна партиция заметно отстаёт сильнее остальных (горячий ключ или медленный экземпляр)
        lags = [rng.randint(2, 40) * net * 6 for _ in range(P)]
        hot = rng.randrange(P)
        lags[hot] = max(lags) + rng.randint(10, 60) * net * 6
        leo = [c + lg for c, lg in zip(cur, lags)]
        right = max(lags) / net / 60
        if right > 240:
            continue
        # Типовые ошибки (по обе стороны от ключа): сумма отставаний — «один поток»; скорость c − p на всю группу,
        # а не на партицию (×P); секунды вместо минут; деление на c — входящий поток забыт; среднее отставание;
        # деление на c + p; часы вместо минут.
        pool = {"sum": sum(lags) / net / 60, "group_rate": P * max(lags) / net / 60, "seconds": max(lags) / net,
                "no_produce": max(lags) / consume / 60, "avg": sum(lags) / P / net / 60,
                "c_plus_p": max(lags) / (consume + produce) / 60, "hours": max(lags) / net / 3600}
        pool = {k: v for k, v in pool.items() if 0.1 <= v <= 50_000}
        picked = pick_ranked(rng, right, pool, n_below, fmt=_fmt)
        if picked:
            texts = [_fmt(right)] + [_fmt(pool[n]) for n in picked]
            break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    wg, wt = max(len(group), 5) + 2, max(len(topic), 5) + 2
    head = f"{'GROUP':<{wg}}{'TOPIC':<{wt}}{'PARTITION':<11}{'CURRENT-OFFSET':<16}LOG-END-OFFSET"
    lines = [head] + [f"{group:<{wg}}{topic:<{wt}}{i:<11}{cur[i]:<16}{leo[i]}" for i in range(P)]
    table = "\n".join(lines)
    opts, key = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]])
    stem = (f"Kafka, {ctx}: группа `{group}` читает топик `{topic}` ({P} {plural(P, 'партиция', 'партиции', 'партиций')}, по одному экземпляру на "
            f"партицию). После сбоя экземпляры простаивали разное время; сейчас все снова работают. Вывод `kafka-consumer-groups --describe` (колонку LAG "
            f"обрезали) — ниже. Продюсер пишет в каждую партицию {produce} сообщений/с, каждый экземпляр обрабатывает "
            f"{consume} сообщений/с; скорости не меняются, ребалансировок нет. Через сколько минут отставание группы "
            "станет нулевым по всем партициям?")
    expl = (f"Отставание партиции — LOG-END-OFFSET − CURRENT-OFFSET; максимум — {max(lags)} у партиции {hot}. Каждая "
            f"партиция догоняет независимо со скоростью {consume} − {produce} = {net} сообщений/с, поэтому время "
            f"определяет худшая: {max(lags)} / {net} / 60 = {texts[0]}. Дистракторы — типовые ошибки: "
            + "; ".join(f"{_fmt(pool[n])} — {_LAG_ERR[n]}" for n in picked) + ".")
    prog = program(f"PRODUCE, CONSUME = {produce}, {consume}\n" + MODEL, TABLE=table)
    checks = [Check(name="lag_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=texts[0], embeds_display_code=False)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=table, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Показан вывод kafka-consumer-groups; исполняется модель отставания по "
                                           "показанной таблице",
                         params={"P": P, "produce": produce, "consume": consume, "hot": hot, "traps": picked})
