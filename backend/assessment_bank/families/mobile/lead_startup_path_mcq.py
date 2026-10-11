"""mobile.lead.startup_path_mcq — mcq_concept (Lead): время до первого экрана после переработки холодного старта.

Сейчас задачи инициализации выполняются по очереди на главном потоке. План: задачи, не нужные первому экрану,
отложить до момента после первого кадра; нужные — запускать параллельно, как только готовы их зависимости (потоков
достаточно); отрисовка первого экрана — на главном потоке, когда готовы её зависимости. Время до первого кадра —
длина критического пути к отрисовке по нужным задачам. Какие задачи нужны первому экрану, зависит от варианта
(персональная или общая лента, флаги из сети или из кэша).

Дистракторы — из пула шести ошибок; по seed от 0 до 3 из них завышают время (ранг верного ответа среди вариантов
равномерен, «середина» или «крайнее» ключ не выдают). Занижают: ``ignore_deps`` — без зависимостей (самая долгая
задача + отрисовка); ``no_ui`` — критический путь без самой отрисовки; ``direct_only`` — только прямые зависимости
отрисовки. Завышают: ``sum_required`` — нужные задачи по очереди; ``no_defer`` — параллельно, но отрисовка ждёт и
отложенные задачи; ``sum_all`` — нынешнее последовательное время. Ключ проверяется исполнением: программа считает
критический путь по графу.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import computed_mcq, ru_num
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.lead.startup_path_mcq"

CONTEXTS = ["мобильный банк", "приложение доставки еды", "маркетплейс", "приложение такси", "новостное приложение",
            "приложение для заметок", "стриминговый сервис", "приложение авиакомпании"]
TITLES = {"crash": "отчёты о сбоях (SDK)", "di": "контейнер зависимостей", "prefs": "чтение настроек",
          "db": "миграция локальной базы", "session": "восстановление сессии из защищённого хранилища",
          "config": "удалённая конфигурация (флаги) из сети", "analytics": "SDK аналитики",
          "assets": "шрифты и иконки первого экрана", "feed": "кэш ленты из локальной базы",
          "ui": "отрисовка первого экрана (главный поток)"}
SMALLER = ["ignore_deps", "no_ui", "direct_only"]
LARGER = ["sum_required", "no_defer", "sum_all"]

PROGRAM = '''DUR = {dur!r}        # задача: длительность, мс
DEPS = {deps!r}      # задача: от каких задач зависит
finish = {{}}


def done(t):   # момент готовности задачи: все зависимости готовы, затем сама задача (потоков достаточно)
    if t not in finish:
        finish[t] = max((done(d) for d in DEPS[t]), default=0) + DUR[t]
    return finish[t]


print(f"≈ {{done('ui')}} мс")
'''


def _finish(dur, deps):
    fin: dict[str, int] = {}

    def done(t):
        if t not in fin:
            fin[t] = max((done(d) for d in deps[t]), default=0) + dur[t]
        return fin[t]

    for t in dur:
        done(t)
    return fin


def _needed(deps, t="ui"):
    out, stack = set(), [t]
    while stack:
        x = stack.pop()
        if x not in out:
            out.add(x)
            stack.extend(deps[x])
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    n_up = seed % 4
    for _ in range(20000):
        dur = {"crash": rng.choice([20, 30, 40, 60]), "di": rng.choice([40, 60, 80, 120]),
               "prefs": rng.choice([20, 30, 50]), "db": rng.choice([60, 90, 150, 220, 300]),
               "session": rng.choice([40, 70, 100, 150]), "config": rng.choice([120, 180, 250, 350, 450]),
               "analytics": rng.choice([80, 120, 180, 250, 400]), "assets": rng.choice([50, 80, 120, 200]),
               "feed": rng.choice([40, 60, 90, 140]), "ui": rng.choice([60, 80, 100, 120])}
        personal = rng.random() < 0.5
        net_flags = rng.random() < 0.5
        deps = {"crash": [], "di": [], "prefs": [], "db": ["di"], "session": ["prefs"], "config": ["di"],
                "analytics": ["di", "config"] if rng.random() < 0.5 else ["di"], "assets": [],
                "feed": ["db", "session"] if personal else ["db"],
                "ui": ["crash", "feed", "assets"] + (["config"] if net_flags else [])}
        need = _needed(deps)
        fin = _finish(dur, deps)
        good = fin["ui"]
        req = [t for t in dur if t in need and t != "ui"]
        allc = {"ignore_deps": max(dur[t] for t in req) + dur["ui"],
                "no_ui": good - dur["ui"],
                "direct_only": max(dur[t] for t in deps["ui"]) + dur["ui"],
                "sum_required": sum(dur[t] for t in need),
                "no_defer": max(fin[t] for t in dur if t != "ui") + dur["ui"],
                "sum_all": sum(dur.values())}
        down = sorted(SMALLER, key=lambda k: rng.random())[:3 - n_up]
        up = sorted(LARGER, key=lambda k: rng.random())[:n_up]
        cands = {"good": good, **{k: allc[k] for k in down + up}}
        vals = list(cands.values())
        if len(set(vals)) != 4 or min(abs(a - b) for i, a in enumerate(vals) for b in vals[i + 1:]) < 20:
            continue
        if any(allc[k] >= good for k in down) or any(allc[k] <= good for k in up):
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("не удалось построить вариант")
    rows = ["задача | длительность, мс | зависит от"]
    for t in dur:
        rows.append(f"{TITLES[t]} | {dur[t]} | " + (", ".join(TITLES[d] for d in deps[t]) or "—"))
    code = "\n".join(rows)
    feed_txt = ("лента персональная — её кэш читается после восстановления сессии" if personal else
                "лента общая — сессия ей не нужна")
    flags_txt = ("первый экран зависит от флагов, загружаемых из сети" if net_flags else
                 "флаги первый экран не меняют (применяются при следующем запуске)")
    stem = (f"{ctx.capitalize()}: холодный старт — сейчас все задачи инициализации выполняются по очереди на главном "
            f"потоке ({ru_num(allc['sum_all'])} мс). План: задачи, без которых первый экран не может отрисоваться, "
            f"запускать параллельно, как только готовы их зависимости (потоков достаточно); остальные — отложить "
            f"до момента после первого кадра. Условия варианта: {feed_txt}; {flags_txt}. Зависимости и длительности "
            f"— в таблице. Сколько займёт время до первого кадра после переработки?")
    path = []
    t = "ui"
    while True:
        path.append(t)
        if not deps[t]:
            break
        t = max(deps[t], key=lambda d: fin[d])
    path_txt = " → ".join(TITLES[x] for x in reversed(path))
    defer = [TITLES[t] for t in dur if t not in need]
    errs = {"ignore_deps": "без учёта зависимостей (самая долгая задача + отрисовка)",
            "no_ui": "без самой отрисовки", "direct_only": "только по прямым зависимостям отрисовки",
            "sum_required": "если выполнять нужные задачи по очереди",
            "no_defer": "если отрисовка ждёт и отложенные задачи",
            "sum_all": "нынешнее последовательное время"}
    why = (f"Первому экрану нужны: {', '.join(TITLES[t] for t in dur if t in need and t != 'ui')}; откладываются: "
           f"{', '.join(defer) if defer else 'ничего'}. Критический путь: {path_txt} = {good} мс. Ошибки: "
           + "; ".join(f"{errs[k]} — {cands[k]} мс" for k in cands if k != "good")
           + ". Для Lead: старт измеряется до первого кадра, порядок инициализации — по графу зависимостей экрана, "
             "всё остальное — после кадра или лениво.")
    return computed_mcq(FAMILY_ID, seed, rng, stem=stem, correct=f"≈ {good} мс",
                        distractors=[f"≈ {cands[k]} мс" for k in cands if k != "good"],
                        program=PROGRAM.format(dur=dur, deps=deps), why=why, context=ctx, code=code,
                        language="text",
                        note="Программа считает момент готовности отрисовки по графу зависимостей (критический путь) "
                             "по тем же числам.",
                        params={"personal": personal, "net_flags": net_flags, "n_up": n_up})
