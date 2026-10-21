"""mobile.forms.t21_submit_finally_output — predict_output (набор t21, порог Senior): отправка формы из
async-функции с try / catch / finally — порядок строк и итоговое значение промиса.

React Native-экран отправляет две формы параллельно; send — запрос на таймере, который выполняется или
отклоняется. submit оборачивает его в try / catch / finally и возвращает статус; снаружи `.then` печатает
результат. Что проследить: до await всё выполняется синхронно (оба «send» и строка после вызовов — раньше любых
ответов); после ответа catch / finally / then идут подряд микрозадачами до следующего таймера; finally
выполняется после return из try или catch, а `return` внутри finally (в части вариантов) подменяет
возвращаемое значение. Ключ — модель таймеров и микрозадач в генераторе; проверка — исполнение показанного кода в
песочнице Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.forms.t21_submit_finally_output"

CTX = ["заявка на кредит", "отзыв о курьере", "запись к врачу", "заказ такси", "обращение в поддержку"]
RETURNS = [("done", "retry"), ("saved", "queued"), ("ok", "later")]
ERRORS = ["timeout", "offline", "conflict"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    ids = rng.sample(range(11, 99), 2)
    delays = rng.sample([10, 20, 30, 40], 2)
    pattern = rng.choice([(True, False), (False, True), (False, False), (True, False), (False, True)])
    ret_ok, ret_fail = rng.choice(RETURNS)
    err = rng.choice(ERRORS)
    code_ok = rng.choice(["201", "200", "'ok'"])
    if code_ok == "'ok'" and ret_ok == "ok":
        code_ok = "201"
    override = rng.random() < 0.4
    ov_val = rng.choice(["idle", "reset", "closed"])
    tail = rng.choice(["button locked", "spinner on", "form disabled"])
    fn = rng.choice(["submit", "sendForm", "postForm"])
    lines = ["const send = (id, ms, ok) => new Promise((resolve, reject) =>",
             f"  setTimeout(() => (ok ? resolve({code_ok}) : reject(new Error('{err}'))), ms));",
             f"async function {fn}(id, ms, ok) {{",
             "  try {",
             "    console.log('send', id);",
             "    console.log('sent', id, await send(id, ms, ok));",
             f"    return '{ret_ok}';",
             "  } catch (e) {",
             "    console.log('catch', id, e.message);",
             f"    return '{ret_fail}';",
             "  } finally {",
             "    console.log('finally', id);"]
    if override:
        lines.append(f"    return '{ov_val}';")
    lines += ["  }", "}"]
    for i in range(2):
        lines.append(f"{fn}({ids[i]}, {delays[i]}, {'true' if pattern[i] else 'false'})"
                     f".then((r) => console.log('result', {ids[i]}, r));")
    lines.append(f"console.log('{tail}');")
    code = "\n".join(lines)
    shown_ok = code_ok.strip("'")
    log = [f"send {ids[0]}", f"send {ids[1]}", tail]
    traces = []
    for i in sorted(range(2), key=lambda k: delays[k]):
        res = ov_val if override else (ret_ok if pattern[i] else ret_fail)
        if pattern[i]:
            log += [f"sent {ids[i]} {shown_ok}", f"finally {ids[i]}", f"result {ids[i]} {res}"]
            traces.append(f"{delays[i]} мс — ответ для {ids[i]}: sent, затем finally, затем then")
        else:
            log += [f"catch {ids[i]} {err}", f"finally {ids[i]}", f"result {ids[i]} {res}"]
            traces.append(f"{delays[i]} мс — ошибка для {ids[i]}: catch, затем finally, затем then")
    out = "\n".join(log)
    ov_txt = (f" return '{ov_val}' в finally подменяет значение, возвращённое из try / catch, поэтому оба "
              f"результата — {ov_val}." if override else
              " finally ничего не возвращает, поэтому результат — значение return из try или catch.")
    expl = (f"Синхронно: оба вызова печатают «send» и останавливаются на await, затем «{tail}». Дальше таймеры по "
            f"возрастанию задержки, после каждого строки идут подряд микрозадачами: " + "; ".join(traces) +
            f". finally выполняется после return из try или catch, до then.{ov_txt}")
    stem = (f"React Native-экран ({ctx}) отправляет две формы параллельно; send имитирует запрос с задержкой ms, "
            f"который выполняется (ok = true) или завершается ошибкой.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"ids": ids, "delays": delays, "pattern": list(pattern), "override": override},
                          language="javascript")
