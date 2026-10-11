"""mobile.js.background_timer_bug — find_bug: таймер считает тики, а в фоне таймеры приостановлены.

В свёрнутом приложении (iOS приостанавливает процесс, Android ограничивает фоновые таймеры) колбэки
setInterval не выполняются, пропущенные тики не догоняются. Таймер тренировки/парковки/ожидания увеличивает
счётчик на 1 в каждом тике и после возврата из фона отстаёт на время, проведённое в фоне. Верно — считать
прошедшее время от момента старта по часам. Один подтип дефекта; варьируются контекст, имена, служебные
функции и их порядок. Ключ проверяется исполнением: модель таймеров приложения в Node (передний план — тики
идут, фон — часы идут, тики нет, после возврата следующий тик через интервал).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, js_harness, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "mobile.js.background_timer_bug"

CTX = [("тренировка", "startWorkout", "stopWorkout"), ("парковка по времени", "startParking", "stopParking"),
       ("платное ожидание такси", "startWaiting", "stopWaiting"), ("приготовление по рецепту", "startCooking",
                                                                    "stopCooking"),
       ("медитация", "startSession", "stopSession"), ("аренда самоката", "startRide", "stopRide")]

PRELUDE = """const __clock = { t: 0, intervals: [] };
function now() { return __clock.t; }
function setInterval(fn, ms) { __clock.intervals.push({ fn, ms, next: __clock.t + ms, on: true }); return __clock.intervals.length; }
function clearInterval(id) { if (__clock.intervals[id - 1]) __clock.intervals[id - 1].on = false; }
function foreground(until) {
  for (;;) {
    const due = __clock.intervals.filter((x) => x.on).sort((a, b) => a.next - b.next)[0];
    if (!due || due.next > until) break;
    __clock.t = due.next; due.next += due.ms; due.fn();
  }
  __clock.t = until;
}
function background(until) {
  __clock.t = until;
  for (const x of __clock.intervals) x.next = until + x.ms;
}
const shown = [];
function vibrate() {}"""

TEST = """const state = {};
START(state, (text) => shown.push(text));
foreground(F1);
background(B1);
foreground(F2);
STOP(state);
__assert(shown[shown.length - 1] === EXPECT, 'на экране ' + shown[shown.length - 1] + ', ожидалось ' + EXPECT);"""


def _fmt(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, start, stop = rng.choice(CTX)
    st = rng.choice(["state", "timer", "session"])
    fmt_name = rng.choice(["formatTime", "toClock", "mmss"])
    good = f"    {st}.elapsed = Math.floor((now() - {st}.startedAt) / 1000);"
    bad = f"    {st}.elapsed += 1;"
    extra = rng.random() < 0.5

    def body(line):
        out = [f"function {start}({st}, render) {{", f"  {st}.startedAt = now();", f"  {st}.elapsed = 0;",
               f"  {st}.handle = setInterval(() => {{", line]
        if extra:
            out.append(f"    if ({st}.elapsed > 0 && {st}.elapsed % 60 === 0) vibrate();")
        out += [f"    render({fmt_name}({st}.elapsed));", "  }, 1000);", "}", "",
                f"function {stop}({st}) {{", f"  clearInterval({st}.handle);", f"  {st}.handle = null;", "}"]
        return out
    helper = [f"function {fmt_name}(sec) {{", "  const m = Math.floor(sec / 60);", "  const s = sec % 60;",
              "  return `${m}:${String(s).padStart(2, '0')}`;", "}"]
    first = rng.random() < 0.5

    def assemble(line):
        b = body(line)
        return "\n".join((helper + [""] + b) if first else (b + [""] + helper))
    buggy, fixed = assemble(bad), assemble(good)
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))
    f1 = rng.randint(8, 40) * 1000
    b1 = f1 + rng.randint(2, 9) * 60_000 + rng.randint(0, 59) * 1000
    f2 = b1 + rng.randint(2, 6) * 1000
    expect = _fmt(f2 // 1000)
    test = (TEST.replace("START", start).replace("STOP", stop).replace("F1", str(f1)).replace("B1", str(b1))
            .replace("F2", str(f2)).replace("EXPECT", repr(expect)))
    checks = [Check(name="buggy_fails", runner="node", program=js_harness(buggy, test, PRELUDE), expect="fail"),
              Check(name="fixed_passes", runner="node", program=js_harness(fixed, test, PRELUDE), expect="pass",
                    embeds_display_code=False)]
    away = (b1 - f1) // 1000
    stem = (f"Экран «{ctx}» мобильного приложения показывает, сколько прошло времени, и обновляет его раз в "
            f"секунду; `now()` — текущее время в миллисекундах (обёртка над `Date.now`). Пользователь запустил "
            f"отсчёт, через {f1 // 1000} с свернул приложение и вернулся ещё через {away // 60} мин "
            f"{away % 60} с. Жалоба: после возврата время на экране меньше реально прошедшего, а сумма к оплате "
            f"и статистика считаются по этому значению. Укажите номер строки с ошибкой.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: время считается числом тиков. Пока приложение в фоне, ОС "
                                f"приостанавливает JS-таймеры (iOS — процесс целиком, Android — фоновые "
                                f"ограничения), пропущенные тики не догоняются, и счётчик отстаёт на время в "
                                f"фоне. Прошедшее время нужно вычислять от момента старта: "
                                f"`Math.floor((now() - startedAt) / 1000)`."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="tick_counting",
                         params={"fixed_code": fixed, "f1": f1, "b1": b1, "f2": f2})
