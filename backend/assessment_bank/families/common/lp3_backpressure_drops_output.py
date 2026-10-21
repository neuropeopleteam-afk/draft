"""common.queues.lp3_backpressure_drops_output — predict_output: сколько сообщений потеряется при всплеске.

Очередь перед обработчиками: ёмкость Q, обработчики забирают μ сообщений в минуту (не больше, чем есть).
Поступления по минутам заданы. Каждую минуту: сначала приходят новые (что не влезло в очередь — отбрасывается),
затем обработчики забирают до μ. Нужно число отброшенных сообщений. Ловушки: сравнить среднее поступление с μ
(«в среднем справляемся — потерь нет»); обрабатывать до прихода; забыть, что очередь не сбрасывается между
минутами. Ответ — целое число.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.queues.lp3_backpressure_drops_output"
SVCS = ["приём заказов", "обработка платежей", "рассылка уведомлений", "импорт прайс-листов", "приём телеметрии"]

CALC = r'''
import re
v, arr = {}, []
for l in DATA.splitlines():
    if l.startswith("поступления"):
        arr = [int(x) for x in l.split(":", 1)[1].split(";")]
    else:
        m = re.match(r"^([^:]+):\s*(\d+)", l)
        if m:
            v[m.group(1).strip()] = int(m.group(2))
Q, mu = v["ёмкость очереди"], v["обработка, сообщений в минуту"]
q, drop = 0, 0
for a in arr:
    room = Q - q
    drop += max(0, a - room)
    q = min(Q, q + a)
    q -= min(q, mu)
print(drop)
'''


def _sim(arr, Q, mu, process_first=False):
    q, drop = 0, 0
    for a in arr:
        if process_first:
            q -= min(q, mu)
        room = Q - q
        drop += max(0, a - room)
        q = min(Q, q + a)
        if not process_first:
            q -= min(q, mu)
    return drop


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    svc = rng.choice(SVCS)
    for _ in range(3000):
        mu = rng.choice([100, 150, 200, 300, 500])
        Q = rng.choice([200, 300, 500, 800, 1000])
        n = rng.randint(8, 12)
        arr = [int(mu * rng.choice([0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])) for _ in range(n)]
        b0 = rng.randrange(n - 3)
        for i in range(b0, b0 + rng.randint(2, 3)):  # всплеск — несколько минут подряд
            arr[i] = int(mu * rng.choice([1.5, 2.0, 2.5, 3.0, 4.0]))
        good = _sim(arr, Q, mu)
        pf = _sim(arr, Q, mu, process_first=True)
        avg_ok = sum(arr) / n <= mu
        if good == 0 or not avg_ok and rng.random() < 0.7:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    block = "\n".join([f"ёмкость очереди: {Q}", f"обработка, сообщений в минуту: {mu}",
                       "поступления по минутам: " + "; ".join(map(str, arr))])
    stem = (f"Сервис «{svc}»: перед обработчиками очередь ограниченной ёмкости (блок ниже), в начале пустая. Каждую "
            "минуту сначала приходят новые сообщения — то, что не помещается в очередь, отбрасывается, — затем "
            "обработчики забирают из очереди не больше своей скорости. Сколько сообщений будет отброшено за всё "
            "время? Ответ — целое число.")
    expl = (f"Пошагово: место = {Q} − очередь, отброшено += max(0, приход − место), затем очередь −= min(очередь, {mu}). "
            f"Итого {good}. Среднее поступление {sum(arr) / n:.0f} в минуту при скорости {mu} создаёт иллюзию «потерь "
            f"нет»{'; обработка до прихода даёт ' + str(pf) if pf != good else ''}. Вывод: всплески решает ёмкость и обратное давление, а не среднее.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=svc,
                         accept=num_accept(good, ("сообщений", "сообщения")), params={"Q": Q, "mu": mu, "arr": arr})
