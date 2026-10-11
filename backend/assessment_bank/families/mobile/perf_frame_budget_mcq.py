"""mobile.perf.frame_budget_mcq — mcq_concept: бюджет кадра при прокрутке списка на дисплее 60/90/120 Гц.

Модель: за секунду прокрутки дисплей показывает F кадров, бюджет кадра — 1000/F мс. Работа главного потока
на кадр — базовая (layout, отрисовка) плюс через каждые k кадров привязка новой ячейки (с декодированием
картинки на главном потоке или без). Кадр, в котором работа больше бюджета, показывается с опозданием.
Вопрос: сколько кадров за секунду опоздают. Состав дистракторов фиксирован — расчёт с одной типичной ошибкой: бюджет
16,7 мс (как у 60 Гц) на дисплее 90/120 Гц; подсчёт пропущенных интервалов обновления вместо опоздавших
кадров; сравнение со средним временем кадра. Ключ проверяется исполнением модели в песочнице.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import balanced_options

FAMILY_ID = "mobile.perf.frame_budget_mcq"

MODEL = r"""
def late_frames(hz, base, k, bind, img_every, img, wrong=()):
    # Число кадров за секунду, в которых работа главного потока больше бюджета (wrong — заблуждение)
    budget = 1000 / 60 if "budget60" in wrong else 1000 / hz
    works = []
    binds = 0
    for f in range(1, hz + 1):
        work = base
        if f % k == 0:
            binds += 1
            work += bind
            if binds % img_every == 0:
                work += img
        works.append(work)
    if "average" in wrong:
        return 0 if sum(works) / hz <= budget else hz
    if "dropped" in wrong:
        return sum(int(w // budget) for w in works if w > budget)
    return sum(1 for w in works if w > budget)
"""
_ns: dict = {}
exec(MODEL, _ns)  # noqa: S102 — код модели банка, тот же исполняется в проверке
late_frames = _ns["late_frames"]

CTX = [("лента новостей", "карточка поста"), ("каталог товаров", "карточка товара"), ("чат", "сообщение"),
       ("галерея", "превью фото"), ("список заказов", "строка заказа"), ("лента вакансий", "карточка вакансии"),
       ("афиша событий", "карточка события"), ("список треков", "строка трека")]
WRONGS = ["budget60", "dropped", "average"]


def _n(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(500):
        hz = rng.choice([90, 120])
        bud = 1000 / hz
        base = round(rng.uniform(bud * 0.45, bud * 0.65), 1)
        k = rng.randint(4, 9)
        img_every = rng.choice([2, 3])
        bind = round(rng.uniform(bud + 0.4, min(16.0, 1.9 * bud)) - base, 1)
        lo = max(2 * bud, 1000 / 60) + 0.3 - base - bind
        img = round(rng.uniform(lo, 3 * bud - 0.3 - base - bind), 1)
        good = late_frames(hz, base, k, bind, img_every, img)
        vals = {w: late_frames(hz, base, k, bind, img_every, img, (w,)) for w in WRONGS}
        if len({good, *vals.values()}) == 4 and img > 0.5:
            break
    else:
        raise RuntimeError("нет параметров")
    ws = WRONGS
    opts, key = balanced_options(FAMILY_ID, seed, rng, (str(good), None), [(str(vals[w]), None) for w in ws])
    ctx, cell = rng.choice(CTX)
    stem = (f"Экран «{ctx}», прокрутка на дисплее {hz} Гц. Измерено на главном потоке: каждый кадр — {_n(base)} мс "
            f"(расчёт расположения и отрисовка); в каждом {k}-м кадре в список добавляется новый элемент "
            f"({cell}) — привязка ячейки добавляет {_n(bind)} мс (новые ячейки — в кадрах {k}, {2 * k}, {3 * k}, …); у каждой {img_every}-й новой ячейки в том же кадре на главном потоке "
            f"декодируется картинка — ещё {_n(img)} мс. Кадр, в котором работа главного потока превышает бюджет "
            f"кадра, показывается с опозданием. Сколько кадров за одну секунду прокрутки опоздают (каждый опоздавший кадр "
            f"считается один раз)?")
    opt_map = {o.id: o.text for o in opts}
    prog = (MODEL + f"\nopts = {opt_map!r}\nv = str(late_frames({hz}, {base}, {k}, {bind}, {img_every}, {img}))\n"
            "hit = [k for k, t in opts.items() if t == v]\nprint(hit[0] if len(hit) == 1 else 'AMBIGUOUS')\n")
    checks = [Check(name="frame_model", runner="python", program=prog, expect="stdout_equals", expected_stdout=key)]
    n_bind = hz // k
    n_img = n_bind // img_every
    ak = AnswerKey(kind="option", value=key,
                   explanation=(f"Бюджет кадра при {hz} Гц — 1000/{hz} ≈ {_n(1000 / hz, 2)} мс. Обычный кадр "
                                f"({_n(base)} мс) укладывается; кадр с новой ячейкой — {_n(base + bind)} мс, уже больше "
                                f"бюджета, с картинкой — {_n(base + bind + img)} мс. Новых ячеек за {hz} кадров — {n_bind}, "
                                f"все эти кадры опаздывают: ответ {good}. Ошибки: бюджет 16,7 мс, как у 60 Гц "
                                f"(тогда опаздывают только кадры с картинкой — {n_img}); считать пропущенные "
                                f"интервалы обновления вместо опоздавших кадров ({vals['dropped']}); сравнивать "
                                f"со средним временем кадра (0)."))
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется моделью бюджета кадра на Python.",
                         params={"hz": hz, "base": base, "k": k, "bind": bind, "img_every": img_every, "img": img,
                                 "distractors": ws})
