"""Помощники семейств уровней Lead и Principal (волна 7, 6 уровней).

Три заготовки, общие для семейств Lead/Principal всех направлений:

* :func:`review_variant` — «ревью на уровне ведущего»: фрагмент дизайн-документа (или описания PR) из
  пунктов, среди которых k заложенных изъянов из пула семейства и несколько здравых решений-«приманок».
  Рубрика собирается по заложенным изъянам (по критерию на изъян, с номером пункта) плюс критерий
  «приоритеты и ложные тревоги»: здравые пункты перечислены в рубрике — объявлять их дефектами нельзя.
  Это даёт параметрические варианты одной трудности: меняются предметная область, числа, набор и
  порядок пунктов, а суть задания (найти и ранжировать риски, предложить проверяемые меры) — нет.
* :func:`scenario_variant` — открытый сценарный вопрос (стратегия, миграция, постмортем): генератор
  семейства строит условие, критерии и эталоны по числам варианта, здесь — общий ключ и сборка.
* :func:`numeric_mcq` — расчётный mcq_concept: варианты ответа — числа одной формы, ключ проверяется
  исполнением программы-модели (обычно — перебором или имитацией, а не той же формулой, что в генераторе).

Оценка открытых ответов — по рубрике с доказательствами (цитата из ответа на каждый пункт рубрики):
формулировки критериев перечисляют наблюдаемые признаки, а не общие слова.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from assessment_bank.gen_utils import build_variant, make_options, make_rng, rubric_from
from assessment_bank.schema import AnswerKey, Check

EVIDENCE_NOTE = (
    "Оценка с доказательствами: пункт рубрики засчитывается только по цитате из ответа, где названо конкретное "
    "решение, число или проверка, относящиеся к условию варианта; общие слова («повысить надёжность», «добавить "
    "мониторинг», «написать тесты») без привязки к условию доказательством не считаются. Эталоны — ориентиры уровня. "
    "Шкала каждого критерия 0–4 (частичный балл): 0 — нет; 1 — упомянуто общими словами; 2 — верная мысль без "
    "привязки к условию; 3 — с числами или фактами условия; 4 — с числами условия, ценой решения и проверкой, что "
    "мера сработала. Балл критерия = уровень / 4 × вес, итог — сумма по критериям. ")
SCALE_0_4 = True


def _weights(k: int, share: float) -> list[float]:
    """k весов, сумма которых ровно share (последний добирает остаток после округления)."""
    w = [round(share / k, 2) for _ in range(k)]
    w[-1] = round(share - sum(w[:-1]), 2)
    return w


def review_variant(family_id: str, seed: int, *, contexts: Sequence[str],
                   facts: Callable[[Any, str], tuple[dict[str, Any], str]],
                   flaws: dict[str, dict[str, str]], sound: Sequence[str], k: int, ask: str,
                   doc_title: str = "Фрагмент дизайн-документа", n_sound: int = 2,
                   code: str | None = None, language: str = "text",
                   weak: str = "", prio_extra: str = "", as_code: str | None = None) -> Any:
    """Вариант «ревью»: k изъянов из ``flaws`` и ``n_sound`` здравых пунктов из ``sound`` в случайном порядке.

    flaws[id] = {item, crit, strong, medium} — шаблоны с полями из ``facts`` (str.format);
    facts(rng, ctx) -> (значения для шаблонов, вводный абзац).
    """
    rng = make_rng(family_id, seed)
    ctx = rng.choice(list(contexts))
    vals, intro = facts(rng, ctx)
    chosen = sorted(rng.sample(sorted(flaws), k))
    decoys = rng.sample(list(sound), n_sound)
    items: list[tuple[str, str | None]] = [(flaws[f]["item"].format(**vals), f) for f in chosen]
    items += [(d.format(**vals), None) for d in decoys]
    rng.shuffle(items)
    num = {f: i for i, (_t, f) in enumerate(items, 1) if f}
    sound_nums = [i for i, (_t, f) in enumerate(items, 1) if f is None]
    if as_code:   # пункты — фрагменты кода (язык as_code), документ уходит в поле code с заголовками фрагментов
        cm = "//" if as_code in ("javascript", "typescript", "go", "java", "kotlin", "swift") else "#"
        code = "\n\n".join(f"{cm} ── Фрагмент {i} ──\n{t}" for i, (t, _f) in enumerate(items, 1)) + "\n"
        language = as_code
        stem = f"{intro}\n\n{ask}"
    else:
        doc = "\n".join(f"{i}. {t}" for i, (t, _f) in enumerate(items, 1))
        stem = f"{intro}\n\n{doc_title}:\n{doc}\n\n{ask}"
    order = sorted(chosen, key=lambda f: num[f])
    ws = _weights(k, 0.8)
    lbl = "Фрагмент" if as_code else "Пункт"
    criteria = [(f, f"{lbl} {num[f]}: " + flaws[f]["crit"].format(**vals), w) for f, w in zip(order, ws)]
    sn = ", ".join(str(n) for n in sound_nums)
    criteria.append(("priorities", (f"Ранжирует риски (что блокирует запуск, что можно позже) и не объявляет "
                                    f"дефектами здравые решения — пункты {sn}; предлагает, как проверить меры "
                                    f"(нагрузочный тест, учения отказа, метрика до/после). {prio_extra}").strip(), 0.2))
    strong = " ".join(f"{lbl} {num[f]}: " + flaws[f]["strong"].format(**vals) for f in order)
    strong += (f" Порядок: сначала пункты {', '.join(str(num[f]) for f in order[:2])} — они блокируют запуск, "
               f"остальное — до первого роста нагрузки; пункты {sn} — здравые решения, их оставляю.")
    medium = " ".join(f"{lbl} {num[f]}: " + flaws[f]["medium"].format(**vals) for f in order[:2])
    weak = weak or "Дизайн в целом нормальный; я бы добавил серверов, мониторинг и побольше тестов."
    ak = AnswerKey(kind="rubric", value="rubric",
                   explanation=(f"Заложены изъяны в пунктах {', '.join(str(num[f]) for f in order)}; пункты {sn} — "
                                f"здравые решения (ложная тревога по ним снижает балл за приоритеты)."))
    rub = rubric_from({"criteria": criteria, "strong": strong, "medium": medium, "weak": weak,
                       "notes": EVIDENCE_NOTE + f"Заложенные изъяны: {', '.join(order)}."})
    return build_variant(family_id, seed, stem=stem, answer_key=ak, rubric=rub,
                         context=ctx if isinstance(ctx, str) else ctx[0],
                         verification="rubric_only", language=language, code=code,
                         params={"flaws": order, "flaw_items": {f: num[f] for f in order},
                                 "sound_items": sound_nums, **{k_: v for k_, v in vals.items()
                                                               if isinstance(v, (int, float, str))}})


def scenario_variant(family_id: str, seed: int, *, contexts: Sequence[str],
                     build: Callable[[Any, str], dict[str, Any]]) -> Any:
    """Открытый сценарный вопрос: build(rng, ctx) -> {stem, criteria, strong, medium, weak, params, explanation?}."""
    rng = make_rng(family_id, seed)
    ctx = rng.choice(list(contexts))
    d = build(rng, ctx)
    ak = AnswerKey(kind="rubric", value="rubric",
                   explanation=d.get("explanation") or "Открытый ответ оценивается по рубрике с доказательствами.")
    rub = rubric_from({"criteria": d["criteria"], "strong": d["strong"], "medium": d["medium"], "weak": d["weak"],
                       "notes": EVIDENCE_NOTE + d.get("notes", "")})
    return build_variant(family_id, seed, stem=d["stem"], answer_key=ak, rubric=rub,
                         context=ctx if isinstance(ctx, str) else ctx[0],
                         verification="rubric_only", language="text", params=d.get("params", {}))


def numeric_mcq(family_id: str, seed: int, rng: Any, *, ctx: str, stem: str, good: str,
                distractors: Sequence[str], program: str, explanation: str, params: dict[str, Any],
                note: str) -> Any:
    """Расчётный mcq_concept: тексты вариантов различны; ``program`` — шаблон программы-модели, в который
    подставляется словарь {буква: текст варианта} как ``{opts!r}``; программа печатает букву верного варианта."""
    opts, key = make_options(rng, (good, None), [(t, None) for t in distractors])
    shown = {o.id: o.text for o in opts}
    checks = [Check(name="model", runner="python", program=program.replace("__OPTS__", repr(shown)),
                    expect="stdout_equals", expected_stdout=key, embeds_display_code=False)]
    ak = AnswerKey(kind="option", value=key, explanation=explanation)
    return build_variant(family_id, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note=note, params=params)


def fmt_num(x: float, nd: int = 1) -> str:
    """Число по-русски: десятичная запятая, неразрывный пробел в тысячах."""
    s = f"{x:,.{nd}f}".replace(",", " ").replace(".", ",")
    return s


def well_separated(values: Sequence[float], rel: float = 0.12) -> bool:
    """Все попарно различаются не меньше чем на rel от большего (варианты не сливаются при округлении)."""
    v = sorted(values)
    return all(b - a >= rel * max(abs(b), 1e-9) for a, b in zip(v, v[1:]))
