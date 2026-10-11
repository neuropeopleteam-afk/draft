"""mobile.swift.ui_main_thread_bug — find_bug (Swift, чтение кода): обновление интерфейса из фоновой очереди.

Обработчик завершения `URLSession.dataTask` вызывается на фоновой очереди сессии. Разбор ответа там допустим,
а изменение UIKit (текст метки, скрытие индикатора, `reloadData`) — только на главной очереди (Main Thread
Checker, «UI API called on a background thread»). В шаблоне ровно одно обращение к UIKit внутри обработчика без
`DispatchQueue.main.async`; рядом — обращения к UIKit до запуска запроса (на главной очереди) и внутри уже
обёрнутого блока. Один подтип дефекта; варьируются экран, элемент интерфейса, порядок служебных строк.

Swift в песочнице не исполняется: ключ проверяет модель очередей на Python, которая разбирает ПОКАЗАННЫЙ код
(вложен дословно): функция вызывается на главной очереди, тело обработчика `dataTask { … in` — фоновая очередь,
`DispatchQueue.main.async { … }` — главная; обращение к UIKit вне главной — ошибка.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import py_literal_block

FAMILY_ID = "mobile.swift.ui_main_thread_bug"

SCREENS = [("WeatherViewController", "погода", "Forecast", "temperatureLabel.text = forecast.text"),
           ("BalanceViewController", "баланс счёта", "Balance", "balanceLabel.text = balance.formatted"),
           ("TrackingViewController", "отслеживание посылки", "Parcel", "statusLabel.text = parcel.status"),
           ("ProfileViewController", "профиль", "Profile", "nameLabel.text = profile.fullName"),
           ("RatesViewController", "курсы валют", "Rates", "rateLabel.text = rates.summary"),
           ("ScoreViewController", "счёт матча", "Score", "scoreLabel.text = score.text")]
UI_EXTRA = ["spinner.stopAnimating()", "refreshControl.endRefreshing()", "retryButton.isHidden = true",
            "tableView.reloadData()"]

MODEL = r'''
import re

UI = re.compile(r"\b(\w+Label\.text\s*=|spinner\.\w+\(|refreshControl\.\w+\(|\w+Button\.isHidden\s*=|tableView\.reloadData\(|view\.\w+\s*=)")

def violations(src):
    """Модель очередей: обращения к UIKit не на главной очереди (номера строк)."""
    bad, stack = [], ["main"]
    for no, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        inline = re.match(r"DispatchQueue\.main\.async\s*\{(.*)\}$", s)
        if inline:
            continue                                   # однострочный блок на главной очереди
        if UI.search(s) and stack[-1] != "main":
            bad.append(no)
        if re.search(r"dataTask\(with: \w+\)\s*\{.*\bin\s*$", s):
            stack.append("bg"); continue
        if re.search(r"DispatchQueue\.main\.async\s*\{\s*$", s):
            stack.append("main"); continue
        for _ in range(s.count("{")):
            stack.append(stack[-1])
        for _ in range(s.count("}")):
            if len(stack) > 1:
                stack.pop()
    return bad
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    vc, ctx, model, ui_line = rng.choice(SCREENS)
    var = ui_line.split(" = ")[1].split(".")[0]
    extra_ui = rng.choice(UI_EXTRA)
    url_name = rng.choice(["url", "endpoint", "requestURL"])
    task_name = rng.choice(["task", "request", "job"])
    start_ui = rng.choice(["spinner.startAnimating()", "retryButton.isHidden = true"])
    if start_ui.split(".")[0] == extra_ui.split(".")[0]:
        start_ui = "view.isUserInteractionEnabled = false" if start_ui.startswith("retry") else "retryButton.isHidden = true"
    guard_style = rng.random() < 0.5
    bad = f"            self.{ui_line}"
    good = f"            DispatchQueue.main.async {{ self.{ui_line} }}"
    wrapped = ["            DispatchQueue.main.async {", f"                self.{extra_ui}", "            }"]
    wrapped_first = rng.random() < 0.5

    def body(target):
        out = [f"final class {vc}: UIViewController {{", "    func reload() {", f"        {start_ui}",
               f"        let {task_name} = URLSession.shared.dataTask(with: {url_name}) {{ data, _, error in"]
        if guard_style:
            out += ["            guard let data = data, error == nil else { return }",
                    f"            let {var} = try? JSONDecoder().decode({model}.self, from: data)"]
        else:
            out += ["            if error != nil { return }",
                    f"            let {var} = try? JSONDecoder().decode({model}.self, from: data ?? Data())"]
        out += [f"            guard let {var} = {var} else {{ return }}"]
        tail = wrapped + [target] if wrapped_first else [target] + wrapped
        out += tail + ["        }", f"        {task_name}.resume()", "    }", "}"]
        return "\n".join(out)
    buggy, fixed = body(bad), body(good)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))

    def prog(src):
        return (MODEL + "\n" + py_literal_block("SRC", src) +
                "bad = violations(SRC.strip('\\n'))\nprint('RESULT: PASS' if not bad else 'RESULT: FAIL ' + repr(bad))\n")
    checks = [Check(name="buggy_fails", runner="python", program=prog(buggy), expect="fail"),
              Check(name="fixed_passes", runner="python", program=prog(fixed), expect="pass",
                    embeds_display_code=False)]
    sec = rng.choice([2, 5, 10])
    stem = (f"iOS-приложение, экран «{ctx}». `reload()` вызывается из `viewDidLoad` и по нажатию «Обновить». "
            f"Жалоба: данные иногда появляются на экране только через {sec} с или после касания, в консоли Xcode — "
            f"предупреждение Main Thread Checker «UI API called on a background thread». Укажите номер строки "
            f"с ошибкой.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: обработчик завершения `dataTask` выполняется на фоновой очереди "
                                f"URLSession, а `{ui_line.split(' = ')[0]}` — свойство UIKit, менять его можно "
                                f"только на главной очереди: `DispatchQueue.main.async {{ self.{ui_line} }}`. "
                                f"Разбор JSON в фоне допустим; `{start_ui}` выполняется до запуска "
                                f"запроса на главной очереди; `{extra_ui}` уже обёрнут."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="ui_off_main",
                         display_code_note=("Swift не исполняется: показанный код вложен дословно в программу на "
                                            "Python — модель очередей (фоновый обработчик dataTask, main.async)."),
                         params={"fixed_code": fixed, "extra_ui": extra_ui})
