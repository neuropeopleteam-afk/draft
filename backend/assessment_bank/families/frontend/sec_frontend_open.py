"""frontend.sec.frontend_open — open_answer: безопасность фронтенда (хранение токенов, CSP,
пользовательский HTML, OAuth в SPA, postMessage)."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng, rubric_from
from assessment_bank.schema import AnswerKey

FAMILY_ID = "frontend.sec.frontend_open"

CTX = ["личный кабинет банка", "платформа найма", "B2B-портал", "маркетплейс", "медицинский сервис",
       "CRM для продаж"]

TOPICS = {
    "tokens": dict(
        text=("SPA ({ctx}) хранит access-токен (JWT, срок {ttl}) и refresh-токен в localStorage и "
              "передаёт access в заголовке Authorization. После аудита просят «убрать токены из "
              "localStorage». Какие риски у текущей схемы и какую схему вы предложите?"),
        criteria=[("risk", "Объясняет риск: любой XSS читает localStorage и уносит долгоживущий "
                           "refresh-токен; токен нельзя отозвать до истечения", 0.35),
                  ("scheme", "Предлагает схему: refresh в httpOnly Secure SameSite-cookie (или BFF "
                             "с сессией), короткий access в памяти, ротация refresh с обнаружением "
                             "повторного использования", 0.4),
                  ("csrf", "Учитывает CSRF при cookie (SameSite, CSRF-токен, проверка Origin) и "
                           "что XSS всё равно опасен — нужны CSP и экранирование", 0.25)],
        strong="""Главный риск — XSS: любой внедрённый скрипт читает localStorage и уносит
            refresh-токен, с которым злоумышленник получает новые access-токены с любой машины;
            JWT при этом не отозвать до истечения срока {ttl}. Схема: refresh-токен — только в
            cookie с флагами httpOnly, Secure, SameSite=Strict или Lax и узким Path на эндпоинт
            обновления; access-токен короткий (5–15 минут) и живёт только в памяти вкладки,
            после перезагрузки получается заново через refresh. Refresh ротирую на каждое
            использование и при повторном предъявлении старого отзываю всю цепочку. Ещё
            надёжнее — BFF: браузер хранит только сессионную cookie, токены остаются на
            сервере. Раз есть cookie, нужна защита от CSRF: SameSite, CSRF-токен или проверка
            Origin на изменяющих запросах. httpOnly не спасает от действий от имени
            пользователя при XSS, поэтому параллельно — CSP и экранирование вывода.""",
        medium="""localStorage доступен любому скрипту, поэтому при XSS токены украдут. Лучше
            хранить refresh-токен в httpOnly-cookie с флагами Secure и SameSite, а access
            держать в памяти и делать коротким.""",
        weak="""Нужно хранить токены в sessionStorage — так безопаснее."""),
    "csp": dict(
        text=("Нужно внедрить Content-Security-Policy (продукт — {ctx}): сейчас политики нет, в коде есть "
              "inline-скрипты, подключены {n} сторонних скриптов (аналитика, чат, A/B-тесты). "
              "Как будете внедрять CSP, чтобы не сломать продакшен?"),
        criteria=[("policy", "Строит строгую политику: nonce или hash для скриптов, "
                             "strict-dynamic, запрет unsafe-inline/unsafe-eval, object-src 'none', "
                             "base-uri, frame-ancestors", 0.4),
                  ("rollout", "Внедряет поэтапно: Content-Security-Policy-Report-Only, сбор "
                              "отчётов (report-to), разбор нарушений, затем включение", 0.35),
                  ("refactor", "Убирает inline-обработчики и eval, ревизует сторонние скрипты, "
                               "понимает, что CSP — дополнительный слой, а не замена экранированию", 0.25)],
        strong="""Цель — строгая политика на nonce: script-src 'nonce-<случайный на каждый
            ответ>' 'strict-dynamic', без 'unsafe-inline' и 'unsafe-eval', плюс object-src
            'none', base-uri 'none' или 'self', frame-ancestors для защиты от кликджекинга.
            strict-dynamic разрешает скриптам с nonce подгружать свои зависимости, поэтому
            не нужен длинный список доменов для {n} сторонних скриптов. Внедряю поэтапно:
            сначала заголовок Content-Security-Policy-Report-Only с report-to, неделю собираю
            нарушения в отдельный сборщик, разбираю их. Параллельно переписываю inline-
            обработчики onclick на addEventListener, inline-скрипты получают nonce при
            серверном рендере, убираю eval и new Function. Сторонние скрипты ревизую: что-то
            удаляю, что-то загружаю через тег-менеджер с nonce. Затем включаю политику на
            части трафика и на всех. Помню, что CSP — дополнительный слой: экранирование и
            санитизация остаются обязательными.""",
        medium="""Нужно начать с режима Report-Only, собрать нарушения, убрать inline-скрипты или
            добавить им nonce и затем включить политику без unsafe-inline.""",
        weak="""Нужно добавить CSP с default-src * и unsafe-inline, чтобы ничего не сломалось."""),
    "user_html": dict(
        text=("Продукт — {ctx}: пользователи пишут {what} в WYSIWYG-редакторе, текст сохраняется как HTML и "
              "показывается другим пользователям через innerHTML. Как сделать это безопасно?"),
        criteria=[("sanitize", "Санитизирует allowlist-ом проверенной библиотекой (DOMPurify, "
                               "серверный санитайзер), на сервере при сохранении и/или при выводе", 0.4),
                  ("urls", "Учитывает опасные атрибуты и URL: обработчики on*, javascript:, "
                           "style, SVG/MathML, target=_blank без rel=noopener", 0.3),
                  ("layers", "Добавляет слои защиты: CSP, Trusted Types, изоляция в sandbox-iframe "
                             "или на отдельном домене, альтернатива — Markdown/AST вместо HTML", 0.3)],
        strong="""Вставлять пользовательский HTML как есть нельзя — это хранимый XSS для всех
            читателей. Санитизирую по allowlist: только нужные теги (p, a, strong, ul/li,
            img) и атрибуты, проверенной библиотекой — DOMPurify на клиенте перед innerHTML и
            серверный санитайзер при сохранении, чтобы в базе не лежал опасный HTML и
            другие клиенты (почта, мобильное приложение) были защищены. Отдельно — атрибуты
            и URL: удаляю on*-обработчики и style, разрешаю только схемы http, https, mailto
            (никакого javascript: и data: для ссылок), к ссылкам с target=_blank добавляю
            rel="noopener noreferrer", SVG и MathML запрещаю. Дополнительные слои: CSP без
            unsafe-inline и Trusted Types, чтобы innerHTML принимал только результат
            санитайзера; для особо рискованного контента — sandbox-iframe или отдельный
            домен. Ещё надёжнее хранить документ в структурированном виде (AST/Markdown) и
            рендерить его компонентами.""",
        medium="""Перед вставкой через innerHTML нужно очищать HTML библиотекой вроде DOMPurify,
            оставляя только безопасные теги и удаляя скрипты и обработчики событий.""",
        weak="""Нужно запретить пользователям вводить слово script."""),
    "oauth": dict(
        text=("{ctx}: SPA без своего бэкенда логинит пользователей через внешний OAuth 2.0 / "
              "OpenID Connect провайдер. Сейчас используется implicit flow (токен приходит во "
              "фрагменте URL). Что не так и как сделать вход правильно?"),
        criteria=[("flow", "Переходит на Authorization Code + PKCE (code_verifier/challenge S256), "
                           "объясняет проблемы implicit: токен в URL, истории, логах, Referer", 0.4),
                  ("state", "Использует state (и nonce для OIDC) против CSRF и подмены ответа, "
                            "точный redirect_uri, проверяет id_token", 0.3),
                  ("storage", "Решает хранение токенов: в памяти, короткие сроки, ротация "
                              "refresh или BFF как предпочтительный вариант", 0.3)],
        strong="""Implicit flow устарел: токен приходит во фрагменте URL и может попасть в
            историю браузера, логи, расширения и заголовок Referer, refresh-токена нет, а
            перехват ответа не обнаруживается. Правильно — Authorization Code с PKCE: клиент
            генерирует случайный code_verifier, отправляет code_challenge (S256), получает
            код на точно зарегистрированный redirect_uri и обменивает его на токены вместе с
            verifier — перехваченный код бесполезен. Обязательно параметр state, привязанный
            к сессии вкладки, против CSRF при входе, и nonce для OpenID Connect с проверкой
            подписи, aud, iss и срока id_token. Токены — в памяти, access короткий, refresh с
            ротацией; если провайдер не поддерживает ротацию для публичных клиентов — refresh
            не выдавать и использовать тихое обновление. Предпочтительный вариант для
            чувствительных данных — тонкий BFF, который хранит токены на сервере.""",
        medium="""Нужно использовать Authorization Code с PKCE вместо implicit flow, так как
            токен в URL может утечь; также проверять параметр state.""",
        weak="""Нужно зашифровать токен в URL с помощью base64."""),
    "postmessage": dict(
        text=("Фронтенд ({ctx}) встраивает виджет оплаты в iframe и общается с ним через window.postMessage: "
              "родитель слушает message и по сообщению {{type: 'paid', orderId}} помечает заказ "
              "оплаченным в интерфейсе и шлёт запрос на сервер. Какие здесь уязвимости и как "
              "организовать обмен безопасно?"),
        criteria=[("origin", "Проверяет event.origin по точному allowlist и event.source, "
                             "отправляет с конкретным targetOrigin, а не '*'", 0.4),
                  ("trust", "Не доверяет содержимому сообщения: валидирует схему, статус "
                            "оплаты подтверждает сервер (webhook от платёжного провайдера)", 0.35),
                  ("framing", "Учитывает встраивание: frame-ancestors/X-Frame-Options, sandbox и "
                              "allow для iframe, MessageChannel для выделенного канала", 0.25)],
        strong="""Сейчас любой сайт или другое окно может отправить родителю сообщение
            {{type: 'paid'}}, если обработчик не проверяет отправителя. Нужно сверять
            event.origin с точным списком доменов платёжного виджета и event.source с
            contentWindow нашего iframe, а сам родитель должен отправлять сообщения с
            конкретным targetOrigin, а не '*', иначе данные может прочитать подменённая
            страница во фрейме. Содержимое сообщения валидирую по схеме и никогда не
            вставляю в DOM как HTML. Главное: сообщение из браузера — лишь сигнал обновить
            интерфейс. Факт оплаты подтверждает сервер по webhook от провайдера или запросом
            статуса к его API, сервер не помечает заказ оплаченным по запросу клиента. Для
            iframe — атрибуты sandbox и allow по минимуму, для нашей страницы —
            frame-ancestors в CSP; для постоянного канала удобен MessageChannel с переданным
            портом.""",
        medium="""В обработчике message нужно проверять event.origin и отправлять сообщения с
            конкретным targetOrigin. Статус оплаты лучше подтверждать на сервере.""",
        weak="""Нужно передавать сообщения в JSON, а не строкой."""),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    topic = rng.choice(sorted(TOPICS))
    T = TOPICS[topic]
    ctx = rng.choice(CTX)
    vals = dict(ctx=ctx, ttl=rng.choice(["24 часа", "7 дней", "30 дней"]), n=rng.choice([5, 7, 9]),
                what=rng.choice(["отзывы", "описания вакансий", "комментарии к заказам",
                                 "статьи базы знаний"]))
    stem = T["text"].format(**vals)
    stem = stem[0].upper() + stem[1:] + " Ответ — 8–15 предложений."
    spec = {**T, "strong": T["strong"].format(**vals),
            "notes": "Оценка по критериям рубрики; эталоны — ориентиры уровня."}
    ak = AnswerKey(kind="rubric", value="rubric",
                   explanation="Открытый ответ оценивается по рубрике (сильный/средний/слабый).")
    return build_variant(FAMILY_ID, seed, stem=stem, answer_key=ak, rubric=rubric_from(spec),
                         context=ctx, verification="rubric_only", language="text",
                         params={"topic": topic})
