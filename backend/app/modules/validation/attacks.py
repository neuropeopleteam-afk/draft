"""«Красная кнопка жюри»: атаки на подбор и тест, которые эксперт запускает сам.

Каждая атака выполняется на живых демо-данных В ПАМЯТИ: объекты меняются только в пределах запроса, после —
db.rollback() (ничего не записывается). Ответ: ожидаемое свойство, факт (числа до/после), нарушено или нет.
"""
from __future__ import annotations

from datetime import date
import random
import re
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EvidenceLevel, FactSource, FspEventLevel
from app.modules.catalog.models import Category
from app.modules.matching.models import EmployerNeed
from app.modules.matching.need_parser import parse_need
from app.modules.matching.ranking import WEIGHTS, score_candidate
from app.modules.profiles.facts import Bundle, CandidateFact, card, load_bundles
from app.modules.fsp.models import FspAchievement
from app.modules.profiles.models import CandidateProfile

DEFAULT_NEED = ("Ищем бэкенд-разработчика уровня middle: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. "
                "Будет плюсом Kafka. Удалённо, 220–300 тыс.")
ATTACKS = [
    {"id": "inflate_keywords", "title": "Раздуть резюме ключевыми словами",
     "action": "Кандидату из середины подборки дописываем в резюме/анкету все навыки потребности и ещё 20 модных слов",
     "expected": "Скор и место в подборке не меняются: заявленные навыки (T0) в ранжирование не входят"},
    {"id": "rename", "title": "Поменять имя при тех же навыках",
     "action": "Тому же кандидату меняем ФИО (другой пол и происхождение имени)",
     "expected": "Скор не меняется ни на тысячную, ФИО нет в карточке работодателя"},
    {"id": "fake_fsp", "title": "Добавить неподтверждённый значок ФСП",
     "action": "Кандидату без ФСП добавляем «победу на Чемпионате России» без подтверждения реестром",
     "expected": "Ни бонуса ФСП, ни отметки T2: в карточке и объяснении — только подтверждённое реестром"},
    {"id": "remove_fsp", "title": "Убрать историю ФСП",
     "action": "У кандидата с подтверждёнными достижениями ФСП удаляем паспорт и достижения",
     "expected": "Скор падает ровно на бонус ФСП (вес 0,10 × сила), без штрафа: статус «нейтрально»"},
    {"id": "leak_bank", "title": "«Слить» часть банка заданий",
     "action": "Симуляция: публикуем долю вариантов банка, четверть кандидатов знает ответы; тест с детектором и без",
     "expected": "Без защиты завышение θ у списывающих заметно; детектор + карантин субпула снижают его, "
                 "ложные срабатывания у честных ≈ 1 %"},
]


def _need_req(db: Session, need_id: uuid.UUID | None) -> tuple[dict, str]:
    if need_id:
        n = db.get(EmployerNeed, need_id)
        if n is not None and n.requirements:
            return n.requirements, n.raw_text
    return parse_need(DEFAULT_NEED, use_llm=False), DEFAULT_NEED


def _pool(db: Session, req: dict) -> list[Bundle]:
    q = select(CandidateProfile).where(CandidateProfile.current_category_id.is_not(None),
                                       CandidateProfile.visible_to_employers.is_(True))
    if req.get("direction"):
        q = q.where(CandidateProfile.current_direction_id == req["direction"])
    ps = db.scalars(q).all()
    return sorted(load_bundles(db, [p.user_id for p in ps]).values(), key=lambda b: b.profile.public_ref or "")


def _rank(pool: list[Bundle], req: dict) -> list[tuple[float, Bundle]]:
    sc = [(score_candidate(b, req)[0], b) for b in pool]
    sc.sort(key=lambda x: (-x[0], -(x[1].profile.rating_score or 0), x[1].profile.public_ref or ""))
    return sc


def _pos(ranked, b) -> int:
    return next(i for i, (_, x) in enumerate(ranked, start=1) if x is b)


def _fact(user_id, tag: str) -> CandidateFact:
    return CandidateFact(user_id=user_id, kind="stack", key=tag, title=tag, value={"declared": True},
                         evidence_level=EvidenceLevel.T0, source=FactSource.resume, source_ref="attack")


BUZZ = ["kubernetes", "kafka", "graphql", "rust", "go", "react", "terraform", "spark", "clickhouse", "airflow",
        "pytorch", "llm", "microservices", "ci_cd", "aws", "redis", "elasticsearch", "rabbitmq", "grpc", "nginx"]


def run(db: Session, attack_id: str, need_id: uuid.UUID | None = None, params: dict | None = None) -> dict:
    meta = next((a for a in ATTACKS if a["id"] == attack_id), None)
    if meta is None:
        raise KeyError(attack_id)
    t0 = time.time()
    try:
        if attack_id == "leak_bank":
            out = _leak(params or {})
        else:
            req, text = _need_req(db, need_id)
            out = _profile_attack(db, attack_id, req)
            out["need"] = text
    finally:
        db.rollback()  # ничего из атаки не записывается
    if isinstance(out.get("fact"), str):  # десятичная запятая и «30 %» — как в остальном интерфейсе
        out["fact"] = re.sub(r"(\d)%", r"\1 %", re.sub(r"(?<=\d)\.(?=\d)", ",", out["fact"]))
    return {**meta, **out, "seconds": round(time.time() - t0, 2)}


def _profile_attack(db: Session, attack_id: str, req: dict) -> dict:
    pool = _pool(db, req)
    if len(pool) < 5:
        return {"violated": None, "fact": "Мало кандидатов в пуле для проверки", "details": {}}
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    ranked = _rank(pool, req)
    rnd = random.Random(int(time.time()))
    with db.no_autoflush:
        if attack_id in ("inflate_keywords", "rename"):
            mid = [b for _, b in ranked[len(ranked) // 3: 2 * len(ranked) // 3]] or [b for _, b in ranked]
            b = rnd.choice(mid)
            s0, p0 = score_candidate(b, req)[0], _pos(ranked, b)
            if attack_id == "inflate_keywords":
                tags = [i["tag"] for i in (req.get("stack_required") or []) + (req.get("stack_desired") or [])] + BUZZ
                added = [t for t in dict.fromkeys(tags) if t not in b.stack_t0]
                b.t0["stack"] = list(b.t0.get("stack", [])) + [_fact(b.profile.user_id, t) for t in added]
                s1, p1 = score_candidate(b, req)[0], _pos(_rank(pool, req), b)
                return {"violated": abs(s1 - s0) > 1e-9 or p1 != p0,
                        "fact": f"Кандидат {b.profile.public_ref}: дописано {len(added)} навыков; скор {s0:.4f} → {s1:.4f}, "
                                f"место {p0} → {p1} из {len(pool)}",
                        "details": {"ref": b.profile.public_ref, "added": added, "score_before": s0, "score_after": s1,
                                    "rank_before": p0, "rank_after": p1, "pool": len(pool)}}
            old = b.profile.full_name or ""
            new = "Гульнара Абдуллаева" if not old.endswith("а") else "Тимур Ким"
            b.profile.full_name = new
            s1 = score_candidate(b, req)[0]
            c = card(b, cats)
            leak = any(x and x in str(c) for x in (new, old, *(new.split()), *(old.split())))
            return {"violated": abs(s1 - s0) > 1e-12 or leak,
                    "fact": f"Кандидат {b.profile.public_ref}: имя изменено; скор {s0:.4f} → {s1:.4f}; "
                            f"ФИО в карточке работодателя: {'есть' if leak else 'нет'}",
                    "details": {"ref": b.profile.public_ref, "score_before": s0, "score_after": s1, "name_in_card": leak}}
        if attack_id == "fake_fsp":
            no_fsp = [b for _, b in ranked if not b.achievements] or [b for _, b in ranked]
            b = rnd.choice(no_fsp[: max(1, len(no_fsp) // 2)])
            s0, p0 = score_candidate(b, req)[0], _pos(ranked, b)
            fake = FspAchievement(passport_id=uuid.uuid4(), discipline="product", event_level=FspEventLevel.national,
                                  event_name="Чемпионат России по продуктовому программированию", event_date=date(2026, 3, 1),
                                  place=1, result_title="победитель", verified=False, source_ref="self-claim")
            b.achievements = [fake]
            s1, reasons = score_candidate(b, req)[0], score_candidate(b, req)[2]
            p1 = _pos(_rank(pool, req), b)
            c = card(b, cats)
            t2 = any(r.get("level") == "T2" for r in reasons) or (c.get("fsp") or {}).get("level") == "T2" \
                or bool((c.get("fsp") or {}).get("achievements"))
            return {"violated": abs(s1 - s0) > 1e-9 or t2 or p1 != p0,
                    "fact": f"Кандидат {b.profile.public_ref}: добавлен значок без подтверждения; скор {s0:.4f} → {s1:.4f}, "
                            f"место {p0} → {p1}; отметка T2: {'есть' if t2 else 'нет'}",
                    "details": {"ref": b.profile.public_ref, "score_before": s0, "score_after": s1, "rank_before": p0,
                                "rank_after": p1, "t2_shown": t2}}
        if attack_id == "remove_fsp":
            with_fsp = [b for _, b in ranked if b.fsp > 0]
            if not with_fsp:
                return {"violated": None, "fact": "В пуле нет кандидатов с подтверждённым ФСП", "details": {}}
            b = rnd.choice(with_fsp)
            s0, comps0, _ = score_candidate(b, req)
            bonus = WEIGHTS["fsp"] * comps0["fsp"]
            b.achievements, b.passport = [], None
            s1, comps1, reasons = score_candidate(b, req)
            st = next((r for r in reasons if r["requirement"] == "Достижения ФСП"), {})
            drop = s0 - s1
            return {"violated": abs(drop - bonus) > 1e-3 or st.get("status") != "neutral",
                    "fact": f"Кандидат {b.profile.public_ref}: скор {s0:.4f} → {s1:.4f}, снижение {drop:.4f} при бонусе ФСП "
                            f"{bonus:.4f}; статус: «{st.get('text', '')}»",
                    "details": {"ref": b.profile.public_ref, "score_before": s0, "score_after": s1, "bonus": round(bonus, 4),
                                "drop": round(drop, 4), "status": st.get("status")}}
    raise KeyError(attack_id)


def _leak(params: dict) -> dict:
    import numpy as np

    from assessment_bank.simulation import make_truth
    from app.modules.assessment.exposure import exposure_table
    from app.modules.validation.sim import app_config_from_settings, leak_experiment, make_pool

    share = float(params.get("leak_share", 0.3))
    share = min(0.8, max(0.1, share))
    direction = params.get("direction") if params.get("direction") in ("backend", "frontend", "data_ml", "qa",
                                                                       "security") else "backend"
    cfg = app_config_from_settings()
    rng = np.random.default_rng(int(time.time()) % 10_000)
    pool = make_pool(cfg.subpools)
    truth = make_truth(pool, rng, misspec=0.5)
    k = (exposure_table() or {}).get("k", {}).get(direction, {})
    r = leak_experiment(pool, truth, direction, cfg, rng, k, n=160, leak_share=share)
    nd, dt, rot = r["leak_no_detector"], r["leak_detector"], r["leak_detector_rotation"]
    infl_nd, infl_dt = nd["cheaters_bias_theta"], dt["cheaters_bias_theta"]
    fpr = dt.get("detector_fpr") or 0.0
    violated = not (infl_dt is not None and infl_nd is not None and infl_dt < infl_nd and fpr <= 0.05)
    return {"violated": violated,
            "fact": f"Утечка {share:.0%} вариантов ({direction}, 160 симулированных кандидатов, из них 25 % списывают): "
                    f"завышение θ у списывающих без детектора {infl_nd:+.2f}, с детектором {infl_dt:+.2f}, "
                    f"с карантином субпула {rot['cheaters_bias_theta']:+.2f}; детектор поймал {dt.get('detector_tpr', 0):.0%} "
                    f"списывающих, ложные срабатывания у честных {fpr:.1%}",
            "details": r}
