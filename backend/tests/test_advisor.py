"""Н1: «ИИ-советник руководителя» на экране сравнения — ответы по фактам сравнения, без генерации и без ПДн."""
import re

from app.modules.matching import advisor
from tests.test_day2_rules import H, employer
from tests.test_employer_matching import _seeded_need


def _ask(client, te, need_id, **body):
    r = client.post(f"/api/employer/needs/{need_id}/advisor", json=body, headers=H(te))
    assert r.status_code == 200, r.text
    return r.json()


def test_classify_intents():
    refs, tags = ["C-AAAA11", "C-BBBB22"], {"kafka": "Kafka", "python": "Python"}
    cases = {
        None: "briefing", "": "briefing",
        "Кого позвать первым и почему?": "first",
        "У кого лучше соотношение навыков и зарплатной вилки?": "salary",
        "О чём спросить лидера на финальном созвоне?": "questions",
        "Чем отличаются их достижения ФСП?": "fsp",
        "Какие риски у второго?": "risks",
        "А что с Kafka?": "skill",
        "расскажи про c-bbbb22": "candidate",
        "Погода в Москве": "briefing",
    }
    for q, want in cases.items():
        assert advisor.classify(q, refs, tags)[0] == want, q
    assert advisor.classify("расскажи про C-BBBB22", refs, tags) == ("candidate", "C-BBBB22")
    assert advisor.classify("Что с Kafka", refs, tags) == ("skill", "kafka")


def test_spoken_text_has_no_symbols():
    s = advisor.spoken(["Лидер C-8D3YPW: 78 из 100, рынок 200\u00a0–\u00a0280\u00a0тыс.\u00a0₽, ФСП 85\u00a0%."])
    assert "₽" not in s and "%" not in s and "C-8D3YPW" not in s
    assert "тысяч рублей" in s and "процентов" in s and "8 D 3 Y P W" in s


def test_advisor_answers_from_compare_facts(client):
    te = employer(client)
    need = _seeded_need(client, te)
    v1 = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te)).json()
    refs = [r["ref"] for r in v1["results"][:3]]
    cmp = client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": refs, "version": 1},
                     headers=H(te)).json()
    top = max(cmp["candidates"], key=lambda c: c["score"])

    brief = _ask(client, te, need["id"], refs=refs, version=1)
    assert brief["intent"] == "briefing" and brief["source"] == "rules" and brief["leader"] == top["ref"]
    assert brief["answer"] and brief["speech"] and len(brief["chips"]) == 4
    assert brief["candidates"][0]["leader"] and brief["candidates"][0]["ref"] == top["ref"]
    assert {c["ref"] for c in brief["candidates"]} == set(refs)
    assert f"{round(top['score'] * 100)} из 100" in brief["answer"][0]

    first = _ask(client, te, need["id"], refs=refs, version=1, question="Кого позвать первым и почему?")
    assert first["intent"] == "first" and first["answer"][0].startswith(f"Первым позовите {top['ref']}")

    money = _ask(client, te, need["id"], refs=refs, version=1,
                 question="У кого лучше соотношение навыков и зарплатной вилки?")
    text = " ".join(money["answer"])
    assert money["intent"] == "salary" and "Ожидания кандидатов скрыты" in text and ("Лучшее соотношение у" in text or "решает балл" in text or "соотношение решают" in text)
    assert "тыс." in text and "220–300" in text  # вилка потребности из текста «220–300 тыс.»

    qs = _ask(client, te, need["id"], refs=refs, version=1, question="О чём спросить лидера на финальном созвоне?")
    assert qs["intent"] == "questions" and qs["answer"][0].startswith(f"На финальном созвоне с {top['ref']}")
    assert sum(1 for x in qs["answer"] if re.match(r"^\d\. ", x)) >= 2

    fsp = _ask(client, te, need["id"], refs=refs, version=1, question="Чем отличаются их достижения ФСП?")
    assert fsp["intent"] == "fsp" and "реестром ФСП" in " ".join(fsp["answer"])

    one = _ask(client, te, need["id"], refs=refs, version=1, question=f"Расскажи про {refs[1]}")
    assert one["intent"] == "candidate" and one["answer"][0].startswith(refs[1])

    # без refs — первые три подборки, как в сравнении; обезличено: ни ФИО, ни почт
    auto = _ask(client, te, need["id"])
    assert len(auto["candidates"]) >= 2
    blob = str(auto) + str(first) + str(money) + str(qs)
    assert "@" not in blob and "Иван" not in blob


def test_advisor_validation_and_ownership(client):
    te = employer(client)
    need = _seeded_need(client, te)
    v1 = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te)).json()
    refs = [r["ref"] for r in v1["results"][:2]]
    url = f"/api/employer/needs/{need['id']}/advisor"
    assert client.post(url, json={"refs": refs[:1]}, headers=H(te)).status_code == 422
    assert client.post(url, json={"refs": refs, "version": 99}, headers=H(te)).status_code == 404
    assert client.post(url, json={"refs": refs, "question": "x" * 501}, headers=H(te)).status_code == 422
    other = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.post(url, json={"refs": refs}, headers=H(other)).status_code == 404
    assert client.post(url, json={"refs": refs}).status_code == 401
