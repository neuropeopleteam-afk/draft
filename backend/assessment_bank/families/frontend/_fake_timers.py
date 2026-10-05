"""Поддельные таймеры для JS-обвязок семейств frontend (детерминированное виртуальное время)."""

FAKE_TIMERS = """const __clock = { now: 0, timers: [], seq: 0 };
function setTimeout(fn, ms, ...args) {
  const id = ++__clock.seq;
  __clock.timers.push({ id, at: __clock.now + ms, fn, args });
  return id;
}
function clearTimeout(id) {
  __clock.timers = __clock.timers.filter((t) => t.id !== id);
}
async function advanceTo(t) {
  for (;;) {
    __clock.timers.sort((a, b) => a.at - b.at || a.id - b.id);
    const next = __clock.timers[0];
    if (!next || next.at > t) break;
    __clock.timers.shift();
    __clock.now = next.at;
    next.fn(...next.args);
    for (let k = 0; k < 10; k++) await null;
  }
  __clock.now = t;
}"""
