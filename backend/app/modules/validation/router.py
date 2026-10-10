"""Страница /validation («Как мы проверяем себя») и «Красная кнопка жюри».

Отчёт — публичный. Атаки — только после входа (любая роль; в режиме жюри фронтенд сам входит под демо-персоной
своей песочницы — кнопка остаётся «в один клик»), с лимитом частоты на пользователя и общим лимитом;
need_id — только потребность своей компании; симуляция утечки — из кэша (attacks.leak_cached).
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import threading
import time
import uuid

from fastapi import APIRouter, Depends, Response
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

    from app.modules.validation.provenance import provenance  # Ф6 (Н7): подписи банка/отчёта/калибровки

    return {**_report(), "provenance": provenance(_report()), "live": _live(db), "attacks": attacks.ATTACKS, "experts": experts_section(db),
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
    return _bench()


PATH_RETEST = Path(__file__).resolve().parent / "data" / "path_retest.json"


@router.get("/path-retest", summary="Test–retest всего пути кандидата и D / r_pb семейств (пересчёт: make path-retest)")
def path_retest():
    if not PATH_RETEST.exists():
        return {"missing": True}
    d = json.loads(PATH_RETEST.read_text(encoding="utf-8"))
    d.get("discrimination", {}).pop("families", None)  # полный список — в JSON репозитория, на страницу — слабые
    return d


@router.get("/test-length", summary="Длина теста для экрана старта: лимиты и итоги симуляции (синтетика, не люди)")
def test_length_route():
    from app.modules.validation.provenance import length_info  # Ф6 (Н8)

    return length_info(_report())


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
    return _stability()


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


# --- И26: доля повторов заданий между попытками (живая по базе + синтетика; пересчёт: attempts_repeat.py) ---
@router.get("/attempts-repeat", summary="Доля повторов заданий между попытками теста: по базе и синтетика (модель)")
def attempts_repeat(db: Session = Depends(get_db)):
    from app.modules.validation import attempts_repeat as ar

    return {"synthetic": ar.load(), "live": ar.live(db)}
