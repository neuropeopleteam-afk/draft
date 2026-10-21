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

from app.core.origin import NO_FSP

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SOURCES = {  # источник → файл расчёта и команда пересчёта (как на /validation)
    "bench": (DATA / "matching_bench.json", "make bench"),
    "path": (DATA / "path_retest.json", "make path-retest"),
    "report": (DATA / "report.json", "make validate"),
    # А4 (21.10): симуляция продукта (движок стенда на реальном банке) и боты через движок
    # итоговый прогон №2 (поправки №3–4): жёсткие условия, FINAL_SEEDS 4401–4410, N = 3 000, повтор и фиксированная форма
    "product": (DATA / "product_sim_final_calibrated.json", "make product-sim"),
    # стандартные условия S-T (поправка №3): заголовок; жёсткие («product») — рядом, как проверка на прочность
    "product_st": (DATA / "product_sim_st.json", "make product-sim"),
    "cheat": (DATA / "cheat_bots.json", "make cheat-bots"),
    # единый источник цифр сайта (копия docs/NUMBERS.json): подбор — отложенная проверка, тот же заголовок, что на главной
    "numbers": (DATA / "numbers.json", "make numbers"),
}
PERSONAS = {"candidate", "candidate_nofsp", "candidate_junior", "candidate_new", "employer", "expert", "fsp"}
PERSONA_TITLE = {"candidate": "кандидат с ФСП", "candidate_nofsp": "кандидат без ФСП", "candidate_new": "кандидат без категории",
                 "candidate_junior": "кандидат Junior", "employer": "работодатель", "expert": "эксперт", "fsp": "ФСП"}


def go(label: str, to: str, persona: str | None = None, need: str | None = None) -> dict:
    """Ссылка «что сделать»: to — адрес продукта (можно с #якорем); persona — вход в один клик в свою песочницу жюри
    (/jury/go), need — открыть подборку демо-потребности по фрагменту названия (у каждой песочницы свои id)."""
    return {"label": label, "to": to, "as": persona, "need": need}


def metric(src: str, path: str, label: str, fmt: str, anchor: str, ci: str | None = None,
           vs: tuple[str, ...] | None = None, note: str | None = None, pair: tuple[str, str, str] | None = None) -> dict:
    """Число из JSON расчёта: path — поле через точку («metrics.platform.p@5.mean»), ci — поле с [lo, hi] или
    префикс с .lo/.hi; vs — (подпись, поле[, формат]) для сравнения; fmt — pct, pct1, num1, num2, num3, signed3;
    pair — (подпись, источник, поле): то же число в других условиях (правило владельца: стандартные условия —
    заголовок, жёсткие — всегда рядом)."""
    return {"kind": "metric", "src": src, "path": path, "label": label, "fmt": fmt, "anchor": anchor, "ci": ci,
            "vs": vs, "note": note, "pair": pair}


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
          "limit": "Живой найм ещё не проверялся: механика проверена на модельных данных и реальных вакансиях hh.ru."},
         {"tz": "практическая применимость механики для обеих сторон",
          "do": [go("Кабинет кандидата", "/candidate", "candidate"),
                 go("Подойдёт ли предложение кандидату", "/employer/needs", "employer", need="платёжного шлюза")],
          "see": "Кандидат: вилка, индекс доверия, «почему вас выбрали». Работодатель: подборка по подтверждённым "
                 "фактам и вторая сторона — подойдёт ли предложение кандидату.",
          "proof": metric("bench", "groups.inflated.platform.irrelevant_inflated_top10",
                          "Неподходящие с раздутым резюме в топ-10", "pct1", "/validation#bench",
                          vs=("у поиска по словам резюме (BM25)", "groups.inflated.bm25.irrelevant_inflated_top10")),
          "limit": "Польза измерена на синтетическом мире; веса второй стороны заданы заранее, не обучены."},
         {"tz": "обоснованность ранжирования и объяснимость выдачи",
          "do": [go("Подборка с «почему»", "/employer/needs", "employer", need="платёжного шлюза"),
                 go("Абляции формулы", "/validation#ablations")],
          "see": "У каждого кандидата — «почему» из подтверждённых фактов (тестом или работой); абляции показывают вклад каждой "
                 "части формулы.",
          "proof": metric("bench", "paired_platform_minus.no_test.ndcg@10.mean",
                          "Вклад теста: качество порядка выдачи (nDCG@10) падает без него", "signed3", "/validation#ablations",
                          ci="paired_platform_minus.no_test.ndcg@10"),
          "limit": "Веса формулы заданы экспертно и проверены на синтетике, а не обучены на найме."},
         {"tz": "Проверяется на тестовом наборе пар «вакансия – кандидат» (доля релевантных кандидатов в топе выдачи)",
          "do": [go("Бенчмарк со скрытой истиной", "/validation#bench"),
                 go("Свой закрытый набор", "/validation#closed-set")],
          "see": "Доля релевантных в топ-5 с 95 % ДИ на отложенной проверке, рядом — жёсткие условия; свой JSON/CSV — метрики сразу, без сохранения.",
          "proof": metric("numbers", "matching.p5.mean", "Доля релевантных в топ-5 (P@5), отложенная проверка", "pct1",
                          "/validation#bench", ci="matching.p5", vs=("в жёстких условиях", "matching.hard.p5.mean")),
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
          "do": [go("«Слить» часть банка вживую", "/validation#red-button"), go("Боты против теста", "/validation#v-cheat-challenge")],
          "see": "Боты проходят настоящий тест: утечка 10 и 100 вариантов каждого задания, угадывание, «решатель без знаний».",
          "proof": metric("cheat", "table.leak_100.false_confirmed.value",
                          "Бот с утечкой 100 вариантов каждого задания: грейд подтверждён", "pct1", "/validation#v-cheat-challenge",
                          ci="table.leak_100.false_confirmed.ci95",
                          vs=("контроль — честный, но слабее заявки", "table.control.false_confirmed.value", "pct1")),
          "limit": "Боты через движок продукта, не люди; развёрнутые ответы ботов не засчитываются (оценка сверху)."},
         {"tz": "согласованность результата (даёт ли тест стабильный грейд при повторном прохождении)",
          "do": [go("Повторяемость", "/validation#headline"),
                 go("Пройти тест самому дважды", "/candidate/express", "candidate_new")],
          "see": "Две независимые попытки одного кандидата без общих семейств заданий: тот же грейд и тот же вердикт.",
          "proof": metric("product_st", "retest.kappa_w_quadratic", "согласие двух независимых попыток (взвешенная каппа)", "num3",
                          "/validation#headline",
                          vs=("тот же грейд", "retest.exact_agreement.value", "pct1"),
                          pair=("в жёстких условиях", "product", "retest.kappa_w_quadratic")),
          "limit": "Симуляция продукта: модельные кандидаты, не люди; повтор на людях — после калибровки."},
         {"tz": "дискриминативность заданий (насколько они разделяют слабых и сильных кандидатов)",
          "do": [go("D и r_pb семейств", "/validation#discrimination")],
          "see": "Индекс D и r_pb по семействам и форматам, слабые семейства с причинами.",
          "proof": metric("path", "discrimination.summary.D_mean", "Средний индекс D семейств", "num3",
                          "/validation#discrimination", vs=("средний r_pb", "discrimination.summary.r_pb_mean")),
          "limit": "Пилот симулирован по авторским параметрам; панель моделей — не люди."},
         {"tz": "соответствие результата экспертной оценке или эталонной разметке команды",
          "do": [go("Модельная панель (не люди)", "/validation#experts"), go("Разметить самому", "/expert", "expert")],
          "see": "Эталон — истинный уровень модельного кандидата: верный ли итоговый вердикт по заявке; разметка людьми — в сборе.",
          "proof": metric("product_st", "summary.verdict_accuracy_final.value", "Верный вердикт по заявке (эталон — истинный уровень)",
                          "pct1", "/validation#headline", ci="summary.verdict_accuracy_final.ci95",
                          vs=("точный грейд", "summary.exact_grade_final.value", "pct1"),
                          pair=("в жёстких условиях", "product", "summary.verdict_accuracy_final.value")),
          "limit": "Эталон — истина симуляции продукта; согласие с экспертами-людьми не измерено."},
         {"tz": "корректность категоризации кандидатов по стеку, специализации и пройденным тестам",
          "do": [go("Категории Марии", "/candidate/category", "candidate"),
                 go("Поиск по категории", "/employer/search", "employer")],
          "see": "Категория «направление · грейд» только по тесту; у Марии две специализации, у каждой свой тест.",
          "proof": metric("product_st", "summary.false_confirm_among_overclaim.value", "Ложное подтверждение у завысивших заявку",
                          "pct1", "/validation#headline", ci="summary.false_confirm_among_overclaim.ci95",
                          vs=("ложный отказ у соответствующих", "summary.false_reject_among_true.value", "pct1"),
                          pair=("в жёстких условиях", "product", "summary.false_confirm_among_overclaim.value")),
          "limit": "Симуляция продукта: модельные кандидаты, не люди."},
         {"tz": "качество предложенной командой процедуры валидации и приведённых ею результатов",
          "do": [go("Точность решения по грейду", "/validation#headline"),
                 go("Проверьте сами на движке", "/validation#self-check")],
          "see": "Симуляция самого продукта: настройки выбраны на одних зёрнах, цифры — на других; 95 % ДИ, команда пересчёта.",
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
          "see": "Палитра ФСП, Montserrat; уровни доказанности («заявлено / подтверждено тестом / подтверждено работой») цветом и словом; числа по-русски.",
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
          "do": [go("OpenAPI: запросы, ответы, коды ошибок", "/api/docs"),
                 go("Какая модель где и почему: замер", "/validation#strongest")],
          "see": ("Роли и права, согласие на ПДн, хеш паролей, ФСП ID (Keycloak); модель под каждую функцию — по "
                  "замеру качества; режим «только российская модель» (LLM_CHAIN=yandex)."),
          "proof": doc("Архитектура и трассировка требований", "docs/ARCHITECTURE.md"),
          "limit": "152-ФЗ — инженерные меры, не юридический аудит."},
         {"tz": "возможность масштабирования и интеграции с внешними системами",
          "do": [go("Передача в ATS и этап обратно", "/employer/ats#ats-stages", "employer"),
                 go("Вход через ФСП ID", "/login")],
          "see": "Адаптеры Talantix, «Поток», Хантфлоу и вебхук; ФСП ID на Keycloak; API реестра ФСП описан.",
          "proof": doc("Интеграции с ATS: протоколы и проверки", "docs/ATS.md"),
          "limit": "В демо ATS — двойники по опубликованным API; реестр ФСП на стенде модельный, протоколы — реальные."},
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
          "see": NO_FSP + ": категория и место — по тесту.",
          "proof": link("Атака «Убрать историю ФСП»: скор падает ровно на бонус", "/validation#red-button"),
          "limit": "У участников ФСП бонус в выдаче; реестр на стенде модельный, протоколы ФСП — реальные."},
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
          "limit": "Вакансии в примере — модельных компаний; импорт с hh.ru поддерживается."},
         {"tz": "регулярные короткие задания от работодателей",
          "do": [go("Адресные задания с рубрикой", "/employer/assignments", "employer"),
                 go("Кубки глазами кандидата", "/candidate/cups", "candidate")],
          "see": "«Почему это задание вам», рубрика на 100 баллов с оценкой подхода работодателем, лента раз в 7 дней; "
                 "кубки работодателя.",
          "proof": doc("Адресные задания: рубрика, расписание, права", "docs/ASSIGNMENTS.md"),
          "limit": "Результат задания — подтверждённый факт по навыку, грейд он не меняет."},
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
     "text": "Своими словами: требования с цитатами, подборка с доказанностью каждого навыка, «Что если», если подходящих мало.",
     "do": [go("Написать потребность", "/employer/needs#need", "employer"),
            go("«Что если»", "/employer/needs#what-if", "employer", need="платёжного шлюза")]},
    {"title": "Свой закрытый набор пар",
     "text": "JSON/CSV «вакансия — кандидат» с метками: точность топа (P@k) и качество порядка (nDCG) в интерфейсе, данные не сохраняются.",
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
     "do": [go("Пройти тест", "/candidate/express", "candidate_new"), go("Повторяемость", "/validation#headline")]},
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
    if src == "numbers":
        m = d.get("matching") or {}
        return {"world": f"отложенная проверка подбора: {m.get('n_needs')} потребностей, {m.get('n_worlds')} мира, один прогон",
                "seed": None, "config_hash": None, "commit": m.get("git_head") or d.get("git_commit") or "не записан",
                "command": m.get("recompute") or SOURCES[src][1], "generated_at": m.get("generated_at") or d.get("generated_at")}
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
    pair = None
    if spec.get("pair"):
        lab, psrc, ppath = spec["pair"]
        pd = _load(psrc)
        pv = _get(pd, ppath) if pd and not pd.get("missing") else None
        pair = ({"label": lab, "value": pv, "fmt": spec["fmt"], "src": psrc, "path": ppath,
                 "signature": signature(psrc, pd)} if isinstance(pv, (int, float)) else None)
    out = {"kind": "metric", "label": spec["label"], "fmt": spec["fmt"], "value": value, "ci": _ci(d, spec.get("ci")),
           "vs": vs, "note": spec.get("note"), "anchor": spec["anchor"], "src": spec["src"], "path": spec["path"],
           "signature": signature(spec["src"], d)}
    if pair:
        out["pair"] = pair
    return out


def _with_provenance(proof: dict) -> dict:
    """Я8 п. 5: у каждого доказательства — строка происхождения, как у чисел /validation (provenance.proof_stamp)."""
    from app.modules.validation.provenance import proof_stamp

    return {**proof, "provenance": proof_stamp(proof)}


def build(db=None) -> dict:
    """Ответ /api/validation/criteria и основа docs/CRITERIA.md."""
    crit = []
    for c in CRITERIA:
        items = [{"id": f"c{c['n']}-{i}", "n": f"{c['n']}.{i}", "tz": it["tz"], "do": it["do"], "see": it["see"],
                  "proof": _with_provenance(resolve(it["proof"], db)), "limit": it["limit"]}
                 for i, it in enumerate(c["items"], 1)]
        if c["n"] == 2 and _interview_on():  # Я15: ссылка на устную защиту — только при включённом флаге
            items[0]["do"] = items[0]["do"] + [INTERVIEW_GO]
        if c["n"] == 2 and _grades_ext_on():  # Я25: Lead/Principal — только при включённом флаге
            for it in items:
                if it["tz"].startswith("корректность категоризации"):
                    it["do"] = it["do"] + [GRADES_EXT_GO]
                    it["see"] = it["see"] + " " + GRADES_EXT_SEE
                    it["limit"] = it["limit"] + " " + GRADES_EXT_LIMIT
        crit.append({"id": f"c{c['n']}", "n": c["n"], "title": c["title"], "short": c["short"], "weight": c["weight"],
                     "items": items})
    _catalog_note(crit)
    return {"criteria": crit, "pitch": PITCH, "unique": UNIQUE + _voice_unique(), "how_to_read": HOW_TO_READ,
            "personas": PERSONA_TITLE, "total_weight": sum(c["weight"] for c in CRITERIA) + PITCH["weight"]}


# Я17: «Надиктовать» потребность — за флагом VOICE_NEED_ENABLED (по умолчанию выкл.), docs/VOICE.md.
VOICE_UNIQUE = {"title": "Надиктовать потребность",
                "text": "У поля «Кого вы ищете» — до 60 с голосом; текст появляется в поле, его правят и разбирают как "
                        "обычно. Запись не хранится, без согласия микрофон не включается.",
                "do": [go("Надиктовать", "/employer/needs#need", "employer")]}
VOICE_NOTE = ("Голосовой ввод потребности (флаг `VOICE_NEED_ENABLED`, по умолчанию выкл.; при включённом — пункт в "
              "«Что можно проверить только здесь»): «Надиктовать» у поля потребности, до 60 с, распознавание речи "
              "функцией движка интервью (через ретранслятор стенда); текст появляется в поле для правки, разбор — "
              "прежний и только по кнопке; ни запись, ни текст не сохраняются. Отказ микрофона, старый браузер, сбой "
              "распознавания — сообщение и ввод с клавиатуры. Механика, лимиты и проверка — `docs/VOICE.md`.")


def _voice_unique() -> list[dict]:
    from app.core.config import get_settings

    return [VOICE_UNIQUE] if getattr(get_settings(), "voice_need_enabled", False) else []


CATEGORIZATION_TZ = "корректность категоризации кандидатов по стеку, специализации и пройденным тестам"


def _catalog_note(crit: list[dict]) -> None:
    """Расширение каталога (CATALOG_EXT_ENABLED, catalog/ext.py): в пункте о категоризации — сколько направлений видно.
    Без флага или без проверенного банка текст не меняется (и docs/CRITERIA.md тоже)."""
    from app.modules.catalog import ext

    n_ext = len(ext.visible_ext())
    if not n_ext:
        return
    for c in crit:
        for it in c["items"]:
            if it["tz"] == CATEGORIZATION_TZ:
                it["see"] += f" Каталог: {5 + n_ext} направлений, новые — только с проверенным банком."


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
    from app.modules.validation.provenance import stamp_text

    pv = stamp_text(p.get("provenance"))
    return _proof_text(p) + (f". Происхождение: {pv}" if pv else "")


def _proof_text(p: dict) -> str:
    if p["kind"] == "metric":
        s = f"{p['label']}: **{fmt(p['value'], p['fmt'])}**"
        if p.get("ci"):
            s += f" (95 % ДИ {fmt(p['ci'][0], p['fmt'])} … {fmt(p['ci'][1], p['fmt'])})"
        if p.get("pair"):  # стандартные условия — заголовок, жёсткие — рядом (правило владельца 21.10)
            s += f" (стандартные условия; {p['pair']['label']} — {fmt(p['pair']['value'], p['pair'].get('fmt') or p['fmt'])})"
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


# Я15: устная защита ответов и ИИ-интервью — за флагом INTERVIEW_ENABLED (по умолчанию выкл.), docs/INTERVIEW.md.
INTERVIEW_GO = go("Устная защита ответа — по желанию", "/candidate/category#defense", "candidate")
INTERVIEW_NOTE = {
    2: ("Устная защита ответа (флаг `INTERVIEW_ENABLED`, по умолчанию выкл.; при включённом — ссылка в 2.1): по желанию "
        "кандидата ИИ-интервьюер 3 минуты спрашивает по его же развёрнутым ответам; работодатель видит «ответ подтверждён "
        "устно» или «есть расхождения» с цитатами, сверенными кодом с расшифровкой. Грейд не меняется — это сигнал против "
        "списывания и чужих ответов, оценивает модель, не люди. Механика, лимиты и проверка — `docs/INTERVIEW.md`."),
    6: ("ИИ-интервью как этап найма (тот же флаг): работодатель в принятом приглашении зовёт кандидата на 10 минут по "
        "навыкам, которые тест не подтвердил; итог и расшифровку видит только эта компания. Канал — голос или чат; на "
        "экране — своя анимация собеседника (волна голоса), без видео и лиц; `docs/INTERVIEW.md`."),
}


# Я25: Lead и Principal (флаг GRADES_EXT_ENABLED, по умолчанию выкл.; docs/GRADES_EXT.md)
GRADES_EXT_GO = go("Lead и Principal: точность по заявке", "/validation#headline")
GRADES_EXT_SEE = ("Шесть уровней: Стажёр…Senior, Lead, Principal; Lead/Principal — только полным тестом и только в "
                  "направлениях, где банк их проверяет.")
GRADES_EXT_LIMIT = ("Точность по заявке Lead и Principal — в таблице «По заявленному грейду» симуляции продукта "
                    "(/validation#headline); у спорного порога Senior+ доп. этап — разбор инцидента.")


def _grades_ext_on() -> bool:
    from app.modules.catalog import levels

    return levels.enabled()


def _interview_on() -> bool:
    from app.core.config import get_settings

    return bool(getattr(get_settings(), "interview_enabled", False))


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
        if c["n"] in INTERVIEW_NOTE:  # Я15
            out += ["", INTERVIEW_NOTE[c["n"]]]
    p = data["pitch"]
    out += ["", VOICE_NOTE]  # Я17: голосовой ввод потребности — после раздела 6 «Дополнительный функционал»
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
