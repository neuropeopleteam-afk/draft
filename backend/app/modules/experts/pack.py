"""Пакет экспертной разметки (версия PACK) и назначения экспертам.

A. Пары «потребность — кандидат». 10 потребностей демо-данных (по две на направление, как в протоколе) ×
   пул кандидатов: объединение топ-5 платформы, топ-5 BM25 и случайной выборки из остальной базы (2 кандидата).
   Платформа и BM25 ранжируют ВСЮ демо-базу кандидатов (150 карточек), поэтому их топ-5 размечены полностью,
   а случайная выборка даёт несмещённую оценку «случайного порядка» по всей базе (стратифицированно: топы — целиком,
   остальное — по выборке). Эксперт видит обезличенную карточку без ранга, скора, объяснения, источника пула и
   разметки по правилам; всё это — в hidden.
B. Развёрнутые ответы: 24 ответа (data/pack_b_answers.json) на варианты открытых заданий банка (seed фиксирован):
   задание, код, вопрос шага, рубрика с эталонами — генерируются банком детерминированно.
C. Ангофф: семейства банка (без канареек) с примером варианта; параметры a, b — те же, что у движка теста.

Пакет — снимок: карточки и ранги сохраняются при сборке, последующие изменения демо-данных его не меняют.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import random

import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.experts.models import ExpertItem

PACK = "v1"
DATA = Path(__file__).resolve().parent / "data"
A_NEEDS = ["N00", "N06", "N08", "N09", "N02", "N03", "N12", "N13", "N04", "N05"]
A_CORE = ["N00", "N06", "N08"]
A_TOP, A_RANDOM = 5, 2
# Распределение потребностей при трёх экспертах (протокол, раздел 5): ядро — всем, остальные — по двое.
A_PLAN3 = {"E1": A_CORE + ["N09", "N02", "N03", "N12", "N05"],
           "E2": A_CORE + ["N02", "N12", "N13", "N04"],
           "E3": A_CORE + ["N09", "N03", "N13", "N04", "N05"]}
# Если экспертов двое: ядро — обоим (на нём считается согласие), остальные потребности — по одному эксперту.
A_PLAN2 = {"E1": A_CORE + ["N09", "N02", "N03"], "E2": A_CORE + ["N12", "N13", "N04", "N05"]}
A_DEMO = ["N00", "N06"]
SLOTS = ("E1", "E2", "E3")
B_SEED, C_SEED = 8100001, 8200001
C_CORE_N = 10
# Ангофф: блоки направлений у слотов (протокол, раздел 7): (направление, сколько семейств, смещение выборки)
C_PLAN = {"E1": [("backend", 10, 0), ("data_ml", 10, 0)],
          "E2": [("frontend", 10, 0), ("qa", 10, 0)],
          "E3": [("security", 12, 0), ("backend", 8, 1)]}
OPTION_FLOOR_FORMATS = {"mcq_concept", "choose_fix"}
FORMAT_TITLES = {"find_bug": "Найти строку с дефектом", "predict_output": "Предсказать вывод", "choose_fix": "Выбрать исправление",
                 "open_book_3step": "Open book, 3 шага", "mcq_concept": "Вопрос с выбором ответа",
                 "open_answer": "Развёрнутый ответ"}
BLOCK_TITLES = {"common": "Общий блок", "backend": "Backend", "frontend": "Frontend", "data_ml": "Data/ML", "qa": "QA",
                "security": "Информационная безопасность"}


def need_texts() -> dict[str, str]:
    from app.modules.demo.seed import NEEDS

    return {f"N{i:02d}": t for i, (_, t) in enumerate(NEEDS)}


# ------------------------------------------------------------------ A: пары
def _blind_card(c: dict) -> dict:
    """Обезличенная карточка для эксперта: только факты кандидата, без ранга, скора и ref."""
    t = c.get("test") or {}
    integ = t.get("integrity") or {}
    return {
        "category": (c.get("category") or {}).get("title"),
        "test": {"theta": t.get("theta"), "se": t.get("se"), "answered": t.get("answered"), "correct": t.get("correct"),
                 "date": t.get("date")} if t else None,
        "integrity": {"level": integ.get("level"), "title": integ.get("title"), "reasons": integ.get("reasons") or []}
        if integ else None,
        "skills_confirmed": [{"title": s["title"], "score": s.get("score")} for s in c.get("skills_confirmed") or []],
        "stack_declared": [s["title"] for s in c.get("stack_declared") or []],
        "experience_years": c.get("experience_years"),
        "work_format": c.get("work_format"),
        "city": c.get("city"),
        "relocation": c.get("relocation"),
        "fsp": [a["text"] for a in ((c.get("fsp") or {}).get("achievements") or [])],
    }


def _demo_bundles(db: Session):
    from app.modules.auth.models import User
    from app.modules.jury.seed import DOMAIN
    from app.modules.profiles.facts import load_bundles
    from app.modules.profiles.models import CandidateProfile

    ids = db.scalars(select(CandidateProfile.user_id).join(User, User.id == CandidateProfile.user_id)
                     .where(User.is_demo.is_(True), CandidateProfile.current_category_id.is_not(None),
                            ~User.email.like(f"%@{DOMAIN}"))).all()
    return sorted(load_bundles(db, list(ids)).values(), key=lambda b: (b.profile.public_ref or ""))


def build_a(db: Session, seed: int = 20261007) -> list[dict]:
    from app.modules.catalog.models import Category
    from app.modules.matching.need_parser import parse_need
    from app.modules.matching.ranking import score_candidate
    from app.modules.profiles.facts import card
    from app.modules.profiles.models import CandidateResume
    from app.modules.validation.matching_eval import BM25, candidate_text, label, selection_categories

    bundles = _demo_bundles(db)
    if len(bundles) < 20:
        return []
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    resumes: dict = {}
    for r in db.scalars(select(CandidateResume).where(CandidateResume.user_id.in_([b.profile.user_id for b in bundles]))):
        resumes[r.user_id] = (resumes.get(r.user_id, "") + " " + (r.text_redacted or "")).strip()
    bm = BM25({b.profile.user_id: candidate_text(b, resumes.get(b.profile.user_id, "")) for b in bundles})
    texts = need_texts()
    out = []
    for ni, nid in enumerate(A_NEEDS):
        text = texts[nid]
        req = parse_need(text, use_llm=False)
        ok = selection_categories(req)
        sc = {b.profile.user_id: score_candidate(b, req)[0] for b in bundles}
        bs = {b.profile.user_id: bm.score(b.profile.user_id, text) for b in bundles}
        tie = random.Random(seed + ni)
        tiebreak = {b.profile.user_id: tie.random() for b in bundles}
        plat = sorted(bundles, key=lambda b: (0 if ok is None or b.profile.current_category_id in ok else 1,
                                              -sc[b.profile.user_id], -(b.profile.rating_score or 0), b.profile.public_ref))
        bm25 = sorted(bundles, key=lambda b: (-bs[b.profile.user_id], tiebreak[b.profile.user_id]))
        rp = {b.profile.user_id: i + 1 for i, b in enumerate(plat)}
        rb = {b.profile.user_id: i + 1 for i, b in enumerate(bm25)}
        union = []
        for b in plat[:A_TOP] + bm25[:A_TOP]:
            if b not in union:
                union.append(b)
        rest = [b for b in bundles if b not in union]
        rnd = random.Random(seed * 31 + ni)
        sample = rnd.sample(rest, min(A_RANDOM, len(rest)))
        for b in union + sample:
            uid = b.profile.user_id
            src = [s for s, top in (("platform", plat[:A_TOP]), ("bm25", bm25[:A_TOP])) if b in top]
            if b in sample:
                src.append("random")
            out.append({
                "kind": "A", "key": f"A:{nid}:{b.profile.public_ref}", "grp": nid,
                "payload": {"need_id": nid, "need_text": text, "card": _blind_card(card(b, cats))},
                "hidden": {"need": nid, "ref": b.profile.public_ref, "category": b.profile.current_category_id,
                           "sources": src, "rank_platform": rp[uid], "rank_bm25": rb[uid],
                           "score_platform": round(sc[uid], 4), "score_bm25": round(bs[uid], 4),
                           "rule_label": label(b, req), "n_population": len(bundles), "n_union": len(union),
                           "parsed": {"direction": req.get("direction"), "grade": req.get("grade")}},
            })
    return out


# ------------------------------------------------------------------ B: ответы
@lru_cache(maxsize=1)
def b_answers() -> dict:
    return json.loads((DATA / "pack_b_answers.json").read_text(encoding="utf-8"))


def _variant_view(family_id: str, seed: int) -> dict:
    from assessment_bank import generate, get_spec

    spec = get_spec(family_id)
    v = generate(family_id, seed)
    steps = [s.model_dump() for s in (v.meta.steps or [])]
    return {"family_id": family_id, "title": spec.title, "format": spec.format, "block": spec.block,
            "target_grades": list(spec.target_grades), "skills": list(spec.skills), "language": spec.language,
            "stem": v.stem, "code": v.code, "steps": steps,
            "options": [o.model_dump(exclude_none=True) for o in (v.options or [])],
            "key": v.answer_key.model_dump(include={"kind", "value"}),
            "rubric": v.rubric.model_dump() if v.rubric else None, "time_limit_s": spec.time_limit_s}


def build_b() -> list[dict]:
    d = b_answers()
    out = []
    for a in d["answers"]:
        v = _variant_view(a["family_id"], d["seed"])
        step_prompt = v["steps"][-1]["prompt"] if v["format"] == "open_book_3step" and v["steps"] else None
        out.append({
            "kind": "B", "key": f"B:{a['id']}", "grp": a["family_id"],
            "payload": {"family_title": v["title"], "block": v["block"], "format": v["format"], "stem": v["stem"],
                        "code": v["code"], "language": v["language"], "step_prompt": step_prompt,
                        "rubric": v["rubric"], "answer": a["answer"]},
            "hidden": {"answer_id": a["id"], "family_id": a["family_id"], "seed": d["seed"], "intended": a["intended"],
                       "control": a.get("control"), "part": 2 if v["format"] == "open_book_3step" else 0, "llm": {}},
        })
    return out


# ------------------------------------------------------------------ C: Ангофф
def _family_params() -> dict[str, dict]:
    from app.modules.assessment.bank_engine import _pool

    return {pi.family_id: {"a": [round(float(x), 4) for x in pi.a_eff], "b": [round(float(x), 4) for x in pi.b],
                           "block": pi.block, "format": pi.format, "canary": pi.canary} for pi in _pool(1)}


def _evenly(fams: list[str], n: int, offset: int = 0) -> list[str]:
    if n >= len(fams):
        return list(fams)
    step = len(fams) / n
    return [fams[min(len(fams) - 1, int(i * step + offset * step / 2))] for i in range(n)]


@lru_cache(maxsize=1)
def c_plan() -> dict[str, list[str]]:
    """Семейства для Ангоффа: ядро общего блока + блоки направлений по слотам, равномерно по трудности."""
    params = _family_params()
    by_block: dict[str, list[str]] = {}
    for fid, p in params.items():
        if not p["canary"]:
            by_block.setdefault(p["block"], []).append(fid)
    for blk in by_block:
        by_block[blk].sort(key=lambda f: (float(np.mean(params[f]["b"])), f))
    core = _evenly(by_block.get("common", []), C_CORE_N)
    plan = {"core": core}
    used: dict[str, set] = {}
    for slot, blocks in C_PLAN.items():
        fams = []
        for blk, n, off in blocks:
            pool = [f for f in by_block.get(blk, []) if f not in used.get(blk, set())]
            pick = _evenly(pool, n, off)
            used.setdefault(blk, set()).update(pick)
            fams += pick
        plan[slot] = fams
    return plan


def build_c() -> list[dict]:
    params = _family_params()
    plan = c_plan()
    fams = list(dict.fromkeys(plan["core"] + [f for s in SLOTS for f in plan[s]]))
    out = []
    for fid in fams:
        v = _variant_view(fid, C_SEED)
        p = params[fid]
        n_opt = len([o for o in v["options"] if not o.get("step")]) if v["options"] else 0
        floor = 25 if v["format"] in OPTION_FLOOR_FORMATS and n_opt == 4 else 0
        out.append({
            "kind": "C", "key": f"C:{fid}", "grp": "core" if fid in plan["core"] else p["block"],
            "payload": {**{k: v[k] for k in ("family_id", "title", "format", "block", "skills", "language",
                                             "stem", "code", "steps", "options", "key", "time_limit_s")},
                        "rubric": ({k: v["rubric"].get(k) for k in ("criteria", "strong", "medium", "weak")}
                                   if v["rubric"] else None),
                        "format_title": FORMAT_TITLES.get(v["format"], v["format"]),
                        "block_title": BLOCK_TITLES.get(v["block"], v["block"]), "floor": floor},
            "hidden": {"a": p["a"], "b": p["b"], "format": p["format"], "block": p["block"]},
        })
    return out


# ------------------------------------------------------------------ сборка и назначение
def pack_exists(db: Session, pack: str = PACK) -> bool:
    return db.scalar(select(ExpertItem.id).where(ExpertItem.pack == pack, ExpertItem.kind == "A").limit(1)) is not None


def ensure_pack(db: Session, pack: str = PACK) -> bool:
    """Собирает пакет, если его ещё нет и есть демо-данные. True — пакет есть (готов или собран сейчас)."""
    if pack_exists(db, pack):
        return True
    items = build_a(db)
    if not items:
        return False
    items += build_b() + build_c()
    try:
        for i, it in enumerate(items):
            db.add(ExpertItem(pack=pack, position=i, **it))
        db.commit()
    except IntegrityError:  # другой воркер собрал одновременно
        db.rollback()
    return pack_exists(db, pack)


def assignment(db: Session, slot: str, team_size: int = 3, pack: str = PACK) -> dict[str, list[str]]:
    """Назначение эксперту: ключи объектов A, B, C в порядке показа (перемешано детерминированно по слоту)."""
    rows = db.execute(select(ExpertItem.kind, ExpertItem.key, ExpertItem.grp, ExpertItem.hidden)
                      .where(ExpertItem.pack == pack).order_by(ExpertItem.position)).all()
    return assignment_from_rows([tuple(r) for r in rows], slot, team_size, pack)


def assignment_from_rows(rows: list[tuple], slot: str, team_size: int = 3, pack: str = PACK) -> dict[str, list[str]]:
    """rows: (kind, key, grp, hidden) в порядке пакета."""
    rnd = random.Random(f"{pack}:{slot}")
    if slot == "DEMO":
        needs = A_DEMO
    elif team_size <= 2:
        needs = A_PLAN2.get(slot, A_NEEDS)
    else:
        needs = A_PLAN3.get(slot, A_NEEDS)
    a_keys = []
    for nid in needs:
        grp = [k for kind, k, g, _ in rows if kind == "A" and g == nid]
        rnd.shuffle(grp)
        a_keys += grp
    b_all = [(k, h) for kind, k, _, h in rows if kind == "B"]
    plain = [k for k, h in b_all if not h.get("control")]
    controls = [k for k, h in b_all if h.get("control")]
    rnd.shuffle(plain)
    b_keys = plain[:]
    for j, c in enumerate(controls):  # контрольные — не первыми и не подряд
        b_keys.insert(min(len(b_keys), 5 + j * 9 + rnd.randint(0, 3)), c)
    if slot == "DEMO":
        b_keys = [k for k in plain[:6]]
    plan = c_plan()
    c_rows = {k: g for kind, k, g, _ in rows if kind == "C"}
    if slot == "DEMO":
        fams = plan["core"][:4] + plan["E1"][:2]
    else:
        fams = plan["core"] + plan.get(slot, [])
    core = [f"C:{f}" for f in fams if f in plan["core"]]
    other = [f"C:{f}" for f in fams if f not in plan["core"]]
    rnd.shuffle(core)
    rnd.shuffle(other)
    c_keys = [k for k in core + other if k in c_rows]
    return {"A": a_keys, "B": b_keys, "C": c_keys}
