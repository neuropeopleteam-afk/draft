"""mobile.kotlin.flow_lifecycle_mcq — mcq_concept: сбор Flow в UI с учётом жизненного цикла.

Экран подписывается на «горячий» источник через callbackFlow (геопозиция, датчик, сокет). Требование: в фоне
обновления не обрабатываются И источник отключается (отписка в awaitClose), при возврате — снова подписка.
Факты (руководство Android «Kotlin flows on Android», статья команды Android «A safer way to collect flows
from Android UIs», 2021): `lifecycleScope.launch { collect }` собирает и в фоне до onDestroy;
`launchWhenStarted` приостанавливает сборщик, но поток-производитель остаётся активным (API устарел);
`repeatOnLifecycle(Lifecycle.State.STARTED)` отменяет сбор при onStop и запускает заново при onStart;
`repeatOnLifecycle(Lifecycle.State.CREATED)` активен и в фоне. Состав дистракторов фиксирован — три последних
неверных варианта. Ключ — справочная таблица по этим источникам (исполнение Android невозможно).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey

from ._mob_utils import balanced_options

FAMILY_ID = "mobile.kotlin.flow_lifecycle_mcq"

SOURCES = [("геопозиция курьера", "locationUpdates()", "LocationManager", "каждую секунду"),
           ("шагомер", "stepCounter()", "SensorManager", "при каждом шаге"),
           ("котировки по WebSocket", "quotes(symbol)", "сокет биржи", "несколько раз в секунду"),
           ("статус заказа по SSE", "orderEvents(orderId)", "поток событий сервера", "при каждом изменении"),
           ("компас", "heading()", "SensorManager", "десятки раз в секунду"),
           ("сканер Bluetooth-меток", "beacons()", "BluetoothLeScanner", "каждые 100 мс")]
HOSTS = [("Fragment", "viewLifecycleOwner.lifecycleScope", "viewLifecycleOwner.repeatOnLifecycle"),
         ("Activity", "lifecycleScope", "repeatOnLifecycle")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, flow, producer, rate = rng.choice(SOURCES)
    host, scope, repeat = rng.choice(HOSTS)
    render = rng.choice(["render(it)", "updateUi(it)", "show(it)"])
    vm = rng.choice(["viewModel", "vm"])
    src = f"{vm}.{flow}"
    good = f"{scope}.launch {{ {repeat}(Lifecycle.State.STARTED) {{ {src}.collect {{ {render} }} }} }}"
    d = {"plain": f"{scope}.launch {{ {src}.collect {{ {render} }} }}",
         "when_started": f"{scope}.launchWhenStarted {{ {src}.collect {{ {render} }} }}",
         "created": f"{scope}.launch {{ {repeat}(Lifecycle.State.CREATED) {{ {src}.collect {{ {render} }} }} }}"}
    dist = ["plain", "when_started", "created"]
    opts, key = balanced_options(FAMILY_ID, seed, rng, (good, None), [(d[k], None) for k in dist])
    where = "onViewCreated" if host == "Fragment" else "onCreate"
    stem = (f"Android-приложение, экран «{ctx}» ({host}). `{src}` — Flow на основе callbackFlow: при начале сбора "
            f"подписывается на {producer} (данные приходят {rate}), в `awaitClose` отписывается. Требование: пока "
            f"приложение свёрнуто, обновления не обрабатываются и подписка на {producer} снята (батарея); при "
            f"возврате на экран обновления возобновляются. Какой код в `{where}` выполняет требование?")
    why = {"plain": "сбор в lifecycleScope.launch продолжается в фоне до уничтожения экрана",
           "when_started": "launchWhenStarted только приостанавливает сборщик — callbackFlow остаётся подписанным "
                           "на источник (API устарел именно поэтому)",
           "created": "состояние CREATED сохраняется и в фоне (после onStop) — сбор не останавливается"}
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Верно: repeatOnLifecycle(STARTED) отменяет сбор при onStop (callbackFlow выполняет "
                                "awaitClose и отписывается) и запускает заново при onStart. Дистракторы: " +
                                "; ".join(why[k] for k in dist) + "."))
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="reference_table", language="kotlin",
                         params={"host": host, "source": flow, "distractors": dist,
                                 "reference": "developer.android.com: Kotlin flows on Android; repeatOnLifecycle"})
