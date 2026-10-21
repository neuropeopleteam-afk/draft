"""mobile.state.t21_screen_state_output — predict_output (набор t21, порог Стажёра): состояние экрана
списка — функция с цепочкой if и ранним return.

Программа на JavaScript (логика React Native-экрана) выбирает, что показать: индикатор загрузки, ошибку, пустое
состояние или список. Проверки идут по порядку, первая сработавшая возвращает результат. Ловушки чтения: при
одновременных loading и error побеждает та проверка, что стоит выше; null — «нет ошибки»; пустой список
проверяется только после них. Ключ — независимая модель в генераторе; проверка — исполнение показанного кода в
песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.state.t21_screen_state_output"

CTX = ["лента заказов курьера", "список избранного", "история платежей", "поиск по каталогу", "чаты поддержки"]
ERRORS = ["'timeout'", "'offline'", "'503'", "'401'", "'429'", "'500'"]


def _state(loading: bool, error: str | None, count: int, first: str) -> str:
    checks = ["loading", "error"] if first == "loading" else ["error", "loading"]
    for c in checks:
        if c == "loading" and loading:
            return "loading"
        if c == "error" and error is not None:
            return "error: " + error.strip("'")
    if count == 0:
        return "empty"
    return f"{count} items"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    first = rng.choice(["loading", "error"])
    fn = rng.choice(["screenState", "renderMode", "viewState"])
    for _ in range(200):
        calls = []
        for _i in range(2):
            loading = rng.random() < 0.5
            error = rng.choice(ERRORS) if rng.random() < 0.55 else None
            count = 0 if rng.random() < 0.35 else rng.randint(1, 12)
            calls.append((loading, error, count))
        # хотя бы в одном вызове — конфликт loading + error (главная ловушка), результаты вызовов различны
        conflict = any(lo and er for lo, er, _c in calls)
        res = [_state(lo, er, c, first) for lo, er, c in calls]
        if conflict and res[0] != res[1]:
            break
    else:
        raise RuntimeError("t21_screen_state: не собрались вызовы")
    ifs = {"loading": "  if (loading) return 'loading';",
           "error": "  if (error) return 'error: ' + error;"}
    order = ["loading", "error"] if first == "loading" else ["error", "loading"]
    code_lines = [f"function {fn}(loading, error, count) {{", ifs[order[0]], ifs[order[1]],
                  "  if (count === 0) return 'empty';",
                  f"  return count + ' items';",
                  "}"]
    outs, traces = [], []
    for lo, er, cnt in calls:
        er_js = er if er is not None else "null"
        code_lines.append(f"console.log({fn}({'true' if lo else 'false'}, {er_js}, {cnt}));")
        res = _state(lo, er, cnt, first)
        outs.append(res)
        traces.append(f"{fn}({'true' if lo else 'false'}, {er_js}, {cnt}) → «{res}»")
    code = "\n".join(code_lines)
    out = "\n".join(outs)
    null_note = " (null — ложь, значит «ошибки нет»)" if any(er is None for _lo, er, _c in calls) else ""
    expl = (f"Проверки идут сверху вниз, первая сработавшая делает return: сначала {order[0]}, затем {order[1]}, "
            f"потом пустой список{null_note}. " + "; ".join(traces) + ".")
    stem = (f"React Native-экран «{ctx.capitalize()}»: функция выбирает, что показать — загрузку, ошибку, "
            f"пустое состояние или список.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"calls": [list(c) for c in calls], "first": first}, language="javascript")
