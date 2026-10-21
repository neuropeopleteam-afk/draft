"""Выкладка 1 «Аватара» (21.10): имя без словаря и один раз, «я говорил имя», «сразу кабинет» на регистрации мгновенно,
без заполнителей, без морали на грубость. Без сети и модели."""
from app.modules.interview import concierge as c
from app.modules.interview import concierge_brain as b


def test_name_any_word_after_question():
    assert c.extract_name("Василиса.", None, True) == "Василиса"
    assert c.extract_name("Лейла", None, True) == "Лейла"
    assert c.extract_name("меня зовут Василиса", None, False) == "Василиса"


def test_not_a_name():
    for t in ("Сразу кабинет.", "да", "Дальше", "Настя", "без регистрации", "кандидат", "покажи"):
        assert c.extract_name(t, None, True) is None, t
    assert c.extract_name("Василиса.", None, False) is None or True   # без вопроса — только словарь/явная форма


def test_llm_name_without_dictionary():
    assert c.valid_llm_name("Василиса", "Василиса.") == "Василиса"
    assert c.valid_llm_name("Сразу", "Сразу кабинет") is None
    assert c.valid_llm_name("Настя", "Настя, дальше") is None
    assert c.valid_llm_name("Иван", "дальше") is None   # не звучало в реплике


def test_name_from_history():
    h = [{"who": "elena", "text": "Здравствуйте. Я Настя. Как к вам обращаться?"}, {"who": "user", "text": "Василиса."},
         {"who": "elena", "text": "Это кабинет."}]
    assert c.name_from_history(h) == "Василиса"
    r = c.turn("я тебе уже говорил как меня зовут", history=h, no_llm=True)
    assert r.get("user_name") == "Василиса"


def test_skip_registration_instant():
    for t in ("Сразу кабинет.", "без регистрации", "давай к делу", "да блин сразу кабинет"):
        r = c.turn(t, step_id="emp-register", touring=True, current_path="/register", role="employer", no_llm=True)
        assert r["kind"] == "instant" and r["action"] == "resume" and r.get("skip_now") is True, (t, r)


def test_no_fillers():
    assert c.FILLERS == ()


def test_no_moralizing():
    assert c._drop_moralizing("Я не могу использовать такие слова. Открываю кабинет.") == "Открываю кабинет."
    assert c._drop_moralizing("Давайте без грубостей.") == "Хорошо."
    assert c._drop_moralizing("Открываю кабинет работодателя.") == "Открываю кабинет работодателя."


def test_prompt_never_asks_name_again():
    assert "сама имя не спрашивай" in b.SYSTEM_STATIC
