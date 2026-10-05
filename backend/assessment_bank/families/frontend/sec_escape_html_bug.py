"""frontend.sec.escape_html_bug — find_bug: экранирование пользовательских данных перед innerHTML."""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, changed_lines, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.sec.escape_html_bug"

# (функция, объект, поле-автор, поле-текст, css-класс, контекст)
CTX = [("renderComment", "comment", "author", "text", "comment", "комментарии к статье"),
       ("renderReview", "review", "name", "body", "review", "отзывы о товаре"),
       ("renderMessage", "msg", "sender", "message", "chat-line", "чат поддержки"),
       ("renderAnswer", "answer", "user", "content", "answer", "вопросы и ответы")]
DECOYS = [["function formatDate(ts) {", "  return new Date(ts).toISOString().slice(0, 10);", "}"],
          ["const MAX_LEN = 500;"],
          ["function truncate(s, n) {", "  return s.length > n ? s.slice(0, n) + '…' : s;", "}"],
          ["const isBlank = (s) => !s || !s.trim();"],
          ["function initials(name) {", "  return name.split(' ').map((w) => w[0]).join('');", "}"]]
ENT = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def _esc(s: str) -> str:
    return "".join(ENT.get(ch, ch) for ch in s)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fn, obj, fa, ft, css, ctx = rng.choice(CTX)
    subtype = rng.choice(["no_global_lt", "no_global_quot", "raw_field", "unquoted_attr"])
    esc_name = rng.choice(["escapeHtml", "htmlEscape", "escapeText", "toSafeHtml"])
    rep = {"&": "    .replace(/&/g, '&amp;')", "<": "    .replace(/</g, '&lt;')",
           ">": "    .replace(/>/g, '&gt;')", '"': "    .replace(/\"/g, '&quot;')",
           "'": "    .replace(/'/g, '&#39;');"}
    good = {"lt": rep["<"], "quot": rep['"'],
            "author": f"  const {fa} = {esc_name}({obj}.{fa});",
            "tpl": f"  return `<li class=\"{css}\" data-{fa}=\"${{{fa}}}\"><b>${{{fa}}}</b>: ${{{ft}}}</li>`;"}
    bad = dict(good)
    if subtype == "no_global_lt":
        bad["lt"] = "    .replace('<', '&lt;')"
    elif subtype == "no_global_quot":
        bad["quot"] = "    .replace('\"', '&quot;')"
    elif subtype == "raw_field":
        bad["author"] = f"  const {fa} = {obj}.{fa}.trim();"
    else:
        bad["tpl"] = f"  return `<li class=\"{css}\" data-{fa}=${{{fa}}}><b>${{{fa}}}</b>: ${{{ft}}}</li>`;"

    def body(g):
        return [f"function {esc_name}(value) {{", "  return String(value)", rep["&"], g["lt"], rep[">"],
                g["quot"], rep["'"], "}", "", f"function {fn}({obj}) {{", g["author"],
                f"  const {ft} = {esc_name}({obj}.{ft});", g["tpl"], "}"]
    decoy = rng.choice(DECOYS)
    first = rng.random() < 0.4

    def assemble(g):
        b = body(g)
        return "\n".join((decoy + [""] + b) if first else (b + [""] + decoy))
    buggy, fixed = assemble(bad), assemble(good)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    nick = rng.choice(["Анна", "Олег", "kate_m", "Dmitry", "Ирина К."])
    payload = {
        "no_global_lt": (ft, f"Смотрите: <b>скидка</b> <img src=x onerror=alert({rng.randint(1, 9)})>"),
        "no_global_quot": (fa, f'{nick}" data-x="1" onmouseover="alert({rng.randint(1, 9)})'),
        "raw_field": (fa, f"<img src=x onerror=alert({rng.randint(1, 9)})>"),
        "unquoted_attr": (fa, f"{nick} onmouseover=alert({rng.randint(1, 9)})"),
    }[subtype]
    cases = [{fa: nick, ft: "Отлично, спасибо!"},
             {fa: f'{nick} <b>"admin"</b>', ft: "a < b && c > d, \"x\" и 'y' <i>курсив</i>"},
             {fa: payload[1], ft: "ок"} if payload[0] == fa else {fa: nick, ft: payload[1]},
             {fa: f'{nick} onmouseover=alert(1) "q" "r"', ft: "it's Bob's <<test>>"}]
    exp = [f'<li class="{css}" data-{fa}="{_esc(c[fa])}"><b>{_esc(c[fa])}</b>: {_esc(c[ft])}</li>'
           for c in cases]
    test = (f"const cases = {json.dumps(cases, ensure_ascii=False)};\n"
            f"const expected = {json.dumps(exp, ensure_ascii=False)};\n"
            f"cases.forEach((c, i) => __assert({fn}(c) === expected[i], 'случай ' + i + ': ' + {fn}(c)));")
    checks = [Check(name="buggy_fails", runner="node", program=js_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="node", program=js_harness(fixed, test),
                    expect="pass", embeds_display_code=False)]
    field_ru = "имени автора" if payload[0] == fa else "тексте"
    stem = (f"Функция `{fn}` ({ctx}) собирает HTML, который вставляется в страницу через "
            f"`innerHTML`. На проверке безопасности выяснилось, что при значении "
            f"`{payload[1]}` в {field_ru} (поле `{payload[0]}`) в браузере выполняется "
            f"JavaScript. Укажите номер строки с ошибкой.")
    why = {"no_global_lt": "replace со строковым шаблоном заменяет только первое вхождение «<» — "
                           "остальные теги попадают в HTML как есть",
           "no_global_quot": "replace со строковым шаблоном заменяет только первую кавычку — "
                             "следующая закрывает атрибут, и можно добавить обработчик события",
           "raw_field": "поле автора не экранируется — его HTML вставляется как есть",
           "unquoted_attr": "значение атрибута без кавычек: пробел завершает значение, и "
                            "следующее слово становится новым атрибутом (onmouseover), "
                            "экранирование < > & \" этого не предотвращает"}
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: {why[subtype]}. В реальном коде надёжнее "
                               f"textContent или шаблонизатор с автоэкранированием.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="xss_escaping",
                         params={"fixed_code": fixed, "subtype": subtype})
