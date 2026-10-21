"""security.auth.lp3_bruteforce_guesses_output — predict_output: сколько паролей атакующий проверит за сутки.

Защита входа: лимит попыток с одного IP в минуту; блокировка учётной записи на L минут после k неудачных попыток
подряд (счётчик сбрасывается разблокировкой). Атакующий перебирает пароли по m учётным записям с n IP-адресов,
действует оптимально (не тратит попытки на заблокированные записи). Нужно максимум проверенных паролей за 24 часа:
min(лимит по IP · n · 1440, лимит по учётным записям), где учётная запись даёт k попыток за каждый цикл
«k попыток + L минут блокировки». Ловушки: учесть только лимит по IP; только блокировку; забыть, что k попыток
укладываются в цикл, а не по одной на L минут. Ответ — целое число.
"""
from __future__ import annotations

from assessment_bank.families._lp3_kit import num_accept, typed_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.auth.lp3_bruteforce_guesses_output"
APPS = ["личный кабинет банка", "панель администратора", "почтовый сервис", "CRM", "портал госуслуг партнёра"]

CALC = r'''
import re
v = {}
for l in DATA.splitlines():
    m = re.match(r"^([^:]+):\s*(\d+)", l)
    if m:
        v[m.group(1).strip()] = int(m.group(2))
ip = v["попыток с одного IP в минуту"] * v["IP-адресов у атакующего"] * 1440
k, L, m = v["неудачных попыток до блокировки"], v["блокировка, мин"], v["учётных записей-целей"]
cycles = 1440 // L + (1 if 1440 % L else 0)
acc = m * k * cycles
print(min(ip, acc))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    app = rng.choice(APPS)
    for _ in range(3000):
        per_ip = rng.choice([3, 5, 10, 20, 30])
        n = rng.choice([1, 2, 5, 10, 50, 200])
        k = rng.choice([3, 5, 10])
        L = rng.choice([15, 30, 60, 90, 240])
        m = rng.choice([1, 3, 10, 50, 200, 1000])
        ip = per_ip * n * 1440
        cycles = 1440 // L + (1 if 1440 % L else 0)
        acc = m * k * cycles
        good = min(ip, acc)
        only_lock_naive = m * (1440 // L)        # по одной попытке на период блокировки
        if good in (ip, acc) and ip == acc or good == only_lock_naive:
            continue
        if rng.random() < 0.5 and good == ip:
            continue  # чаще ограничивает блокировка
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось подобрать параметры")
    block = "\n".join([f"попыток с одного IP в минуту: {per_ip}", f"IP-адресов у атакующего: {n}",
                       f"неудачных попыток до блокировки: {k}", f"блокировка, мин: {L}",
                       f"учётных записей-целей: {m}"])
    stem = (f"Моделирование угроз для входа в «{app}». Защиты и ресурсы атакующего — ниже. Блокировка срабатывает "
            "после указанного числа неудачных попыток подряд и снимается сама через заданное время (тогда снова "
            "доступна полная серия попыток); атакующий распределяет попытки по учётным записям и IP оптимально и "
            "начинает в начале суток. Сколько паролей он сможет проверить за 24 часа в худшем для нас случае? "
            "Ответ — целое число.")
    expl = (f"Ограничение по IP: {per_ip} · {n} · 1440 = {ip}. По блокировке: циклов за сутки ⌈1440 / {L}⌉ = {cycles} "
            f"(серия из {k} попыток в начале каждого), записей {m} → {m} · {k} · {cycles} = {acc}. Итог — меньшее: "
            f"{good}. Ошибка «одна попытка за период блокировки» — {only_lock_naive}. Вывод: лимит по IP почти не "
            "защищает от распределённого перебора, нужна защита на уровне учётной записи и второй фактор.")
    return typed_variant(FAMILY_ID, seed, stem=stem, block=block, calc=CALC, out=str(good), expl=expl, ctx=app,
                         accept=num_accept(good, ("паролей", "попыток")),
                         params={"per_ip": per_ip, "n": n, "k": k, "L": L, "m": m})
