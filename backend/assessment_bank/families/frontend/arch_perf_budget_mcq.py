"""frontend.arch.perf_budget_mcq — mcq_concept (Lead): какое одно изменение укладывает LCP в бюджет.

Клиентское приложение (SPA): HTML → (CSS ∥ JS-бандл → исполнение) → главное изображение, которое JS
находит после исполнения; отрисовка LCP требует CSS, изображение и исполненный JS. Загрузка ресурса —
RTT + размер / пропускная способность; параллельные загрузки друг другу не мешают (сказано в условии).
Четыре предложения команды:
  * ssr — серверная отрисовка: HTML больше на s КБ, изображение указано в разметке, для отрисовки JS не нужен;
  * split — разделение кода: бандл и время исполнения меньше;
  * preload — `<link rel=preload>` изображения: загрузка с HTML, но отрисовка всё ещё ждёт JS;
  * compress — изображение в k раз меньше (AVIF/WebP), находится всё так же из JS.
Бюджет выбран между лучшим и вторым по LCP предложением (разрыв ≥ 15 %), поэтому верно ровно одно, и в
разных вариантах побеждают разные предложения — нужно посчитать критический путь, а не выбрать «любимое».
Ключ проверяется исполнением: программа строит граф зависимостей каждого предложения и ищет самый длинный
путь до отрисовки (а генератор считает по формулам).
"""
from __future__ import annotations

from assessment_bank.families.common._lead_kit import fmt_num, numeric_mcq
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "frontend.arch.perf_budget_mcq"

CONTEXTS = ["карточка вакансии", "витрина маркетплейса", "описание отеля", "лендинг курса", "карточка товара",
            "профиль врача"]

NAMES = {"ssr": "серверная отрисовка", "split": "разделение кода", "preload": "preload изображения",
         "compress": "изображение в AVIF"}

PROGRAM = """P = {p}
def fetch(kb):
    return P["rtt"] + kb / P["bw"]           # мс; bw — КБ/мс
def graph(kind):
    h = P["html"] + (P["ssr_extra"] if kind == "ssr" else 0)
    srv = P["ssr_ttfb"] if kind == "ssr" else 0           # время отрисовки на сервере
    js = P["js_split"] if kind == "split" else P["js"]
    ex = P["exec_split"] if kind == "split" else P["exec"]
    img = P["img"] / P["k"] if kind == "compress" else P["img"]
    g = {{"html": (fetch(h) + srv, []), "css": (fetch(P["css"]), ["html"]), "js": (fetch(js), ["html"]),
          "exec": (ex, ["js"])}}
    g["img"] = (fetch(img), ["html"] if kind in ("ssr", "preload") else ["exec"])
    g["paint"] = (0, ["css", "img"] if kind == "ssr" else ["css", "img", "exec"])
    return g
def finish(g, node, memo):
    if node not in memo:
        dur, deps = g[node]
        memo[node] = dur + max((finish(g, d, memo) for d in deps), default=0)
    return memo[node]
lcp = {{k: finish(graph(k), "paint", {{}}) for k in ("ssr", "split", "preload", "compress")}}
opts = __OPTS__
kind_of = {kinds}
ok = [letter for letter, text in opts.items() if lcp[kind_of[text]] <= P["budget"]]
print(ok[0] if len(ok) == 1 else "AMBIGUOUS")
"""


def _lcp(p: dict, kind: str) -> float:
    f = lambda kb: p["rtt"] + kb / p["bw"]
    html = f(p["html"] + (p["ssr_extra"] if kind == "ssr" else 0)) + (p["ssr_ttfb"] if kind == "ssr" else 0)
    css = html + f(p["css"])
    js = p["js_split"] if kind == "split" else p["js"]
    ex = p["exec_split"] if kind == "split" else p["exec"]
    exec_done = html + f(js) + ex
    img_kb = p["img"] / p["k"] if kind == "compress" else p["img"]
    img_start = html if kind in ("ssr", "preload") else exec_done
    img = img_start + f(img_kb)
    return max(css, img) if kind == "ssr" else max(css, img, exec_done)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    kinds = ["ssr", "split", "preload", "compress"]
    target = rng.choice(kinds)          # победитель задаётся заранее: в разных вариантах верны разные предложения
    for _ in range(5000):
        mbit = rng.choice([4, 8, 12, 20])
        p = dict(rtt=rng.choice([60, 100, 150, 200]), bw=mbit * 1000 / 8 / 1000,     # КБ/мс
                 html=rng.choice([15, 25, 40]), css=rng.choice([30, 60, 90]),
                 js=rng.choice([200, 350, 500, 700, 900]), exec=rng.choice([150, 300, 500, 800, 1200]),
                 img=rng.choice([100, 250, 400, 600, 900]), ssr_extra=rng.choice([40, 80, 150]),
                 ssr_ttfb=rng.choice([300, 500, 800, 1100]), k=rng.choice([2, 3, 4]))
        share = rng.choice([0.35, 0.5, 0.6])
        p["js_split"] = round(p["js"] * share)
        p["exec_split"] = round(p["exec"] * share)
        lcp = {k: _lcp(p, k) for k in kinds}
        order = sorted(kinds, key=lambda k: lcp[k])
        if order[0] != target:
            continue
        best, second = lcp[order[0]], lcp[order[1]]
        if second < best * 1.15:
            continue
        budget = int(round((best + second) / 2 / 50) * 50)
        if best <= budget < second and best <= budget - 40 and second >= budget + 40:
            break
    else:
        raise RuntimeError("не удалось подобрать параметры")
    p["budget"] = budget
    pct = round(100 * share)
    text = {
        "ssr": (f"Серверная отрисовка: сервер тратит на страницу ещё {p['ssr_ttfb']} мс, HTML больше на {p['ssr_extra']} КБ, "
                f"изображение — сразу в разметке, для отрисовки JS не нужен"),
        "split": f"Разделение кода: бандл первого экрана — {p['js_split']} КБ, исполнение — {p['exec_split']} мс",
        "preload": "Подсказка <link rel=preload> для изображения: оно грузится вместе с CSS и JS, отрисовка — после JS",
        "compress": f"Перевести изображение в AVIF: файл в {p['k']} раза меньше, загрузка по-прежнему после исполнения JS",
    }
    stem = (f"Страница «{ctx}» — клиентское приложение. Загрузка на мобильной сети: RTT {p['rtt']} мс, "
            f"{mbit} Мбит/с, параллельные загрузки друг другу не мешают; каждый ресурс — RTT + размер / скорость. "
            f"HTML {p['html']} КБ; из него — CSS {p['css']} КБ и JS-бандл {p['js']} КБ (исполнение {p['exec']} мс); "
            f"главное изображение {p['img']} КБ JS находит только после исполнения. Отрисовка главного изображения "
            f"(LCP) требует CSS, само изображение и исполненный JS. Бюджет LCP — {budget} мс. Команда может сделать "
            f"только одно изменение до релиза. Какое из них укладывает LCP в бюджет?")
    lcp_s = {k: fmt_num(v, 0) for k, v in lcp.items()}
    base = _lcp({**p, "js_split": p["js"], "exec_split": p["exec"]}, "split")
    expl = (f"Критический путь каждого предложения: SSR — {lcp_s['ssr']} мс, разделение кода — {lcp_s['split']} мс, "
            f"preload — {lcp_s['preload']} мс, AVIF — {lcp_s['compress']} мс (исходно — {fmt_num(base, 0)} мс); в бюджет {budget} мс укладывается только "
            f"«{NAMES[order[0]]}». Preload выносит загрузку изображения из хвоста цепочки, но отрисовка всё равно ждёт исполнения JS; сжатие сокращает только последний "
            f"отрезок цепочки; SSR убирает JS из пути, но удлиняет ответ сервера и HTML; разделение кода сокращает и загрузку, и "
            f"исполнение.")
    kinds_map = {text[k]: k for k in kinds}
    program = PROGRAM.format(p=repr(p), kinds=repr(kinds_map))
    good = text[order[0]]
    return numeric_mcq(FAMILY_ID, seed, rng, ctx=ctx, stem=stem, good=good,
                       distractors=[text[k] for k in kinds if k != order[0]], program=program, explanation=expl,
                       params={"winner": order[0], "budget": budget, "lcp": {k: round(v) for k, v in lcp.items()},
                               **{k: v for k, v in p.items() if k != "bw"}, "mbit": mbit},
                       note="Ответ проверяется программой-моделью: граф зависимостей ресурсов каждого предложения и "
                            "самый длинный путь до отрисовки.")
