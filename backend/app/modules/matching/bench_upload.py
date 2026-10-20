"""Режим «Принесите свой набор» для жюри (критерий ТЗ 35 % — проверка качества подбора на тестовом наборе пар).

Позволяет эксперту жюри загрузить собственный набор (CSV или JSON):
* вакансии / потребности (``needs`` или ``vacancies``);
* кандидаты или их профили/резюме (``candidates``);
* необязательная разметка релевантности пар (``labels`` или ``pairs``, оценки 0..3 или 0/1).

Обработка полностью изолирована в памяти запроса (общий пул кандидатов и потребностей не меняется):
1. Разбирает каждую вакансию нашим парсером (``parse_need``).
2. Ранжирует кандидатов нашим продуктовым алгоритмом (``score_candidate`` + ``must_have`` + ``core_skill`` + ``selection_order``).
3. Строит для топ-N кандидатов по каждой вакансии полное объяснение (``explain``) и строку «Почему №1 выше №2» (``why_above_next``).
4. При наличии разметки релевантности считает ``P@5``, ``P@10``, ``nDCG@5``, ``nDCG@10``, ``MRR`` и сравнивает с базовой
   линией по самоописанию резюме (T0).
5. Формирует готовую выгрузку результата в CSV (UTF-8 с защитой от CSV-инъекций).
"""
from __future__ import annotations

import csv
from datetime import date
import io
import json
import re
from typing import Any
import uuid

from pydantic import ValidationError

from app.core.db import utcnow
from app.core.enums import EvidenceLevel, FactSource, FspEventLevel, WorkFormat
from app.core.errors import api_error
from app.modules.catalog.dictionary import find_stack
from app.modules.catalog.seed_data import DIRECTIONS, GRADES, active_stack, known_tag
from app.modules.fsp.models import FspAchievement
from app.modules.matching import bias as bias_mod, core_skill, explain as explain_mod, must_have
from app.modules.matching.need_parser import parse_need
from app.modules.matching.ranking import algorithm, score_candidate, selection_order
from app.modules.profiles.facts import Bundle
from app.modules.profiles.models import CandidateFact, CandidateProfile
from app.modules.validation.matching_eval import ndcg as eval_ndcg


def eval_precision(rels: list[int], k: int, threshold: int = 2) -> float:
    return sum(1 for r in rels[:k] if r >= threshold) / max(k, 1)


def eval_rr(rels: list[int], threshold: int = 2) -> float:
    return next((1.0 / idx for idx, r in enumerate(rels, start=1) if r >= threshold), 0.0)

MAX_UPLOAD_BYTES = 2_000_000
MAX_NEEDS = 100
MAX_CANDIDATES = 1000


def safe_csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _normalize_skill_list(raw_skills: Any) -> list[dict[str, Any]]:
    """Принимает список [{tag, correct, total}] | [{tag, score}] | ['python', 'postgresql'] | 'python, postgresql'."""
    if not raw_skills:
        return []
    if isinstance(raw_skills, str):
        s = raw_skills.strip()
        if s.startswith("["):
            try:
                raw_skills = json.loads(s)
            except Exception:  # noqa: BLE001
                raw_skills = [x.strip() for x in s.split(",") if x.strip()]
        else:
            raw_skills = [x.strip() for x in re.split(r"[,;]", s) if x.strip()] if "re" in globals() else [x.strip() for x in s.split(",") if x.strip()]

    st = active_stack()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_skills:
        if isinstance(item, str):
            tag = item.strip().lower()
            if not known_tag(tag) and tag not in st:
                found = find_stack(item)
                tag = found[0] if found else ""
            if tag and tag not in seen:
                seen.add(tag)
                out.append({"tag": tag, "correct": 4, "total": 5, "score": 0.8})
        elif isinstance(item, dict):
            tag = str(item.get("tag") or item.get("skill") or "").strip().lower()
            if not known_tag(tag) and tag not in st:
                found = find_stack(tag)
                tag = found[0] if found else ""
            if not tag or tag in seen:
                continue
            seen.add(tag)
            if "score" in item and item["score"] is not None:
                sc = max(0.0, min(1.0, float(item["score"])))
                tot = int(item.get("total") or 5)
                cor = int(round(sc * tot))
            else:
                tot = max(1, int(item.get("total") or 5))
                cor = max(0, min(tot, int(item.get("correct") if item.get("correct") is not None else 4)))
                sc = round(cor / tot, 3)
            out.append({"tag": tag, "correct": cor, "total": tot, "score": sc})
    return out


def _normalize_declared_stack(raw_decl: Any, resume_text: str | None = None) -> list[str]:
    tags: list[str] = []
    if isinstance(raw_decl, str):
        s = raw_decl.strip()
        if s.startswith("["):
            try:
                raw_decl = json.loads(s)
            except Exception:  # noqa: BLE001
                raw_decl = [x.strip() for x in s.split(",") if x.strip()]
        else:
            raw_decl = [x.strip() for x in s.split(",") if x.strip()]
    if isinstance(raw_decl, list):
        for x in raw_decl:
            t = str(x).strip().lower()
            if known_tag(t):
                if t not in tags:
                    tags.append(t)
            else:
                for ft in find_stack(str(x)):
                    if ft not in tags:
                        tags.append(ft)
    if resume_text:
        for ft in find_stack(resume_text):
            if ft not in tags:
                tags.append(ft)
    return tags[:80]


def parse_uploaded_dataset(content: str, fmt: str = "json") -> dict[str, Any]:
    """Разбирает JSON или CSV (многострочный kind=need|candidate|label либо плоскую таблицу пар) в единую структуру."""
    if not content or not content.strip():
        raise api_error(422, "empty_dataset", "Передан пустой набор данных. Загрузите файл JSON или CSV либо используйте образец.")
    if len(content.encode("utf-8")) > MAX_UPLOAD_BYTES:
        raise api_error(413, "dataset_too_large", "Размер файла не должен превышать 2 МБ.")

    fmt_clean = (fmt or "json").strip().lower()
    stripped = content.lstrip("\ufeff").strip()
    if fmt_clean == "json" or stripped.startswith("{"):
        try:
            raw = json.loads(stripped)
        except Exception as exc:  # noqa: BLE001
            raise api_error(422, "invalid_json", f"Ошибка разбора JSON: проверьте синтаксис файла ({exc}).") from None
        if not isinstance(raw, dict):
            raise api_error(422, "invalid_json_root", "Корнем JSON должен быть объект с полями needs (или vacancies) и candidates.")
        needs_raw = raw.get("needs") or raw.get("vacancies") or []
        cands_raw = raw.get("candidates") or raw.get("profiles") or []
        labels_raw = raw.get("labels") or raw.get("pairs") or raw.get("qrels") or []
    else:
        try:
            reader = csv.DictReader(io.StringIO(stripped))
            rows = list(reader)
        except Exception as exc:  # noqa: BLE001
            raise api_error(422, "invalid_csv", f"Не удалось прочитать CSV: {exc}") from None
        if not rows:
            raise api_error(422, "empty_csv", "В CSV-файле нет строк данных.")
        needs_raw, cands_raw, labels_raw = [], [], []
        needs_by_id: dict[str, dict] = {}
        cands_by_id: dict[str, dict] = {}
        for idx, row in enumerate(rows, start=1):
            kind = (row.get("kind") or "").strip().lower()
            if kind in ("need", "vacancy"):
                needs_raw.append({k: v for k, v in row.items() if v not in ("", None) and k != "kind"})
            elif kind in ("candidate", "profile"):
                cands_raw.append({k: v for k, v in row.items() if v not in ("", None) and k != "kind"})
            elif kind in ("label", "pair", "qrel"):
                labels_raw.append({k: v for k, v in row.items() if v not in ("", None) and k != "kind"})
            elif "need_id" in row and "candidate_id" in row:
                # Плоский CSV пар: need_id, need_text, candidate_id, direction, grade, theta, skills, relevance
                nid = str(row["need_id"]).strip()
                cid = str(row["candidate_id"]).strip()
                if nid and nid not in needs_by_id:
                    needs_by_id[nid] = {
                        "id": nid,
                        "title": row.get("need_title") or row.get("title"),
                        "text": row.get("need_text") or row.get("text") or f"Вакансия {nid}",
                        "direction": row.get("need_direction") or row.get("direction"),
                        "grade": row.get("need_grade") or row.get("grade"),
                    }
                if cid and cid not in cands_by_id:
                    cands_by_id[cid] = {
                        "id": cid,
                        "direction": row.get("candidate_direction") or row.get("direction") or "backend",
                        "grade": row.get("candidate_grade") or row.get("grade") or "middle",
                        "theta": row.get("theta"),
                        "se": row.get("se") or 0.35,
                        "skills": row.get("skills") or row.get("skills_confirmed"),
                        "declared_stack": row.get("declared_stack") or row.get("stack_t0"),
                        "resume_text": row.get("resume_text"),
                    }
                if row.get("relevance") not in ("", None):
                    labels_raw.append({"need_id": nid, "candidate_id": cid, "relevance": row["relevance"]})
            else:
                raise api_error(
                    422,
                    "invalid_csv_row",
                    f"Строка {idx}: укажите столбец kind (need / candidate / label) или плоские столбцы need_id и candidate_id.",
                )
        if needs_by_id:
            needs_raw.extend(needs_by_id.values())
        if cands_by_id:
            cands_raw.extend(cands_by_id.values())

    if not needs_raw:
        raise api_error(422, "no_needs", "В наборе должна быть хотя бы одна вакансия (поле needs или vacancies).")
    if not cands_raw:
        raise api_error(422, "no_candidates", "В наборе должен быть хотя бы один кандидат (поле candidates).")
    if len(needs_raw) > MAX_NEEDS:
        raise api_error(422, "too_many_needs", f"Не более {MAX_NEEDS} вакансий за один запрос.")
    if len(cands_raw) > MAX_CANDIDATES:
        raise api_error(422, "too_many_candidates", f"Не более {MAX_CANDIDATES} кандидатов за один запрос.")

    needs: list[dict[str, Any]] = []
    seen_n: set[str] = set()
    for i, n in enumerate(needs_raw, start=1):
        nid = str(n.get("id") or n.get("need_id") or f"need-{i}").strip()
        if nid in seen_n:
            raise api_error(422, "duplicate_need_id", f"Повторяющийся идентификатор вакансии: {nid}")
        seen_n.add(nid)
        txt = str(n.get("text") or n.get("description") or n.get("title") or "").strip()
        if len(txt) < 5:
            raise api_error(422, "short_need_text", f"Вакансия {nid}: текст описания слишком короткий (минимум 5 символов).")
        d = (n.get("direction") or "").strip().lower() or None
        if d and d not in DIRECTIONS:
            d = None
        g = (n.get("grade") or "").strip().lower() or None
        if g and g not in GRADES and g not in ("lead", "principal"):
            g = None
        needs.append({"id": nid, "title": n.get("title") or txt.split("\n", 1)[0][:90], "text": txt, "direction": d, "grade": g})

    candidates: list[dict[str, Any]] = []
    seen_c: set[str] = set()
    for i, c in enumerate(cands_raw, start=1):
        cid = str(c.get("id") or c.get("ref") or c.get("candidate_id") or f"cand-{i}").strip()
        if cid in seen_c:
            raise api_error(422, "duplicate_candidate_id", f"Повторяющийся идентификатор кандидата: {cid}")
        seen_c.add(cid)
        resume_txt = str(c.get("resume_text") or c.get("resume") or "").strip()
        parsed_res = parse_need(resume_txt, use_llm=False) if resume_txt else {}
        d = str(c.get("direction") or parsed_res.get("direction") or "backend").strip().lower()
        if d not in DIRECTIONS:
            d = "backend"
        g = str(c.get("grade") or parsed_res.get("grade") or "middle").strip().lower()
        if g not in GRADES and g not in ("lead", "principal"):
            g = "middle"
        theta_raw = c.get("theta")
        theta = float(theta_raw) if theta_raw not in (None, "") else None
        se = float(c.get("se") if c.get("se") not in (None, "") else 0.35)
        wf = str(c.get("work_format") or "any").strip().lower()
        if wf not in ("office", "hybrid", "remote", "any"):
            wf = "any"
        skills = _normalize_skill_list(c.get("skills") or c.get("skills_confirmed") or c.get("skills_t1"))
        decl = _normalize_declared_stack(c.get("declared_stack") or c.get("stack_t0"), resume_txt)
        ach_raw = c.get("achievements") or []
        if isinstance(ach_raw, str) and ach_raw.strip().startswith("["):
            try:
                ach_raw = json.loads(ach_raw)
            except Exception:  # noqa: BLE001
                ach_raw = []
        candidates.append({
            "id": cid,
            "direction": d,
            "grade": g,
            "grade_status": c.get("grade_status") or ("confirmed" if theta is not None or skills else "unconfirmed"),
            "theta": theta,
            "se": max(0.05, min(3.0, se)),
            "work_format": wf,
            "city": c.get("city"),
            "relocation": str(c.get("relocation", "")).lower() in ("true", "1", "yes", "да") if not isinstance(c.get("relocation"), bool) else c["relocation"],
            "skills": skills,
            "declared_stack": decl,
            "achievements": ach_raw if isinstance(ach_raw, list) else [],
            "probe_score": float(c["probe_score"]) if c.get("probe_score") not in (None, "") else None,
        })

    labels: dict[tuple[str, str], int] = {}
    for lb in labels_raw:
        nid = str(lb.get("need_id") or lb.get("vacancy_id") or "").strip()
        cid = str(lb.get("candidate_id") or lb.get("ref") or "").strip()
        if not nid or not cid or nid not in seen_n or cid not in seen_c:
            continue
        try:
            rel_val = int(float(lb.get("relevance", 0)))
        except (ValueError, TypeError):
            continue
        labels[(nid, cid)] = max(0, min(3, rel_val))

    return {"needs": needs, "candidates": candidates, "labels": labels}


def _to_bundle(c: dict[str, Any]) -> Bundle:
    uid = uuid.uuid5(uuid.NAMESPACE_URL, "jury-bench:" + c["id"])
    unconf = c.get("grade_status") == "unconfirmed" or (c.get("theta") is None and not c.get("skills"))
    cat_id = None if unconf else f"{c['direction']}.{c['grade']}"
    p = CandidateProfile(
        user_id=uid,
        public_ref=c["id"],
        current_direction_id=None if unconf else c["direction"],
        current_grade_id=None if unconf else c["grade"],
        current_category_id=cat_id,
        work_format=WorkFormat(c.get("work_format") or "any"),
        city=c.get("city"),
        relocation=bool(c.get("relocation")),
        privacy={},
        roles=[],
    )
    b = Bundle(profile=p)
    if unconf:
        b.claimed_direction_id = c["direction"]
        b.claimed_grade_id = c["grade"]

    def fact(kind: str, key: str, value: dict, level: EvidenceLevel = EvidenceLevel.T1) -> CandidateFact:
        return CandidateFact(
            user_id=uid,
            kind=kind,
            key=key,
            title=key,
            value=value,
            evidence_level=level,
            source=FactSource.test,
            created_at=utcnow(),
            source_ref="jury-upload:external",
        )

    if not unconf:
        theta_val = c["theta"] if c.get("theta") is not None else 0.5
        b.test = fact("test_result", cat_id or f"{c['direction']}.{c['grade']}", {"theta": theta_val, "se": c["se"], "correct": 8, "answered": 10})
    for s in c.get("skills") or []:
        b.skills_t1[s["tag"]] = fact("skill", s["tag"], {"correct": s["correct"], "total": s["total"], "score": s["score"]})
    b.t0["stack"] = [fact("stack", t, {}, EvidenceLevel.T0) for t in (c.get("declared_stack") or [])]
    if c.get("probe_score") is not None:
        b.probes_t1 = [fact("probe", "Тестовое задание работодателя", {"score": c["probe_score"], "verdict": "Успешно выполнено"})]
    achs: list[FspAchievement] = []
    for a in c.get("achievements") or []:
        if not isinstance(a, dict):
            continue
        disc = str(a.get("discipline") or "algorithmic")
        if disc not in ("algorithmic", "product", "security", "robotics", "uav"):
            disc = "algorithmic"
        lvl = str(a.get("level") or "national")
        if lvl not in ("school", "regional", "interregional", "national", "international"):
            lvl = "national"
        achs.append(
            FspAchievement(
                discipline=disc,
                event_level=FspEventLevel(lvl),
                place=int(a.get("place") or 1),
                event_date=date(2026, 1, 1),
                event_name=str(a.get("event_name") or "Соревнование ФСП"),
                verified=bool(a.get("verified", True)),
                source_ref="jury-upload:external",
            )
        )
    b.achievements = achs
    return b


def _baseline_t0_order(cands: list[dict[str, Any]], req: dict[str, Any]) -> list[str]:
    """Базовая линия по самоописанию (T0): совпадение заявленных тегов резюме и заявленного грейда (без теста T1)."""
    req_tags = {s["tag"] for s in (req.get("stack_required") or []) + (req.get("stack_desired") or [])}
    scored: list[tuple[float, str]] = []
    for c in cands:
        if req.get("direction") and c["direction"] != req["direction"]:
            continue
        decl = set(c.get("declared_stack") or []) | {s["tag"] for s in (c.get("skills") or [])}
        cov = len(req_tags & decl) / max(len(req_tags), 1) if req_tags else 0.5
        g_bonus = 0.2 if (not req.get("grade") or c["grade"] == req["grade"]) else 0.0
        scored.append((cov + g_bonus + 0.01 * min(len(decl), 15), c["id"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [cid for _, cid in scored]


def evaluate_uploaded_dataset(content: str, fmt: str = "json", k: int = 5) -> dict[str, Any]:
    """Оценивает пользовательский набор жюри: ранжирование, объяснение, метрики P@5/P@10/nDCG@10/MRR и CSV."""
    try:
        parsed = parse_uploaded_dataset(content, fmt)
    except ValidationError as exc:
        raise api_error(422, "invalid_dataset", str(exc)) from None

    k = max(1, min(50, int(k or 5)))
    bundles = {c["id"]: _to_bundle(c) for c in parsed["candidates"]}
    cands_by_id = {c["id"]: c for c in parsed["candidates"]}
    labels: dict[tuple[str, str], int] = parsed["labels"]

    per_need: list[dict[str, Any]] = []
    plat_metrics_list: list[dict[str, float]] = []
    base_metrics_list: list[dict[str, float]] = []

    for need in parsed["needs"]:
        req = parse_need(need["text"], need.get("direction"), need.get("grade"), use_llm=False)
        eligible: list[tuple[str, Bundle]] = []
        for cid, b in bundles.items():
            c_dir = b.direction or b.claimed_direction_id
            c_grd = b.grade or b.claimed_grade_id
            if req.get("direction") and c_dir != req["direction"]:
                continue
            if req.get("grade") and c_grd != req["grade"]:
                continue
            eligible.append((cid, b))

        scored_raw = []
        for cid, b in eligible:
            s, comps, reasons = score_candidate(b, req)
            scored_raw.append((s, b, comps, reasons))

        must_map = must_have.tiers_for([b for _, b, _, _ in scored_raw], req)
        core_map = core_skill.assess_pool([b for _, b, _, _ in scored_raw], req)
        ordered = selection_order(scored_raw, must_map, core_map)

        rows: list[dict[str, Any]] = []
        for rank, (s, b, comps, reasons) in enumerate(ordered[: max(k, 10)], start=1):
            cid = b.profile.public_ref
            ci = core_map.get(b.profile.user_id)
            rs = core_skill.annotate(reasons[:1] + [core_skill.reason(ci)] + reasons[1:], ci) if ci else reasons
            c_raw = cands_by_id[cid]
            fake_card = {
                "ref": cid,
                "category": {"id": b.category_id, "title": f"{c_raw['direction']} · {c_raw['grade']}"},
                "status": {"status": b.grade_status},
                "work_format": c_raw.get("work_format"),
                "city": c_raw.get("city"),
                "relocation": c_raw.get("relocation"),
                "skills_confirmed": [{"tag": sk["tag"], "title": sk["tag"], "score": sk["score"]} for sk in c_raw.get("skills") or []],
                "test": {"theta": c_raw.get("theta"), "se": c_raw.get("se"), "correct": 8, "answered": 10} if not b.unconfirmed else None,
                "fsp": {"hidden": False, "achievements": [{"text": f"Соревнование ФСП ({a.get('discipline', 'algorithmic')}, место {a.get('place', 1)})"} for a in c_raw.get("achievements") or []]},
                "probes": [{"title": "Тестовое задание работодателя", "verdict": "Выполнено"}] if c_raw.get("probe_score") else [],
            }
            item = {
                "ref": cid,
                "candidate_id": cid,
                "rank": rank,
                "score": s,
                "score100": round(s * 100, 1),
                "grade_status": b.grade_status,
                "components": comps,
                "reasons": rs,
                "must": must_map[b.profile.user_id],
                "core": ci,
                "relevance": labels.get((need["id"], cid)),
                "card": fake_card,
            }
            item["explain"] = explain_mod.build_explain_from_result(item, req)
            rows.append(item)

        explain_mod.annotate_selection_neighbors(rows, req)
        top_k_rows = rows[:k]

        need_labels = {cid: labels[(need["id"], cid)] for cid in bundles if (need["id"], cid) in labels}
        metrics = None
        if need_labels:
            rels_ordered = [need_labels.get(r["candidate_id"], 0) for r in rows]
            all_rels = list(need_labels.values())
            rel_threshold = 1 if (all_rels and max(all_rels) <= 1) else 2
            k5 = min(5, max(1, len(eligible)))
            k10 = min(10, max(1, len(eligible)))
            k_eff = min(k, max(1, len(eligible)))
            metrics = {
                "p@5": round(eval_precision(rels_ordered, k5, rel_threshold), 4),
                "p@10": round(eval_precision(rels_ordered, k10, rel_threshold), 4),
                f"p@{k}": round(eval_precision(rels_ordered, k_eff, rel_threshold), 4),
                "ndcg@5": round(eval_ndcg(rels_ordered, all_rels, 5), 4),
                "ndcg@10": round(eval_ndcg(rels_ordered, all_rels, 10), 4),
                f"ndcg@{k}": round(eval_ndcg(rels_ordered, all_rels, k), 4),
                "mrr": round(eval_rr(rels_ordered, rel_threshold), 4),
            }
            plat_metrics_list.append(metrics)

            base_order = _baseline_t0_order(parsed["candidates"], req)
            base_rels = [need_labels.get(cid, 0) for cid in base_order]
            base_metrics_list.append({
                "p@5": round(eval_precision(base_rels, k5, rel_threshold), 4),
                "p@10": round(eval_precision(base_rels, k10, rel_threshold), 4),
                "ndcg@5": round(eval_ndcg(base_rels, all_rels, 5), 4),
                "ndcg@10": round(eval_ndcg(base_rels, all_rels, 10), 4),
                "mrr": round(eval_rr(base_rels, rel_threshold), 4),
            })

        per_need.append({
            "need_id": need["id"],
            "title": need["title"],
            "requirements": {
                "direction": req.get("direction"),
                "grade": req.get("grade"),
                "stack_required": req.get("stack_required") or [],
                "stack_desired": req.get("stack_desired") or [],
            },
            "eligible": len(eligible),
            "returned": len(top_k_rows),
            "labeled_pairs": len(need_labels),
            "label_coverage": round(len(need_labels) / max(len(bundles), 1), 3),
            "metrics": metrics,
            "results": top_k_rows,
        })

    def _avg(lst: list[dict[str, float]], key: str) -> float:
        return round(sum(m[key] for m in lst) / len(lst), 4)

    summary = None
    baseline_summary = None
    diff_vs_baseline = None
    if plat_metrics_list:
        keys = ("p@5", "p@10", "ndcg@5", "ndcg@10", "mrr", f"p@{k}", f"ndcg@{k}")
        summary = {key: _avg(plat_metrics_list, key) for key in keys if key in plat_metrics_list[0]}
        baseline_summary = {key: _avg(base_metrics_list, key) for key in ("p@5", "p@10", "ndcg@5", "ndcg@10", "mrr")}
        diff_vs_baseline = {
            key: round(summary[key] - baseline_summary[key], 4)
            for key in ("p@5", "p@10", "ndcg@5", "ndcg@10", "mrr")
        }

    # Оценка правила справедливости 4/5 для кандидатов без истории ФСП на загруженном наборе
    with_fsp_hits, with_fsp_tot = 0, 0
    no_fsp_hits, no_fsp_tot = 0, 0
    for n in per_need:
        top_ids = {r["candidate_id"] for r in (n.get("results") or [])[:5]}
        for cid, b in bundles.items():
            if b.unconfirmed:
                continue
            has_fsp = bool(b.achievements)
            in_top = cid in top_ids
            if has_fsp:
                with_fsp_tot += 1
                with_fsp_hits += int(in_top)
            else:
                no_fsp_tot += 1
                no_fsp_hits += int(in_top)
    rate_no_fsp = no_fsp_hits / max(no_fsp_tot, 1) if no_fsp_tot else 1.0
    rate_with_fsp = with_fsp_hits / max(with_fsp_tot, 1) if with_fsp_tot else rate_no_fsp
    fairness = bias_mod.fairness_four_fifths(
        rate_no_fsp,
        rate_with_fsp,
        n_without_fsp=no_fsp_tot,
        n_with_fsp=with_fsp_tot,
    )

    # Генерация CSV для мгновенного скачивания
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow([
        "need_id",
        "need_title",
        "rank",
        "candidate_id",
        "score100",
        "grade_status",
        "relevance",
        "headline",
        "why_above_next",
        "p@5",
        "ndcg@10",
        "mrr",
    ])
    for n in per_need:
        m = n.get("metrics") or {}
        for r in n["results"]:
            exp = r.get("explain") or {}
            why = (r.get("why_above_next") or {}).get("headline") or ""
            writer.writerow([
                safe_csv_cell(x)
                for x in (
                    n["need_id"],
                    n["title"],
                    r["rank"],
                    r["candidate_id"],
                    r["score100"],
                    r["grade_status"],
                    r.get("relevance") if r.get("relevance") is not None else "",
                    exp.get("headline") or "",
                    why,
                    m.get("p@5", ""),
                    m.get("ndcg@10", ""),
                    m.get("mrr", ""),
                )
            ])

    return {
        "algorithm": algorithm(),
        "n_needs": len(parsed["needs"]),
        "n_candidates": len(parsed["candidates"]),
        "n_labels": len(labels),
        "k": k,
        "evaluated_needs": len(plat_metrics_list),
        "summary": summary,
        "baseline_t0": baseline_summary,
        "diff_vs_baseline": diff_vs_baseline,
        "fairness": fairness,
        "per_need": per_need,
        "csv_export": "\ufeff" + csv_buf.getvalue(),
        "note": (
            "Набор обработан изолированно в памяти запроса (общая база кандидатов не изменяется). "
            "Категория и фильтр грейда — только по подтверждённому тесту (T1); внутри категории — тест (T1), "
            "подтверждённый стек (T1), достижения ФСП (T2) и короткие задания (T1). Самоописание (T0) в балл не входит."
        ),
    }


SAMPLE_DATASET: dict[str, Any] = {
    "needs": [
        {
            "id": "vac-backend-py",
            "title": "Backend-разработчик Middle (Python / FastAPI / PostgreSQL)",
            "text": "Backend-разработчик уровня middle: обязательно Python, FastAPI и PostgreSQL, Docker. Будет плюсом Redis и Kafka. Удалённо, 220 000 – 280 000 ₽ на руки.",
            "direction": "backend",
            "grade": "middle",
        },
        {
            "id": "vac-frontend-react",
            "title": "Frontend-разработчик Middle (TypeScript / React)",
            "text": "Ищем Frontend-разработчика middle: обязательно TypeScript, React и HTML/CSS. Желательно Next.js и управление состоянием. Удалённо.",
            "direction": "frontend",
            "grade": "middle",
        },
    ],
    "candidates": [
        {
            "id": "cand-py-strong",
            "direction": "backend",
            "grade": "middle",
            "theta": 0.95,
            "se": 0.25,
            "work_format": "remote",
            "skills": [
                {"tag": "python", "correct": 5, "total": 5},
                {"tag": "fastapi", "correct": 4, "total": 4},
                {"tag": "postgresql", "correct": 4, "total": 5},
                {"tag": "docker", "correct": 3, "total": 4},
                {"tag": "redis", "correct": 3, "total": 4},
            ],
            "declared_stack": ["python", "fastapi", "postgresql", "docker", "redis"],
            "achievements": [{"discipline": "product", "level": "national", "place": 2}],
        },
        {
            "id": "cand-py-solid-no-fsp",
            "direction": "backend",
            "grade": "middle",
            "theta": 0.88,
            "se": 0.27,
            "work_format": "remote",
            "skills": [
                {"tag": "python", "correct": 4, "total": 5},
                {"tag": "fastapi", "correct": 4, "total": 5},
                {"tag": "postgresql", "correct": 4, "total": 5},
                {"tag": "docker", "correct": 3, "total": 4},
            ],
            "declared_stack": ["python", "fastapi", "postgresql", "docker"],
            "achievements": [],
        },
        {
            "id": "cand-py-inflated-t0",
            "direction": "backend",
            "grade": "middle",
            "theta": -0.25,
            "se": 0.38,
            "work_format": "remote",
            "skills": [{"tag": "python", "correct": 1, "total": 5}],
            "declared_stack": ["python", "fastapi", "postgresql", "docker", "redis", "kafka", "kubernetes", "go"],
            "achievements": [],
        },
        {
            "id": "cand-fe-strong",
            "direction": "frontend",
            "grade": "middle",
            "theta": 0.92,
            "se": 0.26,
            "work_format": "remote",
            "skills": [
                {"tag": "typescript", "correct": 5, "total": 5},
                {"tag": "react", "correct": 4, "total": 5},
                {"tag": "html-css", "correct": 4, "total": 4},
                {"tag": "nextjs", "correct": 3, "total": 4},
            ],
            "declared_stack": ["typescript", "react", "html-css", "nextjs"],
            "achievements": [{"discipline": "product", "level": "regional", "place": 1}],
        },
        {
            "id": "cand-fe-inflated-t0",
            "direction": "frontend",
            "grade": "middle",
            "theta": -0.15,
            "se": 0.40,
            "work_format": "remote",
            "skills": [{"tag": "html-css", "correct": 1, "total": 4}],
            "declared_stack": ["typescript", "react", "html-css", "nextjs", "state-management", "vue", "angular"],
            "achievements": [],
        },
    ],
    "labels": [
        {"need_id": "vac-backend-py", "candidate_id": "cand-py-strong", "relevance": 3},
        {"need_id": "vac-backend-py", "candidate_id": "cand-py-solid-no-fsp", "relevance": 3},
        {"need_id": "vac-backend-py", "candidate_id": "cand-py-inflated-t0", "relevance": 0},
        {"need_id": "vac-frontend-react", "candidate_id": "cand-fe-strong", "relevance": 3},
        {"need_id": "vac-frontend-react", "candidate_id": "cand-fe-inflated-t0", "relevance": 0},
    ],
}


def sample_dataset_response(fmt: str = "json") -> tuple[str, str, str]:
    """Возвращает (содержимое, media_type, filename) для образца набора жюри."""
    if (fmt or "json").lower() == "csv":
        buf = io.StringIO()
        fields = [
            "kind",
            "id",
            "title",
            "text",
            "direction",
            "grade",
            "theta",
            "se",
            "work_format",
            "skills",
            "declared_stack",
            "achievements",
            "need_id",
            "candidate_id",
            "relevance",
        ]
        w = csv.DictWriter(buf, fieldnames=fields)
        w.writeheader()
        for n in SAMPLE_DATASET["needs"]:
            w.writerow({"kind": "need", **n})
        for c in SAMPLE_DATASET["candidates"]:
            w.writerow({
                "kind": "candidate",
                **{k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in c.items()},
            })
        for lb in SAMPLE_DATASET["labels"]:
            w.writerow({"kind": "label", **lb})
        return "\ufeff" + buf.getvalue(), "text/csv; charset=utf-8", "jury-benchmark-sample.csv"
    return json.dumps(SAMPLE_DATASET, ensure_ascii=False, indent=2), "application/json", "jury-benchmark-sample.json"
