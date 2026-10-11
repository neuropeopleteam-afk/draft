"""mobile.ios.appearance_mcq — mcq_concept: колбэки появления UIViewController при навигации и модальных экранах.

Экран A — корневой в UINavigationController и уже на экране. Сценарий из двух действий; варианты — какие из
`viewDidLoad`, `viewWillAppear`, `viewDidAppear`, `viewWillDisappear`, `viewDidDisappear` получит A и в каком
порядке. Факты (документация UIKit): push/pop в навигационном стеке — A получает will/didDisappear и при
возврате will/didAppear (без повторного viewDidLoad); модальный показ `.fullScreen` — так же; `.pageSheet`
(и `.automatic`, который для обычного контроллера с iOS 13 означает лист) оставляет A в иерархии — колбэков
появления нет ни при показе, ни при закрытии; уход приложения в фон и возврат — колбэков появления нет
(только уведомления сцены); поворот — только `viewWillTransition`/layout. Дистракторы — та же модель с одним
заблуждением. Ключ проверяется исполнением модели в песочнице.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import balanced_options

FAMILY_ID = "mobile.ios.appearance_mcq"

MODEL = r'''
def callbacks(actions, wrong=()):
    """Колбэки появления экрана A (корневой в UINavigationController, уже на экране)."""
    away = ["viewWillDisappear", "viewDidDisappear"]
    back = ["viewWillAppear", "viewDidAppear"]
    if "reload_on_return" in wrong:
        back = ["viewDidLoad"] + back
    out = []
    for a in actions:
        if a in ("push", "full_screen"):
            out += away + back
        elif a in ("page_sheet", "automatic"):
            if "sheet_disappears" in wrong or (a == "automatic" and "automatic_is_full" in wrong):
                out += away + back
        elif a == "background":
            if "background_disappears" in wrong:
                out += away + back
        elif a == "rotate":
            if "rotate_reappears" in wrong:
                out += back
    return out
'''
_ns: dict = {}
exec(MODEL, _ns)  # noqa: S102 — код модели банка, тот же исполняется в проверке
callbacks = _ns["callbacks"]

ACTIONS = {
    "push": "открывает экран подробностей через `navigationController?.pushViewController(_:animated:)` и "
            "возвращается кнопкой «Назад»",
    "full_screen": "открывает экран оплаты модально с `modalPresentationStyle = .fullScreen` и закрывает его "
                   "(`dismiss(animated:)`)",
    "page_sheet": "открывает фильтры модально с `modalPresentationStyle = .pageSheet` и закрывает лист "
                  "свайпом вниз",
    "automatic": "открывает выбор города через `present(_:animated:)` без настройки `modalPresentationStyle` "
                 "(обычный UIViewController, iOS 17) и закрывает его свайпом вниз",
    "background": "сворачивает приложение и через минуту возвращается в него",
    "rotate": "поворачивает iPhone в альбомную ориентацию и обратно",
}
WRONG = ["reload_on_return", "sheet_disappears", "automatic_is_full", "background_disappears", "rotate_reappears"]
CTX = ["список заказов", "лента", "каталог", "главный экран банка", "список чатов", "расписание"]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _fmt(seq):
    return " → ".join(seq) if seq else "ни одного из перечисленных колбэков"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(300):
        acts = rng.sample(sorted(ACTIONS), 2)
        if {"page_sheet", "automatic"} <= set(acts):
            continue
        good = callbacks(acts)
        wrongs = {}
        for w in WRONG:
            seq = callbacks(acts, (w,))
            if seq != good and tuple(seq) not in {tuple(x) for x in wrongs.values()}:
                wrongs[w] = seq
        for w1 in WRONG:
            for w2 in WRONG:
                if w1 < w2 and len(wrongs) < 3:
                    seq = callbacks(acts, (w1, w2))
                    if seq != good and tuple(seq) not in {tuple(x) for x in wrongs.values()}:
                        wrongs[w1 + "+" + w2] = seq
        if len(wrongs) >= 3:
            break
    else:
        raise RuntimeError("нет сценария с тремя дистракторами")
    chosen = rng.sample(sorted(wrongs), 3)
    opts, key = balanced_options(FAMILY_ID, seed, rng, (_fmt(good), None),
                                 [(_fmt(wrongs[w]), None) for w in chosen])
    ctx = rng.choice(CTX)
    name = rng.choice(["OrdersViewController", "HomeViewController", "ListViewController", "RootViewController"])
    stem = (f"iOS-приложение, экран «{ctx}» — `{name}` (A), корневой в `UINavigationController`, уже на экране. "
            f"В `viewDidLoad`, `viewWillAppear`, `viewDidAppear`, `viewWillDisappear` и `viewDidDisappear` "
            f"экрана A стоит запись в журнал. Пользователь {ACTIONS[acts[0]]}, затем {ACTIONS[acts[1]]}. Какие "
            f"записи A появятся в журнале, по порядку?")
    opt_map = {o.id: o.text for o in opts}
    prog = (MODEL + f"\nopts = {opt_map!r}\ngood = callbacks({acts!r})\n"
            "text = ' → '.join(good) if good else 'ни одного из перечисленных колбэков'\n"
            "hit = [k for k, v in opts.items() if v == text]\nprint(hit[0] if len(hit) == 1 else 'AMBIGUOUS')\n")
    checks = [Check(name="appearance_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=key)]
    notes = {"push": "push и «Назад»: will/didDisappear, затем will/didAppear; view уже загружено — viewDidLoad не "
                     "повторяется",
             "full_screen": "полноэкранный модальный показ убирает A из иерархии: will/didDisappear, при закрытии "
                            "will/didAppear",
             "page_sheet": "лист (.pageSheet) оставляет A в иерархии — колбэков появления нет ни при показе, ни при "
                           "закрытии",
             "automatic": "стиль .automatic для обычного контроллера с iOS 13 — лист: колбэков появления у A нет",
             "background": "уход в фон и возврат не вызывают колбэков появления, только уведомления сцены",
             "rotate": "поворот вызывает viewWillTransition и layout, но не колбэки появления"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"Верно: {_fmt(good)}. " + _cap("; ".join(notes[a] for a in acts)) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется моделью колбэков появления UIViewController на Python.",
                         params={"actions": acts, "distractors": chosen})
