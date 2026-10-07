"""Точка интеграции сервиса тестирования.

Бэкенд работает с тестом только через протокол ``AssessmentEngine``: начать сессию → следующее задание →
ответ → завершить (θ, SE, грейд). Состояние сессии — JSON-словарь, который бэкенд хранит в
``test_sessions.result["state"]`` (движок без БД и без глобального состояния, легко подменяется).

Движки:
* ``bank`` (по умолчанию, ``ASSESSMENT_ENGINE=bank``) — ``bank_engine.BankEngine`` поверх пакета
  ``assessment_bank``: семейства изоморфных заданий, адаптивный выбор, θ/SE, грейды, детектор предзнания;
* ``stub`` — прежняя заглушка из 6 фиксированных вопросов (для быстрых тестов правил и как запасной путь,
  если пакет банка не импортируется).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Protocol

from app.core.fmt import theta_se

GRADES = ("junior", "middle", "senior")
# Временные пороги на шкале θ (как в assessment_bank.psychometrics.grading.GradeScale)
GRADE_CUTS = {"junior": -1.0, "middle": 0.0, "senior": 1.0}
CONFIRM_LEVEL = 0.6  # P(θ ≥ порог заявленного грейда) для подтверждения
UPGRADE_LEVEL = 0.8  # P(θ ≥ порог следующего грейда) для предложения пройти тест выше


@dataclass
class ItemPublic:
    """Задание в виде, безопасном для отдачи кандидату: без ключа ответа, рубрики, семейства и seed.

    item_id — непрозрачный токен сессии (не variant_id: по family_id и seed открытый генератор восстановил бы
    ключ). options — [{id, text, code?}]. answer_kind: option — id варианта; line — номер строки кода;
    text — текст (вывод программы или развёрнутый ответ). Для open_book_3step задание показывается по шагам:
    step/steps_total/step_prompt, options — только для текущего шага.
    """

    item_id: str
    position: int
    total: int
    format: str
    stem: str
    options: list[dict] | None = None
    code: str | None = None
    code_language: str | None = None
    time_limit_s: int = 120
    skills: list[str] = field(default_factory=list)
    answer_kind: str = "option"
    step: int | None = None
    steps_total: int | None = None
    step_prompt: str | None = None
    elapsed_s: int = 0
    block: str = "direction"
    adaptive: bool = False
    min_items: int | None = None
    max_items: int | None = None
    answered: int = 0
    extension: bool = False


@dataclass
class AnswerFeedback:
    accepted: bool
    answered: int
    total: int
    done: bool


@dataclass
class EngineResult:
    engine: str
    theta: float
    se: float
    claimed_grade: str
    point_grade: str  # грейд по точечной оценке θ (none | junior | middle | senior)
    confirmed: bool  # заявленный грейд подтверждён с уверенностью CONFIRM_LEVEL
    upgrade_available: bool
    retake_lower: str | None
    probabilities: dict[str, float]
    answered: int
    correct: int
    skills: dict[str, dict]  # стек-тег → {"correct": k, "total": n, "score": k/n}
    explanation: str
    details: dict = field(default_factory=dict)  # стоп-критерий, дотестирование, предзнание, ответы «на проверке»

    def to_dict(self) -> dict:
        return asdict(self)


class AssessmentEngine(Protocol):
    name: str

    def start(self, *, direction: str, claimed_grade: str, stack_tags: list[str], seed: int) -> dict: ...

    def next_item(self, state: dict) -> ItemPublic | None: ...

    def answer(self, state: dict, item_id: str, answer: Any, time_spent_ms: int | None = None,
               step: int | None = None) -> AnswerFeedback: ...

    def finish(self, state: dict) -> EngineResult: ...


# ---------------------------------------------------------------- общие функции оценки (используются заглушкой)

def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def eap_theta(responses: list[tuple[float, bool]]) -> tuple[float, float]:
    """EAP-оценка θ по модели Раша с априорным N(0, 1) на сетке [-4; 4]. responses: (b, верно?)."""
    grid = [i / 20 for i in range(-80, 81)]
    post = []
    for t in grid:
        w = math.exp(-t * t / 2)
        for b, ok in responses:
            p = 1 / (1 + math.exp(-(t - b)))
            w *= p if ok else 1 - p
        post.append(w)
    z = sum(post) or 1.0
    mean = sum(t * w for t, w in zip(grid, post, strict=True)) / z
    var = sum((t - mean) ** 2 * w for t, w in zip(grid, post, strict=True)) / z
    return round(mean, 3), round(math.sqrt(var), 3)


def grade_decision(theta: float, se: float, claimed: str) -> dict:
    """Решение относительно заявленного грейда: принудительного понижения нет."""
    def p_at_least(g: str) -> float:
        return 1 - _norm_cdf((GRADE_CUTS[g] - theta) / max(se, 1e-6))

    at_least = {g: p_at_least(g) for g in GRADES}
    probs = {
        "none": round(1 - at_least["junior"], 3),
        "junior": round(at_least["junior"] - at_least["middle"], 3),
        "middle": round(at_least["middle"] - at_least["senior"], 3),
        "senior": round(at_least["senior"], 3),
    }
    point = "none"
    for g in GRADES:
        if theta >= GRADE_CUTS[g]:
            point = g
    confirmed = at_least[claimed] >= CONFIRM_LEVEL
    i = GRADES.index(claimed)
    upgrade = confirmed and i + 1 < len(GRADES) and at_least[GRADES[i + 1]] >= UPGRADE_LEVEL
    lower = None
    if not confirmed:
        for g in reversed(GRADES[:i]):
            if at_least[g] >= CONFIRM_LEVEL:
                lower = g
                break
        if lower is None and i > 0:
            lower = GRADES[i - 1]
    return {"point_grade": point, "confirmed": confirmed, "upgrade_available": upgrade, "retake_lower": lower,
            "probabilities": probs}


# ---------------------------------------------------------------- временная заглушка

def _q(item_id, skills, stem, options, key, b=0.0, code=None, lang=None):
    return {"id": item_id, "skills": skills, "stem": stem, "options": options, "key": key, "b": b, "code": code,
            "lang": lang}


COMMON_ITEMS = [
    _q("common.sql.1", ["sql"], "Какой запрос вернёт число заказов каждого клиента, у которого их больше трёх?",
       ["SELECT client_id, COUNT(*) FROM orders WHERE COUNT(*) > 3 GROUP BY client_id",
        "SELECT client_id, COUNT(*) FROM orders GROUP BY client_id HAVING COUNT(*) > 3",
        "SELECT client_id, COUNT(*) FROM orders GROUP BY client_id WHERE COUNT(*) > 3",
        "SELECT DISTINCT client_id FROM orders HAVING COUNT(*) > 3"], 1, b=-0.3),
    _q("common.http.1", ["http"], "Клиент повторил запрос из-за обрыва сети. Какой метод HTTP по спецификации идемпотентен?",
       ["POST", "PUT", "PATCH", "CONNECT"], 1, b=0.0),
    _q("common.alg.1", ["algorithms"], "Какова сложность поиска элемента в отсортированном массиве из n элементов двоичным поиском?",
       ["O(1)", "O(log n)", "O(n)", "O(n log n)"], 1, b=-0.6),
]
DIRECTION_ITEMS = {
    "backend": [
        _q("backend.py.1", ["python"], "Что выведет код?", ["[1] [2]", "[1] [1, 2]", "[1, 2] [1, 2]", "Ошибка"], 1,
           b=0.2, code="def add(x, acc=[]):\n    acc.append(x)\n    return acc\n\nprint(add(1), add(2))", lang="python"),
        _q("backend.db.1", ["postgresql"], "Запрос с фильтром по полю email выполняется медленно на таблице в 10 млн строк. "
           "Что сделать в первую очередь?",
           ["Увеличить shared_buffers", "Создать индекс по email и проверить план через EXPLAIN",
            "Перейти на NoSQL", "Добавить LIMIT 1000"], 1, b=-0.2),
        _q("backend.async.1", ["asyncio"], "В обработчике FastAPI (async def) вызывается синхронная функция, которая 2 секунды "
           "ждёт ответа внешнего сервиса. Что произойдёт под нагрузкой?",
           ["Ничего, FastAPI сам распараллелит", "Блокируется цикл событий, другие запросы ждут",
            "Запрос упадёт с таймаутом", "Python создаст новый поток автоматически"], 1, b=0.5),
    ],
    "frontend": [
        _q("frontend.js.1", ["javascript"], "Что выведет код?", ["0 1 2", "3 3 3", "undefined ×3", "Ошибка"], 1, b=0.0,
           code="for (var i = 0; i < 3; i++) {\n  setTimeout(() => console.log(i), 0);\n}", lang="javascript"),
        _q("frontend.react.1", ["react"], "Компонент перерисовывается бесконечно. Какая строка — причина?",
           ["useEffect(() => { load(); }, [])", "useEffect(() => { setItems([...items]); }, [items])",
            "const [items, setItems] = useState([])", "return <List items={items} />"], 1, b=0.3),
        _q("frontend.ts.1", ["typescript"], "Какой тип у value после проверки?\n\nfunction f(value: string | number) {\n  if (typeof value === \"string\") return;\n  value; // ?\n}",
           ["string", "number", "string | number", "never"], 1, b=-0.4),
    ],
    "data_ml": [
        _q("data.pandas.1", ["pandas"], "Что вернёт df.groupby('city')['price'].mean()?",
           ["DataFrame со всеми колонками", "Series: средняя цена по каждому городу", "Одно число", "Ошибку"], 1, b=-0.5),
        _q("data.ml.1", ["scikit-learn"], "Точность модели на обучении 99 %, на валидации 62 %. Что это?",
           ["Недообучение", "Переобучение", "Утечка целевой переменной в валидацию", "Нормальная ситуация"], 1, b=0.0),
        _q("data.stat.1", ["statistics"], "В A/B-тесте p-value = 0,03 при α = 0,05. Как корректно интерпретировать?",
           ["Вероятность, что B лучше A, — 97 %", "Если различий нет, такой или более сильный эффект наблюдался бы в ~3 % случаев",
            "Эффект составляет 3 %", "Нужно увеличить α"], 1, b=0.6),
    ],
    "qa": [
        _q("qa.design.1", ["test-design"], "Поле принимает возраст от 18 до 65 включительно. Минимальный набор граничных значений?",
           ["18, 65", "17, 18, 65, 66", "0, 18, 65, 100", "18, 40, 65"], 1, b=-0.4),
        _q("qa.pytest.1", ["pytest"], "Как в pytest запустить один тест с тремя наборами входных данных?",
           ["@pytest.fixture(scope='module')", "@pytest.mark.parametrize", "@pytest.mark.skip", "pytest -k"], 1, b=-0.1),
        _q("qa.api.1", ["api-testing"], "API на создание заказа вернул 200 и пустое тело вместо 201 и id. Что это с точки зрения теста?",
           ["Не баг: 200 — успех", "Дефект контракта: код и тело ответа не соответствуют спецификации",
            "Проблема окружения", "Нужно проверить UI"], 1, b=0.3),
    ],
    "security": [
        _q("sec.owasp.1", ["owasp"], "Какой код уязвим для SQL-инъекции?", [
            "cur.execute('SELECT * FROM users WHERE id = %s', (uid,))",
            "cur.execute(f\"SELECT * FROM users WHERE id = {uid}\")",
            "User.objects.filter(id=uid)",
            "session.get(User, uid)"], 1, b=-0.5),
        _q("sec.crypto.1", ["cryptography"], "Как правильно хранить пароли пользователей?",
           ["SHA-256 без соли", "Медленная функция с солью: argon2id или bcrypt", "AES с ключом в конфиге", "Base64"], 1, b=-0.2),
        _q("sec.net.1", ["network-security"], "В журналах — тысячи SYN без завершения рукопожатия с разных адресов. Что это вероятнее всего?",
           ["Сканирование UDP", "SYN-flood (DoS)", "ARP-спуфинг", "Подбор пароля SSH"], 1, b=0.4),
    ],
}
GRADE_SHIFT = {"junior": -1.0, "middle": 0.0, "senior": 1.0}


class StubEngine:
    """Временная заглушка: 3 вопроса общего блока + 3 по направлению. Только закрытые форматы.

    Трудность задания b сдвигается на уровень заявленного грейда — это упрощение до подключения
    откалиброванного банка. Ответы и ключи не покидают сервер.
    """

    name = "stub-v0"

    def start(self, *, direction: str, claimed_grade: str, stack_tags: list[str], seed: int) -> dict:
        items = COMMON_ITEMS + DIRECTION_ITEMS.get(direction, DIRECTION_ITEMS["backend"])
        # Перемешиваем варианты ответов детерминированно по seed (воспроизводимость сессии)
        order = []
        for k, it in enumerate(items):
            n = len(it["options"])
            shift = (seed + 7 * k) % n
            order.append([(j + shift) % n for j in range(n)])
        return {"engine": self.name, "direction": direction, "claimed_grade": claimed_grade, "seed": seed,
                "item_ids": [it["id"] for it in items], "option_order": order, "answers": {}}

    def _items(self, state: dict) -> list[dict]:
        by_id = {it["id"]: it for it in COMMON_ITEMS + [x for v in DIRECTION_ITEMS.values() for x in v]}
        return [by_id[i] for i in state["item_ids"]]

    def next_item(self, state: dict) -> ItemPublic | None:
        items = self._items(state)
        for pos, it in enumerate(items):
            if it["id"] not in state["answers"]:
                order = state["option_order"][pos]
                return ItemPublic(item_id=it["id"], position=pos + 1, total=len(items), format="mcq",
                                  stem=it["stem"], options=[{"id": str(k), "text": it["options"][j]}
                                                            for k, j in enumerate(order)],
                                  code=it["code"], code_language=it["lang"], time_limit_s=120, skills=it["skills"],
                                  answered=len(state["answers"]))
        return None

    def answer(self, state: dict, item_id: str, answer: Any, time_spent_ms: int | None = None,
               step: int | None = None) -> AnswerFeedback:
        items = self._items(state)
        ids = [it["id"] for it in items]
        if item_id not in ids or item_id in state["answers"]:
            return AnswerFeedback(False, len(state["answers"]), len(items), len(state["answers"]) == len(items))
        pos = ids.index(item_id)
        try:
            shown = int(answer)
            original = state["option_order"][pos][shown]
        except (TypeError, ValueError, IndexError):
            return AnswerFeedback(False, len(state["answers"]), len(items), False)
        state["answers"][item_id] = {"choice": original, "ok": original == items[pos]["key"], "ms": time_spent_ms}
        n = len(state["answers"])
        return AnswerFeedback(True, n, len(items), n == len(items))

    def finish(self, state: dict) -> EngineResult:
        items = self._items(state)
        shift = GRADE_SHIFT.get(state["claimed_grade"], 0.0)
        responses, skills = [], {}
        for it in items:
            a = state["answers"].get(it["id"])
            ok = bool(a and a["ok"])
            if a is not None:
                responses.append((it["b"] + shift, ok))
            for s in it["skills"]:
                d = skills.setdefault(s, {"correct": 0, "total": 0})
                d["total"] += 1
                d["correct"] += int(ok)
        for d in skills.values():
            d["score"] = round(d["correct"] / d["total"], 2) if d["total"] else 0.0
        theta, se = eap_theta(responses)
        dec = grade_decision(theta, se, state["claimed_grade"])
        correct = sum(1 for _, ok in responses if ok)
        return EngineResult(
            engine=self.name, theta=theta, se=se, claimed_grade=state["claimed_grade"], answered=len(responses),
            correct=correct, skills=skills, explanation=_explain(dec, theta, se, state["claimed_grade"]), **dec,
        )


def _explain(dec: dict, theta: float, se: float, claimed: str) -> str:
    i = GRADES.index(claimed)
    if dec["confirmed"]:
        s = f"Грейд {claimed.capitalize()} подтверждён (θ = {theta_se(theta, se)})."
        if dec["upgrade_available"]:
            s += f" Результат уверенный — можно пройти тест на {GRADES[i + 1].capitalize()}."
        return s
    s = f"Грейд {claimed.capitalize()} пока не подтверждён (θ = {theta_se(theta, se)}). Принудительного понижения нет"
    return s + (f": можно пройти тест на {dec['retake_lower'].capitalize()}." if dec["retake_lower"] else
                ": можно пройти тест ещё раз после подготовки.")


_ENGINES: dict[str, AssessmentEngine] = {"stub": StubEngine()}
_BANK_ERROR: str | None = None


def get_engine(name: str | None = None) -> AssessmentEngine:
    """Движок по имени (или из ASSESSMENT_ENGINE). Если пакет банка не загрузился — заглушка и запись в лог."""
    global _BANK_ERROR
    from app.core.config import get_settings

    key = name or get_settings().assessment_engine
    if key == "bank" and "bank" not in _ENGINES:
        if _BANK_ERROR is not None:
            return _ENGINES["stub"]
        try:
            from app.modules.assessment.bank_engine import BankEngine

            _ENGINES["bank"] = BankEngine()
        except Exception as e:  # noqa: BLE001 — пакет банка или его реестр не загрузились
            import logging

            _BANK_ERROR = f"{type(e).__name__}: {e}"
            logging.getLogger("assessment").error("Банк заданий не загрузился, работает заглушка: %s", _BANK_ERROR)
            return _ENGINES["stub"]
    return _ENGINES.get(key, _ENGINES["stub"])
