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

from assessment_bank.gen_utils import build_variant, make_options, make_rng, plural
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


def _fmt(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + " мин"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, topic, group = rng.choice(CTX)
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
        wrong = [sum(lags) / net / 60, max(lags) / consume / 60, sum(lags) / P / net / 60]
        texts = [_fmt(right)] + [_fmt(w) for w in wrong]
        if len(set(texts)) == 4 and right <= 240:
            break
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
            f"определяет худшая: {max(lags)} / {net} / 60 = {texts[0]}. Сумма отставаний на {net} — это как будто "
            f"одна партиция; деление на {consume} забывает входящий поток; среднее не учитывает самую отстающую.")
    prog = program(f"PRODUCE, CONSUME = {produce}, {consume}\n" + MODEL, TABLE=table)
    checks = [Check(name="lag_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=texts[0], embeds_display_code=False)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=table, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Показан вывод kafka-consumer-groups; исполняется модель отставания по "
                                           "показанной таблице",
                         params={"P": P, "produce": produce, "consume": consume, "hot": hot})
