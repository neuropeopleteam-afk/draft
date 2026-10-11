"""mobile.push.fcm_message_mcq — mcq_concept: тип сообщения Firebase Cloud Messaging и обработка в фоне.

Факты (Firebase, «Receive messages in an Android app»): сообщение с блоком `notification`, пришедшее в фоне,
показывает система сама, `onMessageReceived` не вызывается (данные `data` — в extras Intent при нажатии);
в переднем плане — вызывается `onMessageReceived`. Сообщение только с `data` вызывает `onMessageReceived` и в
переднем плане, и в фоне. Требование задачи — в фоне выполнить свой код (свой вид уведомления с кнопками,
запись в локальную базу, тихое обновление) — выполнимо только data-сообщением. Состав дистракторов
фиксирован. Ключ — справочная таблица (исполнение невозможно).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey

from ._mob_utils import balanced_options, check_lengths

FAMILY_ID = "mobile.push.fcm_message_mcq"

NEEDS = [("показать уведомление о заказе со своими кнопками «Принять» и «Отклонить»", "приложение курьера"),
         ("сохранить входящее сообщение в локальную базу, чтобы чат открылся сразу без сети", "мессенджер"),
         ("обновить остаток на виджете рабочего стола без показа уведомления", "банковское приложение"),
         ("сгруппировать уведомления о новых откликах в одно со счётчиком", "приложение работодателя"),
         ("показать уведомление с картинкой товара, загруженной приложением", "маркетплейс"),
         ("отметить на сервере доставку уведомления до показа", "приложение аптеки"),
         ("расшифровать текст сообщения ключом с устройства и показать его в уведомлении", "защищённый мессенджер"),
         ("запустить синхронизацию изменённых документов", "корпоративное хранилище файлов"),
         ("показать уведомление только если заказ ещё не открыт на другом устройстве", "приложение ресторана"),
         ("обновить локальный кэш расписания и показать изменение рейса", "приложение авиакомпании")]
STEMS = [
    ("Android-приложение ({ctx}) получает push через Firebase Cloud Messaging. Требование: когда приложение "
     "{state}, по приходу push нужно {need}. В переднем плане всё уже работает. Как отправлять и обрабатывать "
     "сообщение?"),
    ("{Ctx}, Android, push — Firebase Cloud Messaging. Тестировщик сообщил: пока приложение {state}, push "
     "показывается системным уведомлением по умолчанию, а нужно {need}; в открытом приложении всё верно. Что "
     "изменить в отправке и обработке?"),
    ("Бэкенд приложения «{ctx}» шлёт push через FCM. Задача: даже если приложение {state}, в момент прихода "
     "сообщения {need_inf}. Как формировать сообщение на сервере и где его обрабатывать на клиенте?"),
]

OPTS = {
    "good": "Отправлять сообщение только с блоком data и обрабатывать его в onMessageReceived",
    "notification": "Отправлять сообщение с блоком notification и обрабатывать его в onMessageReceived",
    "both": "Отправлять блоки notification и data вместе, обработку вести в onMessageReceived",
    "intent": "Отправлять блок notification, а данные читать из extras Intent при запуске приложения",
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    need, ctx = rng.choice(NEEDS)
    state = rng.choice(["свёрнуто", "в фоне (пользователь переключился на другое приложение)",
                        "свёрнуто, экран телефона выключен"])
    dist = ["notification", "both", "intent"]
    check_lengths([OPTS["good"]] + [OPTS[d] for d in dist], max_ratio=1.45)
    opts, key = balanced_options(FAMILY_ID, seed, rng, (OPTS["good"], None), [(OPTS[d], None) for d in dist])
    stem = rng.choice(STEMS).format(ctx=ctx, Ctx=ctx[:1].upper() + ctx[1:], state=state, need=need,
                                    need_inf="приложение должно " + need)
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Верно: только data-сообщение вызывает onMessageReceived в фоне. Сообщение с блоком "
                                "notification в фоне показывает система сама, onMessageReceived не вызывается — "
                                "и при одном notification, и при notification + data; extras Intent доступны лишь "
                                "после нажатия на уведомление, то есть код в момент прихода не выполняется."))
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="reference_table", language="text",
                         params={"need": need, "distractors": dist,
                                 "reference": "firebase.google.com: Receive messages in an Android app"})
