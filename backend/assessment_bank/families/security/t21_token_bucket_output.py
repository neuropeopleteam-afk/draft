"""security.rate.t21_token_bucket_output — predict_output (набор t21, порог Senior): ведро токенов —
`tokens = min(C, tokens + (t - last) * r)`, пропуск при `tokens >= 1`, ответ 429.

Ограничитель частоты на каждом запросе пополняет ведро за прошедшее время (с потолком ёмкости), затем списывает
токен или отвечает 429. Ловушки: потолок min(C, …) срезает накопление за паузу; запросы в одну секунду не
пополняют ведро; в части вариантов `last = t` стоит только в ветке успеха — тогда после отказа время с последнего
успеха прибавляется повторно (двойное пополнение). Ключ — независимая модель в генераторе; проверка —
исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.rate.t21_token_bucket_output"

CTX = ["API входа", "отправка SMS-кодов", "восстановление пароля", "поиск по каталогу", "API платежей",
       "проверка промокодов"]


NAMES = [("CAP", "RATE", "tokens", "last", "t", ""), ("capacity", "refill", "bucket", "prev", "now", ""),
         ("C", "R", "left", "last_ts", "ts", ""), ("BURST", "PER_SEC", "allowance", "seen_at", "sec", "")]


def _model(cap: int, rate: int, times: list[int], last_on_success: bool) -> list[tuple[int, str, int]]:
    tokens, last, res = cap, 0, []
    for t in times:
        gained = (t - last) * rate
        tokens = cap if tokens + gained > cap else tokens + gained
        if not last_on_success:
            last = t
        if tokens >= 1:
            tokens -= 1
            if last_on_success:
                last = t
            res.append((t, "ok", tokens))
        else:
            res.append((t, "429", tokens))
    return res


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    last_on_success = rng.random() < 0.5
    for _ in range(300):
        cap = rng.randint(2, 4)
        rate = rng.choice([1, 1, 2])
        n = rng.randint(6, 8)
        times, t = [], 0
        for _i in range(n):
            t += rng.choice([0, 0, 0, 1, 1, 2, 3])
            times.append(t)
        res = _model(cap, rate, times, last_on_success)
        alt = _model(cap, rate, times, not last_on_success)
        n429 = sum(1 for _t, s, _k in res if s == "429")
        if 1 <= n429 <= n - 2 and (res != alt or rng.random() < 0.2):
            break
    else:
        raise RuntimeError("t21_token_bucket: не собралась последовательность")
    cv, rv, tv, lv, xv, _ = rng.choice(NAMES)
    upd_before = f"    {lv} = {xv}\n" if not last_on_success else ""
    upd_ok = f"        {lv} = {xv}\n" if last_on_success else ""
    code = (f"{cv}, {rv} = {cap}, {rate}\n"
            f"{tv}, {lv} = {cv}, 0\n"
            f"for {xv} in {times}:\n")
    code += (f"    {tv} = min({cv}, {tv} + ({xv} - {lv}) * {rv})\n"
             f"{upd_before}"
             f"    if {tv} >= 1:\n"
             f"        {tv} -= 1\n"
             f"{upd_ok}"
             f'        print({xv}, "ok", {tv})\n'
             "    else:\n"
             f"        print({xv}, 429, {tv})")
    out = "\n".join(f"{t} {s} {k}" for t, s, k in res)
    where = (f"{lv} обновляется только при успехе: после отказа следующий запрос снова прибавляет время с "
             "последнего успешного, то есть пополнение за эти секунды учитывается дважды" if last_on_success
             else f"{lv} обновляется на каждом запросе, поэтому каждая секунда пополняет ведро один раз")
    expl = (f"Ёмкость {cap}, пополнение {rate} в секунду, старт с полным ведром и {lv} = 0. Каждый запрос: "
            f"{tv} = min({cap}, {tv} + ({xv} − {lv})·{rate}); при {tv} >= 1 списывается токен, иначе 429. "
            f"Здесь {where}. Трассировка: " + "; ".join(f"{xv}={t} → {st}, осталось {k}" for t, st, k in res) +
            f". Вывод: «{out.replace(chr(10), ' / ')}».")
    stem = (f"Ограничитель частоты ({ctx}) пропускает запросы по алгоритму ведра токенов; в списке — секунды, "
            "в которые пришли запросы одного клиента.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"cap": cap, "rate": rate, "times": times, "last_on_success": last_on_success},
                          language="python")
