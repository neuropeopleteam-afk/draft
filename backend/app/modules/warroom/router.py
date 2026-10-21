"""Маршруты API модуля «Боевой ИИ-Полигон» (`/api/warroom/*`).

Строго разделяет два режима работы:
1. «Боевой этап» (`mode="combat"`, вошедший реальный кандидат вне `/demo`):
   - зерно параметризации (`seed`) назначается только сервером от `(user.id, scenario_id)`;
   - клиенту не отдаются ключи ответа (`required`, `helpful`, `harmful`, `opt_min`, `opt_max`,
     `trap`, `rubric.reference`, `incident.actions.sim_effect`), варианты патчей перемешаны под
     нейтральными названиями;
   - попытка сохраняется в `warroom_attempts` (до 5 попыток на сценарий) без прямой мутации `TestSession.result`;
   - при включённом LLM вызывается ИИ-рецензент с проверкой цитат.
2. «Демонстрационная витрина» (`mode="demo"`, гость, учётная запись жюри `*@jury.example.com` или флаг `demo=true` из `/demo/warroom`):
   - доступны обучающие подсказки и быстрый демонстрационный прогон для жюри;
   - запись в `warroom_attempts` и вызов платной LLM принудительно отключены (`saved_to_db = False`).
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Query, Request
import jwt
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, get_db
from app.core.deps import oauth2_scheme, require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.core.ratelimit import SlidingWindow, client_ip, hit
from app.core.security import decode_access_token
from app.modules.assessment.models import TestSession
from app.modules.auth.models import User
from app.modules.warroom.anticheat_live import (
    CONTOURS_SPEC,
    inspect_anticheat_live,
    public_signals_catalog,
)
from app.modules.warroom.catalog import (
    BASE_SCENARIOS,
    MEASURES,
    SCENARIO_BY_ID,
    parameterize_scenario,
)
from app.modules.warroom.models import WarRoomAttempt
from app.modules.warroom.simulator import evaluate_solution, simulate_incident

router = APIRouter(prefix="/api/warroom", tags=["warroom"])

TAGS = [
    {
        "name": "warroom",
        "description": "Боевой ИИ-Полигон: детерминированный симулятор архитектурных инцидентов и проверка античита",
    }
]

candidate_dep = require_role(UserRole.candidate)
employer_dep = require_role(UserRole.employer)

# Ограничители частоты запросов (скользящее окно)
_sim_limiter = SlidingWindow(120, 60.0)
_eval_limiter = SlidingWindow(25, 60.0)
_ac_limiter = SlidingWindow(45, 60.0)

MAX_COMBAT_ATTEMPTS_PER_SCENARIO = 5


def _optional_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User | None:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        if payload.get("typ"):
            return None
        uid = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active or payload.get("ver", 0) != user.token_version:
        return None
    return user


def _is_jury_user(user: User | None) -> bool:
    if user is None:
        return False
    email = (user.email or "").lower()
    return email.endswith("@jury.example.com") or email.startswith("jury")


def _is_combat_candidate(user: User | None, demo_flag: bool) -> bool:
    """Истинно только для реального вошедшего кандидата в боевом режиме (не жюри и не /demo)."""
    return bool(
        user is not None
        and user.role == UserRole.candidate
        and not _is_jury_user(user)
        and not demo_flag
    )


def _resolve_seed(user: User | None, scenario_id: str, explicit_seed: int | None, *, combat_mode: bool) -> int:
    """В боевом режиме кандидата seed вычисляется строго на сервере от (user.id, scenario_id)."""
    if combat_mode and user is not None:
        raw = f"combat-seed:{user.id}:{scenario_id}".encode("utf-8")
        h = int(hashlib.sha256(raw).hexdigest()[:8], 16)
        return 1000 + (h % 9000)
    if explicit_seed is not None:
        return max(1, min(999_999, int(explicit_seed)))
    if user is not None:
        h = int(hashlib.sha256(f"{user.id}:{scenario_id}".encode("utf-8")).hexdigest()[:6], 16)
        return 1000 + (h % 9000)
    return 1001


class MeasureItemIn(BaseModel):
    id: str = Field(max_length=32)
    params: dict[str, int | float | bool] = Field(default_factory=dict)


class SimulateIn(BaseModel):
    scenario_id: str = Field(default="payment", max_length=32)
    seed: int | None = Field(default=None, ge=1, le=999_999)
    measures: list[MeasureItemIn | str] = Field(default_factory=list, max_length=20)
    code_patch: str | None = Field(default=None, max_length=12_000)
    demo: bool = Field(default=False)


class EvaluateIn(BaseModel):
    scenario_id: str = Field(default="payment", max_length=32)
    seed: int | None = Field(default=None, ge=1, le=999_999)
    measures: list[MeasureItemIn | str] = Field(default_factory=list, max_length=20)
    code_patch: str | None = Field(default=None, max_length=12_000)
    justification: str = Field(default="", max_length=8_000)
    elapsed_s: int = Field(default=180, ge=1, le=7_200)
    save: bool = Field(default=True)
    demo: bool = Field(default=False)


class TelemetryIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    paste: int = Field(default=0, ge=0, le=10_000)
    paste_chars: int = Field(default=0, ge=0, le=500_000)
    copy_count: int = Field(default=0, alias="copy", ge=0, le=10_000)
    focus_lost: int = Field(default=0, ge=0, le=10_000)
    hidden_ms: int = Field(default=0, ge=0, le=86_400_000)
    fs_exit: int = Field(default=0, ge=0, le=10_000)
    fs_out_ms: int = Field(default=0, ge=0, le=86_400_000)
    printscreen: int = Field(default=0, ge=0, le=10_000)
    typed: int | None = Field(default=None, ge=0, le=500_000)
    active_ms: int = Field(default=25_000, ge=1, le=86_400_000)
    ik_cv: int | None = Field(default=None, ge=0, le=1000)
    ik_cv_float: float | None = Field(default=None, ge=0.0, le=10.0)
    key_intervals_ms: list[float] = Field(default_factory=list, max_length=300)
    even_rhythm: bool = Field(default=False)
    fast_text: bool = Field(default=False)
    not_typed: bool = Field(default=False)
    api_bypass: bool = Field(default=False)
    canary_fast: bool = Field(default=False)
    preknowledge_flagged: bool = Field(default=False)
    fast_wrong: bool = Field(default=False)
    ai_mark_hit: bool = Field(default=False)
    decoy_hit: bool = Field(default=False)


class LzItemIn(BaseModel):
    a: float = Field(default=1.0, ge=0.1, le=5.0)
    b: float = Field(default=0.0, ge=-5.0, le=5.0)
    x: int = Field(default=0, ge=0, le=1)
    t: float = Field(default=25.0, ge=0.5, le=3600.0)


class CameraEventIn(BaseModel):
    position: int = Field(default=1, ge=1, le=200)
    kind: str = Field(default="no_face", max_length=32)
    duration_ms: int = Field(default=5000, ge=0, le=3_600_000)
    faces: int = Field(default=0, ge=0, le=20)


class AntiCheatInspectIn(BaseModel):
    answer_text: str = Field(default="", max_length=12_000)
    attack_preset: str | None = Field(default=None, max_length=32)
    telemetry: TelemetryIn = Field(default_factory=TelemetryIn)
    camera_events: list[CameraEventIn] = Field(default_factory=list, max_length=30)
    check_lz: bool = Field(default=False)
    lz_theta: float = Field(default=1.2, ge=-4.0, le=4.5)
    lz_items: list[LzItemIn] | None = Field(default=None, max_length=40)
    demo: bool = Field(default=True)


def _public_measures_list(*, demo_mode: bool) -> list[dict[str, Any]]:
    """В боевом режиме скрывает поля `opt_min`, `opt_max`, `trap`, `heals` (ключ решения)."""
    out: list[dict[str, Any]] = []
    for m in MEASURES:
        params_out: list[dict[str, Any]] = []
        for p in m.get("params", []):
            p_item: dict[str, Any] = {
                "key": p["key"],
                "label": p["label"],
                "type": p["type"],
                "min": p["min"],
                "max": p["max"],
                "step": p["step"],
                "default": p["default"],
                "unit": p["unit"],
                "hint": p["hint"],
            }
            if demo_mode:
                p_item["opt_min"] = p["opt_min"]
                p_item["opt_max"] = p["opt_max"]
            params_out.append(p_item)
        item: dict[str, Any] = {
            "id": m["id"],
            "label": m["label"],
            "tech": m["tech"],
            "badge": m["badge"],
            "at": m["at"],
            "base_cost_rub": m["base_cost_rub"],
            "params": params_out,
        }
        if demo_mode:
            item["heals"] = m["heals"]
            item["trap"] = m["trap"]
        out.append(item)
    return out


def _public_scenario_dict(scn: dict[str, Any], *, demo_mode: bool) -> dict[str, Any]:
    """В боевом режиме (`demo_mode=False`) не отдаёт ключи (`required/helpful/harmful/reference/sim_effect`)
    и перемешивает варианты патчей под нейтральными названиями.
    """
    inc = copy.deepcopy(scn["incident"])
    if not demo_mode:
        for act in inc.get("actions", []):
            act.pop("sim_effect", None)

    if demo_mode:
        patches_out = scn["patches"]
        rubric_out = [
            {"id": r["id"], "title": r["title"], "weight": r["weight"], "reference": r["reference"]}
            for r in scn["rubric"]
        ]
    else:
        # Детерминированная перестановка патчей по (id, seed) с нейтральными заголовками
        raw_patches = list(scn["patches"])
        shift = (int(scn["seed"]) + len(scn["id"])) % len(raw_patches)
        rotated = raw_patches[shift:] + raw_patches[:shift]
        patches_out = [
            {
                "label": f"Вариант кода {idx + 1}",
                "lang": p["lang"],
                "code": p["code"],
            }
            for idx, p in enumerate(rotated)
        ]
        rubric_out = [
            {"id": r["id"], "title": r["title"], "weight": r["weight"]}
            for r in scn["rubric"]
        ]

    res: dict[str, Any] = {
        "id": scn["id"],
        "direction": scn["direction"],
        "direction_title": scn["direction_title"],
        "target_grade": scn["target_grade"],
        "title": scn["title"],
        "short": scn["short"],
        "service": scn["service"],
        "release": scn["release"],
        "seed": scn["seed"],
        "story": scn["story"],
        "labels": scn["labels"],
        "problem": scn["problem"],
        "base": scn["base"],
        "extra": scn["extra"],
        "slo": scn["slo"],
        "patches": patches_out,
        "checks": scn["public_checks"],
        "rubric": rubric_out,
        "incident": inc,
        "demo_mode": demo_mode,
    }
    if demo_mode:
        res["required"] = scn["required"]
        res["helpful"] = scn["helpful"]
        res["harmful"] = scn["harmful"]
        res["deploy"] = scn["deploy"]
        res["win"] = scn["win"]
    return res


def _attempt_out(row: WarRoomAttempt) -> dict[str, Any]:
    scn = SCENARIO_BY_ID.get(row.scenario_id) or BASE_SCENARIOS[0]
    return {
        "id": str(row.id),
        "scenario_id": row.scenario_id,
        "scenario_title": scn["title"],
        "direction": row.direction,
        "direction_title": scn["direction_title"],
        "target_grade": row.target_grade,
        "confirmed_grade": row.confirmed_grade,
        "seed": row.seed,
        "slo_met": row.slo_met,
        "cost_rub_month": row.cost_rub_month,
        "cost_budget_rub_month": row.cost_budget_rub_month,
        "sim_score": row.sim_score,
        "code_score": row.code_score,
        "rubric_score": row.rubric_score,
        "total_score": row.total_score,
        "passed": row.passed,
        "reviewer_mode": row.reviewer_mode,
        "rubric_details": row.rubric_details,
        "metrics": row.metrics,
        "incident_stage": row.incident_stage,
        "elapsed_s": row.elapsed_s,
        "sha256_sig": row.sha256_sig,
        "created_at": as_aware(row.created_at).isoformat() if row.created_at else None,
    }


def get_candidate_incident_stage(
    db: Session,
    user_id: uuid.UUID,
    direction: str | None = None,
) -> dict[str, Any] | None:
    """Публичная точка чтения результата боевого этапа кандидата для методики грейда (А4) без мутации TestSession."""
    stmt = select(WarRoomAttempt).where(WarRoomAttempt.user_id == user_id)
    if direction:
        stmt = stmt.where(WarRoomAttempt.direction == direction)
    stmt = stmt.order_by(WarRoomAttempt.total_score.desc(), WarRoomAttempt.created_at.desc()).limit(1)
    row = db.scalar(stmt)
    return dict(row.incident_stage) if row and row.incident_stage else None


@router.get("/scenarios", summary="Каталог 8 боевых инцидентов, архитектурных мер и контуров античита")
def list_scenarios(
    seed: int | None = Query(default=None, ge=1, le=999_999),
    demo: bool = Query(default=False),
    user: User | None = Depends(_optional_user),
) -> dict[str, Any]:
    combat_mode = _is_combat_candidate(user, demo)
    demo_mode = not combat_mode
    items = []
    for s in BASE_SCENARIOS:
        eff_seed = _resolve_seed(user, s["id"], seed, combat_mode=combat_mode)
        items.append(_public_scenario_dict(parameterize_scenario(s["id"], eff_seed), demo_mode=demo_mode))

    # Расшифровка сигналов античита отдаётся только для демо-режима жюри (решение владельца Р27)
    show_detailed_signals = bool(demo and (_is_jury_user(user) or user is None))
    sigs = public_signals_catalog(demo_mode=show_detailed_signals)
    return {
        "mode": "combat" if combat_mode else "demo",
        "demo_mode": demo_mode,
        "seed": items[0]["seed"] if items else 1001,
        "scenarios": items,
        "measures": _public_measures_list(demo_mode=demo_mode),
        "anticheat_contours": CONTOURS_SPEC,
        "anticheat_signals": sigs,
        "total_signals": len(sigs),
    }


@router.get(
    "/scenarios/{scenario_id}",
    summary="Параметризованный по seed боевой инцидент",
    responses={404: err("Сценарий не найден")},
)
def get_scenario(
    scenario_id: str,
    seed: int | None = Query(default=None, ge=1, le=999_999),
    demo: bool = Query(default=False),
    user: User | None = Depends(_optional_user),
) -> dict[str, Any]:
    if scenario_id not in SCENARIO_BY_ID:
        raise api_error(404, "scenario_not_found", "Боевой сценарий не найден")
    combat_mode = _is_combat_candidate(user, demo)
    demo_mode = not combat_mode
    eff_seed = _resolve_seed(user, scenario_id, seed, combat_mode=combat_mode)
    scn = parameterize_scenario(scenario_id, eff_seed)
    return _public_scenario_dict(scn, demo_mode=demo_mode)


@router.post(
    "/simulate",
    summary="Детерминированный расчёт метрик, стоимости и проверки кода",
    responses={404: err("Сценарий не найден"), 429: err("Слишком много запросов")},
)
def simulate_endpoint(
    body: SimulateIn,
    request: Request,
    user: User | None = Depends(_optional_user),
) -> dict[str, Any]:
    rate_key = str(user.id) if user is not None else client_ip(request)
    hit(_sim_limiter, rate_key, "warroom_simulate_rate_limited", "Слишком много запросов к симулятору")
    if body.scenario_id not in SCENARIO_BY_ID:
        raise api_error(404, "scenario_not_found", "Боевой сценарий не найден")

    combat_mode = _is_combat_candidate(user, body.demo)
    eff_seed = _resolve_seed(user, body.scenario_id, body.seed, combat_mode=combat_mode)
    raw_measures = [m.model_dump() if isinstance(m, MeasureItemIn) else m for m in body.measures]
    return simulate_incident(body.scenario_id, eff_seed, raw_measures, body.code_patch)


@router.post(
    "/evaluate",
    summary="Полная оценка решения инцидента (симулятор + код + рубрика с цитатами)",
    responses={404: err("Сценарий не найден"), 429: err("Слишком много запросов")},
)
def evaluate_endpoint(
    body: EvaluateIn,
    request: Request,
    user: User | None = Depends(_optional_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rate_key = str(user.id) if user is not None else client_ip(request)
    hit(_eval_limiter, rate_key, "warroom_evaluate_rate_limited", "Слишком много проверок решения")
    if body.scenario_id not in SCENARIO_BY_ID:
        raise api_error(404, "scenario_not_found", "Боевой сценарий не найден")

    combat_mode = _is_combat_candidate(user, body.demo)
    eff_seed = _resolve_seed(user, body.scenario_id, body.seed, combat_mode=combat_mode)
    raw_measures = [m.model_dump() if isinstance(m, MeasureItemIn) else m for m in body.measures]

    # Вызов платной LLM и запись в БД как свидетельства грейда разрешены ТОЛЬКО для вошедшего кандидата в боевом режиме
    res = evaluate_solution(
        scenario_id=body.scenario_id,
        seed=eff_seed,
        measures=raw_measures,
        code_patch=body.code_patch,
        justification=body.justification,
        elapsed_s=body.elapsed_s,
        allow_llm=combat_mode,
    )

    attempt_id: str | None = None
    saved_to_db = False
    sprt_preview: dict[str, Any] | None = None

    if combat_mode and body.save and user is not None:
        existing_cnt = int(
            db.scalar(
                select(func.count(WarRoomAttempt.id)).where(
                    WarRoomAttempt.user_id == user.id,
                    WarRoomAttempt.scenario_id == res["scenario_id"],
                )
            )
            or 0
        )
        if existing_cnt >= MAX_COMBAT_ATTEMPTS_PER_SCENARIO:
            raise api_error(
                429,
                "warroom_attempt_limit_reached",
                f"Достигнут лимит боевых попыток по этому сценарию ({MAX_COMBAT_ATTEMPTS_PER_SCENARIO})",
            )

        # Находим последнюю сессию теста кандидата по этому направлению (только для FK-связи, без записи в чужое поле TestSession.result)
        latest_ts = db.scalar(
            select(TestSession)
            .where(TestSession.user_id == user.id)
            .order_by(TestSession.created_at.desc())
            .limit(1)
        )
        ts_id = latest_ts.id if latest_ts is not None else None

        # Вызов функции методики А4 (sprt.incorporate_incident_stage) только в режиме чтения для предпросмотра вклада
        if latest_ts is not None and isinstance(latest_ts.result, dict):
            try:
                from app.modules.assessment import sprt as sprt_mod  # type: ignore

                inc_fn = getattr(sprt_mod, "incorporate_incident_stage", None)
                if callable(inc_fn) and "theta" in latest_ts.result:
                    th1, se1, llr_d, _ = inc_fn(
                        float(latest_ts.result.get("theta") or 0.0),
                        float(latest_ts.result.get("se") or 0.5),
                        str(latest_ts.result.get("claimed_grade") or res["target_grade"]),
                        res["incident_stage"],
                    )
                    sprt_preview = {"theta_post": round(th1, 3), "se_post": round(se1, 3), "llr_delta": round(llr_d, 3)}
            except Exception:
                sprt_preview = None

        row = WarRoomAttempt(
            user_id=user.id,
            test_session_id=ts_id,
            scenario_id=res["scenario_id"],
            direction=res["direction"],
            target_grade=res["target_grade"],
            confirmed_grade=res["confirmed_grade"],
            seed=res["seed"],
            measures=raw_measures,
            code_patch=body.code_patch or "",
            justification=body.justification or "",
            metrics=res["metrics"],
            slo_met=res["slo"]["slo_met"],
            cost_rub_month=res["metrics"]["cost_rub_month"],
            cost_budget_rub_month=res["metrics"]["cost_budget_rub_month"],
            sim_score=res["scores"]["sim_score"],
            code_score=res["scores"]["code_score"],
            rubric_score=res["rubric"]["rubric_score"],
            total_score=res["total_score"],
            passed=res["passed"],
            reviewer_mode=res["rubric"]["reviewer_mode"],
            rubric_details=res["rubric"],
            incident_stage=res["incident_stage"],
            elapsed_s=body.elapsed_s,
            sha256_sig=res["sha256_sig"],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        attempt_id = str(row.id)
        saved_to_db = True

    return {
        **res,
        "mode": "combat" if combat_mode else "demo",
        "attempt_id": attempt_id,
        "saved_to_db": saved_to_db,
        "sprt_preview": sprt_preview,
    }


@router.get("/attempts/my", summary="Мои попытки прохождения Боевого ИИ-Полигона (для кабинета кандидата)")
def my_attempts(
    user: User = Depends(candidate_dep),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = db.scalars(
        select(WarRoomAttempt)
        .where(WarRoomAttempt.user_id == user.id)
        .order_by(WarRoomAttempt.created_at.desc())
        .limit(25)
    ).all()
    items = [_attempt_out(r) for r in rows]
    best_by_dir: dict[str, dict[str, Any]] = {}
    for it in items:
        d = it["direction"]
        if d not in best_by_dir or it["total_score"] > best_by_dir[d]["total_score"]:
            best_by_dir[d] = it
    return {
        "count": len(items),
        "passed_count": sum(1 for it in items if it["passed"]),
        "best_by_direction": best_by_dir,
        "attempts": items,
        "latest_incident_stage": items[0]["incident_stage"] if items else None,
    }


@router.get(
    "/candidates/{ref}",
    summary="Результаты Боевого ИИ-Полигона кандидата для карточки работодателя",
    responses={401: err("Не выполнен вход"), 403: err("Только для работодателя"), 404: err("Кандидат не найден")},
)
def candidate_warroom(
    ref: str,
    user: User = Depends(employer_dep),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.modules.invitations.service import profile_by_ref
    from app.modules.matching.router import my_company

    prof = profile_by_ref(db, ref)
    _ = my_company(db, user)
    rows = db.scalars(
        select(WarRoomAttempt)
        .where(WarRoomAttempt.user_id == prof.user_id)
        .order_by(WarRoomAttempt.created_at.desc())
        .limit(20)
    ).all()
    items = [_attempt_out(r) for r in rows]
    best = max(items, key=lambda x: x["total_score"]) if items else None
    return {
        "candidate_ref": ref,
        "has_attempts": bool(items),
        "passed": any(it["passed"] for it in items),
        "best_attempt": best,
        "latest_incident_stage": best["incident_stage"] if best else None,
        "attempts": items,
    }


@router.post(
    "/anticheat/inspect",
    summary="Режим Б: проверка ответа и телеметрии античитом бэкенда",
    responses={429: err("Слишком много запросов")},
)
def anticheat_inspect_endpoint(
    body: AntiCheatInspectIn,
    request: Request,
    user: User | None = Depends(_optional_user),
) -> dict[str, Any]:
    rate_key = str(user.id) if user is not None else client_ip(request)
    hit(_ac_limiter, rate_key, "warroom_anticheat_rate_limited", "Слишком много проверок античита")
    # Детальная расшифровка сигналов — только в демо-режиме (гость на демо-стенде или жюри)
    demo_mode = bool(body.demo and (user is None or _is_jury_user(user) or user.role != UserRole.candidate))
    return inspect_anticheat_live(body.model_dump(by_alias=True), demo_mode=demo_mode)
