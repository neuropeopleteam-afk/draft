"""Stateless jury evaluation: objects live in one request, never in shared tables."""
from __future__ import annotations

import csv
from datetime import date
import io
import json
from typing import Literal
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.db import utcnow
from app.core.deps import require_role
from app.core.enums import EvidenceLevel, FactSource, FspEventLevel, UserRole, WorkFormat
from app.core.errors import api_error
from app.core.ratelimit import SlidingWindow, hit
from app.modules.auth.models import User
from app.modules.catalog.seed_data import STACK
from app.modules.fsp.models import FspAchievement
from app.modules.jury import scope
from app.modules.matching.need_parser import parse_need
from app.modules.matching.ranking import ALGORITHM_VERSION, score_candidate
from app.modules.profiles.facts import Bundle
from app.modules.profiles.models import CandidateFact, CandidateProfile
from app.modules.validation.matching_eval import ndcg, precision

Direction = Literal["backend", "frontend", "data_ml", "qa", "security"]
Grade = Literal["junior", "middle", "senior"]
router = APIRouter(prefix="/closed-set", tags=["validation"])
_rate = SlidingWindow(12, 60)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Need(Strict):
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=10, max_length=8000)
    direction: Direction | None = None
    grade: Grade | None = None


class Skill(Strict):
    tag: str
    correct: int = Field(ge=0, le=10000)
    total: int = Field(ge=1, le=10000)

    @model_validator(mode="after")
    def validate_skill(self):
        if self.tag not in STACK or self.correct > self.total:
            raise ValueError("Навык не из справочника или число верных ответов больше общего")
        return self


class Achievement(Strict):
    discipline: Literal["algorithmic", "product", "security", "robotics", "uav"]
    level: Literal["school", "regional", "interregional", "national", "international"]
    place: int = Field(ge=1, le=100000)
    event_date: date = date(2026, 1, 1)


class Candidate(Strict):
    id: str = Field(min_length=1, max_length=80)
    direction: Direction
    grade: Grade
    # Values are assertions of the uploaded test set, NOT platform verification.
    theta: float | None = Field(None, ge=-5, le=5)
    se: float = Field(0.4, gt=0, le=3)
    work_format: Literal["office", "hybrid", "remote", "any"] = "any"
    city: str | None = Field(None, max_length=100)
    relocation: bool = False
    skills: list[Skill] = Field(default_factory=list, max_length=80)
    declared_stack: list[str] = Field(default_factory=list, max_length=80)
    achievements: list[Achievement] = Field(default_factory=list, max_length=30)
    probe_score: float | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_tags(self):
        if len({s.tag for s in self.skills}) != len(self.skills):
            raise ValueError("Повторяющиеся подтверждённые навыки")
        if any(t not in STACK for t in self.declared_stack):
            raise ValueError("Заявленный тег не из справочника")
        return self


class Label(Strict):
    need_id: str
    candidate_id: str
    relevance: int = Field(ge=0, le=3, strict=True)


class Dataset(Strict):
    needs: list[Need] = Field(min_length=1, max_length=50)
    candidates: list[Candidate] = Field(min_length=1, max_length=500)
    labels: list[Label] = Field(default_factory=list, max_length=25000)

    @model_validator(mode="after")
    def ids(self):
        ns, cs = {n.id for n in self.needs}, {c.id for c in self.candidates}
        if len(ns) != len(self.needs) or len(cs) != len(self.candidates):
            raise ValueError("Идентификаторы потребностей и профилей должны быть уникальны")
        seen = set()
        for label in self.labels:
            pair = (label.need_id, label.candidate_id)
            if pair in seen or label.need_id not in ns or label.candidate_id not in cs:
                raise ValueError("Повторная метка или метка с неизвестным идентификатором")
            seen.add(pair)
        return self


class Upload(Strict):
    format: Literal["json", "csv"] = "json"
    content: str = Field(min_length=1, max_length=2_000_000)
    k: int = Field(5, ge=1, le=50)

    @model_validator(mode="after")
    def byte_limit(self):
        if len(self.content.encode("utf-8")) > 2_000_000:
            raise ValueError("Файл не должен превышать 2 МБ")
        return self


def decode(data: Upload) -> Dataset:
    try:
        if data.format == "json":
            return Dataset.model_validate_json(data.content)
        rows = list(csv.DictReader(io.StringIO(data.content.lstrip("\ufeff"))))
        if len(rows) > 25550:
            raise ValueError("Слишком много строк")
        out = {"needs": [], "candidates": [], "labels": []}
        for row in rows:
            kind = row.pop("kind", "")
            if kind not in ("need", "candidate", "label"):
                raise ValueError("kind должен быть need, candidate или label")
            obj = {k: v for k, v in row.items() if v not in ("", None)}
            if kind == "label":
                obj["relevance"] = int(obj["relevance"])
            if kind == "candidate":
                for key in ("skills", "declared_stack", "achievements"):
                    if key in obj:
                        obj[key] = json.loads(obj[key])
            out[{"need": "needs", "candidate": "candidates", "label": "labels"}[kind]].append(obj)
        return Dataset.model_validate(out)
    except (ValidationError, ValueError, KeyError, TypeError, csv.Error) as exc:
        # No payload echoed back or logged (may contain private information).
        detail = "Проверьте схему и идентификаторы набора"
        if isinstance(exc, ValidationError):
            detail = "; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"]
                               for e in exc.errors(include_input=False)[:4])
        raise api_error(422, "invalid_dataset", detail) from None


def bundle(c: Candidate) -> Bundle:
    uid = uuid.uuid5(uuid.NAMESPACE_URL, "closed-set:" + c.id)
    p = CandidateProfile(user_id=uid, public_ref=c.id, current_direction_id=c.direction,
                         current_grade_id=c.grade, current_category_id=f"{c.direction}.{c.grade}",
                         work_format=WorkFormat(c.work_format), city=c.city, relocation=c.relocation,
                         privacy={}, roles=[])
    b = Bundle(profile=p)

    def fact(kind, key, value, level=EvidenceLevel.T1):
        return CandidateFact(user_id=uid, kind=kind, key=key, title=key, value=value,
                             evidence_level=level, source=FactSource.test,
                             created_at=utcnow(), source_ref="closed-set:external")

    if c.theta is not None:
        b.test = fact("test_result", p.current_category_id,
                      {"theta": c.theta, "se": c.se, "correct": None, "answered": None})
    for s in c.skills:
        b.skills_t1[s.tag] = fact("skill", s.tag,
                                 {"correct": s.correct, "total": s.total, "score": s.correct / s.total})
    b.t0["stack"] = [fact("stack", t, {}, EvidenceLevel.T0) for t in c.declared_stack]
    if c.probe_score is not None:
        b.probes_t1 = [fact("probe", "Внешний зонд", {"score": c.probe_score})]
    b.achievements = [
        FspAchievement(discipline=a.discipline, event_level=FspEventLevel(a.level), place=a.place,
                       event_date=a.event_date, event_name="Достижение из закрытого набора",
                       verified=True, source_ref="closed-set:external") for a in c.achievements
    ]
    return b


def evaluate(dataset: Dataset, k: int = 5) -> dict:
    candidates = {c.id: bundle(c) for c in dataset.candidates}
    labels = {(l.need_id, l.candidate_id): l.relevance for l in dataset.labels}
    results, sums = [], []
    for need in dataset.needs:
        req = parse_need(need.text, need.direction, need.grade, use_llm=False)
        eligible = [(ref, b) for ref, b in candidates.items()
                    if (not req["direction"] or b.profile.current_direction_id == req["direction"])
                    and (not req["grade"] or b.profile.current_grade_id == req["grade"])
                    and b.test is not None]
        scores = [(ref, *score_candidate(b, req)) for ref, b in eligible]
        scores.sort(key=lambda row: (-row[1], row[0]))
        # Imported evidence is never described as having been verified on this platform.
        rows = []
        for rank, (ref, score, components, reasons) in enumerate(scores[:k], start=1):
            for reason in reasons:
                reason["text"] = "Данные загрузившего (не проверены платформой): " + reason["text"]
            rows.append({"candidate_id": ref, "rank": rank, "score": score, "components": components,
                         "reasons": reasons, "relevance": labels.get((need.id, ref))})
        complete = all((need.id, ref) in labels for ref in candidates)
        coverage = sum((need.id, ref) in labels for ref in candidates) / len(candidates)
        metrics = None
        if complete:
            rels = [labels[(need.id, row["candidate_id"])] for row in rows]
            all_rels = [labels[(need.id, ref)] for ref in candidates]
            metrics = {f"p@{k}": round(precision(rels, k), 4),
                       f"ndcg@{k}": round(ndcg(rels, all_rels, k), 4),
                       "no_relevant_labels": not any(all_rels)}
            sums.append(metrics)
        results.append({"need_id": need.id, "requirements": req, "eligible": len(eligible),
                        "returned": len(rows), "label_coverage": coverage,
                        "metrics": metrics, "results": rows})
    summary = {key: round(sum(m[key] for m in sums) / len(sums), 4)
               for key in (f"p@{k}", f"ndcg@{k}")} if sums else None
    return {"algorithm": ALGORITHM_VERSION, "n_needs": len(dataset.needs),
            "n_candidates": len(candidates), "k": k, "evaluated_needs": len(sums),
            "summary": summary, "per_need": results,
            "note": "Набор обрабатывается только в памяти этого запроса. Общий пул не меняется. "
                    "T1/T2 — утверждения загрузившего, не новая верификация платформой. "
                    "Без theta профиль не попадает в подтверждённую подборку. "
                    "p@k: релевантность ≥ 2, делитель k (пустые места нерелевантны). "
                    "nDCG: gain = 2^rel − 1, идеал по всем профилям набора. "
                    "При неполной разметке метрики не считаются, пропуски не заменяются нулями."}


def authorized(user: User = Depends(require_role(UserRole.employer, UserRole.admin))) -> User:
    if not scope.key_of(user.email) or not user.is_demo:
        raise api_error(403, "sandbox_required", "Откройте свою песочницу жюри как работодатель")
    return user


def checked(data: Upload, user: User) -> dict:
    hit(_rate, str(user.id), "dataset_rate", "Не больше 12 проверок в минуту")
    return evaluate(decode(data), data.k)


@router.post("/evaluate", summary="Подбор на закрытом JSON/CSV-наборе, без сохранения")
def run(data: Upload, response: Response, user: User = Depends(authorized)):
    response.headers["Cache-Control"] = "no-store"
    return checked(data, user)


def safe_cell(value):
    text = str(value) if value is not None else ""
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


@router.post("/export", summary="Скачать выдачу и метрики закрытого набора в CSV")
def export(data: Upload, user: User = Depends(authorized)):
    result = checked(data, user)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["need_id", "candidate_id", "rank", "score", "relevance",
                     f"p@{data.k}", f"ndcg@{data.k}", "label_coverage", "explanations"])
    for n in result["per_need"]:
        metrics = n["metrics"] or {}
        for row in n["results"] or [{}]:
            writer.writerow([safe_cell(x) for x in
                             (n["need_id"], row.get("candidate_id"), row.get("rank"), row.get("score"),
                              row.get("relevance"), metrics.get(f"p@{data.k}"), metrics.get(f"ndcg@{data.k}"),
                              n["label_coverage"], json.dumps(row.get("reasons", []), ensure_ascii=False))])
    return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="closed-set-results.csv"',
                             "Cache-Control": "no-store"})


TEMPLATE = {
    "needs": [{"id": "need-1", "text": "Backend middle, Python и PostgreSQL, удалённо."}],
    "candidates": [
        {"id": "candidate-1", "direction": "backend", "grade": "middle", "theta": 0.8, "se": 0.4,
         "work_format": "remote", "skills": [{"tag": "python", "correct": 4, "total": 5},
                                         {"tag": "postgresql", "correct": 3, "total": 4}],
         "declared_stack": ["docker"], "achievements": []},
        {"id": "candidate-2", "direction": "backend", "grade": "middle", "theta": 0.2,
         "skills": [], "declared_stack": ["python", "postgresql"]},
    ],
    "labels": [{"need_id": "need-1", "candidate_id": "candidate-1", "relevance": 3},
               {"need_id": "need-1", "candidate_id": "candidate-2", "relevance": 1}],
}


@router.get("/template/{format}", summary="Шаблон анонимного JSON/CSV-набора жюри")
def template(format: Literal["json", "csv"]):
    if format == "json":
        content, mime = json.dumps(TEMPLATE, ensure_ascii=False, indent=2), "application/json"
    else:
        out = io.StringIO()
        fields = ["kind", "id", "text", "direction", "grade", "theta", "se", "work_format", "city", "relocation", "skills",
                  "declared_stack", "achievements", "probe_score", "need_id", "candidate_id", "relevance"]
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for kind, key in (("need", "needs"), ("candidate", "candidates"), ("label", "labels")):
            for row in TEMPLATE[key]:
                writer.writerow({"kind": kind, **{k: json.dumps(v, ensure_ascii=False) if isinstance(v, list)
                                                  else v for k, v in row.items()}})
        content, mime = "\ufeff" + out.getvalue(), "text/csv; charset=utf-8"
    return Response(content, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="closed-set-template.{format}"'})
