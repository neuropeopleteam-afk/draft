"""mobile.kotlin.main_thread_io_bug — find_bug (Kotlin, чтение кода): блокирующий вызов на главном потоке.

`viewModelScope.launch { … }` по умолчанию исполняется на `Dispatchers.Main.immediate`. Синхронный сетевой или
дисковый вызов внутри (Retrofit `Call.execute()`, OkHttp `newCall(...).execute()`, `File.readText()`) блокирует
главный поток: на Android сеть на главном потоке — `NetworkOnMainThreadException`, диск — ANR/StrictMode.
Результат записывается в `MutableLiveData.value` — `setValue` разрешён только на главном потоке. Поэтому
исправление в одной строке ровно одно: обернуть блокирующий вызов в `withContext(Dispatchers.IO) { … }`;
перенос всего `launch` на `Dispatchers.IO` ломает `_state.value = …` (IllegalStateException) — это тоже
проверяется. Один подтип дефекта; варьируются экран, вид блокирующего вызова, служебные строки.

Kotlin в песочнице не исполняется: ключ проверяет модель потоков на Python, которая разбирает ПОКАЗАННЫЙ код
(он вложен в программу дословно): стек диспетчеров по `launch`/`withContext`, блокирующие вызовы и `setValue`
вне главного потока — ошибка. Модель покрывает только конструкции, встречающиеся в шаблоне.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._mob_utils import py_literal_block

FAMILY_ID = "mobile.kotlin.main_thread_io_bug"

SCREENS = [("ProfileViewModel", "профиль пользователя", "Profile", "userId: String"),
           ("CartViewModel", "корзина", "Cart", "cartId: Long"),
           ("NewsViewModel", "лента новостей", "Feed", "page: Int"),
           ("TicketViewModel", "электронный билет", "Ticket", "orderId: String"),
           ("ScheduleViewModel", "расписание занятий", "Schedule", "groupId: Int"),
           ("OrderViewModel", "статус заказа", "Order", "orderNo: String"),
           ("WalletViewModel", "баланс кошелька", "Wallet", "accountId: Long"),
           ("RecipeViewModel", "рецепт", "Recipe", "recipeId: Int")]
CALLS = [
    ("retrofit", "api.load({arg}).execute()", "Retrofit `Call.execute()`"),
    ("okhttp", "client.newCall(request({arg})).execute()", "синхронный запрос OkHttp"),
    ("file", "cacheFile({arg}).readText()", "чтение файла с диска"),
]

MODEL = r'''
import re

BLOCKING = re.compile(r"\.execute\(\)|\.readText\(\)")

def run(src):
    """Модель потоков: возвращает список нарушений для показанного Kotlin-кода."""
    errors, stack = [], ["main"]          # тело функции load() вызывается с главного потока
    for no, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        ctx = stack[-1]
        inline = re.search(r"withContext\(Dispatchers\.(IO|Default|Main)\)\s*\{(.*)\}", s)
        if inline:
            if BLOCKING.search(inline.group(2)) and inline.group(1) == "Main":
                errors.append((no, "blocking on main"))
        elif BLOCKING.search(s) and ctx == "main":
            errors.append((no, "blocking on main"))
        if re.search(r"\b_\w+\.value\s*=", s) and ctx != "main":
            errors.append((no, "setValue off main"))
        m = re.search(r"(?:launch|withContext)\s*(?:\((?:Dispatchers\.(\w+))?\))?\s*\{\s*$", s)
        if m:
            d = m.group(1)
            stack.append("main" if d in (None, "Main") else "bg")
            continue
        opened, closed = s.count("{"), s.count("}")
        if inline:
            opened -= 1; closed -= 1
        for _ in range(opened):
            stack.append(stack[-1])
        for _ in range(closed):
            if len(stack) > 1:
                stack.pop()
    return errors
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    vm, ctx, state, param = rng.choice(SCREENS)
    kind, call_t, call_name = rng.choice(CALLS)
    arg = param.split(":")[0]
    call = call_t.format(arg=arg)
    var = rng.choice(["result", "response", "data", "payload"])
    log_first = rng.random() < 0.5
    track = rng.random() < 0.5
    retry_line = rng.choice(["none", "retry", "cleared"])
    tag = rng.choice(["TAG", "LOG_TAG"])
    if kind == "file":
        use = [f"            _state.value = {state}UiState.Content(parse({var}))"]
    else:
        use = [f"            if ({var}.isSuccessful) {{",
               f"                _state.value = {state}UiState.Content({var}.body()!!)",
               "            } else {",
               f"                _state.value = {state}UiState.Error({var}.code())",
               "            }"]

    def body(call_line):
        lines = [f"class {vm}(private val repo: {state}Repository) : ViewModel() {{",
                 f"    private val _state = MutableLiveData<{state}UiState>()",
                 f"    val state: LiveData<{state}UiState> = _state", "",
                 f"    fun load({param}) {{", f"        _state.value = {state}UiState.Loading"]
        if track:
            lines.append(f"        analytics.track(\"{state.lower()}_open\")")
        lines.append("        viewModelScope.launch {")
        if log_first:
            lines.append(f"            Log.d({tag}, \"load ${arg}\")")
        lines.append(call_line)
        lines += use
        lines += ["        }", "    }"]
        if retry_line == "retry":
            lines += ["", "    fun retry() = load(last" + arg[0].upper() + arg[1:] + ")"]
        elif retry_line == "cleared":
            lines += ["", "    override fun onCleared() {", f"        Log.d({tag}, \"cleared\")", "    }"]
        lines.append("}")
        return "\n".join(lines)
    buggy = body(f"            val {var} = repo.{call}")
    fixed = body(f"            val {var} = withContext(Dispatchers.IO) {{ repo.{call} }}")
    launch_io = buggy.replace("viewModelScope.launch {", "viewModelScope.launch(Dispatchers.IO) {")
    diff = changed_lines(buggy, fixed)
    assert len(diff) == 1
    key_line = next(iter(diff))

    def prog(src, expect_ok):
        return (MODEL + "\n" + py_literal_block("SRC", src) +
                "errs = run(SRC.strip('\\n'))\n"
                f"print('RESULT: PASS' if not errs else 'RESULT: FAIL ' + repr(errs))\n")
    checks = [Check(name="buggy_fails", runner="python", program=prog(buggy, False), expect="fail"),
              Check(name="fixed_passes", runner="python", program=prog(fixed, True), expect="pass",
                    embeds_display_code=False),
              Check(name="launch_io_fails", runner="python", program=prog(launch_io, False), expect="fail",
                    embeds_display_code=False)]
    symptom = {"retrofit": "на тестовом устройстве с включённым StrictMode экран падает с "
                           "NetworkOnMainThreadException, у части пользователей — «Приложение не отвечает»",
               "okhttp": "на медленной сети интерфейс замирает на несколько секунд, в Play Console растёт "
                         "число ANR на этом экране",
               "file": "при большом кэше экран открывается рывком, StrictMode сообщает о чтении диска на "
                       "главном потоке, в Play Console — ANR"}[kind]
    stem = (f"Экран «{ctx}» Android-приложения. `{vm}.load` вызывается из фрагмента; методы `repo` синхронные "
            f"(не suspend), внутри — {call_name}. Жалоба: {symptom}. Укажите номер строки, которую "
            f"нужно исправить; исправление — в одной строке, остальной код (включая запись в `_state.value`) "
            f"должен продолжать работать.")
    ak = AnswerKey(kind="line", value=key_line,
                   explanation=(f"Строка {key_line}: `viewModelScope.launch` по умолчанию работает на "
                                f"Dispatchers.Main.immediate, поэтому синхронный вызов блокирует главный поток. "
                                f"Исправление — `withContext(Dispatchers.IO) {{ repo.{call} }}`: вызов уходит в пул "
                                f"ввода-вывода, а запись в `_state.value` остаётся на главном потоке. Перенос всего "
                                f"`launch` на Dispatchers.IO не годится: `MutableLiveData.setValue` с фонового "
                                f"потока бросает IllegalStateException (для фона есть `postValue`)."))
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="blocking_call_on_main",
                         display_code_note=("Kotlin не исполняется: показанный код вложен дословно в программу на "
                                            "Python — модель потоков (стек диспетчеров launch/withContext, "
                                            "блокирующие вызовы, setValue вне главного потока)."),
                         params={"fixed_code": fixed, "call": kind})
