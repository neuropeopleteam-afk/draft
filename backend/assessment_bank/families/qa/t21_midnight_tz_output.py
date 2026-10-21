"""qa.time.t21_midnight_tz_output — predict_output (набор t21, порог Senior): события около полуночи
раскладываются по суткам UTC и по суткам Москвы — aware datetime и astimezone.

Журнал событий: часть отметок — по Москве (`timezone(timedelta(hours=3))`, клиент), часть — по UTC (сервер).
Каждое событие переводится astimezone в UTC и в МСК, считается число событий по датам для обоих способов.
Ловушки: отметка МСК 00:00–02:59 — это ещё ПРЕДЫДУЩИЕ сутки UTC; отметка UTC 21:00–23:59 — уже СЛЕДУЮЩИЕ сутки по
Москве; МСК 21:00–23:59 и UTC 00:00–20:59 остаются в своих сутках в обоих способах (переход только через
полночь). Отсюда нестабильный тест «события за вчера», если сравнивать даты в разных поясах. Ключ — независимая
модель (сдвиг наивного времени на ±3 часа) в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "qa.time.t21_midnight_tz_output"

CTX = [("отчёт о заказах за сутки", "orders"), ("выгрузка логинов для теста «за вчера»", "logins"),
       ("подсчёт упавших прогонов по дням", "runs"), ("сверка платежей по датам", "payments"),
       ("журнал алертов дежурной смены", "alerts")]
# (месяц, день) — сутки «вчера»; следующий день может быть в другом месяце
BASES = [(10, 20), (3, 31), (6, 30), (11, 14), (4, 9), (8, 31)]
# слоты времени: (зона, часы, тип) — тип нужен для отбора интересных вариантов
SLOTS_MSK = [("MSK", h, "msk_early") for h in (0, 1, 2)] + [("MSK", h, "msk_late") for h in (21, 22, 23)] + \
            [("MSK", h, "day") for h in (9, 14, 18)]
SLOTS_UTC = [("UTC", h, "utc_late") for h in (21, 22, 23)] + [("UTC", h, "utc_early") for h in (0, 1)] + \
            [("UTC", h, "day") for h in (8, 15)]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, var = rng.choice(CTX)
    mon, day = rng.choice(BASES)
    base = datetime(2026, mon, day)
    for _ in range(500):
        n = rng.randint(5, 6)
        n_utc = rng.choice([1, 2, 2])
        slots = rng.sample(SLOTS_MSK, n - n_utc) + rng.sample(SLOTS_UTC, n_utc)
        rng.shuffle(slots)
        events = []
        for zone, h, kind in slots:
            # раннее время (0–2 ч) — уже «сегодня» (base + 1), остальное — «вчера» (base)
            d = base + timedelta(days=1) if h < 3 or (kind == "day" and rng.random() < 0.3) else base
            events.append((zone, d.replace(hour=h, minute=rng.choice([0, 5, 15, 20, 30, 40, 45, 50, 55])), kind))
        kinds = {k for _z, _t, k in events}
        if "msk_early" not in kinds or "utc_late" not in kinds:
            continue
        if len({(z, t) for z, t, _k in events}) < n:
            continue
        break
    else:
        raise RuntimeError("t21_midnight_tz: не собран вариант")
    # модель: наивное время в UTC и в МСК
    by = {"utc": {}, "msk": {}}
    notes = []
    for zone, t, _k in events:
        utc_t = t - timedelta(hours=3) if zone == "MSK" else t
        msk_t = utc_t + timedelta(hours=3)
        for name, tt in (("utc", utc_t), ("msk", msk_t)):
            key = tt.strftime("%m-%d")
            by[name][key] = by[name].get(key, 0) + 1
        own = t.strftime("%m-%d %H:%M")
        if zone == "MSK" and utc_t.date() != t.date():
            notes.append(f"{own} МСК = {utc_t:%m-%d %H:%M} UTC — предыдущие сутки UTC")
        if zone == "UTC" and msk_t.date() != t.date():
            notes.append(f"{own} UTC = {msk_t:%m-%d %H:%M} МСК — следующие сутки по Москве")
    outs = [name + " " + " ".join(f"{d}:{c}" for d, c in sorted(by[name].items())) for name in ("utc", "msk")]
    tup = lambda z, t: f"({t.month}, {t.day}, {t.hour}, {t.minute}, {z})"  # noqa: E731
    items = [tup(z, t) for z, t, _k in events]
    half = (len(items) + 1) // 2
    lines = ["from datetime import datetime, timedelta, timezone",
             "MSK, UTC = timezone(timedelta(hours=3)), timezone.utc",
             f"{var} = [" + ", ".join(items[:half]) + ",",
             "    " + ", ".join(items[half:]) + "]",
             'by = {"utc": {}, "msk": {}}',
             f"for mon, day, h, m, tz in {var}:",
             "    e = datetime(2026, mon, day, h, m, tzinfo=tz)",
             '    for name, zone in (("utc", UTC), ("msk", MSK)):',
             '        d = e.astimezone(zone).strftime("%m-%d")',
             "        by[name][d] = by[name].get(d, 0) + 1",
             "for name, days in by.items():",
             '    print(name, *(f"{d}:{n}" for d, n in sorted(days.items())))']
    code = "\n".join(lines)
    out = "\n".join(outs)
    late = ("21:00–23:59 МСК — это 18:00–20:59 UTC того же дня, " if any(k == "msk_late" for _z, _t, k in events)
            else "")
    expl = ("astimezone переводит момент времени в другой пояс, дата берётся уже после перевода; МСК = UTC + 3 ч. "
            "Через полночь переходят только: " + "; ".join(notes) + f". Остальные события ({late}дневные отметки) "
            "в обоих способах в своих сутках. Вывод по строкам: " + " / ".join(f"«{o}»" for o in outs) + ".")
    stem = (f"Автотест ({ctx}): события с отметками времени по Москве и по UTC раскладываются по суткам двумя "
            f"способами.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"events": [[z, t.isoformat()] for z, t, _k in events]}, language="python")
