"""Минимальные совместимые обвязки тестовых фреймворков для песочницы банка (направление qa).

В песочнице Python запускается в режиме ``-I -S`` (без site-packages), поэтому настоящий
pytest недоступен. ``PYTEST_SHIM`` реализует ровно то подмножество, которое используют
семейства qa: ``pytest.fixture`` (scope function/module/session, yield-фикстуры, autouse),
``pytest.mark.parametrize`` (в том числе несколько декораторов подряд), ``pytest.mark.skip``,
``pytest.raises``, ``pytest.approx`` для чисел (rel=1e-6, abs=1e-12) и встроенную фикстуру
``monkeypatch`` (setattr/setitem/delitem).
Порядок подготовки фикстур повторяет алгоритм pytest 8 (getfixtureclosure → сортировка по
области видимости → рекурсивная подготовка зависимостей), завершение — в обратном порядке
внутри области. Совпадение с настоящим pytest 8.3.3 проверено при разработке на всех
вариантах семейств, где обвязка определяет ключ (см. отчёт report_bank_qa.md).

``JEST_SHIM`` — подмножество Jest/Vitest для Node: ``test``/``it``/``describe``, ``expect`` с
основными матчерами и ``.not``, ``jest.fn`` (mockReturnValue, mockResolvedValue, mock.calls).
Проверка, сработавшая после завершения всех тестов, не влияет на результат (как
«потерянное» утверждение в настоящем Jest) и не порождает необработанный отказ промиса.
"""
from __future__ import annotations

PYTEST_SHIM = r'''
import sys as _bk_sys, types as _bk_types, inspect as _bk_inspect, itertools as _bk_it


class _BkFixtureDef:
    def __init__(self, func, scope, autouse, name):
        self.func, self.scope, self.autouse, self.name = func, scope, autouse, name
        self.argnames = list(_bk_inspect.signature(func).parameters)


def _bk_fixture(func=None, *, scope="function", autouse=False, name=None, params=None):
    def deco(f):
        f._bk_fixture = _BkFixtureDef(f, scope, autouse, name or f.__name__)
        return f
    if callable(func):
        return deco(func)
    return deco


class _BkMark:
    def parametrize(self, argnames, argvalues, ids=None):
        names = ([a.strip() for a in argnames.split(",") if a.strip()]
                 if isinstance(argnames, str) else list(argnames))
        values = list(argvalues)

        def deco(f):
            f.__dict__.setdefault("_bk_params", []).append((names, values))
            return f
        return deco

    def skip(self, *a, **k):
        if a and callable(a[0]):
            a[0]._bk_skip = True
            return a[0]

        def deco(f):
            f._bk_skip = True
            return f
        return deco

    def __getattr__(self, name):
        def mark(*a, **k):
            if a and callable(a[0]) and len(a) == 1 and not k:
                return a[0]
            return lambda f: f
        return mark


class _BkFailed(AssertionError):
    pass


class _BkRaises:
    def __init__(self, exc, match=None):
        self.exc, self.match, self.value = exc, match, None

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        import re as _re
        if et is None:
            raise _BkFailed("DID NOT RAISE " + getattr(self.exc, "__name__", str(self.exc)))
        if not issubclass(et, self.exc):
            return False
        if self.match is not None and not _re.search(self.match, str(ev)):
            raise _BkFailed("Regex pattern did not match")
        self.value = ev
        return True


def _bk_raises(exc, *, match=None):
    return _BkRaises(exc, match)


class _BkMonkeyPatch:
    _NOTSET = object()

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value, raising=True):
        old = getattr(target, name, self._NOTSET)
        if old is self._NOTSET and raising:
            raise AttributeError(name)
        self._undo.append(("attr", target, name, old))
        setattr(target, name, value)

    def setitem(self, mapping, key, value):
        self._undo.append(("item", mapping, key, mapping.get(key, self._NOTSET)))
        mapping[key] = value

    def delitem(self, mapping, key, raising=True):
        if key not in mapping:
            if raising:
                raise KeyError(key)
            return
        self._undo.append(("item", mapping, key, mapping[key]))
        del mapping[key]

    def undo(self):
        for kind, target, name, old in reversed(self._undo):
            if kind == "attr":
                if old is self._NOTSET:
                    delattr(target, name)
                else:
                    setattr(target, name, old)
            else:
                if old is self._NOTSET:
                    target.pop(name, None)
                else:
                    target[name] = old
        self._undo.clear()


_bk_abs = abs


class _BkApprox:
    """pytest.approx для чисел: допуск rel=1e-6, abs=1e-12 (умолчания pytest), как у ApproxScalar."""

    def __init__(self, expected, rel=None, abs=None):
        self.expected, self.rel, self.abs_ = expected, rel, abs

    def __eq__(self, actual):
        rel = 1e-6 if self.rel is None else self.rel
        tol = max(rel * _bk_abs(self.expected), 1e-12 if self.abs_ is None else self.abs_)
        return _bk_abs(actual - self.expected) <= tol

    def __ne__(self, actual):
        return not self.__eq__(actual)

    def __repr__(self):
        return f"{self.expected} ± tol"


_bk_pytest = _bk_types.ModuleType("pytest")
_bk_pytest.fixture = _bk_fixture
_bk_pytest.mark = _BkMark()
_bk_pytest.raises = _bk_raises
_bk_pytest.approx = _BkApprox
_bk_pytest.fail = lambda msg="": (_ for _ in ()).throw(_BkFailed(msg))
_bk_sys.modules["pytest"] = _bk_pytest

_BK_SCOPES = {"session": 3, "package": 3, "module": 2, "class": 2, "function": 0}


def _bk_collect(ns):
    fixtures, tests = {}, []
    for key, obj in list(ns.items()):
        fd = getattr(obj, "_bk_fixture", None)
        if isinstance(fd, _BkFixtureDef):
            fixtures[fd.name] = fd
        elif key.startswith("test") and _bk_inspect.isfunction(obj):
            tests.append((key, obj))
    return fixtures, tests


def _bk_items(tests):
    items = []
    for name, fn in tests:
        groups = getattr(fn, "_bk_params", [])
        if not groups:
            items.append((name, fn, {}))
            continue
        expanded = []
        for names, values in groups:
            opts = []
            for v in values:
                opts.append(dict(zip(names, v)) if len(names) > 1 else {names[0]: v})
            expanded.append(opts)
        for i, combo in enumerate(_bk_it.product(*expanded)):
            merged = {}
            for d in combo:
                merged.update(d)
            items.append((f"{name}[{i}]", fn, merged))
    return items


def _bk_finish(fin):
    gen = fin
    try:
        next(gen)
    except StopIteration:
        return
    raise RuntimeError("fixture yielded twice")


def _bk_argnames(fn):
    """Имена аргументов теста без тех, что подставляют декораторы mock.patch (как в pytest)."""
    names = list(_bk_inspect.signature(fn).parameters)
    patchings = getattr(fn, "patchings", None)
    if patchings:
        import unittest.mock as _bk_mock
        n = len([p for p in patchings if not p.attribute_name and p.new is _bk_mock.DEFAULT])
        names = names[n:]
    return names


def _bk_run(ns, order=None):
    """Запустить тесты пространства имён ns; вернуть список (id, outcome)."""
    fixtures, tests = _bk_collect(ns)
    items = _bk_items(tests)
    if order is not None:
        by_name = {it[0]: it for it in items}
        items = [by_name[n] for n in order]
    cache = {}
    fins = {3: [], 2: [], 0: []}
    results = []

    def scope_of(name):
        if name == "monkeypatch":
            return 0
        fd = fixtures.get(name)
        return _BK_SCOPES[fd.scope] if fd else 0

    def get(name, params):
        if name in params:
            return params[name]
        if name in cache:
            return cache[name]
        if name == "monkeypatch":
            mp = _BkMonkeyPatch()
            cache[name] = mp
            fins[0].append((name, None, mp))
            return mp
        if name not in fixtures:
            raise LookupError("fixture '%s' not found" % name)
        fd = fixtures[name]
        kwargs = {a: get(a, params) for a in fd.argnames}
        res = fd.func(**kwargs)
        gen = None
        if _bk_inspect.isgenerator(res):
            gen = res
            res = next(gen)
        cache[name] = res
        fins[_BK_SCOPES[fd.scope]].append((name, gen, None))
        return res

    def teardown(level):
        while fins[level]:
            name, gen, mp = fins[level].pop()
            cache.pop(name, None)
            if mp is not None:
                mp.undo()
            elif gen is not None:
                _bk_finish(gen)

    for item_id, fn, params in items:
        if getattr(fn, "_bk_skip", False):
            results.append((item_id, "skipped"))
            continue
        argnames = _bk_argnames(fn)
        autouse = [n for n, fd in fixtures.items() if fd.autouse]
        closure = list(autouse) + [a for a in argnames if a not in autouse]
        last = -1
        while last != len(closure):
            last = len(closure)
            for a in list(closure):
                if a in params or a not in fixtures:
                    continue
                for dep in fixtures[a].argnames:
                    if dep not in closure:
                        closure.append(dep)
        closure.sort(key=scope_of, reverse=True)
        outcome = "passed"
        try:
            values = {}
            for a in closure:
                values[a] = get(a, params)
        except Exception:
            outcome = "error"
        if outcome == "passed":
            try:
                fn(**{a: values[a] if a in values else get(a, params) for a in argnames})
            except Exception:
                outcome = "failed"
        try:
            teardown(0)
        except Exception:
            outcome = "error" if outcome == "passed" else outcome
        results.append((item_id, outcome))
    teardown(2)
    teardown(3)
    return results


def _bk_summary(results):
    count = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for _, outcome in results:
        count[outcome] += 1
    return count
'''

PYTEST_SUMMARY_TAIL = r'''
_bk_c = _bk_summary(_bk_run(dict(globals())))
print("passed=%d failed=%d" % (_bk_c["passed"], _bk_c["failed"] + _bk_c["error"]))
'''


PYTEST_CAUGHT_TAIL = r'''
_bk_c = _bk_summary(_bk_run(dict(globals())))
print("RESULT: PASS" if _bk_c["failed"] + _bk_c["error"] > 0 else "RESULT: FAIL")
'''

PYTEST_GREEN_TAIL = r'''
_bk_c = _bk_summary(_bk_run(dict(globals())))
print("RESULT: PASS" if _bk_c["failed"] + _bk_c["error"] == 0 and _bk_c["passed"] > 0 else "RESULT: FAIL")
'''


def module_prelude(modules: dict[str, str]) -> str:
    """Код, который до показанного кода регистрирует модули {имя: исходник} в sys.modules.

    Так показанный тест может делать `from shop.pricing import ...` и `patch("shop.x.y")`,
    а мы подставляем в модуль правильную реализацию или мутанта.
    """
    out = ["import sys as _bk_s, types as _bk_t"]
    for name, src in modules.items():
        parts = name.split(".")
        for i in range(1, len(parts)):
            pkg = ".".join(parts[:i])
            out.append(f"if {pkg!r} not in _bk_s.modules:\n"
                       f"    _bk_p = _bk_t.ModuleType({pkg!r}); _bk_p.__path__ = []\n"
                       f"    _bk_s.modules[{pkg!r}] = _bk_p")
        out.append(f"_bk_m = _bk_t.ModuleType({name!r})\n_bk_s.modules[{name!r}] = _bk_m\n"
                   f"exec(compile({src!r}, {name!r}, 'exec'), _bk_m.__dict__)")
        if len(parts) > 1:
            out.append(f"setattr(_bk_s.modules[{'.'.join(parts[:-1])!r}], {parts[-1]!r}, _bk_m)")
    return "\n".join(out) + "\n"


def pytest_program(display_code: str, tail: str, modules: dict[str, str] | None = None) -> str:
    """Обвязка pytest (+ модули) + показанный код дословно + хвост, печатающий результат."""
    pre = module_prelude(modules) if modules else ""
    return (PYTEST_SHIM + "\n" + pre + "\n" + display_code.rstrip() + "\n\n"
            + tail.strip("\n") + "\n")


JEST_SHIM = r'''
const __tests = [];
let __running = 0;
function test(name, fn) { __tests.push({ name, fn }); }
const it = test;
function describe(name, fn) { fn(); }
function __deepEq(a, b) {
  if (Object.is(a, b)) return true;
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a), kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && __deepEq(a[k], b[k]));
}
class __ExpectError extends Error {}
function expect(actual) {
  const build = (neg) => {
    const ok = (cond, msg) => {
      if (Boolean(cond) === neg) {
        if (__running === 0) return;  // «потерянная» проверка после завершения тестов
        throw new __ExpectError(msg || 'expect');
      }
    };
    const calls = () => (actual && actual.mock ? actual.mock.calls : []);
    return {
      toBe: (e) => ok(Object.is(actual, e), 'toBe ' + String(e)),
      toEqual: (e) => ok(__deepEq(actual, e), 'toEqual'),
      toBeTruthy: () => ok(actual, 'toBeTruthy'),
      toBeFalsy: () => ok(!actual, 'toBeFalsy'),
      toBeNull: () => ok(actual === null, 'toBeNull'),
      toBeUndefined: () => ok(actual === undefined, 'toBeUndefined'),
      toBeDefined: () => ok(actual !== undefined, 'toBeDefined'),
      toContain: (e) => ok(actual != null && actual.includes(e), 'toContain'),
      toHaveLength: (n) => ok(actual != null && actual.length === n, 'toHaveLength'),
      toBeGreaterThan: (n) => ok(actual > n, 'toBeGreaterThan'),
      toHaveBeenCalled: () => ok(calls().length > 0, 'toHaveBeenCalled'),
      toHaveBeenCalledTimes: (n) => ok(calls().length === n, 'toHaveBeenCalledTimes'),
      toHaveBeenCalledWith: (...args) => ok(calls().some((c) => __deepEq(c, args)), 'toHaveBeenCalledWith'),
    };
  };
  const api = build(false);
  api.not = build(true);
  return api;
}
const jest = {
  fn(impl) {
    let ret = { kind: 'impl' };
    const f = (...args) => {
      f.mock.calls.push(args);
      if (ret.kind === 'value') return ret.value;
      if (ret.kind === 'resolved') return Promise.resolve(ret.value);
      return impl ? impl(...args) : undefined;
    };
    f.mock = { calls: [] };
    f.mockReturnValue = (v) => { ret = { kind: 'value', value: v }; return f; };
    f.mockResolvedValue = (v) => { ret = { kind: 'resolved', value: v }; return f; };
    f.mockImplementation = (g) => { impl = g; ret = { kind: 'impl' }; return f; };
    return f;
  },
};
const vi = jest;
async function __runTests() {
  const res = [];
  for (const t of __tests) {
    __running += 1;
    try {
      await t.fn();
      res.push([t.name, 'passed']);
    } catch (e) {
      res.push([t.name, 'failed']);
    } finally {
      __running -= 1;
    }
  }
  return res;
}
'''
