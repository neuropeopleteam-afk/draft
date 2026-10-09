"""П1 п. 6: перехват тела запроса к модели во всех четырёх вызовах — разбор потребности (parse_need), резюме (resume,
PDF через API), оценка ответа (grade) и вторая оценка (grade_second). В теле не должно быть почты, телефона, адреса
(улица/дом/квартира, индекс), даты рождения, возраста, ФИО кириллицей и латиницей; содержание (стек) — на месте.

ДАННЫЕ СИНТЕТИЧЕСКИЕ: все имена, адреса, телефоны, почты и даты выдуманы для теста и не принадлежат реальным людям.
Сеть не используется — транспорт httpx подменён (tests/test_llm_chain.py: Net, configure).
"""
from __future__ import annotations

import json

import pytest

from tests.test_llm_chain import ANSWER, FABLE, SONNET, _grade, _need_reply, configure, net, reply  # noqa: F401

# 4 синтетических резюме: (строки PDF, секреты, что должно остаться)
RESUMES = [
    (["Смирнова Анна Викторовна", "Женщина, 34 года, родилась 15 марта 1990", "Москва, ул. Тверская, д. 7, кв. 15",
      "+7 (999) 123-45-67, anna.smirnova@example.com", "Желаемая должность: Frontend-разработчик",
      "Опыт работы — 7 лет 2 месяца", "Март 2020 — настоящее время: React, TypeScript, Next.js",
      "Анна Викторовна — автор доклада о React."],
     ["Смирнова", "Анна", "Викторовна", "34 года", "15 марта 1990", "Тверская", "кв. 15", "123-45-67", "anna.smirnova",
      "Женщина"],
     ["React", "TypeScript", "Москва", "7 лет 2 месяца"]),
    (["Ivan Petrov", "Senior Backend Developer", "Male, 35 years old", "Moscow, ul. Tverskaya, 7, apt. 15", "12.04.1989",
      "ivan.petrov@example.com | +7 999 000-11-22 | github.com/ipetrov-test",
      "Experience: Java, Spring Boot, Apache Kafka, PostgreSQL", "2016-2024 Bank; 03.2024 - present Market",
      "Best regards, Ivan Petrov"],
     ["Ivan", "Petrov", "35 years", "Tverskaya", "apt. 15", "12.04.1989", "ivan.petrov", "000-11-22", "ipetrov"],
     ["Spring Boot", "Apache Kafka", "PostgreSQL", "Moscow"]),
    (["Кузнецов Дмитрий Олегович", "QA-инженер, 27 лет", "Санкт-Петербург, Невский пр-т, 28, кв. 4",
      "Дата рождения: 02.02.1997", "Telegram: @dkuz_qa_test, тел. 8 912 555 12 34",
      "Автотесты: Python, pytest, Selenium, Playwright, Allure", "Dmitry Kuznetsov - speaker at a QA conference"],
     ["Кузнецов", "Дмитрий", "Олегович", "27 лет", "Невский", "кв. 4", "02.02.1997", "dkuz_qa_test", "555 12 34", "Dmitry",
      "Kuznetsov"],
     ["Selenium", "Playwright", "Санкт-Петербург"]),
    (["PETROVA MARIA", "Data Scientist", "420111, Казань, ул. Кремлёвская, 18", "Мне 28 лет",
      "maria.petrova@example.org", "Опыт 3 года: Python, pandas, PyTorch, SQL, Airflow"],
     ["PETROVA", "MARIA", "420111", "Кремлёвская", "28 лет", "maria.petrova"],
     ["PyTorch", "Airflow", "Казань", "Data Scientist"]),
]

VACANCIES = [
    ("Ищем Senior Java-разработчика: Spring Boot, Apache Kafka, PostgreSQL. Гибрид, офис: Москва, Пресненская наб., 12, "
     "офис 4501. Рекрутер — Пётр Сидоров, +7 999 123-45-67, hr@acme-corp.ru. Ольга, +7 (495) 111-22-33 — по вопросам "
     "оформления.",
     ["Пётр", "Сидоров", "Ольга", "123-45-67", "111-22-33", "hr@acme-corp.ru", "Пресненская", "4501"],
     ["Spring Boot", "Apache Kafka", "Москва", "Гибрид"]),
    ("Frontend-разработчик (React, TypeScript), удалённо. Contact: Anna Smirnova, anna.hr@example.com. Пишите Маше в tg: "
     "@masha_hr_test. Адрес для документов: 101000, г. Москва, ул. Маросейка, 2.",
     ["Anna", "Smirnova", "anna.hr", "Маше", "masha_hr_test", "101000", "Маросейка"],
     ["React", "TypeScript", "удалённо"]),
]

GRADER_PII = (" Меня зовут Смирнова Анна Викторовна (Anna Smirnova), мне 34 года, дата рождения 15.03.1990, живу: Москва, "
              "ул. Тверская, д. 7, кв. 15, телефон +7 999 123-45-67, почта anna.smirnova@example.com.")
GRADER_SECRETS = ["Смирнова", "Анна", "Викторовна", "Anna", "Smirnova", "34 года", "15.03.1990", "Тверская", "кв. 15",
                  "123-45-67", "anna.smirnova"]


def _sent(call: dict) -> str:
    return json.dumps(call["body"]["messages"], ensure_ascii=False)


def _check(calls: list[dict], secrets: list[str], keep: list[str]):
    assert calls, "запрос к модели не отправлен"
    for c in calls:
        sent = _sent(c)
        for s in secrets:
            assert s not in sent, (s, sent[-700:])
        for k in keep:
            assert k in sent, (k, sent[-700:])


@pytest.mark.parametrize("i", range(len(RESUMES)))
def test_resume_body_has_no_pii(monkeypatch, net, client, i):  # noqa: F811
    from tests.conftest import register_and_verify
    from tests.test_day2_rules import H, _pdf_bytes

    lines, secrets, keep = RESUMES[i]
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, lambda req, body: reply('{"stack": [], "roles": [], "soft_skills": []}', body["model"]))
    t = register_and_verify(client, email=f"pii-body-{i}@example.com")
    r = client.post("/api/me/resume", files={"file": ("cv.pdf", _pdf_bytes(lines), "application/pdf")}, headers=H(t))
    assert r.status_code == 201, r.text
    assert [c["body"]["model"] for c in net.calls] == [SONNET]
    _check(net.calls, secrets, keep)
    # то, что сохраняется и показывается (text_preview), — тоже без ПДн
    for s in secrets:
        assert s not in r.json()["text_preview"], s


@pytest.mark.parametrize("i", range(len(VACANCIES)))
def test_need_parse_body_has_no_pii(monkeypatch, net, i):  # noqa: F811
    from app.modules.matching.need_parser import parse_need

    text, secrets, keep = VACANCIES[i]
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, _need_reply)
    r = parse_need(text)
    assert r["method"] == "llm+rules"
    _check(net.calls, secrets, keep)


def test_grade_and_second_opinion_bodies_have_no_pii(monkeypatch, net):  # noqa: F811
    from app.modules.assessment.grader import grade_open
    from tests.test_llm_chain import RUBRIC

    configure(monkeypatch, LLM_CHAIN="openrouter,yandex")
    net.on("or.test", SONNET, _grade({"cause": 1, "fix": 0}))  # 0,5 — у порога → вторая оценка
    net.on("or.test", FABLE, _grade({"cause": 1, "fix": 0.5}))
    g = grade_open(stem="Найдите ошибку бронирования", code=None, step_prompt=None, rubric=RUBRIC,
                   answer=ANSWER + GRADER_PII)
    assert [c["model"] for c in net.calls] == [SONNET, FABLE], "нужны оба вызова: grade и grade_second"
    assert g.method == "llm2" and g.status == "scored"
    _check(net.calls, GRADER_SECRETS, ["блокировка строки", "два запроса читают остаток одновременно"])
    assert {"person", "email", "phone", "address", "age", "birthdate"} <= set(g.redacted)
