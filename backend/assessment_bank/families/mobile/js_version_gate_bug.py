"""mobile.js.version_gate_bug — find_bug: обязательное обновление по минимальной версии сравнивает строки.

Приложение при запуске получает с сервера минимальную поддерживаемую версию и, если установленная версия
меньше, показывает экран «Обновите приложение». Сравнение частей версии идёт как строк: «10» < «9»
лексикографически, поэтому 2.10.0 считается старее 2.9.5 (или наоборот новее не требуется). Один подтип
дефекта; варьируются имена, версии, служебные функции и их порядок. Ключ проверяется исполнением в Node на
наборе пар версий с двузначными частями.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "mobile.js.version_gate_bug"

CTX = ["банковское приложение", "приложение доставки", "мессенджер", "приложение такси", "онлайн-кинотеатр",
       "приложение магазина"]
DECOYS = [["function formatVersion(v) {", "  return 'v' + v;", "}"],
          ["const isBeta = (v) => v.includes('-beta');"],
          ["function platformName(os) {", "  return os === 'ios' ? 'iOS' : 'Android';", "}"]]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    cmp_name = rng.choice(["compareVersions", "cmpVersion", "versionCompare"])
    gate = rng.choice(["mustUpdate", "needsForceUpdate", "isOutdated"])
    good = "    const x = Number(pa[i] || 0), y = Number(pb[i] || 0);"
    bad = "    const x = pa[i] || '0', y = pb[i] || '0';"

    def body(line):
        return [f"function {cmp_name}(a, b) {{", "  const pa = a.split('.');", "  const pb = b.split('.');",
                "  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {", line,
                "    if (x < y) return -1;", "    if (x > y) return 1;", "  }", "  return 0;", "}", "",
                f"function {gate}(installed, minSupported) {{",
                f"  return {cmp_name}(installed, minSupported) < 0;", "}"]
    decoy = rng.choice(DECOYS)
    first = rng.random() < 0.5

    def assemble(line):
        b = body(line)
        return "\n".join((decoy + [""] + b) if first else (b + [""] + decoy))
    buggy, fixed = assemble(bad), assemble(good)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    major = rng.randint(1, 7)
    minor = rng.randint(2, 9)
    inst = f"{major}.{minor + rng.randint(1, 3) + 10}.0"
    minv = f"{major}.{minor}.{rng.randint(1, 9)}"
    cases = [(inst, minv, False), (minv, inst, True), (f"{major}.{minor}.0", minv, True),
             (f"{major + 1}.0.0", minv, False), (minv, minv, False), (f"{major}.{minor}", f"{major}.{minor}.0", False)]
    test = "\n".join(f"__assert({gate}({a!r}, {b!r}) === {str(r).lower()}, '{a} vs {b}');" for a, b, r in cases)
    checks = [Check(name="buggy_fails", runner="node", program=js_harness(buggy, test), expect="fail"),
              Check(name="fixed_passes", runner="node", program=js_harness(fixed, test), expect="pass",
                    embeds_display_code=False)]
    stem = (f"Мобильное приложение ({ctx}) при запуске получает с сервера минимальную поддерживаемую версию и "
            f"показывает экран «Обновите приложение», если `{gate}(установленная, минимальная)` возвращает true. "
            f"Жалоба: после выпуска версии {inst} пользователи с ней видят требование обновиться, хотя минимальная "
            f"версия — {minv}. Укажите номер строки с ошибкой.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: части версии сравниваются как строки, а строки — "
                                f"посимвольно: «{inst.split('.')[1]}» < «{minv.split('.')[1]}», потому что «{inst.split('.')[1][0]}» < "
                                f"«{minv.split('.')[1][0]}». Нужно сравнивать числа: `Number(pa[i] || 0)`."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="string_compare_version",
                         params={"fixed_code": fixed, "installed": inst, "min": minv})
