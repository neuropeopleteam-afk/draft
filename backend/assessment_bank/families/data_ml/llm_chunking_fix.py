"""data_ml.llm.chunking_fix — choose_fix: нарезка документа на фрагменты с перекрытием для RAG.

Исходная функция теряет «хвост» документа (range до len − size). Требования: каждый токен
входит хотя бы в один фрагмент; соседние фрагменты перекрываются ровно на overlap токенов;
последний фрагмент может быть короче; нет фрагментов, целиком содержащихся в предыдущем;
пустой документ → []. Дистракторы: лишний хвостовой фрагмент без break, строгое сравнение
в условии остановки (лишний фрагмент при точном попадании), шаг без перекрытия, граница
range len − overlap (теряет короткие документы), фрагменты длины step.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, plural, py_harness
from assessment_bank.schema import AnswerKey, Check

from ._dm_utils import balanced_options

FAMILY_ID = "data_ml.llm.chunking_fix"

CONTEXTS = [("база знаний службы поддержки", "tokens"), ("договоры с контрагентами", "words"),
            ("внутренние регламенты", "tokens"), ("статьи корпоративной wiki", "words"),
            ("протоколы совещаний", "tokens"), ("техническая документация API", "tokens")]
DISTRACTORS = ["no_break", "strict_stop", "no_overlap", "minus_overlap", "step_len"]


def _impl(kind, fn, seq, nm):
    C, S, P = nm["chunks"], nm["start"], nm["step"]
    guard = ["    if not 0 <= overlap < size:", "        raise ValueError(\"overlap must be in [0, size)\")"]
    step = f"    {C}, {P} = [], size" if kind == "no_overlap" else f"    {C}, {P} = [], size - overlap"
    end = f"len({seq}) - overlap" if kind == "minus_overlap" else f"len({seq})"
    piece = f"{S} + {P}" if kind == "step_len" else f"{S} + size"
    lines = [f"def {fn}({seq}, size, overlap):"] + guard + [step]
    if kind == "minus_overlap":
        lines += [f"    if not {seq}:", "        return []"]
    lines += [f"    for {S} in range(0, {end}, {P}):",
              f"        {C}.append({seq}[{S}:{piece}])"]
    if kind == "strict_stop":
        lines += [f"        if {S} + size > len({seq}):", "            break"]
    elif kind in ("good", "no_overlap", "step_len"):
        lines += [f"        if {S} + size >= len({seq}):", "            break"]
    elif kind == "no_break":
        lines += [f"    if {C} and len({C}[-1]) < overlap:", f"        {C}.pop()"]
    lines.append(f"    return {C}")
    return "\n".join(lines)


def _buggy(fn, seq, nm):
    C, S, P = nm["chunks"], nm["start"], nm["step"]
    return "\n".join([f"def {fn}({seq}, size, overlap):",
                      f"    {C}, {P} = [], size - overlap",
                      f"    for {S} in range(0, len({seq}) - size, {P}):",
                      f"        {C}.append({seq}[{S}:{S} + size])",
                      f"    return {C}"])


def _ref(n, size, overlap):
    out, s, step = [], 0, size - overlap
    while s < n:
        out.append(list(range(s, min(n, s + size))))
        if s + size >= n:
            break
        s += step
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, seq = rng.choice(CONTEXTS)
    fn = rng.choice(["chunk_document", "split_with_overlap", "make_chunks"])
    size = rng.choice([200, 256, 300, 400, 512])
    overlap = rng.choice([size // 10, size // 8, size // 5, size // 4])
    n_doc = rng.randint(3, 7) * (size - overlap) + rng.randint(1, size - overlap - 1)
    starts = list(range(0, n_doc - size, size - overlap))
    lost = n_doc - (starts[-1] + size) if starts else n_doc
    chosen = rng.sample(DISTRACTORS, 3)
    nm = dict(chunks=rng.choice(["chunks", "pieces", "windows"]),
              start=rng.choice(["start", "pos", "offset"]),
              step=rng.choice(["step", "stride", "shift"]))
    buggy = _buggy(fn, seq, nm)
    opts, key = balanced_options(FAMILY_ID, seed, rng, (f"Заменить функцию {fn} на:", _impl("good", fn, seq, nm)),
                             [(f"Заменить функцию {fn} на:", _impl(d, fn, seq, nm)) for d in chosen])
    # тестовые случаи: обычный, точное попадание, короче окна, короче перекрытия, пустой
    cases = [(23, 6, 2), (18, 6, 2), (4, 6, 2), (2, 6, 3), (0, 5, 1), (31, 8, 3), (13, 5, 0)]
    tests = "\n".join(f"assert {fn}(list(range({n})), {s}, {o}) == {_ref(n, s, o)!r}"
                      for n, s, o in cases)
    checks = [Check(name="buggy_fails", runner="python", program=py_harness(buggy, tests), expect="fail")]
    for o in opts:
        checks.append(Check(name=f"option:{o.id}", runner="python", program=py_harness(o.code, tests),
                            embeds_display_code=False, expect="pass" if o.id == key else "fail"))
    stem = (f"RAG-ассистент отвечает по корпусу «{ctx}». Документ разбивается на фрагменты "
            f"с параметрами size = {size} и overlap = {overlap} (в токенах), фрагменты "
            f"индексируются для поиска. Пользователи жалуются, что ассистент не находит сведения "
            f"из конца длинных документов. Требования к нарезке: каждый токен входит хотя бы в "
            f"один фрагмент; соседние фрагменты перекрываются ровно на overlap токенов; последний "
            f"фрагмент может быть короче; не должно быть фрагментов, целиком содержащихся в "
            f"предыдущем; пустой документ даёт пустой список. Какое исправление верно?")
    why = {"no_break": "без остановки цикла в конце появляются фрагменты, целиком "
                       "содержащиеся в предыдущем; удаление последнего фрагмента короче overlap "
                       "не спасает (фрагмент длиной ровно overlap остаётся, а короткий документ "
                       "исчезает)",
           "strict_stop": "при точном попадании (start + size == len) условие > не срабатывает "
                          "и добавляется лишний вложенный фрагмент",
           "no_overlap": "шаг size — фрагменты не перекрываются",
           "minus_overlap": "range до len − overlap не даёт ни одного фрагмента для непустого "
                            "документа не длиннее overlap",
           "step_len": "фрагменты длины step вместо size — перекрытия нет"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"range(0, len − size, step) не доходит до конца: хвост документа "
                               f"(для документа из {n_doc} {plural(n_doc, 'токена', 'токенов', 'токенов')} — последние {lost}) не попадает ни в один фрагмент. Верно — "
                               "идти до len и остановиться, как только фрагмент дошёл до конца. "
                               "Ошибки дистракторов: " + "; ".join(why[d] for d in chosen) + ".")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         defect_type="lost_tail_chunk",
                         params={"distractors": chosen, "size": size, "overlap": overlap})
