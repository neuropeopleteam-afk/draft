"""«Проверьте сами» на /validation: синтетический кандидат проходит N тестов на НАСТОЯЩЕМ движке банка.

В отличие от симуляции (``sim.py``, сессии ``CATSession`` на параметрах IRT), здесь работает тот же ``BankEngine``,
что и у живого кандидата: генерируются настоящие варианты заданий, ответ сверяется с серверным ключом
(``_score``), адаптивный выбор, канарейки, дотестирование у порога, решение по грейду ``decide`` — всё как в
продукте. В БД ничего не пишется (состояние сессии живёт в памяти запроса): калибровка, частота показа и живые
метрики не искажаются.

Синтетический кандидат отвечает по стратегии:
* ``theta`` / ``level_*`` — уровень θ: верный ответ с вероятностью P(θ) по той же модели заданий, что и у оценщика
  (логистическая без множителя 1,7, ``irt.prob``); ``level_junior`` = −0,5, ``level_middle`` = 0,5,
  ``level_senior`` = 1,5 (середины полос). Демо-респондент песочницы жюри (seed._p_correct) отвечает по кривой с
  множителем 1,7 — круче модели, поэтому там θ̂ систематически уходит от заданного θ; здесь — нет;
* ``all_correct`` — всегда верно; ``all_wrong`` — всегда неверно; ``random`` — случайный вариант (строка, ответ);
* ``common_only`` — знает только общий блок: задания общего блока верно, направления — случайно.

Честные ограничения. Развёрнутые ответы (open_answer, шаг 3 open_book_3step) у синтетического кандидата текста не
имеют — их балл задаёт та же стратегия (а не YandexGPT по рубрике); время ответа — расчётное, 40–90 % рекомендуемого
времени задания. Это проверка механики теста (воспроизводимость, разделение грейдов, длина), а не качества заданий.

Защита стенда: не больше ``MAX_N`` кандидатов (× 2 при повторе), один расчёт за раз на воркер (иначе 429), лимиты
частоты на пользователя и общий; вызов — только после входа (жюри входит в один клик, как у «Красной кнопки»).
"""
from __future__ import annotations

from functools import lru_cache
import math
import threading
import time

import numpy as np

from app.modules.assessment.bank_engine import GRADE_RU, BankEngine
from app.modules.assessment.engine import GRADES
from app.modules.jury.seed import _answer_for
from assessment_bank.psychometrics.hierarchical import effective_a
from assessment_bank.psychometrics.irt import estimate_theta
from assessment_bank.psychometrics.irt import prob as irt_prob

MAX_N = 20
DIRECTIONS = ("backend", "frontend", "data_ml", "qa", "security")
LEVEL_THETA = {"level_junior": -0.5, "level_middle": 0.5, "level_senior": 1.5}
STRATEGIES = [
    {"id": "theta", "title": "Уровень θ (задать)", "text": "Верный ответ с вероятностью по модели задания при заданном θ"},
    {"id": "level_junior", "title": "Уровень Junior (θ = −0,5)", "text": "Середина полосы Junior"},
    {"id": "level_middle", "title": "Уровень Middle (θ = 0,5)", "text": "Середина полосы Middle"},
    {"id": "level_senior", "title": "Уровень Senior (θ = 1,5)", "text": "Середина полосы Senior"},
    {"id": "all_correct", "title": "Всё верно", "text": "Каждый ответ — по ключу"},
    {"id": "all_wrong", "title": "Всё неверно", "text": "Каждый ответ — мимо ключа"},
    {"id": "random", "title": "Случайно", "text": "Случайный вариант, строка или ответ"},
    {"id": "common_only", "title": "Знает только общий блок", "text": "Общий блок — верно, блок направления — случайно"},
]
from app.modules.catalog.seed_data import GRADE_CUTS as CUTS  # шкала платформы со Стажёром (intern), И13
_busy = threading.BoundedSemaphore(1)


class Busy(Exception):
    pass


@lru_cache(maxsize=1)
def _engine() -> BankEngine:
    return BankEngine()


class SyntheticEngine(BankEngine):
    """Движок банка, у которого развёрнутые ответы оценивает стратегия синтетического кандидата (не LLM)."""

    def __init__(self, base: BankEngine, strategy: str, theta: float | None, rng: np.random.Generator):
        # без повторной загрузки реестра: берём готовые поля базового движка
        self.__dict__.update(base.__dict__)
        self.strategy, self.theta, self.rng = strategy, theta, rng

    def _grade_text(self, it: dict, part: int, text_: str, step_prompt: str | None) -> None:
        s = self.strategy
        if s == "all_correct" or (s == "common_only" and it["block"] == "common"):
            score = 1.0
        elif s == "all_wrong":
            score = 0.0
        elif s in ("random", "common_only"):
            score = float(self.rng.uniform(0, 1))
        else:
            b = float(np.mean(it["pool"]["b"]))
            score = float(np.clip(0.55 + 0.35 * (float(self.theta) - b) + self.rng.normal(0, 0.1), 0.2, 1.0))
        it["grading"][part] = {"status": "scored", "method": "synthetic", "score": round(score, 2),
                               "comment": "проверка «Проверьте сами»: балл задан стратегией синтетического кандидата"}
        it["x"][part] = round(score, 2)


def _correct(it: dict, step: int, strategy: str, theta: float | None, rng: np.random.Generator) -> bool:
    if strategy == "all_correct":
        return True
    if strategy == "all_wrong":
        return False
    if strategy == "common_only" and it["block"] == "common":
        return True
    if strategy in ("random", "common_only"):
        fmt = it["format"]
        if fmt in ("choose_fix", "mcq_concept"):
            n = len(it["public"]["options"] or []) or 4
        elif fmt == "open_book_3step" and step < 3:
            n = len([o for o in it["public"]["options"] or [] if o.get("step") == step]) or 3
        elif fmt == "find_bug":
            n = max(2, it["public"]["code_lines"])
        else:
            return False  # вывод программы или развёрнутый ответ наугад не угадать
        return bool(rng.random() < 1.0 / n)
    return bool(rng.random() < _p_correct(it, float(theta), step - 1))


def _p_correct(it: dict, theta: float, part: int) -> float:
    """P(верно) по модели оценщика движка (irt.prob), параметры части part задания."""
    a = np.asarray(it["pool"]["a"], dtype=float)
    b = np.asarray(it["pool"]["b"], dtype=float)
    k = min(part, len(b) - 1)
    return float(irt_prob(theta, float(a[k]), float(b[k])))


def run_one(eng: SyntheticEngine, *, direction: str, claimed: str, mode: str, seed: int,
            previous_subpools: list[int] | None = None) -> dict:
    rng = eng.rng
    st = eng.start(direction=direction, claimed_grade=claimed, stack_tags=[], seed=seed,
                   previous_subpools=previous_subpools, mode=mode)
    t_total = 0.0
    for _ in range(60):
        item = eng.next_item(st)
        if item is None:
            break
        it = eng._current(st)
        spent = float(rng.uniform(0.4, 0.9)) * it["time_limit_s"]
        it["issued_at"] = time.time() - spent
        t_total += spent
        for step in range(1, it["parts"] + 1):
            ok = _correct(it, step, eng.strategy, eng.theta, rng)
            fb = eng.answer(st, it["token"], _answer_for(it, step, ok, rng), None, step=step)
            if not fb.accepted:  # формат ответа не подошёл — отвечаем «пусто», чтобы не зациклиться
                eng.answer(st, it["token"], "", None, step=step)
        if not it["done"]:  # задание так и не принято — завершаем тест тем, что есть
            break
    res = eng.finish(st)
    d = res.details
    return {"theta": res.theta, "se": res.se, "confirmed": res.confirmed, "point_grade": res.point_grade,
            "assigned": claimed if res.confirmed else None, "retake_lower": res.retake_lower,
            "n_items": d.get("n_scored"), "n_canaries": d.get("n_canaries"),
            "n_ext": (d.get("extension") or {}).get("items", 0), "time_min": round(t_total / 60, 1),
            "stop": d.get("stop_reason"), "correct": res.correct, "answered": res.answered,
            "subpool": d.get("subpool"), "probabilities": res.probabilities,
            # потолок оценки на выданных заданиях: EAP при всех верных ответах (для модельного ожидания)
            "theta_hat_max": theta_hat_ceiling([i["pool"] for i in st["items"] if i["done"] and not i["canary"]])}


def theta_hat_ceiling(pools: list[dict]) -> float | None:
    """EAP-оценка θ̂ при всех верных ответах на выданные задания (как считает движок: a_eff, априорное N(0, 1)).
    Это потолок θ̂ данного теста: короткий тест с лёгкими заданиями не поднимет оценку выше, сколько ни отвечай верно."""
    if not pools:
        return None
    a = np.concatenate([np.asarray(p["a"], dtype=float) for p in pools])
    b = np.concatenate([np.asarray(p["b"], dtype=float) for p in pools])
    s = np.concatenate([np.asarray(p["sigma"], dtype=float) for p in pools])
    est = estimate_theta(np.ones_like(b), effective_a(a, s), b)
    return round(float(est.theta), 3)


def _dist(values: list) -> dict:
    out: dict[str, int] = {}
    for v in values:
        k = str(v) if v is not None else "none"
        out[k] = out.get(k, 0) + 1
    return out


def _stat(xs: list[float]) -> dict:
    vals = [x for x in xs if x is not None]
    a = np.asarray(vals, dtype=float)
    if a.size == 0:
        return {"mean": None, "min": None, "max": None, "sd": None}
    ints = all(isinstance(x, (int, np.integer)) for x in vals)
    conv = (lambda v: int(v)) if ints else (lambda v: round(float(v), 2))
    return {"mean": round(float(a.mean()), 2), "min": conv(a.min()), "max": conv(a.max()),
            "sd": round(float(a.std(ddof=1)), 2) if a.size > 1 else 0.0}


def _ru(x: float, nd: int = 2) -> str:
    return str(round(float(x), nd)).replace(".", ",")


def _ncdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def shrink(theta: float, se: float, prior_sd: float = 1.0) -> float:
    """Куда в среднем смещается EAP-оценка θ̂ при априорном N(0, prior_sd) и погрешности se: к нулю,
    примерно в 1/(1 + se²/prior_sd²) раз (точно — для нормального правдоподобия). У короткого теста заметно."""
    return theta / (1.0 + (se / prior_sd) ** 2)


def expected_confirm_rate(theta: float, cut: float, se: float, level: float = 0.8) -> float:
    """Доля подтверждений у кандидата с истинным θ при погрешности se: грейд подтверждается, когда
    P(θ ≥ cut | θ̂, se) ≥ level, то есть θ̂ ≥ cut + z·se; θ̂ ~ N(shrink(θ), se)."""
    z = -math.sqrt(2.0) * _erfinv(1.0 - 2.0 * level)  # квантиль N(0,1) уровня level
    need = cut + z * se
    return _ncdf((shrink(theta, se) - need) / se)


def _erfinv(y: float) -> float:
    # достаточно точная аппроксимация (Giles) для квантиля
    w = -math.log((1.0 - y) * (1.0 + y))
    if w < 5.0:
        w -= 2.5
        p = 2.81022636e-08
        for c in (3.43273939e-07, -3.5233877e-06, -4.39150654e-06, 0.00021858087, -0.00125372503, -0.00417768164,
                  0.246640727, 1.50140941):
            p = c + p * w
    else:
        w = math.sqrt(w) - 3.0
        p = -0.000200214257
        for c in (0.000100950558, 0.00134934322, -0.00367342844, 0.00573950773, -0.0076224613, 0.00943887047,
                  1.00167406, 2.83297682):
            p = c + p * w
    return p * y


def expected_for(strategy: str, theta: float | None, claimed: str, se: float | None = None,
                 theta_hat_max: float | None = None) -> dict:
    """Что должно получиться у честного теста при этой стратегии (для вердикта). se — средняя погрешность
    прогонов: для уровня θ ожидаемая доля подтверждений считается по ней (правило P ≥ 0,8 консервативно у порога).
    theta_hat_max — средний по прогонам потолок θ̂ (EAP при всех верных на выданных заданиях): если он ниже требуемого
    θ̂ = порог + 0,84·SE, подтверждение невозможно ни при каких ответах — ожидание 0 % (так у экспресса за Senior из 7 заданий
    с лимитом 240 с: трудные задания отсечены лимитом, и формула со сдвигом EAP без потолка переоценивала ожидание)."""
    if strategy == "all_correct":
        return {"confirmed": True, "point_grade": "senior", "text": "«Всё верно» — грейд должен подтвердиться, точечная оценка — Senior."}
    if strategy == "all_wrong":
        return {"confirmed": False, "point_grade": "none", "text": "«Всё неверно» — грейд не должен подтвердиться."}
    if strategy == "random":
        return {"confirmed": False, "point_grade": None, "text": "Случайные ответы — грейд не должен подтверждаться (угадать можно отдельные задания, не тест)."}
    if strategy == "common_only":
        return {"confirmed": None, "point_grade": None,
                "text": "Знает только общий блок: верных ответов около 40 % (доля общего блока), заявленный грейд подтверждаться не должен — "
                        "направление он не знает."}
    th = float(theta)
    pg = "none"
    for g in GRADES:
        if th >= CUTS[g]:
            pg = g
    near = min(CUTS.values(), key=lambda c: abs(th - c))
    conf = th >= CUTS[claimed]
    txt = f"Истинный уровень θ = {str(round(th, 2)).replace('.', ',')} — это {GRADE_RU[pg]}; грейд {GRADE_RU[claimed]} "
    txt += "должен подтверждаться" if conf else "подтверждаться не должен"
    out = {"confirmed": conf, "point_grade": pg}
    if se:
        rate = expected_confirm_rate(th, CUTS[claimed], se)
        need = CUTS[claimed] - math.sqrt(2.0) * _erfinv(1.0 - 2.0 * 0.8) * se  # θ̂, при котором P(θ ≥ порог) = 0,8
        out["theta_hat_needed"] = round(need, 2)
        out["theta_hat_expected"] = round(shrink(th, se), 2)
        txt += (f". При погрешности теста ≈ {_ru(se)} оценка θ̂ в среднем сдвинута к нулю "
                f"(≈ {_ru(shrink(th, se))}: априорное N(0, 1) оценки EAP), а для подтверждения нужно θ̂ ≥ {_ru(need)}")
        if theta_hat_max is not None:
            out["theta_hat_max"] = round(theta_hat_max, 2)
            if theta_hat_max < need:
                rate = 0.0
                txt += (f". Потолок оценки на выданных заданиях — θ̂ ≈ {_ru(theta_hat_max)} даже при всех верных ответах: такой короткий "
                        f"тест не может подтвердить {GRADE_RU[claimed]} ни при каких ответах, ожидание — 0 %")
            else:
                txt += f" (потолок θ̂ при всех верных на выданных заданиях ≈ {_ru(theta_hat_max)})"
        out["confirm_rate"] = round(rate, 3)
        if rate > 0:
            txt += (f"; правило «P ≥ 80 %» даёт подтверждение примерно в {round(rate * 100)} % случаев — у порога оно консервативно, "
                    "ошибка в пользу «не подтверждён»")
    if abs(th - near) < 0.35:
        txt += f". Уровень у самого порога {str(near).replace('.', ',')} — решения двух попыток могут расходиться: это ожидаемо, " \
               "именно здесь работает дотестирование у порога"
    out["text"] = txt + "."
    return out


def run(*, strategy: str, theta: float | None, direction: str, claimed: str, n: int, repeat: bool, mode: str,
        seed: int | None = None) -> dict:
    """N синтетических кандидатов (при repeat — две попытки каждого, вторая — на другом субпуле, как у живого
    повтора) на настоящем движке банка. Возвращает распределения и согласие повторов."""
    if strategy not in {s["id"] for s in STRATEGIES}:
        raise ValueError("strategy")
    if strategy in LEVEL_THETA:
        theta = LEVEL_THETA[strategy]
    if strategy == "theta":
        theta = float(np.clip(theta if theta is not None else 0.5, -3.0, 3.0))
    n = max(1, min(MAX_N, int(n)))
    if not _busy.acquire(blocking=False):
        raise Busy()
    t0 = time.time()
    try:
        base = _engine()
        master = np.random.default_rng(seed if seed is not None else int(time.time() * 1000) % (2**31))
        first, second = [], []
        for _ in range(n):
            rng = np.random.default_rng(int(master.integers(2**31)))
            eng = SyntheticEngine(base, strategy, theta, rng)
            r1 = run_one(eng, direction=direction, claimed=claimed, mode=mode, seed=int(master.integers(2**31)))
            first.append(r1)
            if repeat:
                prev = [r1["subpool"]] if r1.get("subpool") is not None else None
                second.append(run_one(eng, direction=direction, claimed=claimed, mode=mode,
                                      seed=int(master.integers(2**31)), previous_subpools=prev))
    finally:
        _busy.release()
    runs = first + second
    confirm_rate = float(np.mean([r["confirmed"] for r in runs]))
    ceilings = [r["theta_hat_max"] for r in runs if r.get("theta_hat_max") is not None]
    exp = expected_for(strategy, theta, claimed, se=float(np.mean([r["se"] for r in runs])),
                       theta_hat_max=float(np.mean(ceilings)) if ceilings else None)
    out = {
        "strategy": strategy, "theta": theta, "direction": direction, "claimed_grade": claimed, "mode": mode,
        "n": n, "repeat": repeat, "runs_total": len(runs), "seconds": round(time.time() - t0, 1),
        "expected": exp,
        "confirm_rate": round(confirm_rate, 3),
        "assigned": _dist([r["assigned"] for r in runs]),
        "point_grade": _dist([r["point_grade"] for r in runs]),
        "theta_hat": _stat([r["theta"] for r in runs]), "se": _stat([r["se"] for r in runs]),
        "n_items": _stat([r["n_items"] for r in runs]), "time_min": _stat([r["time_min"] for r in runs]),
        "extension_share": round(float(np.mean([r["n_ext"] > 0 for r in runs])), 3),
        "correct_share": round(float(np.mean([r["correct"] / r["answered"] if r["answered"] else 0 for r in runs])), 3),
        "stops": _dist([r["stop"] for r in runs]),
        "theta_hat_max": round(float(np.mean(ceilings)), 2) if ceilings else None,
        "runs": [{k: r[k] for k in ("theta", "se", "confirmed", "point_grade", "n_items", "n_ext", "time_min", "stop",
                                    "correct", "answered")} for r in runs],
    }
    if repeat:
        c1 = np.array([r["confirmed"] for r in first]); c2 = np.array([r["confirmed"] for r in second])
        g1 = [r["point_grade"] for r in first]; g2 = [r["point_grade"] for r in second]
        t1 = np.array([r["theta"] for r in first]); t2 = np.array([r["theta"] for r in second])
        idx = {"none": 0, "junior": 1, "middle": 2, "senior": 3}
        gi1 = np.array([idx[g] for g in g1]); gi2 = np.array([idx[g] for g in g2])
        rt = {"decision_agreement": round(float(np.mean(c1 == c2)), 3),
              "grade_exact_agreement": round(float(np.mean(gi1 == gi2)), 3),
              "grade_within_1": round(float(np.mean(np.abs(gi1 - gi2) <= 1)), 3),
              "mean_abs_diff_theta": round(float(np.mean(np.abs(t1 - t2))), 3),
              "mean_se": round(float(np.mean(np.r_[[r["se"] for r in first], [r["se"] for r in second]])), 3)}
        rt["note"] = ("У всех кандидатов здесь один истинный уровень, поэтому разброс θ̂ между попытками — это и есть "
                      "погрешность теста: ожидаемая |Δθ| ≈ 1,13 · SE. Корреляция повторов по таким данным не показательна "
                      "(нет разброса истины) и не считается; ретест-надёжность на разных уровнях — в разделе «Стабильность».")
        out["retest"] = rt
    out["verdict"] = _verdict(out, exp)
    return out


def _verdict(out: dict, exp: dict) -> dict:
    """Вердикт с честной подписью (label): «Как и ожидалось» — разрыв с ожиданием в пределах 2 σ биномиального шума
    выборки; «В допуске выборки, разрыв N п. п.» — больше 2 σ, но в пределах допуска 2 σ + 10 п. п. (разрыв назван, а не спрятан
    за «как ожидалось»); «Расхождение с ожиданием, разрыв N п. п.» — вне допуска."""
    cr = out["confirm_rate"]
    n = out["runs_total"]
    kind, gap_pp = "exact", None
    if exp.get("confirm_rate") is not None:
        # уровень θ: сравниваем с модельным ожиданием с допуском на случайность выборки (2 σ биномиального) и 10 п.п.
        e = exp["confirm_rate"]
        band = 2 * math.sqrt(max(e * (1 - e), 0.0225) / n)
        tol = band + 0.10
        gap = abs(cr - e)
        gap_pp = round(gap * 100)
        ok = gap <= tol
        kind = "exact" if gap <= band else ("tolerance" if ok else "mismatch")
        text = (f"Подтверждений {round(cr * 100)} % при модельном ожидании {round(e * 100)} %: разрыв {gap_pp} п. п. при шуме выборки "
                f"± {round(band * 100)} п. п. (2 σ на {n} прогонов) и допуске ± {round(tol * 100)} п. п.")
        if kind == "tolerance":
            text += " Разрыв больше шума выборки, но в пределах допуска модели: при таком числе прогонов он не доказывает смещения теста."
        text += "." if not text.endswith(".") else ""
    elif exp["confirmed"] is True:
        ok = cr >= 0.8
        text = f"Подтверждений {round(cr * 100)} % при ожидаемых ≥ 80 %."
    elif exp["confirmed"] is False:
        ok = cr <= 0.2
        text = f"Подтверждений {round(cr * 100)} % при ожидаемых ≤ 20 % (ложные подтверждения)."
    else:
        ok = cr <= 0.2
        text = f"Подтверждений {round(cr * 100)} %; доля верных ответов {round(out['correct_share'] * 100)} %."
        if not ok:
            text += (" Грейд подтверждается кандидату, который не знает направления: общий блок — 40 % заданий, и при их "
                     "полном знании одномерная оценка θ выходит за порог. Известное ограничение: решение не проверяет блок "
                     "направления отдельно.")
    rt = out.get("retest")
    if rt:
        text += f" Повтор: решение совпало у {round(rt['decision_agreement'] * 100)} %, грейд точно — у {round(rt['grade_exact_agreement'] * 100)} %, |Δθ| в среднем {str(rt['mean_abs_diff_theta']).replace('.', ',')}."
    if out["mode"] == "express":
        text += " Экспресс-режим: интервал шире, подтверждение у порога даётся реже — это ожидаемо."
    n_items = out["n_items"]
    text += f" Длина: {str(n_items['mean']).replace('.', ',')} заданий в среднем ({n_items['min']}–{n_items['max']}), " \
            f"расчётное время {str(out['time_min']['mean']).replace('.', ',')} мин (40–90 % рекомендуемого времени " \
            "заданий; живой кандидат обычно быстрее)."
    if kind == "exact":
        label = "Как и ожидалось" if ok else "Расхождение с ожиданием"
    elif kind == "tolerance":
        label = f"В допуске выборки, разрыв {gap_pp} п. п."
    else:
        label = f"Расхождение с ожиданием, разрыв {gap_pp} п. п."
    return {"ok": bool(ok), "kind": kind, "label": label, "gap_pp": gap_pp, "text": text}
