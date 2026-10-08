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

Go, Java, Django (добавлены 06.10 для семейств по этим технологиям):
* go — пакет программ собирается одним `go build -race` (каждая программа — свой пакет
  jobN, `package main`/`func main()` переименовываются механически), затем каждая
  исполняется отдельным процессом с таймаутом. Детектор гонок обязателен (нужны cgo и gcc).
  Тулчейн ищется в BANK_GO_BIN, PATH, ~/.local/go/bin, /usr/local/go/bin; сеть и модули
  не нужны (GOPROXY=off, только стандартная библиотека);
* java — один процесс JVM на пакет: исходник каждой программы (`public class Main`)
  компилируется javax.tools в свой каталог и исполняется в своём загрузчике классов с
  перехваченным System.out; при таймауте JVM завершается, остаток пакета идёт новым
  процессом. Нужен JDK с модулем jdk.compiler (BANK_JAVA_BIN или java из PATH);
* django — как python, но без `-S` (Django из окружения банка, requirements.txt): Django
  настроен на SQLite в памяти, каждая программа исполняется в `isolate_apps("bankapp")`
  и со своей базой (соединение закрывается после программы).
Для go и java аварийное завершение (паника, исключение, таймаут, отчёт детектора гонок)
дописывает в вывод строку `RESULT: FAIL <причина>` — это «тест не пройден».
"""
from __future__ import annotations

import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import re
import tempfile
import threading

_SHM = "/dev/shm" if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK) else None
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .schema import Check

DEFAULT_TIMEOUT_S = 5.0
_PY_BATCH = 150
_NODE_BATCH = 120
_GO_BATCH = 120
_JAVA_BATCH = 150


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


def _limits(mem_bytes: int | None, cpu_s: int, fsize: int = 8 * 1024 * 1024, nofile: int = 256):
    def apply() -> None:
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
        if mem_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    return apply


def _base_env(tmp: str) -> dict[str, str]:
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": tmp, "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8", "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8",
            "TZ": "UTC"}


def _exec(cmd: list[str], tmp: str, timeout: float, env: dict[str, str],
          mem: int | None, fsize: int = 8 * 1024 * 1024, nofile: int = 256,
          ) -> tuple[str, str, int | None, bool]:
    proc = subprocess.Popen(cmd, cwd=tmp, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            preexec_fn=_limits(mem, int(timeout) + 2, fsize, nofile))
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


_DJANGO_RUNNER_PRELUDE = r'''
import os as _os, sys as _sys
_tmpdir = _os.path.dirname(_os.path.abspath(_sys.argv[1]))
_os.makedirs(_os.path.join(_tmpdir, "bankapp"), exist_ok=True)
open(_os.path.join(_tmpdir, "bankapp", "__init__.py"), "w").close()
_sys.path.insert(0, _tmpdir)
import django as _django
from django.conf import settings as _settings
_settings.configure(DEBUG=True, USE_TZ=True, TIME_ZONE="UTC", SECRET_KEY="bank-sandbox",
                    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
                    INSTALLED_APPS=["bankapp"], DEFAULT_AUTO_FIELD="django.db.models.AutoField")
_django.setup()
import django.db.models, django.forms, django.db.transaction, django.dispatch  # noqa: E401 — до аудит-хука
import django.db.backends.sqlite3.base, django.db.backends.sqlite3.schema  # noqa: E401
import django.test.utils as _dtu
from django.db import connection as _bank_conn
from django.db.backends.base.base import BaseDatabaseWrapper as _BaseDBW


def _bank_exec(source):
    try:
        with _dtu.isolate_apps("bankapp"):
            exec(compile(source, "<variant>", "exec"), {"__name__": "bankapp.models"})
    finally:
        # база в памяти исчезает вместе с соединением (обёртка SQLite не закрывает её сама)
        _BaseDBW.close(_bank_conn)
        _bank_conn.queries_log.clear()
'''


def _go_binary() -> str | None:
    explicit = os.environ.get("BANK_GO_BIN")
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("go")
    if found:
        return found
    for cand in (os.path.expanduser("~/.local/go/bin/go"), "/usr/local/go/bin/go"):
        if os.access(cand, os.X_OK):
            return cand
    return None


def _java_binary() -> str | None:
    explicit = os.environ.get("BANK_JAVA_BIN")
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    return shutil.which("java")


_AVAIL_CACHE: dict[str, bool] = {}


def _probe(runner: str) -> bool:
    if runner == "go":
        return _go_binary() is not None and (shutil.which("gcc") or shutil.which("cc")) is not None
    if runner == "java":
        java = _java_binary()
        if not java:
            return False
        try:
            out = subprocess.run([java, "--list-modules"], capture_output=True, text=True, timeout=30)
        except Exception:  # noqa: BLE001
            return False
        return "jdk.compiler" in out.stdout
    if runner == "django":
        import importlib.util
        return importlib.util.find_spec("django") is not None
    return False


def runner_available(runner: str) -> bool:
    if runner in ("go", "java", "django"):
        if runner not in _AVAIL_CACHE:
            _AVAIL_CACHE[runner] = _probe(runner)
        return _AVAIL_CACHE[runner]
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
        if kind in ("python", "django"):
            runner = os.path.join(tmp, "runner.py")
            src = _PY_RUNNER
            if kind == "django":
                src = src.replace("sys.addaudithook(_audit)", _DJANGO_RUNNER_PRELUDE + "\nsys.addaudithook(_audit)")
                src = src.replace('exec(compile(_job["source"], "<variant>", "exec"), {"__name__": "__main__"})',
                                  '_bank_exec(_job["source"])')
            with open(runner, "w", encoding="utf-8") as fh:
                fh.write(src)
            # django: без -S — пакет Django берётся из site-packages окружения банка
            flags = ["-I", "-B"] if kind == "django" else ["-I", "-S", "-B"]
            cmd = [sys.executable, *flags, runner, jobs_path]
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


# --------------------------------------------------------------------------- go и java
_HEAVY = {"go": threading.Lock(), "java": threading.Lock()}
_BUILD_LIM = (512 * 1024 * 1024, 4096)  # сборка go: размер файлов кэша/бинарника и дескрипторы  # сборки и JVM — по одной за раз (2 ядра)
_PKG_RE = re.compile(r"^package main\s*$", re.MULTILINE)
_MAIN_RE = re.compile(r"^func main\(\) \{", re.MULTILINE)


def _harness_outcome(stdout: str, status: str, error: str, race: bool = False) -> RunResult:
    """Аварийное завершение программы go/java = «тест не пройден»: дописываем RESULT: FAIL."""
    if race:
        return RunResult(stdout.rstrip("\n") + "\nRESULT: FAIL data race\n", "error",
                         ("data race; " + error)[-400:])
    if status != "ok":
        lines = stdout.strip().splitlines()
        if not (lines and lines[-1].startswith("RESULT: FAIL")):
            stdout = stdout.rstrip("\n") + ("\n" if stdout.strip() else "") + f"RESULT: FAIL {status}\n"
    return RunResult(stdout, status, error[-400:])


def _go_env(tmp: str) -> dict[str, str]:
    env = _base_env(tmp)
    go = _go_binary() or "go"
    env["PATH"] = os.path.dirname(go) + os.pathsep + env["PATH"]
    cache = os.environ.get("BANK_GOCACHE") or os.path.expanduser("~/.cache/bank-go-build")
    env.update({"GOCACHE": cache, "GOPATH": os.path.join(tmp, ".gopath"), "GOFLAGS": "-mod=mod",
                "GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off", "GOTELEMETRY": "off",
                "GOENV": "off", "CGO_ENABLED": "1", "GOMAXPROCS": "2",
                "GORACE": "exitcode=66 halt_on_error=0 atexit_sleep_ms=0"})
    return env


def _go_write(tmp: str, sources: list[str], ok: list[int]) -> None:
    with open(os.path.join(tmp, "go.mod"), "w", encoding="utf-8") as fh:
        fh.write("module bankbatch\n\ngo 1.22\n")
    for i, src in enumerate(sources):
        d = os.path.join(tmp, f"job{i}")
        os.makedirs(d, exist_ok=True)
        body = _MAIN_RE.sub("func Main() {", _PKG_RE.sub(f"package job{i}", src, count=1), count=1)
        with open(os.path.join(d, "main.go"), "w", encoding="utf-8") as fh:
            fh.write(body)
    imports = "\n".join(f'\tj{i} "bankbatch/job{i}"' for i in ok)
    cases = "\n".join(f'\tcase "{i}":\n\t\tj{i}.Main()' for i in ok)
    with open(os.path.join(tmp, "main.go"), "w", encoding="utf-8") as fh:
        fh.write(f'package main\n\nimport (\n\t"os"\n{imports}\n)\n\nfunc main() {{\n'
                 f'\tswitch os.Args[1] {{\n{cases}\n\t}}\n}}\n')


def _run_go_batch(checks: list[Check], timeout: float) -> list[RunResult]:
    """Собрать пакет программ одним бинарником с детектором гонок и исполнить каждую отдельно."""
    tmp = tempfile.mkdtemp(prefix="bank_go_", dir=_SHM)
    try:
        sources = [c.program for c in checks]
        env = _go_env(tmp)
        go = _go_binary() or "go"
        ok = list(range(len(sources)))
        res: list[RunResult | None] = [None] * len(sources)
        with _HEAVY["go"]:
            _go_write(tmp, sources, ok)
            out, err, code, _ = _exec([go, "build", "-race", "-o", "bank_bin", "."], tmp, 300, env, None, *_BUILD_LIM)
            if code != 0:  # ошибка компиляции в какой-то программе: находим её, остальное собираем
                bad = []
                for i in ok:
                    _o, e2, c2, _t = _exec([go, "build", f"./job{i}"], tmp, 120, env, None, *_BUILD_LIM)
                    if c2 != 0:
                        bad.append(i)
                        res[i] = _harness_outcome("", "error", "compile: " + e2[-300:])
                ok = [i for i in ok if i not in bad]
                if ok:
                    _go_write(tmp, sources, ok)
                    out, err, code, _ = _exec([go, "build", "-race", "-o", "bank_bin", "."], tmp, 300, env, None, *_BUILD_LIM)
                if not ok or code != 0:
                    msg = err[-300:] if ok else "все программы с ошибкой компиляции"
                    return [r or RunResult("", "error", "go build: " + msg) for r in res]

        def one(i: int) -> RunResult:
            o, e, c, timed = _exec([os.path.join(tmp, "bank_bin"), str(i)], tmp, timeout, env, None)
            race = "WARNING: DATA RACE" in e
            status = "timeout" if timed else ("ok" if c == 0 else "error")
            return _harness_outcome(o, status, e, race)

        with ThreadPoolExecutor(max_workers=2) as ex:
            for i, r in zip(ok, ex.map(one, ok)):
                res[i] = r
        return [r or RunResult("", "error", "не исполнено") for r in res]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_JAVA_RUNNER = r"""
import javax.tools.*;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class BankRunner {
    static void write(Path dir, String name, String text) throws IOException {
        Files.writeString(dir.resolve(name), text, StandardCharsets.UTF_8);
    }

    public static void main(String[] args) throws Exception {
        Path root = Paths.get(args[0]);
        long timeoutMs = Long.parseLong(args[1]);
        int start = Integer.parseInt(args[2]), n = Integer.parseInt(args[3]);
        JavaCompiler jc = ToolProvider.getSystemJavaCompiler();
        StandardJavaFileManager fm = jc.getStandardFileManager(null, null, StandardCharsets.UTF_8);
        PrintStream realOut = System.out, realErr = System.err;
        PrintStream nullErr = new PrintStream(OutputStream.nullOutputStream());
        for (int i = start; i < n; i++) {
            Path dir = root.resolve(Integer.toString(i));
            Path classes = dir.resolve("classes");
            Files.createDirectories(classes);
            StringWriter diag = new StringWriter();
            boolean ok = jc.getTask(diag, fm, null,
                    List.of("-d", classes.toString(), "-proc:none", "-nowarn", "-encoding", "UTF-8", "-g:none"),
                    null, fm.getJavaFileObjects(dir.resolve("Main.java").toFile())).call();
            if (!ok) { write(dir, "status", "error\ncompile: " + diag); continue; }
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            PrintStream ps = new PrintStream(buf, true, StandardCharsets.UTF_8);
            String[] st = {"ok", ""};
            URLClassLoader cl = new URLClassLoader(new URL[]{classes.toUri().toURL()},
                    ClassLoader.getPlatformClassLoader());
            Thread t = new Thread(() -> {
                try {
                    Method m = cl.loadClass("Main").getMethod("main", String[].class);
                    m.invoke(null, (Object) new String[0]);
                } catch (InvocationTargetException e) {
                    Throwable c = e.getCause();
                    st[0] = "error"; st[1] = c.getClass().getName() + ": " + c.getMessage();
                } catch (Throwable e) {
                    st[0] = "error"; st[1] = e.toString();
                }
            });
            t.setDaemon(true);
            System.setOut(ps); System.setErr(nullErr);
            t.start();
            t.join(timeoutMs);
            System.setOut(realOut); System.setErr(realErr);
            ps.flush();
            write(dir, "stdout", buf.toString(StandardCharsets.UTF_8));
            if (t.isAlive()) { write(dir, "status", "timeout\n"); System.exit(3); }
            write(dir, "status", st[0] + "\n" + st[1]);
            cl.close();
        }
        System.exit(0);
    }
}
"""


def _run_java_batch(checks: list[Check], timeout: float) -> list[RunResult]:
    """Один процесс JVM на пакет; после таймаута программы остаток пакета — новым процессом."""
    tmp = tempfile.mkdtemp(prefix="bank_java_", dir=_SHM)
    try:
        java = _java_binary() or "java"
        n = len(checks)
        for i, c in enumerate(checks):
            d = os.path.join(tmp, str(i))
            os.makedirs(d)
            with open(os.path.join(d, "Main.java"), "w", encoding="utf-8") as fh:
                fh.write(c.program)
        runner = os.path.join(tmp, "BankRunner.java")
        with open(runner, "w", encoding="utf-8") as fh:
            fh.write(_JAVA_RUNNER)
        env = _base_env(tmp)
        env["PATH"] = os.path.dirname(java) + os.pathsep + env["PATH"]
        res: list[RunResult | None] = [None] * n
        start = 0
        with _HEAVY["java"]:
            while start < n:
                cmd = [java, "-Xmx384m", "-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1", "-Xss1m",
                       runner, tmp, str(int(timeout * 1000)), str(start), str(n)]
                _o, err, _code, timed = _exec(cmd, tmp, timeout * (n - start) + 60, env, None,
                                              64 * 1024 * 1024, 4096)
                nxt = start
                while nxt < n and os.path.exists(os.path.join(tmp, str(nxt), "status")):
                    nxt += 1
                if nxt == start:  # JVM не дошла даже до первой программы
                    res[start] = RunResult("", "error", ("jvm: " + ("timeout" if timed else err))[-400:])
                    nxt = start + 1
                start = nxt
        for i in range(n):
            if res[i] is not None:
                continue
            d = os.path.join(tmp, str(i))
            try:
                with open(os.path.join(d, "status"), encoding="utf-8") as fh:
                    status, _, error = fh.read().partition("\n")
            except FileNotFoundError:
                res[i] = RunResult("", "error", "не исполнено")
                continue
            out = ""
            if os.path.exists(os.path.join(d, "stdout")):
                with open(os.path.join(d, "stdout"), encoding="utf-8") as fh:
                    out = fh.read()
            res[i] = _harness_outcome(out, status.strip(), error)
        return [r or RunResult("", "error", "не исполнено") for r in res]
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
    for kind, batch in (("django", _PY_BATCH), ("go", _GO_BATCH), ("java", _JAVA_BATCH)):
        k_idx = [i for i, c in enumerate(checks) if c.runner == kind]
        if k_idx and runner_available(kind):
            for i in range(0, len(k_idx), batch):
                chunk = k_idx[i:i + batch]
                tasks.append((kind, chunk, [checks[j] for j in chunk] if kind != "django"
                              else [checks[j].program for j in chunk]))
        else:
            for j in k_idx:
                results[j] = RunResult("", "unavailable", f"{kind}: нет исполнителя")
    shell_ok = {r: runner_available(r) for r in ("bash", "git")}

    def do(task):
        kind, idx, payload = task
        if kind in ("python", "node", "django"):
            return idx, _run_batch(kind, payload, timeout)
        if kind == "go":
            return idx, _run_go_batch(payload, timeout)
        if kind == "java":
            return idx, _run_java_batch(payload, timeout)
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
