"""qa.bash.smoke_masked_failure — find_bug: смоук-скрипт CI теряет код ошибки и даёт ложный «зелёный».

Подтипы: `!` перед конвейером с tee (статус берётся у tee), `local x=$(cmd) || ...` (статус
команды `local`), неэкранированная пустая переменная в `[ $code != ... ]` (ошибка `[` трактуется
как «условие ложно»). Ключ проверяется исполнением в bash-песочнице: на сломанном стенде
скрипт с дефектом завершается кодом 0, исправленный — ненулевым; на исправном стенде оба
скрипта завершаются кодом 0 (нет ложной тревоги).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.bash.smoke_masked_failure"

STANDS = [
    ("https://stage.shop.example", "интернет-магазин",
     [("health", "/health", 200), ("catalog", "/api/v1/products", 200), ("cart", "/api/v1/cart", 401),
      ("search", "/api/v1/search?q=test", 200)]),
    ("https://test.bank.example", "интернет-банк",
     [("health", "/healthz", 200), ("rates", "/api/rates", 200), ("accounts", "/api/accounts", 401),
      ("cards", "/api/cards", 401)]),
    ("https://preprod.video.example", "видеосервис",
     [("health", "/ping", 200), ("feed", "/api/feed", 200), ("upload", "/api/upload", 401),
      ("player", "/player/config", 200)]),
    ("https://stage.lms.example", "онлайн-школа",
     [("health", "/status", 200), ("courses", "/api/courses", 200), ("grades", "/api/grades", 403),
      ("schedule", "/api/schedule", 200)]),
]

API_STEPS = {
    "pipe": (["if ! ./run_api_tests.sh | tee api_tests.log; then", "  echo \"FAIL api-tests\"",
              "  failed=1", "fi"],
             "if ! (set -o pipefail; ./run_api_tests.sh | tee api_tests.log); then"),
    "func": (["run_api_suite() {",
              "  local report=$(./run_api_tests.sh) || { echo \"FAIL api-tests\"; failed=1; }",
              "  echo \"$report\" > api_tests.log", "}", "", "run_api_suite"],
             "  local report; report=$(./run_api_tests.sh) || { echo \"FAIL api-tests\"; failed=1; }"),
}
CHECK_BAD = "  if [ $code != \"$expected\" ]; then"
CHECK_GOOD = "  if [ \"$code\" != \"$expected\" ]; then"


def _script(url, ctx, checks, quoted, api_kind, api_fixed, log):
    lines = ["#!/usr/bin/env bash", f"# smoke.sh — смоук-проверка стенда ({ctx}) после деплоя",
             f"BASE_URL=\"{url}\"", "failed=0", "", "check() {",
             "  local name=\"$1\" path=\"$2\" expected=\"$3\"", "  local code",
             "  code=$(./http_get.sh \"$BASE_URL$path\")", CHECK_GOOD if quoted else CHECK_BAD,
             "    echo \"FAIL $name: получен '$code', ожидался $expected\"",
             "    failed=1", "  fi", "}", ""]
    lines += [f"check {n} '{p}' {e}" for n, p, e in checks] + [""]
    step, fixed_line = API_STEPS[api_kind]
    step = [x.replace("api_tests.log", log) for x in step]
    fixed_line = fixed_line.replace("api_tests.log", log)
    if api_fixed:
        idx = 0 if api_kind == "pipe" else 1
        step[idx] = fixed_line
    lines += step + ["exit $failed"]
    return "\n".join(lines)


def _http_stub(checks, broken_path):
    out = ["case \"$1\" in"]
    for _n, p, e in checks:
        pat = p.replace("?", "\\?")
        if p == broken_path:
            out.append(f"  *{pat}) echo 'curl: (7) Failed to connect' >&2; exit 7 ;;")
        else:
            out.append(f"  *{pat}) echo {e} ;;")
    out += ["  *) echo 404 ;;", "esac"]
    return "\n".join(out) + "\n"


def _program(script, expect_nonzero):
    cond = "-ne" if expect_nonzero else "-eq"
    return ("cat > smoke.sh <<'BANK_EOF'\n" + script + "\nBANK_EOF\n"
            "chmod +x smoke.sh http_get.sh run_api_tests.sh\n"
            "bash ./smoke.sh > smoke.out 2>&1; rc=$?\n"
            f"if [ \"$rc\" {cond} 0 ]; then echo 'RESULT: PASS'; else echo 'RESULT: FAIL'; fi\n")


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    url, ctx, endpoints = rng.choice(STANDS)
    env = rng.choice(["stage", "test", "preprod", "rc"])
    url = "https://" + env + "." + url.split("//", 1)[1].split(".", 1)[1]
    ver = rng.choice(["v1", "v2", "v3"])
    endpoints = [(n, p.replace("/api/v1/", f"/api/{ver}/"), e) for n, p, e in endpoints]
    checks = [endpoints[0]] + rng.sample(endpoints[1:], 2)
    log = rng.choice(["api_tests.log", "api-report.log", "api.log"])
    sub = rng.choice(["pipe_status", "local_masks", "unquoted_empty"])
    if sub == "unquoted_empty":
        api_kind = rng.choice(["pipe", "func"])
        buggy = _script(url, ctx, checks, False, api_kind, True, log)
        fixed = _script(url, ctx, checks, True, api_kind, True, log)
        bad_line = CHECK_BAD
        broken = rng.choice(checks[1:])
        files_broken = {"http_get.sh": _http_stub(checks, broken[1]),
                        "run_api_tests.sh": "echo '48 passed'\nexit 0\n"}
        symptom = (f"сервис по адресу `{broken[1]}` не отвечал: `http_get.sh` ничего не вывел и "
                   f"завершился с кодом 7")
    else:
        api_kind = "pipe" if sub == "pipe_status" else "func"
        buggy = _script(url, ctx, checks, True, api_kind, False, log)
        fixed = _script(url, ctx, checks, True, api_kind, True, log)
        bad_line = API_STEPS[api_kind][0][0 if api_kind == "pipe" else 1].replace("api_tests.log", log)
        n_fail = rng.randint(1, 9)
        files_broken = {"http_get.sh": _http_stub(checks, None),
                        "run_api_tests.sh": f"echo '{rng.randint(30, 90)} passed, {n_fail} failed'\nexit 1\n"}
        symptom = (f"API-тесты упали: `run_api_tests.sh` вывел «{n_fail} failed» и завершился с "
                   f"кодом 1")
    key_line = buggy.splitlines().index(bad_line) + 1
    assert changed_lines(buggy, fixed) == {key_line}
    files_ok = {"http_get.sh": _http_stub(checks, None), "run_api_tests.sh": "echo '48 passed'\nexit 0\n"}
    checks_ = [
        Check(name="buggy_misses_broken_stand", runner="bash", expect="fail",
              program=_program(buggy, True), files=files_broken),
        Check(name="buggy_green_on_healthy_stand", runner="bash", expect="pass",
              program=_program(buggy, False), files=files_ok),
        Check(name="fixed_detects_broken_stand", runner="bash", expect="pass", embeds_display_code=False,
              program=_program(fixed, True), files=files_broken),
        Check(name="fixed_green_on_healthy_stand", runner="bash", expect="pass", embeds_display_code=False,
              program=_program(fixed, False), files=files_ok),
    ]
    stem = (f"Скрипт `smoke.sh` запускается в CI после деплоя на стенд ({ctx}); ненулевой код "
            f"завершения останавливает выкатку. `http_get.sh URL` печатает HTTP-код ответа, "
            f"`run_api_tests.sh` запускает API-тесты (код 0 — все прошли). Сегодня {symptom}, но "
            f"`smoke.sh` завершился с кодом 0, и сборка ушла дальше. Укажите номер строки с дефектом.")
    why = {"pipe_status": "`!` и `if` смотрят на код завершения последней команды конвейера — "
                          "`tee`, а он равен 0; нужен pipefail (или PIPESTATUS[0])",
           "local_masks": "код завершения строки `local x=$(...)` — это код встроенной команды "
                          "`local` (0), а не подстановки; объявление и присваивание нужно разделить",
           "unquoted_empty": "при пустом `$code` выражение превращается в `[ != \"200\" ]`, `[` "
                             "завершается с ошибкой (код 2), и `if` считает условие ложным; "
                             "переменную нужно взять в кавычки"}
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=f"Строка {key_line}: {why[sub]}. Исправленная строка: `{fixed.splitlines()[key_line - 1].strip()}`.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks_, defect_type="masked_failure",
                         params={"fixed_code": fixed, "subtype": sub, "api_step": api_kind})
