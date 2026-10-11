"""mobile.android.lifecycle_mcq — mcq_concept: какие колбэки жизненного цикла Activity вызовутся и в каком порядке.

Сценарий из двух действий пользователя над экраном A (Activity уже на переднем плане). Варианты ответа —
последовательности колбэков A; дистракторы — результат той же модели с одним типичным заблуждением:
поворот без пересоздания, обычный диалог (AlertDialog/DialogFragment) приостанавливает Activity,
полупрозрачная Activity (тема Dialog) останавливает экран под ней, возврат без onRestart, «Домой» уничтожает
Activity, объявленный configChanges не отменяет пересоздание. Факты — документация Android «The activity
lifecycle» и «Handle configuration changes».

Ключ проверяется исполнением: модель жизненного цикла (функция ниже) исполняется в песочнице на сценарии и
печатает букву варианта, совпавшего с верной последовательностью.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import balanced_options

FAMILY_ID = "mobile.android.lifecycle_mcq"

MODEL = r'''
def callbacks(actions, config_handled, wrong=()):
    """Колбэки Activity A (уже на переднем плане) на последовательность действий; wrong — заблуждения."""
    out = []
    for a in actions:
        if a == "rotate":
            if config_handled and "config_ignored" not in wrong:
                out += ["onConfigurationChanged"]
            elif "rotate_no_recreate" in wrong:
                out += ["onPause", "onResume"]
            else:
                out += ["onPause", "onStop", "onDestroy", "onCreate", "onStart", "onResume"]
        elif a == "alert":            # AlertDialog / DialogFragment поверх A
            out += ["onPause", "onResume"] if "dialog_pauses" in wrong else []
        elif a == "dialog_activity":  # Activity с темой Dialog (полупрозрачная) и «Назад»
            out += (["onPause", "onStop", "onRestart", "onStart", "onResume"] if "translucent_stops" in wrong
                    else ["onPause", "onResume"])
        elif a in ("opaque", "home", "lock"):   # уход в фон / перекрытие и возврат
            if a == "home" and "home_destroys" in wrong:
                out += ["onPause", "onStop", "onDestroy", "onCreate", "onStart", "onResume"]
            elif "no_restart" in wrong:
                out += ["onPause", "onStop", "onStart", "onResume"]
            else:
                out += ["onPause", "onStop", "onRestart", "onStart", "onResume"]
    return out
'''
_ns: dict = {}
exec(MODEL, _ns)  # noqa: S102 — код модели банка, тот же исполняется в проверке
callbacks = _ns["callbacks"]

ACTIONS = {
    "rotate": "поворачивает экран",
    "alert": "нажимает «Удалить», появляется AlertDialog с подтверждением, пользователь нажимает «Отмена»",
    "dialog_activity": ("открывает выбор даты — отдельную Activity с темой `Theme.Material3.Dialog` "
                        "(полупрозрачная, A видна под ней) — и возвращается кнопкой «Назад»"),
    "opaque": "открывает полноэкранную Activity настроек и возвращается кнопкой «Назад»",
    "home": "нажимает «Домой» и через минуту возвращается в приложение из списка недавних",
    "lock": "блокирует телефон кнопкой питания и сразу разблокирует",
}
WRONG = ["rotate_no_recreate", "config_ignored", "dialog_pauses", "translucent_stops", "no_restart",
         "home_destroys"]
CTX = ["редактор заметки", "оформление заказа", "профиль", "карточка товара", "чат", "плеер подкаста",
       "экран тренировки"]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _fmt(seq):
    return " → ".join(seq) if seq else "ни одного из перечисленных колбэков"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(200):
        acts = rng.sample(sorted(ACTIONS), 2)
        cfg = "rotate" in acts and rng.random() < 0.4
        good = callbacks(acts, cfg)
        wrongs = {}
        for w in WRONG:
            seq = callbacks(acts, cfg, (w,))
            if seq != good and tuple(seq) not in {tuple(x) for x in wrongs.values()}:
                wrongs[w] = seq
        if len(wrongs) < 3:
            for w1 in WRONG:
                for w2 in WRONG:
                    if w1 < w2 and len(wrongs) < 3:
                        seq = callbacks(acts, cfg, (w1, w2))
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
    name = rng.choice(["EditorActivity", "MainActivity", "DetailsActivity", "HostActivity"])
    manifest = ("в манифесте у A объявлено `android:configChanges=\"orientation|screenSize|screenLayout\"`, "
                "`onConfigurationChanged` переопределён" if cfg else
                "`android:configChanges` в манифесте не объявлен")
    stem = (f"Android-приложение, экран «{ctx}» — `{name}` (A), сейчас на переднем плане; {manifest}. Во всех "
            f"колбэках жизненного цикла A (`onCreate`, `onStart`, `onResume`, `onPause`, `onStop`, `onRestart`, "
            f"`onDestroy`) и в `onConfigurationChanged` стоит запись в журнал. Пользователь {ACTIONS[acts[0]]}, "
            f"затем {ACTIONS[acts[1]]}. Система процесс не завершает. Какие записи A появятся в журнале, по порядку?")
    opt_map = {o.id: o.text for o in opts}
    prog = (MODEL + f"\nopts = {opt_map!r}\ngood = callbacks({acts!r}, {cfg!r})\n"
            "text = ' → '.join(good) if good else 'ни одного из перечисленных колбэков'\n"
            "hit = [k for k, v in opts.items() if v == text]\nprint(hit[0] if len(hit) == 1 else 'AMBIGUOUS')\n")
    checks = [Check(name="lifecycle_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=key)]
    notes = {"rotate": ("поворот без configChanges пересоздаёт Activity (onPause → onStop → onDestroy → onCreate → "
                        "onStart → onResume)" if not cfg else "при объявленном configChanges Activity не "
                        "пересоздаётся, вызывается только onConfigurationChanged"),
             "alert": "AlertDialog и DialogFragment — окна внутри той же Activity, колбэков жизненного цикла нет",
             "dialog_activity": "под полупрозрачной Activity экран A остаётся видимым: только onPause, затем onResume",
             "opaque": "перекрытие полноэкранной Activity: onPause → onStop, возврат: onRestart → onStart → onResume",
             "home": "«Домой» останавливает, но не уничтожает Activity: возврат через onRestart",
             "lock": "блокировка экрана останавливает Activity, разблокировка — onRestart → onStart → onResume"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"Верно: {_fmt(good)}. " + _cap("; ".join(notes[a] for a in acts)) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Ответ проверяется моделью жизненного цикла Activity на Python.",
                         params={"actions": acts, "config_handled": cfg, "distractors": chosen})
