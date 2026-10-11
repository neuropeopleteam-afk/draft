"""common.process.principal_team_split_mcq — mcq_concept (Principal, короткое): границы команд по совместным изменениям.

Девять компонентов продукта делят между тремя командами по три компонента. Даны две таблицы: статические вызовы
между компонентами (кто кого вызывает) и совместные изменения за квартал (в скольких релизах менялись оба
компонента пары). Вопрос — какое разбиение даёт меньше всего изменений, которые требуют согласования двух и более
команд (изменение пары компонентов разных команд — одно согласование).

Верный ответ — разбиение с минимальной суммой совместных изменений через границы команд. Варианты построены по
схеме 2×2 из двух обменов компонентами между командами (верное, обмен a, обмен b, оба обмена) — ни один вариант
не «центральный». Генератор подбирает статические вызовы так, что меньше всего вызовов через границы — у одного из
неверных вариантов: ловушка «границы по графу вызовов» (Lead часто режет по зависимостям кода, а согласования
порождают совместные изменения). Разрыв верного варианта и ближайшего неверного по совместным изменениям — не
меньше 12 %.
Ключ проверяется исполнением: программа разбирает показанный текст каждого варианта, считает совместные изменения
через границы и печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "common.process.principal_team_split_mcq"

CONTEXTS = {
    "интернет-магазин": ["каталог", "поиск", "корзина", "оплата", "доставка", "склад", "профиль", "уведомления",
                         "отзывы", "цены", "акции"],
    "банковское приложение": ["счета", "переводы", "карты", "кредиты", "вклады", "скоринг", "вход", "уведомления",
                              "выписки", "лимиты", "антифрод"],
    "логистическая платформа": ["заказы", "маршруты", "курьеры", "склады", "тарифы", "трекинг", "биллинг",
                                "уведомления", "отчёты", "возвраты", "интеграции"],
    "платформа онлайн-обучения": ["курсы", "уроки", "видео", "задания", "проверка", "оценки", "оплата", "профиль",
                                  "сертификаты", "расписание", "форум"],
    "сервис записи к врачу": ["запись", "расписание", "пациенты", "врачи", "клиники", "оплата", "напоминания",
                              "медкарта", "отзывы", "телемедицина", "отчёты"],
    "маркетплейс услуг": ["заказы", "исполнители", "поиск", "чат", "сделки", "выплаты", "рейтинг", "споры",
                          "календарь", "профиль", "уведомления"],
}

PROGRAM = """opts = __OPTS__
co = {co!r}      # (компонент, компонент) -> совместных изменений за квартал
best, best_cut = None, None
for letter, text in sorted(opts.items()):
    team = {{}}
    for i, part in enumerate(text.split("; ")):
        names = part.split(": ", 1)[1].split(", ")
        for n in names:
            team[n] = i
    cut = sum(w for (a, b), w in co.items() if team[a] != team[b])
    if best_cut is None or cut < best_cut:
        best, best_cut = letter, cut
print(best)
"""


def _canon(part, names):
    teams = [sorted(t, key=names.index) for t in part]
    return tuple(tuple(t) for t in sorted(teams, key=lambda t: names.index(t[0])))


def _cut(part, pairs):
    team = {n: i for i, t in enumerate(part) for n in t}
    return sum(w for (a, b), w in pairs.items() if team[a] != team[b])


def _swap(part, x, y):
    out = [list(t) for t in part]
    for t in out:
        if x in t:
            t[t.index(x)] = y
        elif y in t:
            t[t.index(y)] = x
    return out


def _text(part):
    return "; ".join(f"команда {i}: " + ", ".join(t) for i, t in enumerate(part, 1))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(sorted(CONTEXTS))
    for _ in range(5000):
        names = rng.sample(CONTEXTS[ctx], 9)
        rng.shuffle(names)
        best = [names[0:3], names[3:6], names[6:9]]
        co = {}
        for t in best:                                   # внутри «правильных» команд — частые совместные изменения
            for i in range(3):
                for j in range(i + 1, 3):
                    if rng.random() < 0.85:
                        co[(t[i], t[j])] = rng.randint(4, 14)
        inter = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
                 if not any(a in t and b in t for t in best)]
        for a, b in rng.sample(inter, rng.randint(5, 8)):
            co[(a, b)] = rng.randint(1, 5)
        team_of = {n: i for i, t in enumerate(best) for n in t}
        x1, y1, x2, y2 = rng.sample(names, 4)
        if team_of[x1] == team_of[y1] or team_of[x2] == team_of[y2]:
            continue
        pa = _swap(best, x1, y1)
        pb = _swap(best, x2, y2)
        pab = _swap(pa, x2, y2)
        parts = [best, pa, pb, pab]
        disp = list(names)
        rng.shuffle(disp)                                 # порядок показа не связан с «правильными» командами
        canon = [_canon(p, disp) for p in parts]
        if len(set(canon)) != 4:
            continue
        cuts = [_cut(p, co) for p in parts]
        if min(cuts[1:]) < cuts[0] * 1.12 + 1:
            continue
        calls = {}
        for _k in range(rng.randint(9, 12)):              # статические вызовы — независимы от совместных изменений
            a, b = rng.sample(names, 2)
            calls[(a, b)] = 1
        sc = [_cut(p, calls) for p in parts]
        low = min(sc)
        if sc.count(low) != 1 or sc.index(low) == 0 or sc[0] - low < 2:
            continue
        break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    trap_static = sc.index(low)
    co_rows = ", ".join(f"{a}–{b} {w}" for (a, b), w in sorted(co.items(), key=lambda kv: (-kv[1], kv[0])))
    call_rows = ", ".join(f"{a} → {b}" for (a, b) in sorted(calls, key=lambda e: (disp.index(e[0]), disp.index(e[1]))))
    intro = rng.choice([
        f"Вы — главный инженер продукта «{ctx}». Команд становится три, и нужно поделить между ними девять "
        f"компонентов — по три на команду.",
        f"Продукт «{ctx}» растёт: одну большую команду делят на три по три компонента в каждой. Предложения "
        f"разбиения собраны, решение — за вами как за главным инженером.",
        f"Руководство продукта «{ctx}» просит главного инженера выбрать, как поделить девять компонентов между "
        f"тремя новыми командами (по три компонента).",
    ])
    stem = (f"{intro}\nСтатические вызовы (кто кого вызывает в коде): {call_rows}.\nСовместные изменения за прошлый "
            f"квартал (пара — в скольких релизах менялись оба компонента): {co_rows}; остальные пары вместе не "
            f"менялись.\nИзменение, которое затрагивает компоненты разных команд, требует согласования этих команд. "
            f"Состав релизов в следующем квартале ожидается таким же.\n\nКакое разбиение даёт меньше всего "
            f"согласований между командами?")
    expl = (f"Согласования порождают совместные изменения через границы команд, а не статические вызовы. Сумма "
            f"совместных изменений через границы: " + "; ".join(f"{_text(canon[i])} — {cuts[i]}" for i in range(4)) +
            f". Минимум — {cuts[0]}. Ловушка: меньше всего статических вызовов через границы ({low}) у разбиения "
            f"«{_text(canon[trap_static])}», но совместных изменений у него {cuts[trap_static]}.")
    program = PROGRAM.format(co=co)
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=_text(canon[0]),
                       distractors=[_text(c) for c in canon[1:]], program=program, explanation=expl,
                       params={"cuts": "/".join(map(str, cuts)), "static_cuts": "/".join(map(str, sc)),
                               "trap_static": trap_static, "names": ",".join(names)},
                       note="Ответ проверяется программой: разбор показанных разбиений и подсчёт совместных изменений.")
