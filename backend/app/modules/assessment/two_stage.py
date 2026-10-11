"""Двухэтапное подтверждение уровня у границы (флаг ASSESSMENT_TWO_STAGE_ENABLED, по умолчанию выключен).

Одна сессия теста (≤ 60 мин) заканчивается с погрешностью SE ≈ 0,33–0,40: у кандидатов, чей уровень близко к порогу,
решение по одной сессии — почти монетка (docs/validation/GRADE_ACCURACY.md: потолок одной сессии ≈ 65–74 % точных
попаданий). Двухэтапная схема: после основного теста кандидату «на границе» предлагается **уточнение уровня** —
отдельная короткая сессия (10–15 мин) только из заданий у этой границы, из других семейств (без повторов прошлых сессий,
с контролем частоты показа). Итог считается по ответам обеих сессий вместе (одна общая апостериорная оценка θ), а не
по второй сессии отдельно.

Правила (общие для продукта и симуляции ``app.modules.validation.two_stage``; значения — настройки, выбраны на симуляции):

* **«На границе»** (``boundary``): после сессии с заявленным грейдом c итог g (подтверждён c, принят уровень ниже,
  «предварительно» или без категории), оценка θ̂ ± SE. Рассматриваются пороги уровней от g (от Стажёра, если категории
  нет) до c включительно. Граница есть, если у одного из них P(θ ≥ порога) лежит строго между 1 − L и L
  (L = ``assessment_two_stage_level``; то же, что |θ̂ − порог| < z_L · SE, z_L = Φ⁻¹(L)) — берётся порог с
  вероятностью, ближайшей к 0,5: «keep» — уровень итога под вопросом, «up» — возможно, уровень выше итога (до заявленного).
  Режим «выше заявленного» (``above`` > 0): если на заявленном уровне границы нет и у порога уровня выше заявленного
  P ≥ ``above`` — граница «above» у наивысшего такого порога (тест на заявленный грейд выше его не поднимает).
  **Lead/Principal** (флаг GRADES_EXT_ENABLED, пометка «предварительно» — catalog.levels): если границы по правилу выше
  нет, второй этап всё равно предлагается — граница «ext» у порога своего уровня (Senior/Lead для Lead, Lead/Principal
  для Principal): точность различения этих уровней одной сессией ниже цели (docs/validation/GRADES_EXT_NEED.md).
  Шкала уровней — направления (``catalog.levels.available_grades``): выше уровня, который банк направления не
  проверяет, ни граница, ни итог не поднимаются.
* **До уточнения** уровень — по первой сессии (не выше, чем позволяет она), с пометкой «на границе: можно уточнить».
* **Вторая сессия** (``RefineSession``): ответы первой сессии перенесены (в θ и в детектор предзнания, заново не
  показываются); новые задания — короткие (лимит ≤ 5 мин), с наибольшей информацией в выбранном пороге, семейства
  прошлых сессий исключены, частота показа — Sympson — Hetter как в основном тесте. Не больше N заданий
  (``assessment_two_stage_items``) и M минут (``assessment_two_stage_minutes``); досрочный стоп, когда после
  ``MIN_NEW`` заданий порог вышел из θ̂ ± z_L · SE.
* **Итог** (``final_grade``): наивысший уровень, доказанный общей оценкой обеих сессий: до заявленного включительно —
  с P ≥ c₂ (``assessment_two_stage_confirm``), выше заявленного — с P ≥ c↑ (``assessment_two_stage_confirm_up``,
  строже: повышение без запаса даёт завышение). Итог может быть и ниже уровня первой сессии, если общая оценка его не
  держит. Уровень — только по тесту (FTT.4).

Всё, что проверено, — на синтетике (модель, не люди): docs/validation/TWO_STAGE.md.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from assessment_bank.psychometrics import PoolItem

from app.modules.assessment.exposure import AppCATSession
from app.modules.assessment.grades import p_at_least
from app.modules.catalog.seed_data import EXT_GRADE_ORDER, GRADE_CUTS, GRADE_ORDER

# Значения по умолчанию — выбор на симуляции (docs/validation/TWO_STAGE.md); настройки — app.core.config
DEFAULT_LEVEL = 0.8
DEFAULT_ITEMS = 8
DEFAULT_MINUTES = 15
DEFAULT_CONFIRM = 0.45  # по make two-stage 11.10 (docs/validation/TWO_STAGE.md): лучше одной сессии по всем ограничениям
DEFAULT_CONFIRM_UP = 0.9
DEFAULT_ABOVE = 0.0    # 0 — уточнение «выше заявленного» не предлагается
MIN_NEW = 3            # не меньше 3 новых заданий: подтверждение — новыми ответами, а не одной первой сессией
ITEM_TIME_S = 300.0    # только короткие задания (как дотестирование у порога)


def _z(level: float) -> float:
    """Φ⁻¹(level) без scipy (бисекция по erf): уровень 0,5–0,999."""
    lo, hi = 0.0, 6.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < level:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _rank(grade: str) -> int:
    return -1 if grade in (None, "none") else GRADE_ORDER.index(grade)


@dataclass(frozen=True)
class Boundary:
    grade: str          # уровень первой сессии
    cut_grade: str      # грейд, порог которого уточняется (граница «ниже cut_grade / cut_grade»)
    cut: float          # порог на шкале θ
    p: float            # P(θ ≥ порога) по первой сессии
    kind: str           # up — возможно, уровень выше; keep — уровень первой сессии под вопросом; above — выше уже вероятен;
    #                     ext — второй этап для Lead/Principal «предварительно» (порог своего уровня)

    @property
    def lower(self) -> str:
        i = GRADE_ORDER.index(self.cut_grade)
        return GRADE_ORDER[i - 1] if i > 0 else "none"

    def as_dict(self) -> dict:
        return {"grade": self.grade, "cut_grade": self.cut_grade, "lower": self.lower, "cut": self.cut,
                "p": round(self.p, 4), "kind": self.kind}


def boundary(theta: float | None, se: float | None, grade: str | None, claimed: str | None = None,
             level: float = DEFAULT_LEVEL, above: float = DEFAULT_ABOVE, order: tuple[str, ...] | None = None,
             ext: bool = False) -> Boundary | None:
    """Граница для уточнения после сессии с заявленным грейдом ``claimed`` и итогом ``grade`` (см. описание модуля)
    или None — уточнять нечего. claimed None — заявленный = итог. order — шкала направления (по умолчанию — все
    уровни платформы); ext — у итога Lead/Principal пометка «предварительно»: второй этап и без границы по правилу."""
    if theta is None or se is None:
        return None
    order = tuple(order or GRADE_ORDER)
    theta, se, grade = float(theta), max(float(se), 1e-6), grade or "none"
    claimed = claimed if claimed in order else (grade if grade in order else order[0])
    lo, hi = max(_rank(grade), 0), _rank(claimed)
    rel = GRADE_ORDER[min(lo, hi):max(lo, hi) + 1]
    probs = {g: p_at_least(theta, se, g) for g in rel}
    band = [g for g in rel if 1 - level < probs[g] < level]
    if band:
        g = min(band, key=lambda x: (abs(probs[x] - 0.5), -_rank(x)))
        kind = "keep" if _rank(g) <= _rank(grade) else "up"
        return Boundary(grade, g, float(GRADE_CUTS[g]), probs[g], kind)
    if ext and grade in EXT_GRADE_ORDER and grade in order:  # Lead/Principal «предварительно»: порог своего уровня
        return Boundary(grade, grade, float(GRADE_CUTS[grade]), p_at_least(theta, se, grade), "ext")
    if above > 0 and _rank(grade) >= _rank(claimed):
        ups = [g for g in order if _rank(g) > _rank(claimed) and p_at_least(theta, se, g) >= above]
        if ups:
            g = ups[-1]
            return Boundary(grade, g, float(GRADE_CUTS[g]), p_at_least(theta, se, g), "above")
    return None


def final_grade(theta: float, se: float, claimed: str | None = None, confirm: float = DEFAULT_CONFIRM,
                confirm_up: float = DEFAULT_CONFIRM_UP, order: tuple[str, ...] | None = None) -> str:
    """Итог по общей оценке обеих сессий: наивысший уровень с P(θ ≥ порога) ≥ confirm (до заявленного включительно)
    или ≥ confirm_up (выше заявленного). Без потолка длины: вторая сессия добавляет задания к первой. order — шкала
    направления (выше уровня, который банк направления не проверяет, итог не поднимается)."""
    order = tuple(order or GRADE_ORDER)
    cr = order.index(claimed) if claimed in order else len(order)
    out = "none"
    for i, g in enumerate(order):
        if p_at_least(float(theta), float(se), g) >= (confirm if i <= cr else confirm_up):
            out = g
    return out


def stop_z(level: float) -> float:
    return _z(level)


class RefineSession(AppCATSession):
    """Вторая сессия: перенесённые ответы первой (``record_prior``) + короткие задания у порога ``cut``.

    Выбор — ``CATSession._pick`` по информации в пороге (контроль частоты показа), кандидаты —
    ``AppCATSession._ext_candidates`` (короткие задания всего банка направления без семейств первой сессии, лимиты
    форматов, при исчерпании — давно виденные из прошлых попыток с новым вариантом). Лимит времени — от начала второй
    сессии: cfg.max_time_s = время первой, cfg.ext_time_s = минуты второй.
    """

    def __init__(self, *args, cut: float, n_new: int, min_new: int = MIN_NEW, z_stop: float = 1.28, **kwargs):
        kwargs.setdefault("ext_lru", True)
        super().__init__(*args, **kwargs)
        self.cut, self.n_new_max, self.min_new, self.z_stop = float(cut), int(n_new), int(min_new), float(z_stop)
        self.n_prior = 0
        self.ext_start = 0
        self.ext_cut = self.cut

    def record_prior(self, adms, items: dict[str, PoolItem], time_s: float) -> None:
        """Ответы первой сессии без пересчёта θ на каждом шаге (итог тот же: одна EAP по всем ответам)."""
        for adm in adms:
            self.items.setdefault(adm.family_id, items[adm.family_id])
            self.administered.append(adm)
            self.used.add(adm.family_id)
        self.time_used = float(time_s)
        self.n_prior = self.n_scored
        self.ext_start = self.n_prior
        if self.n_prior:
            self._update_theta()

    @property
    def n_new(self) -> int:
        return self.n_scored - self.n_prior

    def next_item(self) -> PoolItem | None:
        if self.n_new >= self.n_new_max:
            self.stop_reason = "refine_done"
            return None
        if self.n_new >= self.min_new and abs(self.theta - self.cut) >= self.z_stop * self.se:
            self.stop_reason = "refine_classified"
            return None
        cands = self._ext_candidates()
        if not cands:
            self.stop_reason = "refine_pool_exhausted" if self.n_new else "refine_no_items"
            return None
        if self.cfg.ext_own_first and self.subpool is not None:
            cands = [i for i in cands if i.subpool == self.subpool] or cands
        return self._pick(cands, self.cut)



# ---------------------------------------------------------------- продукт (флаг ASSESSMENT_TWO_STAGE_ENABLED)

TITLE = {"none": "без категории", "intern": "Стажёр", "junior": "Junior", "middle": "Middle", "senior": "Senior",
         "lead": "Lead", "principal": "Principal"}


def _order(direction: str | None) -> tuple[str, ...]:
    """Шкала уровней направления: без флага GRADES_EXT_ENABLED — прежние 4, с флагом — и Lead/Principal по банку."""
    from app.modules.catalog import levels

    return tuple(levels.available_grades(direction)) if direction else GRADE_ORDER


def _ext(grade: str | None) -> bool:
    from app.modules.catalog import levels

    return bool(levels.ext_preliminary(grade))


def params() -> dict:
    """Настройки двухэтапного подтверждения (app.core.config)."""
    from app.core.config import get_settings

    s = get_settings()
    return {"enabled": bool(s.assessment_two_stage_enabled), "level": float(s.assessment_two_stage_level),
            "items": int(s.assessment_two_stage_items), "minutes": int(s.assessment_two_stage_minutes),
            "confirm": float(s.assessment_two_stage_confirm), "confirm_up": float(s.assessment_two_stage_confirm_up),
            "above": float(s.assessment_two_stage_above), "floor": bool(s.assessment_two_stage_floor)}


def enabled() -> bool:
    return params()["enabled"]


def _state(ts) -> dict:
    return (ts.result or {}).get("state") or {}


def mode_of(ts) -> str:
    r = ts.result or {}
    return r.get("mode") or _state(ts).get("mode") or "full"


def session_grade(ts) -> str:
    """Уровень по завершённой полной сессии — как путь симуляции: подтверждён заявленный; «Junior (предварительно)»;
    принятый уровень ниже; иначе — уровень ниже заявленного, доказанный тем же тестом (его можно принять без нового
    теста), или без категории."""
    from app.modules.assessment.grades import confirm_level

    r = ts.result or {}
    er = r.get("engine_result") or {}
    acc = (r.get("outcome") or {}).get("accepted_lower")
    if acc:
        return acc
    if er.get("confirmed"):
        return ts.claimed_grade_id
    if er.get("provisional"):
        return "junior"
    th, se = er.get("theta"), er.get("se")
    if th is None or se is None or ts.claimed_grade_id not in GRADE_ORDER:
        return "none"
    lvl = confirm_level(se)
    lower = [g for g in GRADE_ORDER[:GRADE_ORDER.index(ts.claimed_grade_id)] if p_at_least(th, se, g) >= lvl]
    return lower[-1] if lower else "none"


def session_boundary(ts, p: dict | None = None) -> Boundary | None:
    """Граница для уточнения по завершённой полной сессии банка (экспресс, дотестирование и уточнение — нет)."""
    from app.core.enums import TestSessionStatus

    p = p or params()
    r = ts.result or {}
    if ts.status != TestSessionStatus.finished or mode_of(ts) != "full" or not str(r.get("engine", "")).startswith("bank"):
        return None
    er = r.get("engine_result") or {}
    g = session_grade(ts)
    return boundary(er.get("theta"), er.get("se"), g, ts.claimed_grade_id, level=p["level"], above=p["above"],
                    order=_order(ts.direction_id), ext=_ext(g))


def label(b: dict) -> str:
    return f"на границе {TITLE.get(b.get('lower'), b.get('lower'))}/{TITLE.get(b.get('cut_grade'), b.get('cut_grade'))}"


def _refines(db, ts) -> list:
    from sqlalchemy import select

    from app.core.enums import TestSessionStatus
    from app.modules.assessment.models import TestSession

    rows = db.scalars(select(TestSession).where(
        TestSession.user_id == ts.user_id, TestSession.direction_id == ts.direction_id,
        TestSession.status != TestSessionStatus.aborted).order_by(TestSession.created_at.desc()).limit(30)).all()
    return [t for t in rows if mode_of(t) == "refine"
            and (_state(t).get("refine") or {}).get("source_session_id") == str(ts.id)]


def latest_full(db, user_id, direction: str):
    """Последняя завершённая полная сессия банка в направлении — основа уточнения."""
    from sqlalchemy import select

    from app.core.enums import TestSessionStatus
    from app.modules.assessment.models import TestSession

    rows = db.scalars(select(TestSession).where(
        TestSession.user_id == user_id, TestSession.direction_id == direction,
        TestSession.status == TestSessionStatus.finished).order_by(TestSession.finished_at.desc()).limit(20)).all()
    for t in rows:
        if mode_of(t) == "refine":
            return None  # после уточнения новое уточнение — только после нового полного теста
        if mode_of(t) == "full" and str((t.result or {}).get("engine", "")).startswith("bank"):
            return t
    return None


def offer(db, ts) -> dict | None:
    """Блок «на границе: можно уточнить» для итога полной сессии (None — флаг выключен или границы нет)."""
    p = params()
    if not p["enabled"]:
        return None
    b = session_boundary(ts, p)
    if b is None:
        return None
    from app.core.enums import TestSessionStatus

    refs = _refines(db, ts)
    last = latest_full(db, ts.user_id, ts.direction_id)
    active = next((t for t in refs if t.status == TestSessionStatus.in_progress), None)
    done = next((t for t in refs if t.status == TestSessionStatus.finished), None)
    bd = b.as_dict()
    text = (f"Уровень {label(bd)}: одна сессия теста не отделяет эти уровни уверенно. Можно уточнить уровень "
            f"за 10–{p['minutes']} минут — до {p['items']} коротких заданий у этой границы из новых семейств; "
            "итог считается по ответам обеих сессий вместе и может оказаться как выше, так и ниже нынешнего.")
    if b.kind == "ext":
        text = (f"{TITLE.get(b.grade, b.grade)} по тесту — предварительно. Второй этап — до {p['items']} коротких "
                f"заданий у границы {TITLE.get(bd['lower'], bd['lower'])}/{TITLE.get(b.cut_grade, b.cut_grade)} из новых "
                f"семейств, 10–{p['minutes']} минут; итог считается по ответам обеих сессий вместе и может оказаться как "
                "выше, так и ниже нынешнего. Пометка «предварительно» у Lead/Principal остаётся и после второго этапа: "
                "банк заданий этих уровней пока мал (модель, не люди; /validation, «Lead и Principal»).")
    out = {"boundary": bd, "label": label(bd), "items": p["items"], "minutes": p["minutes"], "ext": b.kind == "ext",
           "status": "done" if done else ("in_progress" if active else "offered"),
           "available": bool(not refs and last is not None and last.id == ts.id),
           "refine_session_id": str((done or active).id) if (done or active) else None,
           "outcome": outcome(done) if done else None, "text": text}
    return out


def current_offer(db, user_id, direction: str | None) -> dict | None:
    """Предложение по последней полной сессии направления — для экрана «Категория и грейд» (статус теста):
    «можно уточнить» / уточнение идёт / итог уточнения. None — флаг выключен, полной сессии нет или границы нет."""
    if not direction or not enabled():
        return None
    from sqlalchemy import select

    from app.core.enums import TestSessionStatus
    from app.modules.assessment.models import TestSession

    rows = db.scalars(select(TestSession).where(
        TestSession.user_id == user_id, TestSession.direction_id == direction,
        TestSession.status == TestSessionStatus.finished).order_by(TestSession.finished_at.desc()).limit(20)).all()
    for t in rows:
        if mode_of(t) == "full" and str((t.result or {}).get("engine", "")).startswith("bank"):
            off = offer(db, t)
            return {**off, "session_id": str(t.id), "direction": direction} if off else None
    return None


def outcome(ts) -> dict | None:
    """Итог уточнения (сессия mode=refine): граница, уровень до и после, пройдено ли."""
    if ts is None or mode_of(ts) != "refine":
        return None
    d = (((ts.result or {}).get("engine_result") or {}).get("details") or {}).get("two_stage")
    return dict(d) if d else None


def refine_result(state: dict, theta: float, se: float, n_new: int) -> dict:
    """Итог уточнения для движка (bank_engine.finish): уровень по общей оценке обеих сессий."""
    rf = state.get("refine") or {}
    claimed = state.get("claimed_grade")
    f = final_grade(theta, se, claimed, float(rf.get("confirm", DEFAULT_CONFIRM)),
                    float(rf.get("confirm_up", DEFAULT_CONFIRM_UP)), order=_order(state.get("direction")))
    if rf.get("floor") and _rank(f) < _rank(rf.get("grade") or "none"):  # итог не ниже первой сессии
        f = rf["grade"]
    cut_g = rf.get("cut_grade")
    passed = bool(cut_g in GRADE_ORDER and _rank(f) >= _rank(cut_g))
    b = {k: rf.get(k) for k in ("grade", "cut_grade", "lower", "cut", "p", "kind")}
    return {**b, "label": label(b), "claimed": claimed, "grade_before": rf.get("grade"), "final_grade": f,
            "passed": passed, "theta_before": rf.get("theta_before"), "se_before": rf.get("se_before"),
            "theta": round(float(theta), 4), "se": round(float(se), 4), "new_items": int(n_new),
            "source_session_id": rf.get("source_session_id"), "confirm": rf.get("confirm"),
            "confirm_up": rf.get("confirm_up")}


def explain(o: dict) -> str:
    """Текст итога уточнения для кандидата."""
    f, before = o.get("final_grade"), o.get("grade_before")
    s = (f"Уточнение уровня ({o.get('label')}): к ответам основного теста добавлено новых коротких заданий — "
         f"{o.get('new_items')}, уровень посчитан по ответам обеих сессий вместе. ")
    if f == "none":
        s += "Общая оценка не подтверждает ни один уровень; принудительного понижения нет — прежняя категория сохраняется."
    elif f == before:
        s += f"Итог — {TITLE.get(f, f)}, как и после основного теста."
    else:
        s += f"Итог — {TITLE.get(f, f)} (после основного теста было: {TITLE.get(before, before)})."
    return s + (" Уточнение пройдено." if o.get("passed") else " Уточнение не подтвердило уровень у границы.")


def fact_payload(db, ts) -> dict | None:
    """Пометка в факте результата теста (карточка работодателя, подборка): граница и уточнение."""
    if not enabled():
        return None
    if mode_of(ts) == "refine":
        o = outcome(ts)
        if not o:
            return None
        return {"status": "passed" if o["passed"] else "failed", "label": o["label"], "cut_grade": o["cut_grade"],
                "lower": o["lower"], "kind": o["kind"], "grade_before": o["grade_before"], "final_grade": o["final_grade"],
                "new_items": o["new_items"]}
    off = offer(db, ts)
    if not off:
        return None
    b = off["boundary"]
    return {"status": "offered", "label": off["label"], "cut_grade": b["cut_grade"], "lower": b["lower"],
            "kind": b["kind"], "grade_before": b["grade"]}


def card_note(value: dict | None) -> dict | None:
    """Пометка для работодателя из факта test_result: «на границе Middle/Senior — уточнение пройдено / не пройдено»."""
    t = (value or {}).get("two_stage")
    if not t or not enabled():
        return None
    st = t.get("status")
    lab = t.get("label") or ""
    oral, oral_text = oral_mark(value)
    if st == "passed":
        text = f"{lab[:1].upper()}{lab[1:]} — уточнение пройдено: {TITLE.get(t.get('final_grade'), '')} по двум сессиям теста"
    elif st == "failed":
        fin = t.get("final_grade")
        text = (f"{lab[:1].upper()}{lab[1:]} — уточнение не пройдено"
                + (f": {TITLE.get(fin, fin)} по двум сессиям теста" if fin and fin != "none" else ""))
    elif oral:  # п. 4: устная защита меняет пометку «на границе», не уровень
        text = f"{lab[:1].upper()}{lab[1:]} — {oral_text}"
    else:
        text = f"{lab[:1].upper()}{lab[1:]} — уточнение уровня не проходил (одна сессия теста)"
    if oral and st in ("passed", "failed"):
        text += f" · устная защита: {oral_text}"
    return {**t, "text": text, "oral": oral}


ORAL = {"confirmed": ("confirmed", "подтверждено устной защитой"), "strong": ("confirmed", "подтверждено устной защитой"),
        "discrepancies": ("check", "требует проверки"), "weak": ("check", "требует проверки")}


def oral_mark(value: dict | None) -> tuple[str | None, str | None]:
    """Устная защита ответов теста (модуль interview, флаг INTERVIEW_ENABLED) как дополнительное доказательство у границы:
    уровень не меняет (FTT.4), меняет пометку — «подтверждено устной защитой» / «требует проверки»; «мало данных» и
    пример модельного кандидата пометку не меняют."""
    d = (value or {}).get("defense") or {}
    if not d.get("verdict") or d.get("example"):
        return None, None
    try:
        from app.modules.interview.service import enabled as interview_on
    except ImportError:  # модуля интервью нет в сборке
        return None, None
    if not interview_on():
        return None, None
    return ORAL.get(d["verdict"], (None, None))


def as_result(ts, res):
    """Итог движка для сессии уточнения → итог продукта: заявленным становится уровень по двум сессиям (если он
    есть), дальше — обычные правила записи категории (apply_engine_result). Исходный заявленный — в details."""
    from dataclasses import replace

    o = (res.details or {}).get("two_stage") or {}
    f = o.get("final_grade") or "none"
    text = explain(o)
    if f == "none":
        return replace(res, confirmed=False, provisional=False, provisional_reason=None, upgrade_available=False,
                       retake_lower=None, explanation=text)
    ts.claimed_grade_id = f
    return replace(res, claimed_grade=f, confirmed=True, provisional=False, provisional_reason=None,
                   upgrade_available=False, retake_lower=None, explanation=text,
                   p_claimed=round(p_at_least(res.theta, res.se, f), 4))


def view(db, ts) -> dict | None:
    """Блок two_stage итога теста: для полной сессии — предложение (offer), для уточнения — его итог."""
    if not enabled():
        return None
    if mode_of(ts) == "refine":
        o = outcome(ts)
        if not o:
            return None
        return {"status": "passed" if o["passed"] else "failed", "label": o["label"], "refine": o,
                "text": explain(o), "source_session_id": o.get("source_session_id")}
    return offer(db, ts)


def mark_fact(db, ts) -> None:
    """Итог уточнения — в факт результата теста направления (если факт не переписан итогом, например при «none»)."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.enums import FactSource
    from app.modules.profiles.models import CandidateFact

    v = fact_payload(db, ts)
    if not v:
        return
    for f in db.scalars(select(CandidateFact).where(
            CandidateFact.user_id == ts.user_id, CandidateFact.source == FactSource.test,
            CandidateFact.kind == "test_result")).all():
        if (f.value or {}).get("direction") == ts.direction_id and (f.value or {}).get("two_stage") != v:
            f.value = {**f.value, "two_stage": v}
            flag_modified(f, "value")
