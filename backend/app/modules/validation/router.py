"""Страница /validation («Как мы проверяем себя») и «Красная кнопка жюри».

Отчёт — публичный. Атаки — только после входа (любая роль; в режиме жюри фронтенд сам входит под демо-персоной
своей песочницы — кнопка остаётся «в один клик»), с лимитом частоты на пользователя и общим лимитом;
need_id — только потребность своей компании; симуляция утечки — из кэша (attacks.leak_cached).
"""
from __future__ import annotations

from functools import lru_cache
import datetime as dt
import json
from pathlib import Path
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, release
from app.core.deps import get_current_user
from app.core.enums import TestSessionStatus, UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, hit
from app.modules.assessment.models import TestSession
from app.modules.auth.models import User
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.models import EmployerProfile
from app.modules.validation import attacks, selfcheck

router = APIRouter(prefix="/api/validation", tags=["validation"])
from app.modules.validation.closed_set import router as closed_set_router

router.include_router(closed_set_router)
REPORT = Path(__file__).resolve().parent / "data" / "report.json"
INTERN_CUT = Path(__file__).resolve().parent / "data" / "intern_cut.json"
# Лимиты «Красной кнопки» (на воркер): 12 атак в минуту на пользователя, 90 в минуту всего
_per_user = SlidingWindow(12, 60)
_global = SlidingWindow(90, 60)
# «Проверьте сами»: до 20 кандидатов × 2 попытки за запрос; не чаще 6 запусков в минуту на пользователя, 30 всего
_sc_user = SlidingWindow(6, 60)
_sc_global = SlidingWindow(30, 60)


@lru_cache(maxsize=1)
def _report() -> dict:
    if not REPORT.exists():
        return {"missing": True}
    return json.loads(REPORT.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _intern_cut() -> dict:
    """Обоснование порога Стажёра (пересчёт: python -m app.modules.validation.intern_cut) — без сырых строк."""
    if not INTERN_CUT.exists():
        return {"missing": True}
    d = json.loads(INTERN_CUT.read_text(encoding="utf-8"))
    from app.modules.assessment.intern_pool import intern_pool_summary
    from app.modules.catalog.seed_data import GRADE_CUTS

    return {k: d.get(k) for k in ("generated_at", "n_per_theta", "candidate_cuts", "rule", "config", "by_cut",
                                  "with_easy_families", "retest", "chosen", "current_bank_rule", "pool")} | {
        "cut_in_use": GRADE_CUTS["intern"], "pool_now": {d_: intern_pool_summary(d_) for d_ in d.get("directions", [])}}


def _live(db: Session) -> dict:
    from app.modules.assessment.exposure import exposure_table
    from app.modules.assessment.review import agreement

    rows = db.scalars(select(TestSession).where(TestSession.status == TestSessionStatus.finished)
                      .order_by(TestSession.created_at.desc()).limit(2000)).all()
    bank = [t for t in rows if str((t.result or {}).get("engine", "")).startswith("bank")]
    levels = {"high": 0, "medium": 0, "low": 0}
    flagged = 0
    for t in bank:
        d = ((t.result or {}).get("engine_result") or {}).get("details") or {}
        lv = (d.get("integrity") or {}).get("level")
        if lv in levels:
            levels[lv] += 1
        flagged += 1 if (d.get("preknowledge") or {}).get("flagged") else 0
    total = db.scalar(select(func.count()).select_from(TestSession)) or 0
    exp = exposure_table() or {}
    return {"sessions_total": total, "bank_sessions_finished": len(bank), "integrity": levels,
            "preknowledge_flagged": flagged, "expert_llm_agreement": agreement(db),
            "exposure_k": {"generated_at": exp.get("generated_at"), "r_max": exp.get("r_max"),
                           "families_limited": {d: len(v) for d, v in (exp.get("k") or {}).items()}}}


def _report_body(db: Session) -> dict:
    from app.modules.experts.section import section as experts_section

    from app.modules.validation.provenance import experts_stamp, provenance  # Ф6 (Н7), Я8: подписи и происхождение

    ex = experts_section(db)
    return {**_report(), "provenance": {**provenance(_report()), "experts": experts_stamp(ex)}, "live": _live(db),
            "attacks": attacks.ATTACKS, "experts": ex,
            "intern_cut": _intern_cut(),
            "self_check": {"strategies": selfcheck.STRATEGIES, "max_n": selfcheck.MAX_N,
                           "directions": list(selfcheck.DIRECTIONS)}}


# Готовый ответ /report (байты JSON) на воркер: VALIDATION_REPORT_TTL_S секунд. 10.10 под нагрузкой 100 пользователей
# отчёт считался на каждый запрос (до 2000 сессий из БД, экспертный раздел, 105 КБ JSON): p50 4,1 с, p95 21 с, 504 —
# и всё это время держал соединение с БД. Теперь считает один поток, остальные получают прошлый ответ (не старше TTL,
# пока идёт пересчёт — прошлый); соединение возвращается в пул до сериализации. 0 — без кэша (тесты).
_rep_cache: dict = {}
_rep_lock = threading.Lock()


def _report_bytes(db: Session) -> bytes:
    data = _report_body(db)
    release(db)  # дальше — только CPU: соединение не держим
    return json.dumps(jsonable_encoder(data), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


@router.get("/report", summary="Метрики валидации (пересчёт: make validate)",
            description="Ответ кэшируется на воркер на VALIDATION_REPORT_TTL_S секунд (живые счётчики — с этой задержкой).")
def report(db: Session = Depends(get_db)):
    ttl = get_settings().validation_report_ttl_s
    if ttl <= 0:
        return _report_body(db)
    body, at = _rep_cache.get("body"), _rep_cache.get("at", 0.0)
    if body is not None and time.monotonic() - at < ttl:
        return Response(body, media_type="application/json")
    if not _rep_lock.acquire(blocking=body is None):  # пересчёт уже идёт — прошлый ответ
        return Response(body, media_type="application/json", headers={"X-Report-Stale": "1"})
    try:
        body, at = _rep_cache.get("body"), _rep_cache.get("at", 0.0)
        if body is None or time.monotonic() - at >= ttl:  # пока ждали блокировку, мог посчитать другой поток
            body = _report_bytes(db)
            _rep_cache.update(body=body, at=time.monotonic())
        return Response(body, media_type="application/json")
    finally:
        _rep_lock.release()


class AttackIn(BaseModel):
    need_id: uuid.UUID | None = None
    leak_share: float = Field(0.3, ge=0.1, le=0.8)
    direction: str | None = None


def _own_need(db: Session, user: User, need_id: uuid.UUID) -> uuid.UUID:
    """need_id — только потребность компании текущего работодателя (иначе 404, как для несуществующей)."""
    ep = db.get(EmployerProfile, user.id) if user.role == UserRole.employer else None
    n = db.get(EmployerNeed, need_id)
    if ep is None or n is None or n.company_id != ep.company_id:
        raise api_error(404, "need_not_found", "Потребность не найдена")
    return need_id


@router.post("/attacks/{attack_id}", summary="Запустить атаку «Красной кнопки» (вход обязателен, ничего не записывается)",
             responses={401: err("Не выполнен вход"), 404: err("Нет такой атаки или потребности"),
                        429: err("Слишком частые запуски")})
def run_attack(attack_id: str, data: AttackIn | None = None, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    data = data or AttackIn()
    if attack_id not in {a["id"] for a in attacks.ATTACKS}:
        raise api_error(404, "attack_not_found", "Нет такой атаки")
    hit(_per_user, str(user.id), "attack_rate", "Слишком часто: не больше 12 атак в минуту")
    hit(_global, "all", "attack_rate_global", "Красную кнопку сейчас нажимают слишком часто")
    if attack_id == "leak_bank":
        release(db)  # симуляция утечки — без БД (кэш на процесс), секунды CPU: соединение в пул
        try:
            return attacks.run(db, attack_id, None, {"leak_share": data.leak_share, "direction": data.direction})
        except attacks.AttackBusy:
            raise api_error(429, "attack_busy", "Симуляция утечки уже идёт, повторите через несколько секунд") from None
    need_id = _own_need(db, user, data.need_id) if data.need_id else None
    return attacks.run(db, attack_id, need_id)


class SelfCheckIn(BaseModel):
    strategy: str = Field("level_middle", description="theta | level_junior | level_middle | level_senior | all_correct | "
                                                      "all_wrong | random | common_only")
    theta: float | None = Field(None, ge=-3, le=3, description="Истинный уровень для strategy=theta")
    direction: str = Field("backend")
    claimed_grade: str = Field("middle", pattern="^(junior|middle|senior)$")
    n: int = Field(10, ge=1, le=selfcheck.MAX_N, description="Сколько синтетических кандидатов")
    repeat: bool = Field(True, description="Вторая попытка каждого кандидата на другом субпуле — согласие повторов")
    mode: str = Field("full", pattern="^(full|express)$", description="full — обычный тест, express — экспресс-тест жюри")
    seed: int | None = Field(None, ge=0, description="Для воспроизводимости; без него — случайный")


@router.post("/self-check",
             summary="«Проверьте сами»: синтетический кандидат проходит N тестов на настоящем движке банка (вход обязателен)",
             description="Настоящий BankEngine, настоящие варианты заданий и ключи, адаптивный выбор, канарейки, "
                         "дотестирование и правило решения — как у живого кандидата; в БД ничего не пишется. Развёрнутые "
                         "ответы синтетический кандидат не пишет — их балл задаёт стратегия, время расчётное. "
                         "Один расчёт за раз (иначе 429 self_check_busy).",
             responses={401: err("Не выполнен вход"), 404: err("Нет такого направления или стратегии"),
                        429: err("Слишком частые запуски или расчёт уже идёт")})
def self_check(data: SelfCheckIn, user: User = Depends(get_current_user)):
    if data.direction not in selfcheck.DIRECTIONS:
        raise api_error(404, "direction_not_found", "Нет такого направления")
    if data.strategy not in {s["id"] for s in selfcheck.STRATEGIES}:
        raise api_error(404, "strategy_not_found", "Нет такой стратегии")
    hit(_sc_user, str(user.id), "self_check_rate", "Слишком часто: не больше 6 проверок в минуту")
    hit(_sc_global, "all", "self_check_rate_global", "«Проверьте сами» сейчас запускают слишком часто")
    try:
        return selfcheck.run(strategy=data.strategy, theta=data.theta, direction=data.direction,
                             claimed=data.claimed_grade, n=data.n, repeat=data.repeat, mode=data.mode, seed=data.seed)
    except selfcheck.Busy:
        raise api_error(429, "self_check_busy", "Проверка уже идёт, повторите через несколько секунд") from None


BENCH = Path(__file__).resolve().parent / "data" / "matching_bench.json"


@lru_cache(maxsize=1)
def _bench() -> dict:
    if not BENCH.exists():
        return {"missing": True}
    return json.loads(BENCH.read_text(encoding="utf-8"))


@router.get("/matching-bench", summary="Бенчмарк подбора со скрытой истиной (пересчёт: make bench)")
def matching_bench():
    from app.modules.validation.provenance import stamp  # Я8

    b = _bench()
    return b if b.get("missing") else {**b, "provenance": stamp("bench", b)}


PATH_RETEST = Path(__file__).resolve().parent / "data" / "path_retest.json"


@router.get("/path-retest", summary="Test–retest всего пути кандидата и D / r_pb семейств (пересчёт: make path-retest)")
def path_retest():
    if not PATH_RETEST.exists():
        return {"missing": True}
    d = json.loads(PATH_RETEST.read_text(encoding="utf-8"))
    d.get("discrimination", {}).pop("families", None)  # полный список — в JSON репозитория, на страницу — слабые
    from app.modules.validation.headline import retest_vs_truth  # Я8: точность к истине рядом с κ
    from app.modules.validation.provenance import stamp

    return {**d, "vs_truth": retest_vs_truth(d), "provenance": stamp("path", d)}


GRADE_SWEEP = Path(__file__).resolve().parent / "data" / "grade_sweep.json"


@router.get("/grade-accuracy", summary="Точность уровня: перебор параметров теста, Парето и выбор (пересчёт: make grade-sweep)")
def grade_accuracy():
    """Я22: компактно для страницы — текущая и прежняя конфигурация, выбор, Парето-фронт основного мира (σ = 0,5),
    другие условия измерения (4 ступени, σ 0,35, 20 заданий, P ≥ 0,5) нашей процедурой. Полный список точек — в JSON."""
    if not GRADE_SWEEP.exists():
        return {"missing": True}
    from app.modules.validation.grade_sweep import compact

    return compact(json.loads(GRADE_SWEEP.read_text(encoding="utf-8")))


from app.modules.catalog.seed_data import GRADES_EXT as _GRADES_EXT  # noqa: E402

if _GRADES_EXT:  # Lead/Principal (флаг GRADES_EXT_ENABLED): без флага маршрута нет — openapi прежний
    @router.get("/grades-ext", summary="Lead и Principal: точность различения 6 уровней и что нужно для цели (модель, не люди)")
    def grades_ext_route():
        from app.modules.validation.grades_ext_view import view

        return view()


TWO_STAGE = Path(__file__).resolve().parent / "data" / "two_stage.json"


@router.get("/two-stage", summary="Двухэтапное подтверждение у границы: одна сессия / две сессии, Парето, выбор "
                                  "(пересчёт: make two-stage)")
def two_stage_route():
    """Я26: сводка симуляции и состояние в продукте (флаг ASSESSMENT_TWO_STAGE_ENABLED и его параметры)."""
    from app.modules.assessment.two_stage import params

    p = params()
    if not TWO_STAGE.exists():
        return {"missing": True, "product": p}
    from app.modules.validation.two_stage import compact

    return {**compact(json.loads(TWO_STAGE.read_text(encoding="utf-8"))), "product": p}


PARTIAL_SIM = Path(__file__).resolve().parent / "data" / "partial_credit_sim.json"
PARTIAL_NOISE = Path(__file__).resolve().parent / "data" / "partial_credit_noise.json"


@router.get("/partial-credit", summary="Частичный балл 0–4 у развёрнутых: «0/1» против «0–4» (синтетика; пересчёт: "
                                       "make partial-credit-sim)")
def partial_credit_route():
    d = json.loads(PARTIAL_SIM.read_text(encoding="utf-8")) if PARTIAL_SIM.exists() else {"missing": True}
    if PARTIAL_NOISE.exists():
        nz = json.loads(PARTIAL_NOISE.read_text(encoding="utf-8"))
        d["grader"] = {k: nz.get(k) for k in ("grader", "reference", "n", "agreement", "intermediate_share_reference",
                                               "set", "points_rule")}
    return {**d, "enabled": bool(get_settings().assessment_partial_credit_enabled)}


@router.get("/test-length", summary="Длина теста для экрана старта: лимиты и итоги симуляции (синтетика, не люди)")
def test_length_route():
    from app.modules.validation.provenance import length_info  # Ф6 (Н8)

    return length_info(_report())


@router.get("/provenance", summary="Происхождение чисел /validation: синтетика/модель/люди, дата, SHA, банк, команда")
def validation_provenance():
    from app.modules.validation.provenance import snapshots  # Я8: снимки расчётов, текущий банк и код

    return snapshots()


@router.get("/headline", summary="Первый экран /validation: 5 чисел с ДИ и подписью мира")
def validation_headline():
    from app.modules.validation.headline import headline
    return headline()


@router.get("/criteria", summary="Страница /criteria: критерии ТЗ → что сделать → что увидите → чем доказано",
            description="Подпункты раздела 6 ТЗ дословно; числа — из тех же расчётов, что /validation, с подписью мира "
                        "(seed, конфигурация, коммит). Источник docs/CRITERIA.md (make criteria-doc).")
def validation_criteria(db: Session = Depends(get_db)):
    from app.modules.validation.criteria import build
    return build(db)


@router.get("/fsp-rating", summary="Парный регрессионный бенчмарк формулы ФСП v1/v2")
def fsp_rating_regression():
    path = BENCH.parent / "fsp_rating_regression_0710.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"missing": True}


STABILITY = Path(__file__).resolve().parent / "data" / "junior_stability.json"


@lru_cache(maxsize=1)
def _stability() -> dict:
    if not STABILITY.exists():
        return {"missing": True}
    return json.loads(STABILITY.read_text(encoding="utf-8"))


@router.get("/junior-stability", summary="Стабильность статуса «Junior (предварительно)» (пересчёт: make stability)")
def junior_stability():
    from app.modules.validation.provenance import stamp  # Я8

    s = _stability()
    return s if s.get("missing") else {**s, "provenance": stamp("stability", s)}


GRADER = Path(__file__).resolve().parent / "data" / "grader_check.json"


@lru_cache(maxsize=1)
def _grader() -> dict:
    if not GRADER.exists():
        return {"missing": True}
    return json.loads(GRADER.read_text(encoding="utf-8"))


@router.get("/grader-check", summary="Оценщик открытых ответов на наборе панели 06.10: инъекции и завышение, до и после")
def grader_check():
    return _grader()


LLM_MODELS = Path(__file__).resolve().parent / "data" / "llm_models.json"


@router.get("/llm-models", summary="Какая модель где: облачные модели, открытая Qwen на CPU и правила на одних наборах")
def llm_models():
    if not LLM_MODELS.exists():
        return {"missing": True}
    return json.loads(LLM_MODELS.read_text(encoding="utf-8"))


# --- режим «только российская модель» — все LLM-функции на YandexGPT против Sonnet и правил (tools/llm/ru_llm_bench.py) ---
RU_LLM = Path(__file__).resolve().parent / "data" / "ru_llm.json"


@router.get("/ru-llm", summary="Режим «только российская модель»: YandexGPT 5.1 против Claude Sonnet 5.5 и правил на одних входах")
def ru_llm():
    if not RU_LLM.exists():
        return {"missing": True}
    return json.loads(RU_LLM.read_text(encoding="utf-8"))


# --- сильнейшие модели по функциям — качество, надёжность, задержка, цена (tools/llm/strongest_summary.py) ---
STRONGEST = Path(__file__).resolve().parent / "data" / "strongest.json"


@router.get("/strongest", summary="Какая модель где и почему: качество, отказы, задержка и цена каждой модели по LLM-функциям")
def strongest():
    if not STRONGEST.exists():
        return {"missing": True}
    return json.loads(STRONGEST.read_text(encoding="utf-8"))


# --- И26: доля повторов заданий между попытками (живая по базе + синтетика; пересчёт: attempts_repeat.py) ---
@router.get("/attempts-repeat", summary="Доля повторов заданий между попытками теста: по базе и синтетика (модель)")
def attempts_repeat(db: Session = Depends(get_db)):
    from app.modules.validation import attempts_repeat as ar

    return {"synthetic": ar.load(), "live": ar.live(db)}


# --- А4 (21.10): прежние блоки «SPRT-симуляция», «утечка K», «согласие с экспертами» сняты — проверка 20.10 показала,
# что они считались не на продукте (синтетический пул, множитель D = 1,7, константы). Замена — симуляция продукта
# (product_sim.py → docs/NUMBERS.json grade_verdict) и настоящие боты через движок (cheat_bots.py). Адреса оставлены,
# чтобы старые ссылки получали честный ответ, а не 404.
_RETIRED = {
    "retired": True,
    "reason_ru": "Расчёт снят 21.10: он был не на движке продукта. Актуальные цифры — docs/NUMBERS.json → grade_verdict "
                 "(симуляция продукта) и cheat_bots (боты через движок).",
}
CHEAT_JSON = Path(__file__).resolve().parent / "data" / "cheat_bots.json"
_CHEAT_LIVE: list[dict] = []
_CHEAT_LOCK = threading.Lock()
_CHEAT_TIMES: list[float] = []
CHEAT_LIVE_PER_HOUR = 40
_CHEAT_BOTS = None


@router.get("/sprt-verdict", summary="Снято 21.10 (не на продукте) — см. NUMBERS.json → grade_verdict")
def get_sprt_verdict():
    return _RETIRED


@router.get("/leak-k-variants", summary="Снято 21.10 (формула, а не прогон) — см. NUMBERS.json → cheat_bots")
def get_leak_k_variants():
    return _RETIRED


@router.get("/cheat-challenge", summary="«Обмани тест»: отчётный прогон ботов через движок и последние живые попытки")
def get_cheat_challenge():
    rep = json.loads(CHEAT_JSON.read_text(encoding="utf-8")) if CHEAT_JSON.exists() else {}
    meta = dict(rep.get("meta") or {})
    if isinstance(meta.get("settings"), dict):
        # настройки прогона публикуются для воспроизводимости, но без флагов механики честности (ИИ-метка в условии):
        # их название не должно уходить анониму (test_integrity_r27); полный снимок — в data/cheat_bots.json в репозитории
        meta["settings"] = {k: v for k, v in meta["settings"].items() if "ai_mark" not in k}
    return {"table": rep.get("table"), "meta": meta, "attempts": list(reversed(_CHEAT_LIVE[-20:]))}


class CheatAttemptIn(BaseModel):
    strategy: str = "longest"


_LIVE_STRATEGIES = {"random", "longest", "median_number", "overlap", "position_A", "position_B", "position_C",
                    "position_D", "leak_10", "control"}


@router.post("/cheat-challenge/attempt", summary="Живая попытка бота: настоящий тест через движок (реальные варианты и проверка)")
def post_cheat_attempt(body: CheatAttemptIn | None = None):
    import time as _time

    from app.modules.validation import cheat_bots

    b = body or CheatAttemptIn()
    if b.strategy not in _LIVE_STRATEGIES:
        raise HTTPException(status_code=400, detail="Неизвестная стратегия")
    now = _time.time()
    while _CHEAT_TIMES and now - _CHEAT_TIMES[0] > 3600:
        _CHEAT_TIMES.pop(0)
    if len(_CHEAT_TIMES) >= CHEAT_LIVE_PER_HOUR:
        raise HTTPException(status_code=429, detail="Лимит живых попыток на час исчерпан — смотрите отчётный прогон")
    if not _CHEAT_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Другой бот уже проходит тест — попробуйте через полминуты")
    try:
        global _CHEAT_BOTS
        if _CHEAT_BOTS is None:
            _CHEAT_BOTS = cheat_bots.Bots(seed=int(now) % (2**31 - 1))
        _CHEAT_TIMES.append(now)
        t0 = _time.time()
        k = 10 if b.strategy == "leak_10" else 0
        r = _CHEAT_BOTS.attempt(b.strategy, k)
        entry = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "strategy": b.strategy,
                 "claim": r["claim"], "direction": r["direction"], "verdict_main": r["verdict_main"],
                 "grade_final": r["grade_final"], "refined": r["refined"], "false_confirmed": bool(r["false_confirmed"]),
                 "items": int(r.get("items") or 0), "elapsed_s": round(_time.time() - t0, 1)}
        _CHEAT_LIVE.append(entry)
        del _CHEAT_LIVE[:-200]
        return {"latest": entry, "attempts": list(reversed(_CHEAT_LIVE[-20:]))}
    finally:
        _CHEAT_LOCK.release()


@router.get("/expert-surrogate", summary="Снято 21.10 (числа без источника) — разметка E1–E3 была модельной")
def get_expert_surrogate():
    return _RETIRED

