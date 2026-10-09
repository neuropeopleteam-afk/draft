"""П1: вырезание ПДн до отправки в модель — адреса, дата рождения без подписи и возраст в шапке, имена латиницей,
одиночное имя рядом с контактом; ложные срабатывания (словарь стека, «ул.»/«д.»/«пр.» в тексте задач, «Гибрид»).

Все данные синтетические: имена, адреса, телефоны и даты выдуманы для теста.
"""
from __future__ import annotations

import re

import pytest

from app.modules.resume.pii import redact


def _vac(text: str):  # как в need_parser._merge_llm
    return redact(text, use_ner=True, ner_min_tokens=2, contact_cues=True, header=False)


def _answer(text: str):  # как в assessment.grader
    return redact(text, use_ner=True, header=False)


# ------------------------------------------------------------------ 1. адреса
@pytest.mark.parametrize("line, secret, keep", [
    ("г. Москва, ул. Тверская, д. 7, корп. 2, кв. 15", ["Тверская", "кв. 15", "корп. 2"], ["г. Москва"]),
    ("Москва, ул. Ленина 5-3", ["Ленина", "5-3"], ["Москва"]),
    ("Казань, улица Баумана, дом 12, квартира 4", ["Баумана", "квартира 4"], ["Казань"]),
    ("Санкт-Петербург, Невский пр-т, 28, оф. 301", ["Невский", "оф. 301"], ["Санкт-Петербург"]),
    ("Москва, Ленинский проспект, 45", ["Ленинский", "45"], ["Москва"]),
    ("Москва, проспект Вернадского, 86, стр. 2", ["Вернадского", "86"], ["Москва"]),
    ("Москва, пер. Сивцев Вражек, 3", ["Сивцев", "Вражек"], ["Москва"]),
    ("Москва, Пресненская наб., 12, офис 4501", ["Пресненская", "4501"], ["Москва"]),
    ("Москва, Варшавское ш., 9", ["Варшавское", ", 9"], ["Москва"]),
    ("Москва, Дмитровское шоссе, 9Б", ["Дмитровское", "9Б"], ["Москва"]),
    ("Новосибирск, б-р Молодёжи, 15", ["Молодёжи"], ["Новосибирск"]),
    ("Екатеринбург, ул. 8 Марта, 51", ["8 Марта", "51"], ["Екатеринбург"]),
    ("Москва, ул. 1-я Тверская-Ямская, д. 21", ["Тверская-Ямская"], ["Москва"]),
    ("Пермь, д. 5, кв. 3", ["д. 5", "кв. 3"], ["Пермь"]),
    ("Индекс: 101000", ["101000"], []),
    ("101000, г. Москва, ул. Маросейка, 2", ["101000", "Маросейка"], ["г. Москва"]),
    ("Россия, 420111, Казань, ул. Кремлёвская, 18", ["420111", "Кремлёвская"], ["Казань"]),
    ("Адрес: Москва, Ленина 5-3", ["Ленина", "5-3"], ["Москва"]),
    ("Адрес проживания: Томск, Ленина 5, кв. 7", ["Ленина 5", "кв. 7"], ["Томск"]),
    ("Проживает: Москва, м. Тверская", ["м. Тверская"], ["Москва"]),
    ("Moscow, ul. Tverskaya, 7, apt. 15", ["Tverskaya", "apt. 15"], ["Moscow"]),
    ("Kazan, Baumana Street 12, apt. 4", ["Baumana", "apt. 4"], ["Kazan"]),
    ("221B Baker Street, London", ["Baker"], ["London"]),
])
def test_address_variants(line, secret, keep):
    for fn in (redact, _vac, _answer):
        r = fn(f"Python-разработчик\n{line}\nОпыт: FastAPI, PostgreSQL.")
        for s in secret:
            assert s not in r.text, (fn.__name__, s, r.text)
        for k in keep:
            assert k in r.text, (fn.__name__, k, r.text)
        assert "[адрес]" in r.text and r.summary.get("address"), r.text
        assert "FastAPI, PostgreSQL" in r.text


@pytest.mark.parametrize("text", [
    "Задачи: разработка API, ревью кода, документация и пр.",
    "Логи, метрики, трассировки и т. д. Покрытие тестами 80 %.",
    "пр. — прочее; см. п. 3.2, стр. 15 документации.",
    "Отчёт за 2 кв. 2024 года, площадь покрытия 90 %.",
    "Д. Кнут, «Искусство программирования», т. 1.",
    "Компенсация проезда и питания, бесплатный проезд 5 дней в месяц.",
    "def street(row):\n    return row['ул.'] + ', д.' + str(row['дом'])  # ул. и д. — ключи словаря",
    "Красная площадь видна из офиса; Ленинградский вокзал рядом.",
    "Зарплата 150000, Москва, гибрид; от 200000 на руки.",
    "Опыт от 3 лет, 5 лет коммерческой разработки, 10 лет в ИТ.",
    "SELECT * FROM users WHERE age > 18 AND city = 'Москва';",
    "Wall Street experience; St. Petersburg, 5 years of Java; Main Street Bank.",
])
def test_address_and_age_false_positives(text):
    for fn in (redact, _vac, _answer):
        r = fn(text)
        assert "[адрес]" not in r.text and "[возраст]" not in r.text and "[дата]" not in r.text, (fn.__name__, r.text)


def test_city_kept_for_matching():
    from app.modules.matching.need_parser import parse_rules

    text = ("Backend-разработчик Python, гибрид, офис в Москве: ул. Льва Толстого, 16. Опыт от 3 лет, FastAPI, "
            "PostgreSQL, Docker. Зарплата 250–320 тыс. ₽")
    red = _vac(text).text
    assert "Льва Толстого" not in red and "Москве" in red
    a, b = parse_rules(text), parse_rules(red)
    for k in ("direction", "experience_years_min", "work_format", "city", "salary_from", "salary_to"):
        assert a.get(k) == b.get(k), k
    assert {i["tag"] for i in a["stack_required"]} == {i["tag"] for i in b["stack_required"]}


# ------------------------------------------------------------------ 2. дата рождения без подписи и возраст в шапке
HH_HEAD = """Смирнова Анна Викторовна
Женщина, 34 года, родилась 15 марта 1990
15.03.1990
Москва, готова к переезду
Желаемая должность: Frontend-разработчик
Опыт работы — 7 лет 2 месяца
Март 2020 — настоящее время (4 года 7 месяцев)
ООО «Пример»: React, TypeScript, Next.js
Сентябрь 2017 — Февраль 2020
01.09.2008 — 30.06.2012 МГТУ
"""


def test_header_birthdate_and_age():
    r = redact(HH_HEAD)
    for s in ("15.03.1990", "15 марта 1990", "34 года", "Женщина", "Смирнова", "Анна"):
        assert s not in r.text, (s, r.text)
    assert "[дата]" in r.text and "[возраст]" in r.text and "[пол]" in r.text
    # периоды и стаж — на месте
    for s in ("7 лет 2 месяца", "Март 2020 — настоящее время", "Сентябрь 2017 — Февраль 2020", "01.09.2008 — 30.06.2012"):
        assert s in r.text, (s, r.text)
    assert {"birthdate", "age", "gender"} <= set(r.summary)


@pytest.mark.parametrize("line", ["Дата рождения: 15.03.1990", "Дата рождения: 15 марта 1990 г.", "д.р. 01.02.95",
                                  "Date of birth: March 15, 1990", "Born 15 March 1990", "Родился 3 мая 1988 года"])
def test_birthdate_with_label_anywhere(line):
    for fn in (redact, _vac, _answer):
        r = fn(f"Опыт 3 года, Python.\n{line}")
        assert not re.search(r"19\d\d|\b95\b", r.text), (fn.__name__, r.text)


@pytest.mark.parametrize("text", ["Мне 25 лет, ищу стажировку", "Возраст: 41", "Age: 29, Python", "29 y.o. developer",
                                  "29 years old, Python developer"])
def test_age_with_cue_anywhere(text):
    for fn in (redact, _vac, _answer):
        r = fn(text)
        assert "[возраст]" in r.text and not re.search(r"\b(25|41|29)\b", r.text), (fn.__name__, r.text)


def test_header_rules_only_for_resume():
    code = "Ответ: дата 15.03.1990 парсится как date(1990, 3, 15); 34 года — это int."
    assert "15.03.1990" in _answer(code).text and "34 года" in _answer(code).text
    assert "15.03.1990" in _vac("Вакансия от 15.03.1990").text


RESUMES = [
    HH_HEAD,
    "Ivan Petrov\nSenior Backend Developer\nMale, 35 years old\nMoscow, ул. Тверская, д. 7, кв. 15\n12.04.1989\n"
    "ivan.petrov@example.com, +7 999 000-11-22\nОпыт работы 8 лет: Java, Spring Boot, Apache Kafka, PostgreSQL\n"
    "2016–2024 ООО «Банк»; 03.2024 — н. в. ООО «Маркет»\nBest regards, Ivan Petrov",
    "Кузнецов Дмитрий\nQA-инженер, 27 лет\nСанкт-Петербург, Невский пр-т, 28, кв. 4\nАвтотесты: Python, pytest, Selenium, "
    "Playwright, Allure, Docker\nМай 2019 — н. в. (5 лет 5 месяцев)",
    "Petrova Maria Sergeevna\nData Scientist\n420111, Казань, ул. Кремлёвская, 18\nДата рождения: 02.02.1996\n"
    "Опыт 3 года: Python, pandas, scikit-learn, PyTorch, SQL, Airflow\n2021–2024 — ML-инженер",
]


@pytest.mark.parametrize("text", RESUMES)
def test_resume_parse_unchanged(text):
    from app.modules.resume.extract import experience_years, extract_rules

    red = redact(text).text
    a, b = extract_rules(text), extract_rules(red)
    assert experience_years(text) == experience_years(red)
    assert [s["tag"] for s in a["stack"]] == [s["tag"] for s in b["stack"]], (a["stack"], b["stack"])
    assert a["roles"] == b["roles"] and a["grade_hint"] == b["grade_hint"] and a["direction_hint"] == b["direction_hint"]
    assert a["soft_skills"] == b["soft_skills"]


def test_ner_single_word_without_name_signs_is_kept():
    """NER принимал «Автотесты:» в начале строки за имя — слово пропадало из разбора (направление QA)."""
    r = redact("Кузнецов Дмитрий\nQA-инженер\nАвтотесты: Python, pytest, Selenium\nДмитрий — автор доклада.")
    assert "Автотесты" in r.text and "Кузнецов" not in r.text and "Дмитрий" not in r.text


# ------------------------------------------------------------------ 3. имена латиницей
@pytest.mark.parametrize("text, secret", [
    ("Ivan Petrov\nSenior Backend Developer", ["Ivan", "Petrov"]),
    ("Petrov Ivan\nPython Developer", ["Ivan", "Petrov"]),
    ("IVAN PETROV\nJava Developer", ["IVAN", "PETROV"]),
    ("Резюме\nPetrova Maria Sergeevna\nData Scientist", ["Petrova", "Maria", "Sergeevna"]),
    ("Ivan Sergeevich Petrov — Senior Developer", ["Ivan", "Sergeevich", "Petrov"]),
    ("Python Developer\nAleksandr Smirnov, Team Lead", ["Aleksandr", "Smirnov"]),
    ("Dmitriy Kuznetsov, Senior QA Engineer", ["Dmitriy", "Kuznetsov"]),
    ("Опыт: React. Автор доклада — Yulia Sokolova, Frontend Lead.", ["Yulia", "Sokolova"]),
    ("Timur Bekmambetov\nBackend Developer", ["Timur", "Bekmambetov"]),
    ("Backend Developer\nSkills: Go, Kafka\nBest regards,\nEvgeniy Orlov", ["Evgeniy", "Orlov"]),
    ("Code review — спасибо. Regards, Ksenia", ["Ksenia"]),
])
def test_latin_names(text, secret):
    for fn in (redact, _vac, _answer):
        r = fn(text)
        for s in secret:
            assert not re.search(rf"(?<!\w){s}(?!\w)", r.text), (fn.__name__, s, r.text)


def _stack_terms() -> list[str]:
    from app.modules.catalog.dictionary import STACK_ALIASES, UNSUPPORTED_TECH
    from app.modules.catalog.seed_data import STACK

    terms = set(UNSUPPORTED_TECH) | {t[0] for t in STACK.values()}
    for aliases in [*STACK_ALIASES.values(), *UNSUPPORTED_TECH.values()]:
        for a in aliases:
            a = a.strip()
            if re.fullmatch(r"[a-z][a-z0-9.+#/ \-]*", a):  # латиница: как пишут в резюме — с заглавных
                terms.add(" ".join(w[:1].upper() + w[1:] for w in a.split()))
    terms |= {"Spring Boot", "React Native", "Apache Kafka", "Apache Spark", "Power BI", "GitHub Actions", "GitLab CI",
              "Visual Studio Code", "IntelliJ IDEA", "Yandex Cloud", "Google Cloud", "Jetpack Compose", "Active Directory",
              "Cobalt Strike", "Burp Suite", "Spring Cloud", "Spring Security", "Spring Data", "Node.js", "Vue.js"}
    return sorted(terms)


def test_stack_dictionary_is_not_cut():
    """Каждый термин словаря стека — отдельной строкой в шапке и в тексте рядом с именем — остаётся на месте."""
    terms = _stack_terms()
    assert len(terms) > 250
    bad = []
    for i in range(0, len(terms), 12):
        chunk = terms[i:i + 12]
        lines = "\n".join(chunk[:4])
        text = (f"Ivan Petrov\n{lines}\nСтек: " + ", ".join(chunk) + ".\n" +
                " ".join(f"Работал с {t} и {u} в команде." for t, u in zip(chunk, chunk[1:] + chunk[:1])) +
                "\nBest regards, Ivan Petrov")
        for fn in (redact, _vac, _answer):
            out = fn(text).text
            assert "Petrov" not in out
            for t in chunk:
                if out.count(t) < text.count(t):
                    bad.append((fn.__name__, t))
    assert not bad, bad[:40]


def test_role_and_city_lines_are_not_names():
    text = "Frontend Developer\nData Scientist\nНижний Новгород\nSpring Boot\nОпыт 3 года: React, TypeScript, Frontend."
    r = redact(text)
    for s in ("Frontend Developer", "Data Scientist", "Нижний Новгород", "Spring Boot", "React, TypeScript, Frontend"):
        assert s in r.text, (s, r.text)
    assert "person" not in r.summary


# ------------------------------------------------------------------ 4. одиночное имя рядом с контактом (вакансия)
@pytest.mark.parametrize("text, name", [
    ("Backend Python, гибрид. Ольга, +7 999 123-45-67", "Ольга"),
    ("Резюме присылайте: hr@example.com — Мария", "Мария"),
    ("Пишите Ольге в tg, ответим за день", "Ольге"),
    ("Вопросы — звоните Никите: 8 (912) 555-12-34", "Никите"),
    ("Отправляйте резюме Марии на почту", "Марии"),
    ("По всем вопросам — Ольга (HR), @olga_hr", "Ольга"),
    ("Контакты: t.me/sample_hr, Саша", "Саша"),
    ("Write to Olga: hr@example.com", "Olga"),
    ("Обращайтесь к Ивану Петрову, +7 999 123-45-67", "Петров"),
])
def test_single_name_near_contact(text, name):
    r = _vac(text)
    assert name not in r.text, r.text
    assert "[имя]" in r.text or "[ФИО]" in r.text
    assert "person" in r.found


@pytest.mark.parametrize("text", [
    "Гибрид, Андроид, офис в Москве; пишите в Telegram: [ник]. Звоните нам: +7 999 123-45-67",
    "Стек: Kotlin, Android, Jetpack Compose. Гибрид. Контакты в профиле компании, +7 999 123-45-67",
    "Офис: г. Владимир, +7 999 123-45-67. Удалёнка возможна",
    "Пишите в личку, отвечаем быстро. Вера в продукт и команда — главное.",
])
def test_single_name_false_positives(text):
    r = _vac(text)
    for w in ("Гибрид", "Андроид", "Android", "Kotlin", "Jetpack", "Telegram", "Владимир", "Вера"):
        assert text.count(w) == r.text.count(w), (w, r.text)
    assert "[имя]" not in r.text
