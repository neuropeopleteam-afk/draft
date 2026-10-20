"""Маршруты API модуля «Боевой ИИ-Полигон» (`/api/warroom/*`)."""
from __future__ import annotations

import hashlib
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Query
import jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import as_aware, get_db
from app.core.deps import oauth2_scheme, require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.core.security import decode_access_token
from app.modules.assessment.models import TestSession
from app.modules.auth.models import User
from app.modules.warroom.anticheat_live import CONTOURS_SPEC, SIGNALS_SPEC, inspect_anticheat_live
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
        "description": "Боевой ИИ-Полигон: детерминированный симулятор архитектурных инцидентов и живая проверка античита",
    }
]

candidate_dep = require_role(UserRole.candidate)
employer_dep = require_role(UserRole.employer)


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


def _seed_for_user(user: User | None, explicit_seed: int | None) -> int:
    if explicit_seed is not None:
        return max(1, min(999_999, int(explicit_seed)))
    if user is not None:
        h = int(hashlib.sha256(str(user.id).encode("utf-8")).hexdigest()[:6], 16)
        return 1000 + (h % 9000)
    return 1001


class MeasureItemIn(BaseModel):
    id: str = Field(max_length=32)
    params: dict[str, int | float | bool] = Field(default_factory=dict)


class SimulateIn(BaseModel):
    scenario_id: str = Field(default="payment", max_length=32)
    seed: int | None = Field(default=None, ge=1, le=999_999)
    measures: list[MeasureItemIn | str] = Field(default_factory=list)
    code_patch: str | None = Field(default=None, max_length=12_000)


class EvaluateIn(BaseModel):
    scenario_id: str = Field(default="payment", max_length=32)
    seed: int | None = Field(default=None, ge=1, le=999_999)
    measures: list[MeasureItemIn | str] = Field(default_factory=list)
    code_patch: str | None = Field(default=None, max_length=12_000)
    justification: str = Field(default="", max_length=8_000)
    elapsed_s: int = Field(default=180, ge=1, le=7_200)
    save: bool = Field(default=True)


class AntiCheatInspectIn(BaseModel):
    answer_text: str = Field(default="", max_length=12_000)
    canary_word: str = Field(default="Бергамот", max_length=64)
    attack_preset: str | None = Field(default=None, max_length=32)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    camera_events: list[dict[str, Any]] = Field(default_factory=list)
    check_lz: bool = Field(default=False)
    lz_theta: float = Field(default=1.2)
    lz_items: list[dict[str, float]] | None = Field(default=None)


def _public_scenario_dict(scn: dict[str, Any]) -> dict[str, Any]:
    return {
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
        "required": scn["required"],
        "helpful": scn["helpful"],
        "harmful": scn["harmful"],
        "base": scn["base"],
        "extra": scn["extra"],
        "slo": scn["slo"],
        "patches": scn["patches"],
        "checks": scn["public_checks"],
        "rubric": [{"id": r["id"], "title": r["title"], "weight": r["weight"], "reference": r["reference"]} for r in scn["rubric"]],
        "deploy": scn["deploy"],
        "win": scn["win"],
        "incident": scn["incident"],
    }


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


@router.get("/scenarios", summary="Каталог 8 боевых инцидентов, архитектурных мер и 21 сигнала античита")
def list_scenarios(
    seed: int | None = Query(default=None, ge=1, le=999_999),
    user: User | None = Depends(_optional_user),
) -> dict[str, Any]:
    eff_seed = _seed_for_user(user, seed)
    items = [_public_scenario_dict(parameterize_scenario(s["id"], eff_seed)) for s in BASE_SCENARIOS]
    return {
        "seed": eff_seed,
        "scenarios": items,
        "measures": MEASURES,
        "anticheat_contours": CONTOURS_SPEC,
        "anticheat_signals": SIGNALS_SPEC,
        "total_signals": len(SIGNALS_SPEC),
    }


@router.get(
    "/scenarios/{scenario_id}",
    summary="Параметризованный по seed боевой инцидент",
    responses={404: err("Сценарий не найден")},
)
def get_scenario(
    scenario_id: str,
    seed: int | None = Query(default=None, ge=1, le=999_999),
    user: User | None = Depends(_optional_user),
) -> dict[str, Any]:
    if scenario_id not in SCENARIO_BY_ID:
        raise api_error(404, "scenario_not_found", "Боевой сценарий не найден")
    eff_seed = _seed_for_user(user, seed)
    scn = parameterize_scenario(scenario_id, eff_seed)
    return _public_scenario_dict(scn)


@router.post("/simulate", summary="Живой детерминированный расчёт метрик, стоимости и проверки кода")
def simulate_endpoint(
    body: SimulateIn,
    user: User | None = Depends(_optional_user),
) -> dict[str, Any]:
    eff_seed = _seed_for_user(user, body.seed)
    raw_measures = [m.model_dump() if isinstance(m, MeasureItemIn) else m for m in body.measures]
    return simulate_incident(body.scenario_id, eff_seed, raw_measures, body.code_patch)


@router.post("/evaluate", summary="Полная оценка решения инцидента (симулятор + код + ИИ-рецензент с цитатами) и сохранение")
def evaluate_endpoint(
    body: EvaluateIn,
    user: User | None = Depends(_optional_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    eff_seed = _seed_for_user(user, body.seed)
    raw_measures = [m.model_dump() if isinstance(m, MeasureItemIn) else m for m in body.measures]
    res = evaluate_solution(
        scenario_id=body.scenario_id,
        seed=eff_seed,
        measures=raw_measures,
        code_patch=body.code_patch,
        justification=body.justification,
        elapsed_s=body.elapsed_s,
    )

    attempt_id: str | None = None
    if body.save:
        ts_id: uuid.UUID | None = None
        if user is not None and user.role == UserRole.candidate:
            latest_ts = db.scalar(
                select(TestSession)
                .where(TestSession.user_id == user.id)
                .order_by(TestSession.created_at.desc())
                .limit(1)
            )
            if latest_ts is not None:
                ts_id = latest_ts.id
                res_dict = dict(latest_ts.result or {})
                res_dict["incident_stage"] = res["incident_stage"]
                # Если в ветке уже влит модуль sprt от А4 — вызываем incorporate_incident_stage
                try:
                    from app.modules.assessment import sprt as sprt_mod  # type: ignore

                    inc_fn = getattr(sprt_mod, "incorporate_incident_stage", None)
                    if callable(inc_fn) and "theta" in res_dict:
                        updated = inc_fn(
                            res_dict.get("theta"),
                            res_dict.get("se"),
                            res_dict.get("claimed_grade") or res["target_grade"],
                            res["incident_stage"],
                        )
                        if isinstance(updated, dict):
                            res_dict["incident_stage_sprt"] = updated
                except Exception:
                    pass
                latest_ts.result = res_dict
                flag_modified(latest_ts, "result")

        row = WarRoomAttempt(
            user_id=user.id if user is not None else None,
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

    return {
        **res,
        "attempt_id": attempt_id,
        "saved_to_db": attempt_id is not None,
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


@router.post("/anticheat/inspect", summary="Режим Б: живая проверка ответа и телеметрии настоящим античитом бэкенда")
def anticheat_inspect_endpoint(body: AntiCheatInspectIn) -> dict[str, Any]:
    return inspect_anticheat_live(body.model_dump())
