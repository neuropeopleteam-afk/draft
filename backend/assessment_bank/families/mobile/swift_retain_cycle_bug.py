"""mobile.swift.retain_cycle_bug — find_bug (Swift, чтение кода): цикл сильных ссылок через сохранённое замыкание.

Экран (UIViewController) владеет моделью представления (`let viewModel`), а модель хранит замыкание-колбэк,
которое захватывает `self` сильно: контроллер → модель → замыкание → контроллер. После закрытия экрана ARC не
освобождает этот цикл — `deinit` не вызывается, подписки и таймеры экрана продолжают работать. Рядом — замыкания,
которые тоже упоминают `self`, но не сохраняются (`UIView.animate`, `DispatchQueue.main.async`), и сохранённое
замыкание с `[weak self]`: они цикла не образуют. Один подтип дефекта; варьируются экран, имена, состав и
порядок служебных строк.

Swift в песочнице не исполняется: ключ проверяет модель ARC на Python, которая разбирает ПОКАЗАННЫЙ код (вложен
дословно): сильные свойства-объекты, замыкания, присвоенные свойствам объектов (хранятся), и захват `self` без
`[weak self]`/`[unowned self]`; контроллер утекает, если из него по сильным ссылкам достижим он сам.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng, plural
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import py_literal_block

FAMILY_ID = "mobile.swift.retain_cycle_bug"

SCREENS = [("ChatViewController", "ChatViewModel", "чат", "onMessages", "messages", "render(messages)"),
           ("CartViewController", "CartViewModel", "корзина", "onTotalChange", "total", "updateTotal(total)"),
           ("MapViewController", "MapViewModel", "карта курьера", "onLocation", "point", "move(to: point)"),
           ("PlayerViewController", "PlayerViewModel", "плеер", "onProgress", "time", "showProgress(time)"),
           ("OrderViewController", "OrderViewModel", "статус заказа", "onStatus", "status", "apply(status)"),
           ("FeedViewController", "FeedViewModel", "лента", "onItems", "items", "reload(with: items)")]
OTHER = [("onError", "error", "showError(error)"), ("onLoading", "isLoading", "setSpinner(isLoading)"),
         ("onEmpty", "isEmpty", "showPlaceholder(isEmpty)")]

MODEL = r'''
import re

def leaks(src):
    """Модель ARC: True, если контроллер достижим сам из себя по сильным ссылкам."""
    owned = set()            # свойства контроллера — сильные ссылки на объекты
    stored = []              # (объект-владелец, захват self сильный?) для сохранённых замыканий
    for line in src.splitlines():
        s = line.strip()
        m = re.match(r"(?:private )?let (\w+) = \w+\(", s)
        if m:
            owned.add(m.group(1))
        m = re.match(r"(?:self\.)?(\w+)\.\w+ = \{(.*)\}$", s)
        if m:
            body = m.group(2)
            weak = re.match(r"\s*\[(weak|unowned) self\]", body) is not None
            uses_self = re.search(r"\bself\b", body) is not None
            stored.append((m.group(1), uses_self and not weak))
        # UIView.animate / DispatchQueue.main.async: замыкание не хранится объектом контроллера
    graph = {"vc": set(owned)}
    for owner, strong in stored:
        if strong:
            graph.setdefault(owner, set()).add("vc")
    seen, todo = set(), list(graph["vc"])
    while todo:
        n = todo.pop()
        if n == "vc":
            return True
        if n in seen:
            continue
        seen.add(n)
        todo.extend(graph.get(n, ()))
    return False
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    vc, vmt, ctx, cb, arg, call = rng.choice(SCREENS)
    vm = rng.choice(["viewModel", "model", "presenter"])
    ocb, oarg, ocall = rng.choice(OTHER)
    animate = rng.random() < 0.5
    bad = f"        {vm}.{cb} = {{ {arg} in self.{call} }}"
    good = f"        {vm}.{cb} = {{ [weak self] {arg} in self?.{call} }}"
    other = f"        {vm}.{ocb} = {{ [weak self] {oarg} in self?.{ocall} }}"
    lines_bind = [bad, other]
    rng.shuffle(lines_bind)
    extra = (["        UIView.animate(withDuration: 0.25) { self.view.alpha = 1 }"] if animate else
             ["        DispatchQueue.main.async { self.title = \"" + ctx.capitalize() + "\" }"])

    def body(target):
        b = [x if x != bad else target for x in lines_bind]
        out = [f"final class {vc}: UIViewController {{", f"    private let {vm} = {vmt}()", "",
               "    override func viewDidLoad() {", "        super.viewDidLoad()"]
        mid = b + extra
        if rng_order:
            mid = extra + b
        out += mid + [f"        {vm}.start()", "    }", "",
                      "    deinit {", f"        {vm}.stop()", "    }", "}"]
        return "\n".join(out)
    rng_order = rng.random() < 0.5
    buggy, fixed = body(bad), body(good)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))

    def prog(src, expect_leak):
        return (MODEL + "\n" + py_literal_block("SRC", src) +
                f"leak = leaks(SRC)\nprint('RESULT: PASS' if not leak else 'RESULT: FAIL leak')\n")
    checks = [Check(name="buggy_fails", runner="python", program=prog(buggy, True), expect="fail"),
              Check(name="fixed_passes", runner="python", program=prog(fixed, False), expect="pass",
                    embeds_display_code=False)]
    n = rng.choice([3, 4, 5, 6, 8])
    stem = (f"iOS-приложение, экран «{ctx}» (`{vc}`). После того как пользователь {n} "
            f"{plural(n, 'раз', 'раза', 'раз')} открыл и закрыл экран, в Memory Graph Debugger видно {n} живых "
            f"экземпляров `{vc}` и `{vmt}`, `deinit` не вызывается, а `{vm}.stop()` не срабатывает. Укажите номер "
            f"строки, из-за которой экран не освобождается.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: замыкание сохраняется в свойстве `{vm}.{cb}` и захватывает "
                                f"`self` сильно — цикл «контроллер → {vm} → замыкание → контроллер», ARC его не "
                                f"освобождает. Исправление — `[weak self]` и `self?.`. Замыкание "
                                f"{'UIView.animate' if animate else 'DispatchQueue.main.async'} не хранится "
                                f"объектами контроллера (выполняется и отпускается), колбэк `{ocb}` уже со "
                                f"`[weak self]`."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="stored_closure_strong_self",
                         display_code_note=("Swift не исполняется: показанный код вложен дословно в программу на "
                                            "Python — модель ARC (сильные свойства, сохранённые замыкания, захват self)."),
                         params={"fixed_code": fixed, "callback": cb})
