"""devops.bash.quoting_bug — find_bug: переменная с путём без кавычек — разбиение на слова (пробелы в именах).

Скрипт обрабатывает файлы каталога, имена каталогов и файлов содержат пробелы. Дефект один: в одной строке
раскрытие `$переменной` без кавычек там, где bash делит его на слова (аргумент команды, цель
перенаправления, шаблон в for). Ловушки — строки, где кавычки не нужны и ошибкой не являются: присваивание
`target=$dest/$name.txt` и проверка внутри `[[ ... ]]`. Проверка — исполнение показанного скрипта в bash на
каталоге с пробелами в именах: дефектный скрипт даёт неверный результат или ошибку, исправленный проходит.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.bash.quoting_bug"

CTX = [("выгрузки банка", "csv", "входящие выписки", "готовые выписки", ["выписка март", "выписка апрель",
                                                                          "выписка май"]),
       ("логи кассы", "log", "журналы касс", "очищенные журналы", ["касса 1", "касса 2", "касса 3"]),
       ("отчёты склада", "csv", "отчёты склада", "отчёты для 1С", ["остатки west", "остатки east",
                                                                    "приход 10"]),
       ("тексты писем", "txt", "черновики писем", "письма к отправке", ["письмо клиенту", "письмо партнёру",
                                                                       "письмо банку"]),
       ("заявки поддержки", "txt", "новые заявки", "разобранные заявки", ["заявка 101", "заявка 102", "заявка 7"]),
       ("прайс-листы", "csv", "прайсы поставщиков", "прайсы для сайта", ["прайс альфа", "прайс бета", "прайс 2026"]),
       ("журналы датчиков", "log", "сырые журналы", "журналы после очистки", ["датчик север", "датчик юг",
                                                                            "датчик 12"])]
ACTIONS = [("sort", 'sort {inp} > {out}'), ("tr", "tr -d '\\r' < {inp} > {out}"),
           ("cp", "cp {inp} {out}"), ("uniq", "sort -u {inp} > {out}")]
SPOTS = ["mkdir", "for", "inp", "out"]
VARS = [("src", "dest", "f"), ("in_dir", "out_dir", "file"), ("from", "to", "path"), ("input", "output", "item")]

HARNESS = '''cat > job.sh <<'BANK_EOF'
{code}
BANK_EOF
mkdir -p "{src}"
{make_files}
out=$(bash job.sh "{src}" "{dest}" 2>/dev/null); st=$?
ok=1
[ "$st" -eq 0 ] || ok=0
[ "$out" = "обработано: {n}" ] || ok=0
{check_files}
if [ "$ok" = 1 ]; then echo "RESULT: PASS"; else echo "RESULT: FAIL st=$st"; fi
'''


def _script(ext, action, bug, extras):
    S, D, F = extras["names"]
    q = lambda name, spot: (f"${name}" if spot == bug else f'"${name}"')  # noqa: E731
    lines = ["#!/usr/bin/env bash", "set -euo pipefail"]
    if extras["nullglob"]:
        lines.append("shopt -s nullglob")
    lines += [f'{S}="$1"', f'{D}="$2"', f"mkdir -p {q(D, 'mkdir')}"]
    if extras["count"]:
        lines.append("count=0")
    glob = f"${S}/*.{ext}" if bug == "for" else f'"${S}"/*.{ext}'
    lines.append(f"for {F} in {glob}; do")
    lines.append(f"  [[ -f ${F} ]] || continue")
    lines.append(f'  name=$(basename "${F}" .{ext})')
    lines.append(f"  target=${D}/$name.{extras['out_ext']}")
    if extras["echo"]:
        lines.append(f'  echo "→ $name" >&2')
    lines.append("  " + action.format(inp=q(F, "inp"), out=q("target", "out")))
    if extras["count"]:
        lines.append("  count=$((count + 1))")
    lines.append("done")
    if extras["count"]:
        lines.append('echo "обработано: $count"')
    else:
        lines.append(f'echo "обработано: $(ls "${D}" | wc -l)"')
    return "\n".join(lines)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, ext, src, dest, names = rng.choice(CTX)
    act_name, action = rng.choice(ACTIONS)
    bug = rng.choice(SPOTS)
    if act_name == "cp" and bug == "out":
        bug = "inp"
    extras = {"nullglob": rng.random() < 0.5, "count": rng.random() < 0.6,
              "out_ext": rng.choice(["txt", "out", ext]), "echo": rng.random() < 0.4,
              "names": rng.choice(VARS)}
    files = rng.sample(names, rng.randint(2, 3))
    rows = {f: sorted({f"{rng.choice(['b', 'a', 'c', 'd'])}{rng.randint(1, 9)}" for _ in range(4)}, reverse=True)
            for f in files}
    code = _script(ext, action, bug, extras)
    fixed = _script(ext, action, None, extras)
    ch = changed_lines(code, fixed)
    assert len(ch) == 1, ch
    key = next(iter(ch))
    make = "\n".join(f"printf '%s\\n' {' '.join(rows[f])} > \"{src}/{f}.{ext}\"" for f in files)
    chk = []
    for f in files:
        path = f'"{dest}/{f}.{extras["out_ext"]}"'
        want = sorted(rows[f]) if act_name in ("sort", "uniq") else rows[f]
        exp = "\\n".join(want)
        chk.append(f"[ \"$(cat {path} 2>/dev/null)\" = \"$(printf '{exp}')\" ] || ok=0")
    harness = HARNESS.replace("{src}", src).replace("{dest}", dest).replace("{n}", str(len(files))).replace(
        "{make_files}", make).replace("{check_files}", "\n".join(chk))
    checks = [Check(name="buggy_fails", runner="bash", program=harness.replace("{code}", code), expect="fail"),
              Check(name="fixed_passes", runner="bash", program=harness.replace("{code}", fixed), expect="pass",
                    embeds_display_code=False)]
    what = {"mkdir": "аргумент mkdir", "for": "шаблон в for", "inp": "входной файл команды",
            "out": "цель перенаправления/копирования"}[bug]
    S, D, F = extras["names"]
    expl = (f"Строка {key}: без кавычек {what} делится на слова по пробелам, и путь «{src}/…» или «{dest}» "
            f"превращается в несколько аргументов. Присваивание `target=${D}/…` и `[[ -f ${F} ]]` на слова не "
            "делятся — там кавычки не обязательны.")
    stem = (f"Скрипт обработки ({ctx}) запускают как `bash job.sh \"{src}\" \"{dest}\"`; в каталоге лежат "
            f"файлы с пробелами в именах, например «{files[0]}.{ext}». Скрипт работает на каталогах без пробелов, "
            "но здесь падает или обрабатывает не всё. Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    ak = AnswerKey(kind="line", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="unquoted_expansion",
                         params={"fixed_code": fixed, "spot": bug, "action": act_name})
