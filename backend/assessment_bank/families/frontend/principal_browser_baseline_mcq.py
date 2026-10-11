"""frontend.strategy.principal_browser_baseline_mcq — mcq_concept (Principal, короткое): какие браузеры поддерживать.

Аудитория делится на три группы браузеров: старые (старше 5 лет, s_old), средние (3–5 лет, s_mid) и современные.
Четыре политики поддержки:
  * поддерживать всё — одна сборка под старые браузеры с полифилами: +ms_all к LCP у всех; тестирование T_all;
  * не старше 5 лет — одна сборка под средние: старые теряются (доля λ их выручки уходит), +ms_mid к LCP у всех;
    тестирование T_mid;
  * двойная сборка (современная и запасная для старых) — лишний вес только у старых (+ms_all у s_old), доплата D
    (сборка, тестирование двух вариантов);
  * только последние версии вечнозелёных браузеров — теряются старые и средние, без лишнего веса и тестирования.
Каждые 100 мс LCP стоят x % выручки группы, у которой выросло время загрузки. Годовая цена = доплата и тестирование
+ потерянная выручка неподдержанных групп + потеря выручки от LCP.

Ловушки: «максимальный охват» (поддерживать всё), «самый лёгкий бандл и ноль тестирования» (только вечнозелёные),
расчёт без цены тестирования и доплаты. Верная политика распределена поровну по четырём и отличается хотя бы от
двух ловушек (если верна сама ловушка — хотя бы от одной). Ключ проверяется исполнением: программа разбирает
аудиторию по группам и для каждой политики и группы считает исход (поддержана с добавкой LCP / ушла), затем
печатает букву минимума.
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.strategy.principal_browser_baseline_mcq"

CONTEXTS = ["портал госуслуг региона", "интернет-магазин электроники", "сервис онлайн-записи", "интернет-банк",
            "сайт авиакомпании", "сервис объявлений", "онлайн-аптека", "сайт сети кинотеатров"]
NAMES = {"all": "поддерживать все браузеры одной сборкой", "mid": "поддерживать браузеры не старше 5 лет",
         "dual": "двойная сборка: современная и запасная", "evergreen": "только последние версии браузеров"}
ORDER = ["all", "mid", "dual", "evergreen"]

PROGRAM = """opts = __OPTS__
W, x, lam = {W}, {x}, {lam}
groups = {groups!r}          # группа -> доля аудитории
policy = {policy!r}          # подпись -> (группа -> добавка LCP мс или None, если не поддержана; доплата млн ₽)
cost = {{}}
for label, (outcome, extra) in policy.items():
    total = extra
    for g, share in groups.items():
        add = outcome[g]
        if add is None:
            total += W * share * lam                       # неподдержанная группа: уходит доля lam выручки
        else:
            total += W * share * x / 100 * add / 100       # поддержанная: потеря от добавки к LCP
    cost[label] = total
best = min(cost, key=cost.get)
hit = [k for k, t in opts.items() if t == best]
print(hit[0] if len(hit) == 1 else "AMBIGUOUS")
"""


def _argmin(d, rel=0.04):
    v = sorted(d.values())
    return min(d, key=d.get) if v[1] - v[0] >= rel * v[1] else None


def _policy(ms_all, ms_mid, T_all, T_mid, D):
    return {"all": ({"old": ms_all, "mid": ms_all, "new": ms_all}, T_all),
            "mid": ({"old": None, "mid": ms_mid, "new": ms_mid}, T_mid),
            "dual": ({"old": ms_all, "mid": 0, "new": 0}, D),
            "evergreen": ({"old": None, "mid": None, "new": 0}, 0)}


def _cost(pol, groups, W, x, lam, with_extra=True):
    out = {}
    for k, (oc, extra) in pol.items():
        t = extra if with_extra else 0
        for g, sh in groups.items():
            t += W * sh * lam if oc[g] is None else W * sh * x / 100 * oc[g] / 100
        out[k] = t
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    target = rng.choice(ORDER)
    for _ in range(60000):
        s_old = rng.choice([0.005, 0.01, 0.02, 0.04])
        s_mid = rng.choice([0.02, 0.04, 0.06, 0.1])
        groups = {"old": s_old, "mid": s_mid, "new": round(1 - s_old - s_mid, 4)}
        W = rng.choice([500, 1000, 3000, 8000])               # млн ₽ в год
        x = rng.choice([0.5, 1.0, 1.5])
        lam = rng.choice([0.3, 0.5, 0.8])                      # доля выручки неподдержанной группы, которая уходит
        ms_all, ms_mid = rng.choice([150, 250, 400]), rng.choice([40, 60, 100])
        T_all, T_mid, D = rng.choice([4, 6, 10]), rng.choice([2, 3, 5]), rng.choice([5, 8, 12])
        pol = _policy(ms_all, ms_mid, T_all, T_mid, D)
        full = _cost(pol, groups, W, x, lam)
        good = _argmin(full)
        if good != target:
            continue
        no_extra = _argmin(_cost(pol, groups, W, x, lam, with_extra=False))
        if no_extra is None:
            continue
        traps = ("all", "evergreen", no_extra)
        if sum(t != good for t in traps) >= (1 if good in ("all", "evergreen") else 2):
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    pc = lambda v: fmt_num(100 * v, 1).replace(",0", "")
    cap = lambda t: t[0].upper() + t[1:]
    rows = [f"• {cap(NAMES['all'])} (с полифилами): +{ms_all} мс к LCP у всех; тестирование в старых браузерах — "
            f"{T_all} млн ₽ в год.",
            f"• {cap(NAMES['mid'])}: старые браузеры не поддерживаются; +{ms_mid} мс к LCP у всех; тестирование — "
            f"{T_mid} млн ₽ в год.",
            f"• {cap(NAMES['dual'])}: лишний вес (+{ms_all} мс) только у старых браузеров; сборка и тестирование двух "
            f"вариантов — {D} млн ₽ в год.",
            f"• {cap(NAMES['evergreen'])}: старые и средние браузеры не поддерживаются; без лишнего веса и отдельного "
            f"тестирования."]
    intro = rng.choice([
        f"Вы — главный инженер фронтенда; продукт — {ctx}. Пора пересмотреть, какие браузеры поддерживать.",
        f"Для продукта «{ctx}» нужно утвердить политику поддержки браузеров на год; решение за вами как за "
        f"главным инженером фронтенда.",
        f"Команда продукта «{ctx}» предлагает отказаться от старых браузеров, и вы как главный инженер фронтенда "
        f"должны выбрать политику поддержки.",
    ])
    stem = (f"{intro} Выручка ≈ {fmt_num(W, 0)} млн ₽ в год, распределена по аудитории равномерно. Аудитория: "
            f"старые браузеры (старше 5 лет) — {pc(s_old)} %, браузеры 3–5 лет — {pc(s_mid)} %, остальные — "
            f"современные. Если браузер не поддерживается, уходит {fmt_num(100 * lam, 0)} % выручки этих "
            f"пользователей (остальные перейдут в другой браузер). Каждые 100 мс LCP стоят {fmt_num(x, 1)} % выручки "
            f"тех, у кого страница загружается дольше. Варианты:\n" + "\n".join(rows) +
            "\n\nКакая политика даёт минимальную годовую цену (тестирование и доплата, ушедшая выручка и потеря от LCP)?")
    expl = ("Цена = доплата/тестирование + Σ по неподдержанным группам (выручка × доля × уходящая часть) + Σ по "
            "поддержанным (выручка × доля × x % × добавка / 100 мс). Итоги: " +
            "; ".join(f"{NAMES[k]} — {fmt_num(full[k], 1)} млн ₽" for k in ORDER) +
            f". Минимум — {NAMES[good]}. Без цены тестирования и доплаты вышло бы: {NAMES[no_extra]}.")
    program = PROGRAM.format(W=W, x=x, lam=lam, groups=groups, policy={NAMES[k]: v for k, v in pol.items()})
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=NAMES[good],
                       distractors=[NAMES[k] for k in ORDER if k != good], program=program, explanation=expl,
                       params={"W": W, "x": x, "lam": lam, "s_old": s_old, "s_mid": s_mid, "ms_all": ms_all,
                               "ms_mid": ms_mid, "T_all": T_all, "T_mid": T_mid, "D": D, "good": good,
                               "no_extra": no_extra},
                       note="Ответ проверяется программой: исход каждой группы браузеров при каждой политике.")
