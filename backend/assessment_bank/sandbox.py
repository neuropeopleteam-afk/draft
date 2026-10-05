"""Песочница для проверки ключей ответов исполнением.

ВАЖНО: здесь исполняется только код, сгенерированный нашими же шаблонами, и только на этапе
генерации/валидации банка. Код и ответы кандидатов никогда не исполняются — ни здесь, ни на
сервере (решение консилиума и требование брифа).

Меры изоляции (защита «в глубину», а не граница доверия):
* отдельный процесс с пустым окружением, временный рабочий каталог, лимиты ресурсов
  (CPU, память, размер файлов, число дескрипторов), жёсткий таймаут с убийством группы;
* Python: режим `-I -S`, audit-хук запрещает сеть, запуск процессов и удаление файлов;
* Node: каждая программа в отдельном контексте `vm` без `require`/`process`.

Для скорости программы Python и Node исполняются пакетами (одна программа — свой
namespace/контекст, общий процесс). bash/git — по одному процессу на программу.
"""
from __future__ import annotations

import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile

_SHM = "/dev/shm" if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK) else None
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .schema import Check

DEFAULT_TIMEOUT_S = 5.0
_PY_BATCH = 150
_NODE_BATCH = 120


@dataclass
class RunResult:
    stdout: str
    status: str  # ok | error | timeout | unavailable
    error: str = ""


_PY_RUNNER = r'''
import contextlib, io, json, signal, sys

class _BankTimeout(BaseException):
    pass

def _on_alarm(signum, frame):
    raise _BankTimeout()

signal.signal(signal.SIGALRM, _on_alarm)
with open(sys.argv[1], encoding="utf-8") as fh:
    _jobs = json.load(fh)
_real_stdout = sys.stdout

_BLOCKED = {"socket.connect", "socket.bind", "socket.getaddrinfo", "subprocess.Popen",
            "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty",
            "os.kill", "os.remove", "os.rmdir", "os.rename", "shutil.rmtree", "ctypes.dlopen",
            "urllib.Request"}

def _audit(event, args):
    if event in _BLOCKED:
        raise PermissionError("sandbox: запрещено " + event)

sys.addaudithook(_audit)
_results = []
for _job in _jobs:
    _buf = io.StringIO()
    _status, _err = "ok", ""
    signal.setitimer(signal.ITIMER_REAL, _job["timeout"])
    try:
        with contextlib.redirect_stdout(_buf):
            exec(compile(_job["source"], "<variant>", "exec"), {"__name__": "__main__"})
    except _BankTimeout:
        _status = "timeout"
    except SystemExit as _e:
        _status = "ok" if _e.code in (None, 0) else "error"
    except BaseException as _e:  # noqa: BLE001 — фиксируем любую ошибку программы
        _status, _err = "error", f"{type(_e).__name__}: {_e}"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    _results.append({"stdout": _buf.getvalue(), "status": _status, "error": _err[-400:]})
_real_stdout.write(json.dumps(_results, ensure_ascii=False))
'''

_NODE_RUNNER = r'''
'use strict';
const vm = require('vm');
const fs = require('fs');
const util = require('util');
const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
let current = null;
process.on('uncaughtException', (e) => {
  if (current) { current.out.push('UNCAUGHT ' + (e && e.name)); current.status = 'error';
    current.error = String(e && e.message); }
});
process.on('unhandledRejection', (e) => {
  if (current) { current.status = 'error'; current.error = 'unhandledRejection: ' + String(e && e.message || e); }
});
const tick = () => new Promise((r) => setImmediate(r));
async function runJob(job) {
  const rec = { out: [], status: 'ok', error: '' };
  current = rec;
  const timers = new Map();
  let nextId = 1;
  const ctx = {
    console: {
      log: (...a) => rec.out.push(util.format(...a)),
      error: (...a) => rec.out.push(util.format(...a)),
      warn: (...a) => rec.out.push(util.format(...a)),
    },
    setTimeout: (fn, ms, ...args) => {
      const id = nextId++;
      const h = setTimeout(() => { timers.delete(id); fn(...args); }, ms);
      timers.set(id, h);
      return id;
    },
    clearTimeout: (id) => { const h = timers.get(id); if (h) { clearTimeout(h); timers.delete(id); } },
    queueMicrotask: queueMicrotask,
  };
  vm.createContext(ctx);
  const deadline = Date.now() + job.timeout * 1000;
  try {
    vm.runInContext(job.source, ctx, { timeout: job.timeout * 1000, filename: 'variant.js' });
  } catch (e) {
    rec.out.push('UNCAUGHT ' + (e && e.name)); rec.status = 'error'; rec.error = String(e && e.message);
  }
  for (;;) {
    await tick();
    if (timers.size === 0) { await tick(); await tick(); if (timers.size === 0) break; }
    if (Date.now() > deadline) {
      for (const h of timers.values()) clearTimeout(h);
      timers.clear(); rec.status = 'timeout'; break;
    }
  }
  current = null;
  return { stdout: rec.out.length ? rec.out.join('\n') + '\n' : '', status: rec.status, error: rec.error };
}
(async () => {
  const results = [];
  for (const job of jobs) results.push(await runJob(job));
  process.stdout.write(JSON.stringify(results));
})();
'''

_SQLITE_DRIVER = '''import sqlite3
_con = sqlite3.connect(":memory:")
_con.executescript({setup!r})
for _row in _con.execute({query!r}).fetchall():
    print("|".join("NULL" if v is None else str(v) for v in _row))
'''

def _git_binary() -> str | None:
    """Путь к настоящему git.

    В некоторых окружениях `git` в PATH — обёртка-скрипт (телеметрия, прокси), которая
    запускает настоящий бинарник; в песочнице она не нужна и сильно замедляет проверки.
    Можно явно задать путь переменной BANK_GIT_BIN.
    """
    explicit = os.environ.get("BANK_GIT_BIN")
    if explicit:
        return explicit
    found = shutil.which("git")
    if not found:
        return None
    for cand in (os.path.join(os.path.dirname(found), ".git-real"), "/usr/local/bin/.git-real",
                 "/usr/bin/.git-real"):
        if os.access(cand, os.X_OK):
            return cand
    return found


_GIT_PRELUDE = """set -e
git init -q -b main
git config user.name "Bank Bot"
git config user.email "bank@example.invalid"
git config commit.gpgsign false
"""


def _limits(mem_bytes: int | None, cpu_s: int):
    def apply() -> None:
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        if mem_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    return apply


def _base_env(tmp: str) -> dict[str, str]:
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": tmp, "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8", "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8",
            "TZ": "UTC"}


def _exec(cmd: list[str], tmp: str, timeout: float, env: dict[str, str],
          mem: int | None) -> tuple[str, str, int | None, bool]:
    proc = subprocess.Popen(cmd, cwd=tmp, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, preexec_fn=_limits(mem, int(timeout) + 2))
    try:
        out, err = proc.communicate(timeout=timeout)
        return out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), proc.returncode, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, err = proc.communicate()
        return out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), None, True


def runner_available(runner: str) -> bool:
    if runner in ("python", "sqlite"):
        return True
    if runner == "node":
        return shutil.which("node") is not None
    if runner == "bash":
        return shutil.which("bash") is not None
    if runner == "git":
        return shutil.which("git") is not None and shutil.which("bash") is not None
    return False


def _python_source(check: Check) -> str:
    if check.runner == "sqlite":
        return _SQLITE_DRIVER.format(setup=check.files.get("setup.sql", ""),
                                     query=check.program)
    return check.program


def _run_batch(kind: str, sources: list[str], timeout: float) -> list[RunResult]:
    tmp = tempfile.mkdtemp(prefix="bank_sbx_", dir=_SHM)
    try:
        jobs_path = os.path.join(tmp, "jobs.json")
        with open(jobs_path, "w", encoding="utf-8") as fh:
            json.dump([{"source": s, "timeout": timeout} for s in sources], fh, ensure_ascii=False)
        total = timeout * len(sources) + 10
        if kind == "python":
            runner = os.path.join(tmp, "runner.py")
            with open(runner, "w", encoding="utf-8") as fh:
                fh.write(_PY_RUNNER)
            cmd = [sys.executable, "-I", "-S", "-B", runner, jobs_path]
            mem = 1024 * 1024 * 1024
        else:
            runner = os.path.join(tmp, "runner.js")
            with open(runner, "w", encoding="utf-8") as fh:
                fh.write(_NODE_RUNNER)
            cmd = ["node", "--max-old-space-size=256", "--disallow-code-generation-from-strings",
                   runner, jobs_path]
            mem = None  # V8 резервирует большое адресное пространство; лимит — через heap
        out, err, code, timed_out = _exec(cmd, tmp, total, _base_env(tmp), mem)
        if timed_out or code != 0:
            msg = "timeout" if timed_out else f"exit {code}: {err[-300:]}"
            return [RunResult("", "error", f"batch failed: {msg}") for _ in sources]
        data = json.loads(out)
        return [RunResult(d["stdout"], d["status"], d.get("error", "")) for d in data]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_shell(check: Check, timeout: float) -> RunResult:
    tmp = tempfile.mkdtemp(prefix="bank_sbx_", dir=_SHM)
    try:
        for name, content in check.files.items():
            path = os.path.join(tmp, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        script = os.path.join(tmp, ".bank_script.sh")
        env = _base_env(tmp)
        body = check.program
        if check.runner == "git":
            body = _GIT_PRELUDE + body
            bindir = os.path.join(tmp, ".bank_bin")
            os.makedirs(bindir)
            os.symlink(_git_binary() or "git", os.path.join(bindir, "git"))
            env["PATH"] = bindir + os.pathsep + env.get("PATH", os.defpath)
            env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                        "GIT_AUTHOR_DATE": "2026-10-05T12:00:00+03:00",
                        "GIT_COMMITTER_DATE": "2026-10-05T12:00:00+03:00",
                        "GIT_TERMINAL_PROMPT": "0", "GIT_ADVICE": "0"})
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(body)
        out, err, code, timed_out = _exec(["bash", "--noprofile", "--norc", script], tmp,
                                          timeout, env, 1024 * 1024 * 1024)
        if timed_out:
            return RunResult(out, "timeout")
        return RunResult(out, "ok" if code == 0 else "error", "" if code == 0 else err[-400:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_checks(checks: list[Check], timeout: float = DEFAULT_TIMEOUT_S,
               workers: int | None = None) -> list[RunResult]:
    """Исполнить проверки; порядок результатов совпадает с порядком checks."""
    results: list[RunResult | None] = [None] * len(checks)
    py_idx = [i for i, c in enumerate(checks) if c.runner in ("python", "sqlite")]
    node_idx = [i for i, c in enumerate(checks) if c.runner == "node"]
    sh_idx = [i for i, c in enumerate(checks) if c.runner in ("bash", "git")]
    tasks = []
    for i in range(0, len(py_idx), _PY_BATCH):
        chunk = py_idx[i:i + _PY_BATCH]
        tasks.append(("python", chunk, [_python_source(checks[j]) for j in chunk]))
    if node_idx and runner_available("node"):
        for i in range(0, len(node_idx), _NODE_BATCH):
            chunk = node_idx[i:i + _NODE_BATCH]
            tasks.append(("node", chunk, [checks[j].program for j in chunk]))
    else:
        for j in node_idx:
            results[j] = RunResult("", "unavailable", "node не найден")
    shell_ok = {r: runner_available(r) for r in ("bash", "git")}

    def do(task):
        kind, idx, payload = task
        if kind in ("python", "node"):
            return idx, _run_batch(kind, payload, timeout)
        return idx, [_run_shell(checks[idx[0]], timeout)]

    for j in sh_idx:
        if shell_ok[checks[j].runner]:
            tasks.append(("shell", [j], None))
        else:
            results[j] = RunResult("", "unavailable", f"{checks[j].runner} не найден")
    # оболочка и git ждут в основном ввода-вывода и запуска процессов — пул шире числа ядер
    with ThreadPoolExecutor(max_workers=workers or max(4, 4 * (os.cpu_count() or 2))) as ex:
        for idx, res in ex.map(do, tasks):
            for j, r in zip(idx, res):
                results[j] = r
    return [r if r is not None else RunResult("", "error", "не исполнено") for r in results]


def run_python(source: str, timeout: float = DEFAULT_TIMEOUT_S) -> RunResult:
    """Удобная обёртка: исполнить одну программу Python в песочнице."""
    return run_checks([Check(name="adhoc", runner="python", program=source,
                             expect="pass", embeds_display_code=False)], timeout)[0]
