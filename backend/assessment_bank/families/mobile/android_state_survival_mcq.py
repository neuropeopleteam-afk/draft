"""mobile.android.state_survival_mcq — mcq_concept: какие данные экрана переживут поворот, смерть процесса, закрытие.

Экран Android хранит четыре значения в разных местах: поле Activity, свойство ViewModel, SavedStateHandle
(или onSaveInstanceState / rememberSaveable), Room, `remember {}` в Compose, Kotlin `object`. Факты
(developer.android.com, «Save UI states»): пересоздание Activity при повороте теряет поля Activity и
`remember`, ViewModel переживает поворот; смерть процесса, инициированная системой в фоне, теряет всё в
памяти (ViewModel, object), но сохранённое состояние экземпляра (SavedStateHandle, Bundle, rememberSaveable)
восстанавливается; закрытие задачи пользователем (смахивание из «Недавних») сбрасывает и сохранённое
состояние; Room — на диске, переживает всё. Дистракторы — модель с одним заблуждением.
Ключ проверяется исполнением модели в песочнице.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import balanced_options

FAMILY_ID = "mobile.android.state_survival_mcq"

MODEL = r'''
def survives(store, event, wrong=()):
    """Переживёт ли значение в хранилище store событие event (wrong — заблуждения)."""
    if store == "room":
        return True
    if event == "rotate":
        if store in ("field", "remember"):
            return store == "field" and "field_survives_rotation" in wrong or \
                   store == "remember" and "remember_survives_rotation" in wrong
        return True
    if event == "process_death":
        if store == "saved_state":
            return True
        return (store == "viewmodel" and "viewmodel_survives_death" in wrong) or \
               (store == "object" and "object_survives_death" in wrong)
    if event == "user_closes":
        return store == "saved_state" and "saved_survives_close" in wrong
    raise ValueError(event)
'''
_ns: dict = {}
exec(MODEL, _ns)  # noqa: S102 — код модели банка, тот же исполняется в проверке
survives = _ns["survives"]

STORES = {"field": "в поле Activity (`private var {n}`)", "viewmodel": "в свойстве ViewModel",
          "saved_state": "в `SavedStateHandle` ViewModel", "room": "в таблице Room",
          "remember": "в Compose через `remember {{ mutableStateOf(...) }}`", "object": "в Kotlin `object` (синглтон)"}
EVENTS = {"rotate": "поворачивает экран",
          "process_death": ("сворачивает приложение; пока оно в фоне, система завершает процесс из-за нехватки "
                            "памяти; затем пользователь возвращается в приложение из «Недавних»"),
          "user_closes": "смахивает приложение из списка «Недавние» и запускает его заново с иконки"}
WRONG = ["field_survives_rotation", "remember_survives_rotation", "viewmodel_survives_death",
         "object_survives_death", "saved_survives_close"]
FIELDS = [("черновик комментария", "draft"), ("номер выбранной вкладки", "tab"), ("текст поиска", "query"),
          ("позиция прокрутки", "scroll"), ("выбранная дата", "date"), ("отмеченные фильтры", "filters"),
          ("номер шага анкеты", "step")]
CTX = ["маркетплейс", "приложение банка", "соцсеть", "трекер задач", "приложение доставки", "онлайн-школа"]


def _fmt(names):
    return ", ".join(names) if names else "ни одно из значений"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(300):
        event = rng.choice(sorted(EVENTS))
        stores = rng.sample(sorted(STORES), 4)
        fields = rng.sample(FIELDS, 4)
        good = [f[0] for f, s in zip(fields, stores) if survives(s, event)]
        wrongs = {}
        for w in WRONG:
            res = [f[0] for f, s in zip(fields, stores) if survives(s, event, (w,))]
            if res != good and tuple(res) not in {tuple(x) for x in wrongs.values()}:
                wrongs[w] = res
        for w1 in WRONG:
            for w2 in WRONG:
                if w1 < w2 and len(wrongs) < 3:
                    res = [f[0] for f, s in zip(fields, stores) if survives(s, event, (w1, w2))]
                    if res != good and tuple(res) not in {tuple(x) for x in wrongs.values()}:
                        wrongs[w1 + "+" + w2] = res
        if len(wrongs) >= 3:
            break
    else:
        raise RuntimeError("нет сценария с тремя дистракторами")
    chosen = rng.sample(sorted(wrongs), 3)
    opts, key = balanced_options(FAMILY_ID, seed, rng, (_fmt(good), None),
                                 [(_fmt(wrongs[w]), None) for w in chosen])
    ctx = rng.choice(CTX)
    desc = "; ".join(f"{f[0]} — {STORES[s].format(n=f[1])}" for f, s in zip(fields, stores))
    stem = (f"Android-приложение ({ctx}), экран на одной Activity, `android:configChanges` не объявлен. Экран "
            f"хранит: {desc}. Пользователь заполняет всё, затем {EVENTS[event]}. Какие значения будут на экране "
            f"после этого (не сброшены к начальным)?")
    opt_map = {o.id: o.text for o in opts}
    prog = (MODEL + f"\nopts = {opt_map!r}\nfields = {[f[0] for f in fields]!r}\nstores = {stores!r}\n"
            f"good = [f for f, s in zip(fields, stores) if survives(s, {event!r})]\n"
            "text = ', '.join(good) if good else 'ни одно из значений'\n"
            "hit = [k for k, v in opts.items() if v == text]\nprint(hit[0] if len(hit) == 1 else 'AMBIGUOUS')\n")
    checks = [Check(name="state_model", runner="python", program=prog, expect="stdout_equals", expected_stdout=key)]
    rule = {"rotate": "поворот пересоздаёт Activity: теряются поля Activity и `remember`; ViewModel, "
                      "SavedStateHandle, Room и object живут",
            "process_death": "после смерти процесса память пуста (ViewModel и object потеряны), но система "
                             "восстанавливает сохранённое состояние экземпляра (SavedStateHandle); Room — на диске",
            "user_closes": "закрытие задачи пользователем сбрасывает и сохранённое состояние экземпляра; "
                           "остаётся только записанное на диск (Room)"}[event]
    ak = AnswerKey(kind="option", value=key, explanation=f"Верно: {_fmt(good)}. {rule[:1].upper() + rule[1:]}.")
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется моделью сохранения состояния на Python.",
                         params={"event": event, "stores": stores, "distractors": chosen})
