"""devops.bash.retry_ob3 — open_book_3step: функция retry в bash возвращает 0, когда все попытки исчерпаны.

Функция `retry N команда…` повторяет команду до N раз. Дефект: после цикла нет явного `return 1`, и функция
возвращает статус последней выполненной команды тела цикла (`sleep`, `echo` или присваивания) — то есть 0.
Шаг выкладки «retry N check_health || откат» продолжается, хотя сервис так и не поднялся.
Шаг 1 — сценарий, на котором дефект проявляется (все попытки неудачны); шаг 2 — исправление: верное —
`return 1` после цикла; почти верные — `return $?` после цикла (это статус sleep/echo), `return 1` внутри
цикла (повторов не будет), `set -e` в начале (команда в условии `if` под set -e не подпадает).
Шаг 3 — перенос: задержка с джиттером и общий лимит времени, неидемпотентная команда под retry или
поведение set -e в функциях. Проверка шагов 1–2 — исполнение скрипта в bash на сценариях с разным числом
неудачных попыток.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, ob3_steps, rubric_from
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.bash.retry_ob3"

# (контекст, команда проверки, сообщение успеха, сообщение отказа)
CTX = [("выкладка API", "check_health", "выкладка продолжена", "сервис не поднялся, откат"),
       ("миграция БД", "acquire_lock", "миграция запущена", "блокировка не получена, выход"),
       ("публикация образа", "push_image", "образ опубликован", "реестр недоступен, сборка остановлена"),
       ("загрузка артефакта", "fetch_artifact", "артефакт получен", "артефакт не скачан, шаг провален"),
       ("прогрев кеша", "warm_cache", "кеш прогрет", "прогрев не удался, алерт дежурному")]
TAILS = {"sleep": ['sleep "${RETRY_DELAY:-0}"'],
         "echo_last": ['sleep "${RETRY_DELAY:-0}"', 'echo "повтор через ${RETRY_DELAY:-0} с" >&2'],
         "backoff": ['sleep "$delay"', "delay=$((delay * 2))"]}

PRELUDE = '''{probe}() {{ n=$(cat calls 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > calls; [ "$n" -gt "$FAIL_UNTIL" ]; }}
export -f {probe}
export RETRY_DELAY=0
cat > step.sh <<'BANK_EOF'
{code}
BANK_EOF
for f in {scenarios}; do
  rm -f calls
  out=$(FAIL_UNTIL=$f bash step.sh 2>/dev/null); st=$?
  echo "f=$f st=$st calls=$(cat calls) $out"
done
'''


def _script(probe, ok, bad, n, tail, fix=None):
    lines = ["#!/usr/bin/env bash"]
    if fix == "set_e":
        lines.append("set -e")
    lines += ["", "retry() {", "  local attempts=$1", "  shift", "  local i"]
    if tail == "backoff":
        lines.append('  local delay="${RETRY_DELAY:-0}"')
    lines += ["  for ((i = 1; i <= attempts; i++)); do", '    if "$@"; then', "      return 0", "    fi",
              '    echo "попытка $i из $attempts не удалась: $*" >&2']
    if fix == "return_inside":
        lines.append("    return 1")
    lines += ["    " + t for t in TAILS[tail]]
    lines.append("  done")
    if fix == "return_1":
        lines.append("  return 1")
    if fix == "return_status":
        lines.append("  return $?")
    lines += ["}", "", f'retry {n} {probe} || {{ echo "{bad}"; exit 1; }}', f'echo "{ok}"']
    return "\n".join(lines)


def _ref(f, n, ok, bad):
    return f"f={f} st=0 calls={f + 1} {ok}" if f < n else f"f={f} st=1 calls={n} {bad}"


def _prog(probe, code, scenarios):
    return PRELUDE.format(probe=probe, code=code, scenarios=" ".join(map(str, scenarios)))


CONDITIONS = {
    "backoff_deadline": dict(
        text=("Попросили добавить в retry экспоненциальную задержку и общий лимит времени: шаг CI не должен "
              "ждать дольше 2 минут, а десятки раннеров не должны повторять запросы синхронно. Как вы это "
              "сделаете в bash и что проверите?"),
        criteria=[("backoff", "Задержка растёт (×2) с верхней границей, добавлен случайный джиттер ($RANDOM), "
                              "чтобы раннеры не били в сервис одновременно", 0.35),
                  ("deadline", "Общий лимит: запоминает время старта ($SECONDS или date +%s) и прекращает "
                               "повторы, если следующая пауза выйдет за лимит; одиночную попытку ограничивает "
                               "timeout", 0.35),
                  ("status", "Сохраняет код возврата: после исчерпания попыток/времени функция возвращает "
                             "ненулевой код; проверяет сценарии «успех с первой», «успех с последней», «все "
                             "неудачны», «зависшая попытка»", 0.3)],
        strong="""Внутри retry завожу delay с верхней границей (например, 30 с) и умножаю на 2 после каждой
            неудачи, к паузе добавляю джиттер $((RANDOM % delay)), чтобы раннеры не повторяли синхронно.
            Перед циклом запоминаю start=$SECONDS; если $SECONDS - start + delay больше лимита — выхожу с
            return 1, не начиная новую попытку. Саму попытку оборачиваю в timeout 20s, чтобы зависший
            запрос не съел весь лимит. После цикла — явный return 1. Тесты: команда-заглушка со счётчиком
            вызовов, сценарии успех с первой/последней попытки, все неудачны, зависание; RETRY_DELAY=0 в
            тестах, чтобы они шли быстро.""",
        medium="""Добавлю delay=$((delay * 2)) и sleep, а общий лимит — через timeout на весь шаг. Проверю,
            что после трёх неудач скрипт падает.""",
        weak="""Поставлю sleep 10 между попытками и увеличу число попыток до 10."""),
    "non_idempotent": dict(
        text=("Коллега предлагает обернуть в такой же retry команду `create_release` (создаёт релиз и "
              "списывает квоту) и миграцию схемы БД. Какие риски вы видите и как сделать повтор безопасным?"),
        criteria=[("idempotency", "Повтор безопасен только для идемпотентных команд: таймаут или обрыв после "
                                  "выполнения на сервере приводит к двойному релизу/списанию или частично "
                                  "применённой миграции", 0.4),
                  ("make_safe", "Предлагает ключ идемпотентности/проверку состояния перед повтором (релиз с "
                                "таким тегом уже есть?), транзакционные миграции или журнал версий схемы, "
                                "повтор только для заведомо временных ошибок", 0.35),
                  ("classify", "Различает временные ошибки (сеть, 503, блокировка) и постоянные (4xx, "
                               "конфликт схемы): постоянные не повторяет, код возврата сохраняет", 0.25)],
        strong="""retry годится только для идемпотентных команд. Если create_release выполнился на сервере, а
            ответ потерялся по таймауту, повтор создаст второй релиз и спишет квоту дважды; миграция может
            упасть посередине и при повторе применить половину изменений ещё раз. Делаю повтор безопасным:
            передаю ключ идемпотентности или перед повтором проверяю состояние (релиз с этим тегом уже есть
            — считаю успехом); миграции — в транзакции, с таблицей версий, чтобы применённая версия не
            выполнялась снова. Повторяю только временные ошибки (сеть, 503, занятая блокировка) по коду
            возврата, а 4xx и конфликт схемы сразу возвращаю наверх ненулевым кодом.""",
        medium="""Повтор может создать релиз дважды, поэтому перед повтором нужно проверить, что релиза ещё нет.
            Миграции лучше не повторять.""",
        weak="""Всё нормально, retry как раз помогает при сбоях сети."""),
    "set_e_functions": dict(
        text=("В команде договорились «просто писать set -e в начале каждого скрипта», чтобы такие ошибки "
              "не повторялись. Почему set -e не спас бы этот скрипт и какие правила вы бы предложили вместо?"),
        criteria=[("set_e_limits", "set -e не срабатывает для команд в условиях if/while, в левой части && и "
                                   "||, внутри функции, вызванной из такого контекста; статус функции — статус "
                                   "последней команды", 0.4),
                  ("rules", "Явные return/exit с кодом в функциях, set -euo pipefail как базовая страховка, "
                            "проверка статуса там, где он важен; shellcheck в CI", 0.35),
                  ("tests", "Тесты на неудачные сценарии: заглушки со счётчиком, проверка кода возврата шага "
                            "(bats или простой скрипт в CI)", 0.25)],
        strong="""Здесь retry вызывается в левой части ||, а команда внутри — в условии if: в обоих контекстах
            set -e отключён, и функция вернула статус последней команды цикла — 0. set -e не исправляет
            логику кода возврата, он только иногда останавливает скрипт. Правила: в функциях всегда явный
            return с кодом после цикла/ветки; set -euo pipefail как страховка, а не как обработка ошибок;
            shellcheck в CI; для важных шагов — тесты неудачных сценариев с заглушками команд (bats), где
            проверяется код возврата и то, что шаг не продолжился.""",
        medium="""set -e не работает внутри if, поэтому надо явно писать return 1 в конце функции и проверять
            скрипты shellcheck.""",
        weak="""Нужно писать set -e везде, тогда скрипт будет падать на любой ошибке."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, probe, ok, bad = rng.choice(CTX)
    n = rng.randint(3, 5)
    tail = rng.choice(sorted(TAILS))
    code = _script(probe, ok, bad, n, tail)
    # шаг 1: четыре сценария; дефект только при f ≥ n
    f_bad = rng.choice([n, n + 1, n + 2])
    scen = [(f_bad, f"`{probe}` неудачна во всех {n} попытках"),
            (0, f"`{probe}` успешна с первой попытки"),
            (1, f"`{probe}` неудачна один раз, затем успешна"),
            (n - 1, f"`{probe}` успешна только на последней, {n}-й попытке")]
    if f_bad > n:
        scen[0] = (f_bad, f"`{probe}` неудачна во всех попытках (сервис лежит дольше, чем идут повторы)")
    opts1, key1 = make_options(rng, (scen[0][1], None), [(t, None) for _, t in scen[1:]], step=1)
    by_text = {t: f for f, t in scen}
    checks = []
    for o in opts1:
        f = by_text[o.text]
        checks.append(Check(name=f"step1:{o.id}", runner="bash", program=_prog(probe, code, [f]),
                            expect="stdout_differs" if o.id == key1 else "stdout_equals",
                            expected_stdout=_ref(f, n, ok, bad)))
    fixes = {"return_1": "После цикла добавить `return 1`:",
             "return_status": "После цикла добавить `return $?`:",
             "return_inside": "В конце тела цикла, после сообщения о неудаче, добавить `return 1`:",
             "set_e": "Добавить `set -e` в начало скрипта:"}
    opts2, key2 = make_options(rng, (fixes["return_1"], _script(probe, ok, bad, n, tail, "return_1")),
                               [(fixes[k], _script(probe, ok, bad, n, tail, k))
                                for k in ("return_status", "return_inside", "set_e")], step=2)
    scen2 = [0, 1, n - 1, n, n + 2]
    ref2 = "\n".join(_ref(f, n, ok, bad) for f in scen2)
    for o in opts2:
        checks.append(Check(name=f"step2:{o.id}", runner="bash", program=_prog(probe, o.code, scen2),
                            expect="stdout_equals" if o.id == key2 else "stdout_differs",
                            expected_stdout=ref2, embeds_display_code=False))
    cond_name = rng.choice(sorted(CONDITIONS))
    cond = CONDITIONS[cond_name]
    rubric = rubric_from({**cond, "notes": "Оценивается шаг 3; шаги 1–2 проверяются автоматически."})
    last = {"sleep": "sleep", "echo_last": "echo", "backoff": "delay=$((delay * 2))"}[tail]
    stem = (f"Шаг CI «{ctx}» использует функцию retry из общего скрипта: команда `{probe}` повторяется до {n} раз, "
            f"при неудаче всех попыток должен выполниться откат («{bad}»). На разборе инцидента выяснилось, что "
            f"однажды шаг напечатал «{ok}», хотя `{probe}` так и не прошла.")
    steps = ob3_steps(
        "Шаг 1. Воспроизведите дефект: в каком сценарии скрипт поведёт себя неверно?",
        "Шаг 2. Выберите исправление, после которого скрипт верен во всех сценариях.",
        "Шаг 3. " + cond["text"] + " Ответьте развёрнуто (5–10 предложений).")
    expl = (f"Без явного return после цикла функция возвращает статус последней команды тела цикла (`{last}`) — "
            "0, поэтому откат не выполняется. Верно — `return 1` после цикла. `return $?` возвращает тот же статус "
            "последней команды; `return 1` внутри цикла убирает повторы; set -e не действует на команды в условии "
            f"if и в левой части ||. Шаг 3 — «{cond_name}».")
    ak = AnswerKey(kind="steps", value={"1": key1, "2": key2, "3": "rubric"}, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts1 + opts2, answer_key=ak,
                         rubric=rubric, context=ctx, verification="execution", checks=checks, steps=steps,
                         defect_type="missing_return_status",
                         params={"attempts": n, "tail": tail, "condition": cond_name})
