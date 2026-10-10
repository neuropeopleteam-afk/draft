"""Страница /criteria «Проверьте нас по критериям ТЗ» и раздел документации docs/CRITERIA.md — из одного источника.

Здесь только связки: формулировка ТЗ (раздел 6, дословно, по подпунктам) → что сделать (глубокая ссылка в песочницу
жюри или якорь /validation) → что увидите → чем доказано → ограничение. Числа руками не пишутся: «чем доказано»
ссылается на поле JSON расчёта (те же файлы, что читает /validation: make bench, make path-retest, make validate) и
получает значение, интервал и подпись мира (seed, конфигурация, коммит) в момент запроса. Нет расчёта или поля —
нет числа, остаётся ссылка на блок. Документация собирается тем же модулем:

    python -m app.modules.validation.criteria --md ../docs/CRITERIA.md     # make criteria-doc

tests/test_criteria.py сверяет подпункты с полным текстом раздела 6, числа — с JSON расчётов, якоря и маршруты —
с исходниками фронтенда, docs/CRITERIA.md — с выводом этого модуля.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SOURCES = {  # источник → файл расчёта и команда пересчёта (как на /validation)
    "bench": (DATA / "matching_bench.json", "make bench"),
    "path": (DATA / "path_retest.json", "make path-retest"),
    "report": (DATA / "report.json", "make validate"),
}
PERSONAS = {"candidate", "candidate_nofsp", "candidate_junior", "candidate_new", "employer", "expert", "fsp"}
PERSONA_TITLE = {"candidate": "кандидат с ФСП", "candidate_nofsp": "кандидат без ФСП", "candidate_new": "кандидат без категории",
                 "candidate_junior": "кандидат Junior", "employer": "работодатель", "expert": "эксперт", "fsp": "ФСП"}


def go(label: str, to: str, persona: str | None = None, need: str | None = None) -> dict:
    """Ссылка «что сделать»: to — адрес продукта (можно с #якорем); persona — вход в один клик в свою песочницу жюри
    (/jury/go), need — открыть подборку демо-потребности по фрагменту названия (у каждой песочницы свои id)."""
    return {"label": label, "to": to, "as": persona, "need": need}


def metric(src: str, path: str, label: str, fmt: str, anchor: str, ci: str | None = None,
           vs: tuple[str, ...] | None = None, note: str | None = None) -> dict:
    """Число из JSON расчёта: path — поле через точку («metrics.platform.p@5.mean»), ci — поле с [lo, hi] или
    префикс с .lo/.hi; vs — (подпись, поле[, формат]) для сравнения; fmt — pct, pct1, num1, num2, num3, signed3."""
    return {"kind": "metric", "src": src, "path": path, "label": label, "fmt": fmt, "anchor": anchor, "ci": ci,
            "vs": vs, "note": note}


def link(label: str, anchor: str) -> dict:
    return {"kind": "link", "label": label, "anchor": anchor}


def doc(label: str, path: str) -> dict:
    return {"kind": "doc", "label": label, "path": path}


def live_sus(label: str, anchor: str) -> dict:
    return {"kind": "sus", "label": label, "anchor": anchor}


# ------------------------------------------------------------------------------------------------ раздел 6 ТЗ
# tz — полный текст критерия из ТЗ (раздел 6) без номера и веса; items[*].tz — его подпункты дословно, по порядку.
CRITERIA: list[dict] = [
    {"n": 1, "title": "Новая механика подбора", "weight": 35, "short": "Подбор",
     "tz": ("Оригинальность и работоспособность предложенного сценария выхода на контакт между работодателем и "
            "кандидатом; практическая применимость механики для обеих сторон; обоснованность ранжирования и "
            "объяснимость выдачи. Проверяется на тестовом наборе пар «вакансия – кандидат» (доля релевантных "
            "кандидатов в топе выдачи), на реальном сценарии (работодатель описывает потребность и получает подборку) "
            "и через сквозное пользовательское тестирование с участием жюри или привлечённых пользователей."),
     "items": [
         {"tz": "Оригинальность и работоспособность предложенного сценария выхода на контакт между работодателем и кандидатом",
          "do": [go("Приглашение глазами кандидата", "/candidate/invitations", "candidate_nofsp"),
                 go("Приглашения работодателя", "/employer/invitations", "employer")],
          "see": "Компания пишет первой и сразу с вилкой; вопрос до согласия — без контактов; встречная вилка; "
                 "контакты — только после «Принять».",
          "proof": doc("Сквозные e2e-сценарии: приглашение → ответ → контакты, жалоба", "docs/testing.md"),
          "limit": "Демо-компании и демо-кандидаты: на живом найме механика ещё не проверялась."},
         {"tz": "практическая применимость механики для обеих сторон",
          "do": [go("Кабинет кандидата", "/candidate", "candidate"),
                 go("Подойдёт ли предложение кандидату", "/employer/needs", "employer", need="платёжного шлюза")],
          "see": "Кандидат: вилка, индекс доверия, «почему вас выбрали». Работодатель: подборка по подтверждённым "
                 "фактам и вторая сторона — подойдёт ли предложение кандидату.",
          "proof": metric("bench", "groups.inflated.platform.irrelevant_inflated_top10",
                          "Неподходящие с раздутым резюме в топ-10", "pct1", "/validation#bench",
                          vs=("у BM25", "groups.inflated.bm25.irrelevant_inflated_top10")),
          "limit": "Польза измерена на синтетическом мире; веса второй стороны заданы заранее, не обучены."},
         {"tz": "обоснованность ранжирования и объяснимость выдачи",
          "do": [go("Подборка с «почему»", "/employer/needs", "employer", need="платёжного шлюза"),
                 go("Абляции формулы", "/validation#ablations")],
          "see": "У каждого кандидата — «почему» из подтверждённых фактов T1/T2; абляции показывают вклад каждой "
                 "части формулы.",
          "proof": metric("bench", "paired_platform_minus.no_test.ndcg@10.mean",
                          "Вклад теста: nDCG@10 падает без него", "signed3", "/validation#ablations",
                          ci="paired_platform_minus.no_test.ndcg@10"),
          "limit": "Веса формулы заданы экспертно и проверены на синтетике, а не обучены на найме."},
         {"tz": "Проверяется на тестовом наборе пар «вакансия – кандидат» (доля релевантных кандидатов в топе выдачи)",
          "do": [go("Бенчмарк со скрытой истиной", "/validation#bench"),
                 go("Свой закрытый набор", "/validation#closed-set")],
          "see": "Доля релевантных в топ-5 с 95 % ДИ против BM25; свой JSON/CSV — метрики сразу, без сохранения.",
          "proof": metric("bench", "metrics.platform.p@5.mean", "Доля релевантных в топ-5 (P@5)", "pct1",
                          "/validation#bench", ci="metrics.platform.p@5", vs=("у BM25", "metrics.bm25.p@5.mean")),
          "limit": "Истина бенчмарка — правила синтетического мира, не разметка людей."},
         {"tz": "на реальном сценарии (работодатель описывает потребность и получает подборку)",
          "do": [go("Написать свою потребность", "/employer/needs#need", "employer")],
          "see": "Требования с цитатой из вашего текста, подборка с уровнями доказанности; «Что если», когда "
                 "подходящих мало.",
          "proof": link("Тот же разбор на своём закрытом наборе", "/validation#closed-set"),
          "limit": "Без LLM разбор идёт по словарю: редкую технологию можно добавить вручную."},
         {"tz": "через сквозное пользовательское тестирование с участием жюри или привлечённых пользователей",
          "do": [go("Демо-учётки и проводник", "/#jury"), go("Анкета удобства SUS", "/sus")],
          "see": "Проводник ведёт по сквозному пути в вашей копии демо; после — короткая анкета SUS.",
          "proof": live_sus("SUS по анкетам после входа", "/sus"),
          "limit": "Анкеты людей копятся на стенде; e2e-прогоны — автоматические, не люди."},
     ]},
    {"n": 2, "title": "Механика тестирования, валидация и категоризация кандидатов", "weight": 25, "short": "Тест",
     "tz": ("Устойчивость механики к распространению заданий между кандидатами; согласованность результата (даёт ли "
            "тест стабильный грейд при повторном прохождении); дискриминативность заданий (насколько они разделяют "
            "слабых и сильных кандидатов); соответствие результата экспертной оценке или эталонной разметке команды; "
            "корректность категоризации кандидатов по стеку, специализации и пройденным тестам; качество "
            "предложенной командой процедуры валидации и приведённых ею результатов."),
     "items": [
         {"tz": "Устойчивость механики к распространению заданий между кандидатами",
          "do": [go("«Слить» часть банка вживую", "/validation#red-button"), go("Таблица утечки", "/validation#leak")],
          "see": "Атака утечкой на живом движке: детектор предзнания и карантин субпула против фиксированной формы.",
          "proof": metric("report", "simulation.asr_mean.app.leak_detector_rotation",
                          "Успех атаки при утечке 30 % вариантов: детектор + карантин", "pct1", "/validation#leak",
                          vs=("фиксированная форма", "simulation.asr_mean.app.fixed_leak")),
          "limit": "Симуляция: модель списывающих (25 % кандидатов), не люди."},
         {"tz": "согласованность результата (даёт ли тест стабильный грейд при повторном прохождении)",
          "do": [go("Весь путь дважды", "/validation#path-retest"),
                 go("Пройти тест самому дважды", "/candidate/express", "candidate_new")],
          "see": "Совпадение грейда при повторе опроса, теста и решения; ваша вторая попытка — из другого набора заданий.",
          "proof": metric("path", "total.path_grade.kappa_w", "κ с весами, повтор всего пути", "num3",
                          "/validation#path-retest", ci="total.path_grade.kappa_w_ci",
                          vs=("грейд совпал", "total.path_grade.exact", "pct1")),
          "limit": "Синтетические кандидаты (модель 2PL); повтор на людях — после калибровки."},
         {"tz": "дискриминативность заданий (насколько они разделяют слабых и сильных кандидатов)",
          "do": [go("D и r_pb семейств", "/validation#discrimination")],
          "see": "Индекс D и r_pb по семействам и форматам, слабые семейства с причинами.",
          "proof": metric("path", "discrimination.summary.D_mean", "Средний индекс D семейств", "num3",
                          "/validation#discrimination", vs=("средний r_pb", "discrimination.summary.r_pb_mean")),
          "limit": "Пилот симулирован по авторским параметрам; панель моделей — не люди."},
         {"tz": "соответствие результата экспертной оценке или эталонной разметке команды",
          "do": [go("Экспертная разметка", "/validation#experts"), go("Разметить самому", "/expert", "expert")],
          "see": "Согласие с эталоном, статус панели и кто размечал: люди или модель в ролях экспертов.",
          "proof": metric("path", "total.truth.kappa_w_true", "κ с весами: грейд против истинного", "num3",
                          "/validation#path-retest", note="эталон — истина симуляции"),
          "limit": "Эталон — истина симуляции и модельная панель; разметка людьми — в сборе."},
         {"tz": "корректность категоризации кандидатов по стеку, специализации и пройденным тестам",
          "do": [go("Категории Марии", "/candidate/category", "candidate"),
                 go("Поиск по категории", "/employer/search", "employer")],
          "see": "Категория «направление · грейд» только по тесту (T1); у Марии две специализации, у каждой свой тест.",
          "proof": metric("path", "total.truth.over_share", "Грейд выше истинного", "pct1", "/validation#path-retest",
                          vs=("ниже истинного", "total.truth.under_share")),
          "limit": "При сомнении правило даёт уровень ниже — доля «ниже истинного» заметна."},
         {"tz": "качество предложенной командой процедуры валидации и приведённых ею результатов",
          "do": [go("5 чисел с подписью мира", "/validation#headline"),
                 go("Проверьте сами на движке", "/validation#self-check")],
          "see": "Каждое число — с 95 % ДИ, seed, конфигурацией и коммитом; синтетический кандидат на настоящем движке.",
          "proof": link("Калибровка: что есть сейчас и что будет на людях", "/validation#calibration"),
          "limit": "Параметры заданий — экспертная предкалибровка; калибровка на людях — после пилота."},
     ]},
    {"n": 3, "title": "Удобство и интуитивность интерфейса", "weight": 10, "short": "Интерфейс",
     "tz": ("Понятность сквозного пользовательского пути в обоих кабинетах без дополнительных пояснений; логичная "
            "группировка блоков, читаемость, достаточный контраст; аккуратная визуальная подача решения."),
     "items": [
         {"tz": "Понятность сквозного пользовательского пути в обоих кабинетах без дополнительных пояснений",
          "do": [go("Начать как кандидат", "/register?role=candidate"),
                 go("Кабинет работодателя", "/employer", "employer")],
          "see": "Кандидат: регистрация → опрос → тест → категория → приглашения. Работодатель: потребность → "
                 "подборка → приглашение.",
          "proof": live_sus("SUS по анкетам после входа", "/sus"),
          "limit": "Проводник можно скрыть; путь без него на сторонних людях ещё не замерен."},
         {"tz": "логичная группировка блоков, читаемость, достаточный контраст",
          "do": [go("Сравнение кандидатов", "/employer/compare", "employer"),
                 go("Категория кандидата", "/candidate/category", "candidate")],
          "see": "Палитра ФСП, Montserrat; уровни T0/T1/T2 цветом и словом; числа по-русски.",
          "proof": doc("Проверка 390 px и доступности в e2e", "docs/testing.md"),
          "limit": "Контраст проверен на ключевых экранах, не на каждом."},
         {"tz": "аккуратная визуальная подача решения",
          "do": [go("Главная", "/"), go("Демонстрация в зале", "/jury/live")],
          "see": "Единый стиль экранов: главное сверху, подробности — по ссылке.",
          "proof": link("Тот же стиль на /validation", "/validation#headline"),
          "limit": "Оценка вкусовая — проверьте сами на 1440 и 390 px."},
     ]},
    {"n": 4, "title": "Техническая проработка решения", "weight": 7, "short": "Техника",
     "tz": ("Качество кода, работоспособность прототипа, скорость работы, соответствие архитектурным требованиям, "
            "возможность масштабирования и интеграции с внешними системами."),
     "items": [
         {"tz": "Качество кода",
          "do": [go("Документация API", "/api/docs")],
          "see": "FastAPI + React, модули по доменам, комментарии у сложных мест; матрица прав по всем маршрутам.",
          "proof": doc("pytest, e2e, покрытие и матрица прав", "docs/testing.md"),
          "limit": "Код — по ссылке на репозиторий из материалов сдачи."},
         {"tz": "работоспособность прототипа",
          "do": [go("Войти как кандидат", "/candidate", "candidate"), go("Статус сервиса", "/api/health")],
          "see": "У каждого эксперта своя копия демо; «Сбросить своё демо» пересоздаёт её за секунды.",
          "proof": doc("Запуск одной командой и локальный стек", "README.md"),
          "limit": "Стенд один; при сбое — локальный запуск по README."},
         {"tz": "скорость работы",
          "do": [go("Открыть подборку", "/employer/needs", "employer", need="платёжного шлюза")],
          "see": "Подборка, профиль и поиск открываются без заметного ожидания; разбор без LLM — сразу.",
          "proof": doc("Нагрузочный тест Locust: условия и результаты", "docs/LOAD_TEST.md"),
          "limit": "Нагрузка мерилась на более ранней версии; время LLM зависит от провайдера."},
         {"tz": "соответствие архитектурным требованиям",
          "do": [go("OpenAPI: запросы, ответы, коды ошибок", "/api/docs")],
          "see": "Роли и права, согласие на обработку данных, хеш паролей, вход через ФСП ID (Keycloak).",
          "proof": doc("Архитектура и трассировка требований", "docs/ARCHITECTURE.md"),
          "limit": "152-ФЗ — инженерные меры, не юридический аудит."},
         {"tz": "возможность масштабирования и интеграции с внешними системами",
          "do": [go("Передача в ATS и этап обратно", "/employer/ats#ats-stages", "employer"),
                 go("Вход через ФСП ID", "/login")],
          "see": "Адаптеры Talantix, «Поток», Хантфлоу и вебхук; ФСП ID на Keycloak; API реестра ФСП описан.",
          "proof": doc("Интеграции с ATS: протоколы и проверки", "docs/ATS.md"),
          "limit": "В демо ATS — двойники по опубликованным API; реестр ФСП — модельные данные."},
     ]},
    {"n": 5, "title": "Полнота реализации и сопроводительная документация", "weight": 6, "short": "Полнота",
     "tz": ("Реализация обязательных этапов пути пользователя-соискателя, корректная обработка профиля кандидата без "
            "истории ФСП, соответствие функциональным требованиям, полнота и качество документации."),
     "items": [
         {"tz": "Реализация обязательных этапов пути пользователя-соискателя",
          "do": [go("Регистрация", "/register?role=candidate"),
                 go("Тест до категории", "/candidate/express", "candidate_new")],
          "see": "Регистрация с кодом → опрос → выбор грейда → тест → категория → поиск работодателем → приглашение.",
          "proof": doc("e2e: путь кандидата и экспресс-тест жюри", "docs/testing.md"),
          "limit": "Демо-учётки регистрацию уже прошли — её можно пройти самому."},
         {"tz": "корректная обработка профиля кандидата без истории ФСП",
          "do": [go("Кандидат без ФСП", "/candidate/category", "candidate_nofsp"),
                 go("Атака «Убрать историю ФСП»", "/validation#red-button")],
          "see": "Нет истории ФСП — нейтрально: категория и место по тесту, без штрафа.",
          "proof": link("Атака «Убрать историю ФСП»: скор падает ровно на бонус", "/validation#red-button"),
          "limit": "У участников ФСП бонус в выдаче, у остальных его нет; реестр — модельные данные."},
         {"tz": "соответствие функциональным требованиям",
          "do": [go("Проводник по сценарию ТЗ", "/#jury")],
          "see": "Каждый этап п. 3.3 ТЗ — шаг проводника и экран продукта.",
          "proof": doc("Функциональная архитектура", "docs/ARCHITECTURE.md"),
          "limit": "Реестр и API ФСП не выданы — работаем на своих тестовых данных."},
         {"tz": "полнота и качество документации",
          "do": [go("Документация API", "/api/docs"), go("Как мы проверяем себя", "/validation")],
          "see": "README, OpenAPI, документы по модулям; эта таблица — в docs/CRITERIA.md.",
          "proof": doc("Критерий → что показываем → чем доказано", "docs/CRITERIA.md"),
          "limit": "Числа в документе — снимок; актуальные — на этой странице и /validation."},
     ]},
    {"n": 6, "title": "Дополнительный функционал", "weight": 7, "short": "Доп. функции",
     "tz": ("Начисляется за реализацию необязательных для MVP возможностей: самостоятельный отклик кандидата на "
            "открытые вакансии и публикация вакансий работодателем (сценарий, при котором кандидат, пока не "
            "получивший приглашений, сохраняет возможность проявить инициативу); регулярные короткие задания от "
            "работодателей; проработанная концепция защиты от фиктивных вакансий и интеграции с ATS; адаптивная "
            "версия для мобильных устройств."),
     "items": [
         {"tz": ("самостоятельный отклик кандидата на открытые вакансии и публикация вакансий работодателем (сценарий, "
                 "при котором кандидат, пока не получивший приглашений, сохраняет возможность проявить инициативу)"),
          "do": [go("Откликнуться на вакансию", "/candidate/vacancies", "candidate_nofsp"),
                 go("Опубликовать вакансию", "/employer/vacancies", "employer")],
          "see": "Открытые вакансии с вилкой и индексом доверия; отклик, статус и переписка.",
          "proof": doc("Вакансии и отклики: маршруты API", "docs/ARCHITECTURE.md"),
          "limit": "Вакансии — демо-компаний."},
         {"tz": "регулярные короткие задания от работодателей",
          "do": [go("Адресные задания с рубрикой", "/employer/assignments", "employer"),
                 go("Кубки глазами кандидата", "/candidate/cups", "candidate")],
          "see": "«Почему это задание вам», рубрика на 100 баллов с оценкой подхода работодателем, лента раз в 7 дней; "
                 "кубки работодателя.",
          "proof": doc("Адресные задания: рубрика, расписание, права", "docs/ASSIGNMENTS.md"),
          "limit": "Результат задания — факт T1 по навыку, грейд он не меняет."},
         {"tz": "проработанная концепция защиты от фиктивных вакансий и интеграции с ATS",
          "do": [go("Пожаловаться на приглашение", "/candidate/invitations", "candidate_nofsp"),
                 go("Журнал передач в ATS", "/employer/ats", "employer")],
          "see": "Индекс доверия по ЕГРЮЛ и жалобам, вилка обязательна; передача в ATS и этап обратно.",
          "proof": doc("Антифрод работодателя: индекс доверия", "docs/ANTIFRAUD.md"),
          "limit": "ЕГРЮЛ — открытый сервис без гарантий; ATS в демо — двойники API."},
         {"tz": "адаптивная версия для мобильных устройств",
          "do": [go("QR: открыть на телефоне", "/jury/live"), go("Установить приложение", "/install")],
          "see": "Экраны на 390 px без горизонтальной прокрутки; приложение на экран «Домой» с push.",
          "proof": doc("e2e на 390 px: снимки ключевых экранов", "docs/testing.md"),
          "limit": "Проверено в Chromium на 390 px; iPhone — push после «На экран Домой»."},
     ]},
]
PITCH = {"n": 7, "title": "Презентация и выступление коллектива на питч-сессии", "weight": 10,
         "tz": ("Ясность изложения идеи и предложенных механик, качество демонстрации решения, обоснованность принятых "
                "решений и ответы на вопросы жюри. Учитывается только при финальной экспертизе.")}

# ------------------------------------------------------------------------- «Что можно проверить только здесь»
UNIQUE: list[dict] = [
    {"title": "Своя потребность → подборка",
     "text": "Своими словами: требования с цитатами, подборка с доказанностью T0/T1/T2, «Что если», если подходящих мало.",
     "do": [go("Написать потребность", "/employer/needs#need", "employer"),
            go("«Что если»", "/employer/needs#what-if", "employer", need="платёжного шлюза")]},
    {"title": "Свой закрытый набор пар",
     "text": "JSON/CSV «вакансия — кандидат» с метками: P@k и nDCG в интерфейсе, данные не сохраняются.",
     "do": [go("Загрузить набор", "/validation#closed-set")]},
    {"title": "Вопрос → приглашение → встречное → контакты",
     "text": "Анонимный вопрос с маскированием контактов, приглашение с вилкой, встречная вилка, контакты после согласия.",
     "do": [go("Как кандидат", "/candidate/invitations", "candidate_nofsp"),
            go("Как работодатель", "/employer/invitations", "employer")]},
    {"title": "Передача в ATS «Поток» и этап обратно",
     "text": "Принятый кандидат уходит в ATS по её API; переведите его на «Интервью» — этап вернётся к обеим сторонам.",
     "note": "В демо — двойник «Потока» по опубликованной спецификации API v3; с токеном компании адаптер тот же.",
     "do": [go("Этапы из «Потока»", "/employer/ats#ats-stages", "employer")]},
    {"title": "QR-демо в зале",
     "text": "Телефон → мини-тест из банка без регистрации → категория → приглашение с вилкой.",
     "do": [go("Открыть QR", "/jury/live")]},
    {"title": "Красная кнопка",
     "text": "Атакуйте сами: слейте часть банка, раздуйте резюме, смените пол и возраст — на живых данных.",
     "do": [go("Атаковать", "/validation#red-button")]},
    {"title": "Повтор теста и сравнение попыток",
     "text": "Пройдите экспресс-тест дважды: вторая попытка — из другого набора заданий; история — в «Категории».",
     "do": [go("Пройти тест", "/candidate/express", "candidate_new"), go("Весь путь дважды", "/validation#path-retest")]},
    {"title": "Камера по согласию",
     "text": "Перед тестом — выбор «с камерой» или «без»; кадры разбираются в браузере, наружу — только события.",
     "do": [go("Экран выбора", "/candidate/express", "candidate_new")]},
]

HOW_TO_READ = ("Формулировки — раздел 6 ТЗ дословно, по подпунктам. «Что сделать» — 1–2 клика: вход в вашу копию демо "
               "или блок /validation. Числа — из тех же расчётов, что на /validation, с подписью мира и коммита; "
               "нет расчёта — нет числа.")


# ------------------------------------------------------------------------------------------------- расчёты
_cache: dict[str, tuple[float, Any]] = {}


def _load(src: str) -> dict | None:
    """JSON расчёта с кэшем по времени изменения файла (пересчёт make … подхватывается без перезапуска)."""
    path = SOURCES[src][0]
    try:
        mt = path.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(src)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    _cache[src] = (mt, d)
    return d


def _get(d: Any, path: str) -> Any:
    """Поле по пути через точку; ключи с точкой внутри («p@5», «ndcg@10») — без разбиения."""
    cur = d
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _ci(d: dict, path: str | None) -> list[float] | None:
    if not path:
        return None
    v = _get(d, path)
    if isinstance(v, list) and len(v) == 2:
        return v
    if isinstance(v, dict) and "lo" in v and "hi" in v:
        return [v["lo"], v["hi"]]
    return None


def signature(src: str, d: dict) -> dict:
    """Подпись мира числа: у бенчмарка и повтора пути — своя (signature в JSON), у отчёта make validate её нет —
    собираем из полей отчёта, коммит честно «не записан»."""
    if src == "bench":
        from app.modules.validation.headline import _bench_signature
        return _bench_signature(d)
    if d.get("signature"):
        return d["signature"]
    sim = d.get("simulation") or {}
    return {"world": f"симуляция теста: {len(sim.get('directions') or {})} направлений × {d.get('n_per_direction')} "
                     "кандидатов", "seed": None, "config_hash": None, "commit": d.get("commit") or "не записан",
            "command": SOURCES[src][1], "generated_at": d.get("generated_at")}


def _sus(db) -> dict | None:
    """Живые анкеты SUS этого стенда (публичный /api/sus/summary): среднее, n, ДИ. Нет анкет — None."""
    if db is None:
        return None
    try:
        from app.integrations.sus.router import summary
        s = summary(True, db)
    except Exception:  # noqa: BLE001 — нет таблицы/модуля: остаётся ссылка на анкету
        return None
    return s if s.get("n") else None


def _ru_date(iso: str | None) -> str | None:
    """ISO-время → «05.10.2026» по Москве (дата последней анкеты в подписи SUS)."""
    if not iso:
        return None
    from datetime import datetime, timedelta, timezone

    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y")


def resolve(spec: dict, db=None) -> dict:
    """«Чем доказано» → значение с интервалом и подписью или ссылка (нет расчёта — нет числа)."""
    kind = spec["kind"]
    if kind in ("link", "doc"):
        return dict(spec)
    if kind == "sus":
        if db is None:  # документация: живые данные стенда в снимок не попадают
            return {"kind": "link", "label": "Анкета SUS: среднее и n — живые данные стенда", "anchor": spec["anchor"]}
        s = _sus(db)
        if not s:
            return {"kind": "link", "label": "Анкета SUS: ответов на этом стенде пока нет", "anchor": spec["anchor"],
                    "missing": True}
        if not s.get("enough", s["n"] >= 5):  # n < 5: число не результат, только «недостаточно ответов» с датой
            when = _ru_date(s.get("updated_at"))
            return {"kind": "link", "label": f"Анкета SUS: пока недостаточно ответов (n = {s['n']}{', на ' + when if when else ''})"
                    " — балл не показываем", "anchor": spec["anchor"], "missing": True}
        return {"kind": "metric", "label": spec["label"], "fmt": "num1", "value": s["mean"], "ci": s.get("ci95"),
                "vs": {"label": "среднее по отрасли", "value": s.get("benchmark"), "fmt": "num1"}, "anchor": spec["anchor"],
                "note": "из 100; живые данные этого стенда, демо-учётки жюри включены"
                        + (f" (их ответов {s['demo_n']}: в т. ч. автотесты и модельные персоны — модель, не люди)"
                           if s.get("demo_n") else ""),
                "signature": {"world": "живые анкеты этого стенда", "n": s["n"], "generated_at": s.get("updated_at")}}
    d = _load(spec["src"])
    value = _get(d, spec["path"]) if d else None
    if d is None or d.get("missing") or not isinstance(value, (int, float)):
        return {"kind": "link", "label": f"{spec['label']} — не посчитано ({SOURCES[spec['src']][1]})",
                "anchor": spec["anchor"], "missing": True}
    vs = None
    if spec.get("vs"):
        v = _get(d, spec["vs"][1])
        vs = ({"label": spec["vs"][0], "value": v, "fmt": spec["vs"][2] if len(spec["vs"]) > 2 else spec["fmt"]}
              if isinstance(v, (int, float)) else None)
    return {"kind": "metric", "label": spec["label"], "fmt": spec["fmt"], "value": value, "ci": _ci(d, spec.get("ci")),
            "vs": vs, "note": spec.get("note"), "anchor": spec["anchor"], "src": spec["src"], "path": spec["path"],
            "signature": signature(spec["src"], d)}


def build(db=None) -> dict:
    """Ответ /api/validation/criteria и основа docs/CRITERIA.md."""
    crit = []
    for c in CRITERIA:
        items = [{"id": f"c{c['n']}-{i}", "n": f"{c['n']}.{i}", "tz": it["tz"], "do": it["do"], "see": it["see"],
                  "proof": resolve(it["proof"], db), "limit": it["limit"]}
                 for i, it in enumerate(c["items"], 1)]
        crit.append({"id": f"c{c['n']}", "n": c["n"], "title": c["title"], "short": c["short"], "weight": c["weight"],
                     "items": items})
    return {"criteria": crit, "pitch": PITCH, "unique": UNIQUE, "how_to_read": HOW_TO_READ,
            "personas": PERSONA_TITLE, "total_weight": sum(c["weight"] for c in CRITERIA) + PITCH["weight"]}


def all_links(data: dict | None = None) -> list[dict]:
    """Все ссылки «что сделать» страницы (для тестов и e2e)."""
    data = data or {"criteria": [{"items": c["items"]} for c in CRITERIA], "unique": UNIQUE}
    out = [g for c in data["criteria"] for it in c["items"] for g in it["do"]]
    out += [g for u in data["unique"] for g in u["do"]]
    return out


# ------------------------------------------------------------------------------------------- docs/CRITERIA.md
def fmt(v: float | None, f: str) -> str:
    """Числа по-русски, как на странице (components/ui.tsx: num, pct, signed)."""
    if v is None:
        return "—"
    if f.startswith("pct"):
        d = 1 if f == "pct1" else 0
        return f"{v * 100:.{d}f}".replace(".", ",") + "\u00a0%"
    d = {"num1": 1, "num2": 2, "num3": 3, "signed3": 3}[f]
    s = f"{abs(v):.{d}f}".replace(".", ",")
    return ("+" if f.startswith("signed") and v > 0 else "−" if v < 0 else "") + s


def proof_text(p: dict) -> str:
    if p["kind"] == "metric":
        s = f"{p['label']}: **{fmt(p['value'], p['fmt'])}**"
        if p.get("ci"):
            s += f" (95 % ДИ {fmt(p['ci'][0], p['fmt'])} … {fmt(p['ci'][1], p['fmt'])})"
        if p.get("vs"):
            s += f"; {p['vs']['label']} — {fmt(p['vs']['value'], p['vs'].get('fmt') or p['fmt'])}"
        if p.get("note"):
            s += f"; {p['note']}"
        sig = p.get("signature") or {}
        known = sig.get("commit") not in (None, "", "unknown", "не записан")
        parts = [sig.get("world")] + ([f"seed {sig['seed']}"] if sig.get("seed") is not None else []) + \
            [f"коммит `{sig['commit']}`" if known else "коммит не записан"] + \
            ([f"расчёт {sig['generated_at'][:10]}"] if sig.get("generated_at") else [])
        return s + ". Мир: " + ", ".join(x for x in parts if x) + f". Блок: `{p['anchor']}`"
    if p["kind"] == "doc":
        return f"{p['label']} — `{p['path']}`"
    return f"{p['label']} — `{p['anchor']}`"


def _do_text(g: dict) -> str:
    who = f" (вход: {PERSONA_TITLE[g['as']]})" if g.get("as") else ""
    need = f", потребность «…{g['need']}…»" if g.get("need") else ""
    return f"{g['label']} — `{g['to']}`{who}{need}"


def markdown(data: dict | None = None) -> str:
    """docs/CRITERIA.md: «Критерий → что показываем → чем доказано». Числа — из build() на момент генерации; живые
    данные стенда (SUS) в документ не попадают — только ссылка."""
    data = data or build()
    out = ["# Критерии ТЗ → что показываем → чем доказано", "",
           "Сгенерировано `make criteria-doc` (`python -m app.modules.validation.criteria --md`) из того же источника, "
           "что страница `/criteria` (`GET /api/validation/criteria`). Не править руками: числа берутся из JSON "
           "расчётов `/validation` (make bench, make path-retest, make validate) вместе с подписью мира.", "",
           data["how_to_read"], "", "## Что можно проверить только здесь", ""]
    for u in data["unique"]:
        out.append(f"- **{u['title']}.** {u['text']} " + "; ".join(_do_text(g) for g in u["do"]) + "."
                   + (f" {u['note']}" if u.get("note") else ""))
    for c in data["criteria"]:
        out += ["", f"## {c['n']}. {c['title']} — {c['weight']} %", "",
                "| № | Формулировка ТЗ | Что сделать | Что увидите | Чем доказано | Ограничение |",
                "|---|---|---|---|---|---|"]
        for it in c["items"]:
            out.append("| " + " | ".join([it["n"], f"«{it['tz']}»", "<br>".join(_do_text(g) for g in it["do"]),
                                          it["see"], proof_text(it["proof"]), it["limit"]]).replace("\n", " ") + " |")
    p = data["pitch"]
    out += ["", f"## {p['n']}. {p['title']} — {p['weight']} %", "", f"«{p['tz']}» В продукте не проверяется.", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--md", type=Path, help="записать docs/CRITERIA.md")
    a = ap.parse_args()
    text = markdown()
    if a.md:
        a.md.write_text(text, encoding="utf-8")
        print(f"записано: {a.md}")
    else:
        print(text)


if __name__ == "__main__":
    main()
