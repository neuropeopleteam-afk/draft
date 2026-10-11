"""devops.linux.cron_next_runs_mcq — mcq_concept: ближайшие запуски по строке crontab.

Поля cron (man 5 crontab): минута, час, день месяца, месяц, день недели (0 или 7 — воскресенье, 1 — понедельник);
`*/N` — значения, кратные N, от начала диапазона (а не от текущего момента); `a-b` — диапазон, `a,b` — список.
Пять видов строки: раз в сутки, */N минут, */N часов в заданную минуту, будни 1-5, два часа через запятую (день
месяца и день недели одновременно не ограничиваются). Дистракторы — типовые ошибки прочтения (порядок
подставляется из списка, пока не наберутся три различных): поля минут и часов перепутаны, */N отсчитано от
текущего момента, неделя с понедельника = 0, учтён уже прошедший сегодня момент, сдвиг на сутки. Ключ —
исполнение модели разбора полей cron над показанной строкой в песочнице Python.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import program

FAMILY_ID = "devops.linux.cron_next_runs_mcq"

CTX = [("резервная копия базы", "/opt/db/backup.sh"), ("ротация журналов", "/usr/local/bin/rotate-logs"),
       ("выгрузка отчёта", "/opt/reports/export.sh"), ("проверка сертификатов", "/opt/ops/check-certs.sh"),
       ("очистка временных файлов", "/opt/ops/cleanup-tmp.sh"), ("синхронизация справочников", "/opt/etl/sync.sh")]
DAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

MODEL = '''
from datetime import datetime, timedelta


def field(spec, lo, hi):
    out = set()
    for part in spec.split(","):
        if part.startswith("*/"):
            out |= set(range(lo, hi + 1, int(part[2:])))
        elif part == "*":
            out |= set(range(lo, hi + 1))
        elif "-" in part:
            a, b = map(int, part.split("-"))
            out |= set(range(a, b + 1))
        else:
            out.add(int(part))
    return out


m, h, dom, mon, dow = CRONTAB.split()[:5]
M, H, D, MO = field(m, 0, 59), field(h, 0, 23), field(dom, 1, 31), field(mon, 1, 12)
W = {d % 7 for d in field(dow, 0, 7)}
t = datetime.strptime(NOW, "%Y-%m-%d %H:%M") + timedelta(minutes=1)
runs = []
while len(runs) < 3:
    if t.minute in M and t.hour in H and t.day in D and t.month in MO and (t.isoweekday() % 7) in W:
        runs.append(t.strftime("%d.%m %H:%M"))
    t += timedelta(minutes=1)
print("; ".join(runs))
'''


def _fmt(ts):
    return "; ".join(t.strftime("%d.%m %H:%M") for t in ts)


def _next(now, pred, k=3):
    t, out = now + timedelta(minutes=1), []
    while len(out) < k:
        if pred(t):
            out.append(t)
        t += timedelta(minutes=1)
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, cmd = rng.choice(CTX)
    tpl = rng.choice(["daily", "every_n_min", "every_n_hours", "weekdays", "twice_daily"])
    for _ in range(500):
        now = datetime(2026, rng.randint(1, 11), rng.randint(1, 27), rng.randint(0, 23),
                       rng.choice([x for x in range(60) if x % 5]))  # «сейчас» не совпадает с запуском
        m = rng.choice([0, 5, 10, 15, 20, 30, 45])
        h = rng.randint(0, 23)
        wrong = []
        if tpl == "daily":
            spec = f"{m} {h} * * *"
            right = _next(now, lambda t: t.minute == m and t.hour == h)
            if m <= 23:  # поля перепутаны: час m, минута h
                wrong.append(_next(now, lambda t: t.minute == h and t.hour == m))
            today = now.replace(hour=h, minute=m)
            wrong.append([today + timedelta(days=i) for i in range(3)])
            wrong.append([r + timedelta(days=1) for r in right])
        elif tpl == "every_n_min":
            n = rng.choice([10, 15, 20, 25])
            spec = f"*/{n} * * * *"
            right = _next(now, lambda t: t.minute % n == 0)
            wrong.append([now + timedelta(minutes=n * i) for i in (1, 2, 3)])
            wrong.append(_next(now, lambda t: t.hour % n == 0 and t.minute == 0) if n <= 23 else [])
            wrong.append(_next(now, lambda t: t.minute % n == 0 and t.minute != 0))
            wrong.append([r + timedelta(minutes=n) for r in right])
        elif tpl == "every_n_hours":
            n = rng.choice([2, 3, 4, 6])
            spec = f"{m} */{n} * * *"
            right = _next(now, lambda t: t.minute == m and t.hour % n == 0)
            base = now.replace(minute=m)
            wrong.append([base + timedelta(hours=n * i) for i in (1, 2, 3)])
            wrong.append(_next(now, lambda t: t.minute == m and t.hour % n == 1))
            wrong.append(_next(now, lambda t: t.minute % n == 0 and t.hour == m) if m <= 23 else [])
        elif tpl == "weekdays":
            spec = f"{m} {h} * * 1-5"
            right = _next(now, lambda t: t.minute == m and t.hour == h and t.isoweekday() <= 5)
            wrong.append(_next(now, lambda t: t.minute == m and t.hour == h and 2 <= t.isoweekday() <= 6))
            wrong.append(_next(now, lambda t: t.minute == m and t.hour == h))
            wrong.append(_next(now, lambda t: t.minute == m and t.hour == h and t.isoweekday() <= 4))
        else:
            h2 = (h + rng.randint(3, 11)) % 24
            spec = f"{m} {min(h, h2)},{max(h, h2)} * * *"
            right = _next(now, lambda t: t.minute == m and t.hour in (h, h2))
            lo, hi = min(h, h2), max(h, h2)
            wrong.append(_next(now, lambda t: t.minute == m and lo <= t.hour <= hi))
            wrong.append(_next(now, lambda t: t.minute == m and t.hour == lo))
            wrong.append([r + timedelta(days=1) for r in right])
        texts = [_fmt(right)]
        for w in wrong:
            if w and _fmt(w) not in texts:
                texts.append(_fmt(w))
        if len(texts) >= 4:
            texts = texts[:4]
            break
    line = f"{spec} {cmd}"
    opts, key = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]])
    stem = (f"Задание «{ctx}» в crontab сервера (часовой пояс сервера, перевода часов нет). Сейчас "
            f"{DAYS[now.weekday()]}, {now:%d.%m.%Y %H:%M}. Когда будут три ближайших запуска (формат ДД.ММ ЧЧ:ММ)?")
    expl = {"daily": "Первое поле — минута, второе — час; если сегодняшний момент прошёл, первый запуск — завтра.",
            "every_n_min": "*/N в поле минут — минуты, кратные N (0, N, 2N…), а не каждые N минут от текущего момента.",
            "every_n_hours": "*/N в поле часов — часы, кратные N, от полуночи; минута фиксирована первым полем.",
            "weekdays": "1-5 в поле дня недели — с понедельника по пятницу (0 и 7 — воскресенье).",
            "twice_daily": "Список через запятую — ровно эти часы, а не диапазон."}[tpl] + f" Итог: {texts[0]}."
    prog = program(MODEL, CRONTAB=line, NOW=now.strftime("%Y-%m-%d %H:%M"))
    checks = [Check(name="cron_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=texts[0], embeds_display_code=False)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=line, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Показана строка crontab; исполняется модель разбора полей cron",
                         params={"template": tpl, "spec": spec})
