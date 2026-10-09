"""Пакет экспертной разметки v2 — вторая волна оценок блока A (пары «потребность — кандидат»), блоки B и C не трогаются.

Зачем. По v1 размечено около 100 пар; на таком объёме разница подбора с базовой линией не значима. v2 добавляет
≈ 200 новых пар по всем демо-потребностям текущего мира, каждая пара — двум ролям из E1–E3 (для согласия).

Состав (на потребность; ранги — в текущем мире, только демо-кандидаты, без персон жюри и живых пользователей):
* top  — топ-8 подборки match-v1 (тот же порядок, что ranking.build_selection: ярус статуса грейда → скор →
         рейтинг → ref);
* mid  — 3 случайных из мест 9–30 подборки;
* hard — 2 «трудных отрицательных»: случайно из той же категории вне топ-30 (места 31+ подборки); если там меньше
         двух — из соседних грейдов того же направления, затем из остального направления (вне подборки).
Пары, совпавшие с v1 (та же потребность по тексту и тот же кандидат по снимку карточки — ref после
`demo.seed --reset` меняется, поэтому сверка по отпечатку карточки), заново не размечаются: строка v2 хранит
ссылку на ключ v1 (hidden.borrowed_from), её эталон для метрик v2 — оценки v1. Зерно фиксировано, кадры выборки
упорядочены по номеру демо-кандидата — сборка детерминирована.

Карточка пары вслепую, как в v1: без места, баллов и названия метода; порядок предъявления перемешан по роли.
Назначение: каждая потребность целиком — паре ролей (E1+E2, E1+E3 или E2+E3), жадно по нагрузке; на роль ≤ 160
пар. Потребности песочницы жюри (J00–J02) добавляются, пока объём помещается в лимит.

Разметка — офлайн, файлами (команды pack2 build / export / import в __main__), оценки проходят те же проверки, что
save_label. Пакет — снимок: после сборки изменения демо-данных его не меняют.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import json
import random
import re
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.enums import UserRole
from app.core.errors import api_error
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.experts import pack as P
from app.modules.experts.models import ExpertItem, ExpertLabel, ExpertPanelist

PACK2 = "v2"
SEED2 = 20261008
TOP, MID_LO, MID_HI, MID_N, HARD_N = 8, 9, 30, 3, 2
ROLES = ("E1", "E2", "E3")
ROLE_PAIRS = (("E1", "E2"), ("E1", "E3"), ("E2", "E3"))
ROLE_MAX = 160
PAIRS_MAX = ROLE_MAX * len(ROLES) // 2  # каждая пара — двум ролям: 240 пар = по 160 на роль
STRATA = {"top": f"топ-{TOP} match-v1", "mid": f"случайно из мест {MID_LO}–{MID_HI}", "hard": "трудный отрицательный"}
WORK_FORMAT = {"remote": "удалённо", "hybrid": "гибрид", "office": "офис", "any": "любой"}
_DEMO_EMAIL = re.compile(r"^demo-candidate-(\d+)@demo\.invalid$")

QUESTION = ("Вы — нанимающий тимлид с этой потребностью. Насколько кандидат подходит, чтобы позвать его "
            "на техническое собеседование?")
SCALE = {
    3: "Направление и грейд совпадают, всё обязательное подтверждено. Позвал бы сразу",
    2: "Направление совпадает; обязательное подтверждено частично, остальное заявлено. Позвал бы, уточнив пробелы",
    1: "Смежное направление, грейд ниже на ступень или подтверждено меньше половины обязательного",
    0: "Другое направление, грейд расходится на две ступени или нет ни одного обязательного навыка",
}
RULES = ["обязательный навык только заявлен — не выше 2", "senior на junior-потребность — не выше 2",
         "формат и город — минус балл только при явном конфликте",
         "низкая достоверность результата — минус балл, если решает дело"]
ANSWER = {"item_id": "<как в строке>", "relevance": "целое 0–3", "comment": "коротко: почему такая оценка",
          "must_have_missing": "чего не хватает (по желанию)"}


# ------------------------------------------------------------------ потребности и отпечатки
def needs2() -> list[dict]:
    """Демо-потребности текущего мира: N00–N16 (как создаёт demo.seed: NEEDS, затем INTERN_NEEDS) и J00–J02
    (песочница жюри, jury.seed.NEEDS)."""
    from app.modules.demo.seed import INTERN_NEEDS, NEEDS
    from app.modules.jury.seed import NEEDS as JURY_NEEDS

    out = [{"id": f"N{i:02d}", "text": t, "origin": "demo"} for i, (_, t) in enumerate(NEEDS + INTERN_NEEDS)]
    out += [{"id": f"J{i:02d}", "text": t, "origin": "jury"} for i, t in enumerate(JURY_NEEDS)]
    return out


def norm_text(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def same_need(a_id: str, a_text: str, b_id: str, b_text: str) -> bool:
    """Та же потребность: тот же текст (с точностью до пробелов) или тот же код и почти тот же текст (правка опечатки)."""
    ta, tb = norm_text(a_text), norm_text(b_text)
    return ta == tb or (a_id == b_id and SequenceMatcher(None, ta, tb).ratio() >= 0.9)


def _num(x, d: int = 2) -> str:
    try:
        return f"{round(float(x), d):.{d}f}"
    except (TypeError, ValueError):
        return ""


def fingerprint(card: dict, category: str | None) -> str:
    """Отпечаток кандидата по снимку карточки — для сверки с v1 после `demo.seed --reset` (ref случайный и меняется).

    Только поля, которые генератор демо-данных задаёт детерминированно и которые не зависят от даты сборки и формата
    показа: категория, θ, погрешность, стаж, город, формат работы. Дата теста, навыки (порог подтверждения) и тексты
    ФСП в отпечаток не входят."""
    t = card.get("test") or {}
    return "|".join([category or str(card.get("category") or ""), _num(t.get("theta")), _num(t.get("se")),
                     _num(card.get("experience_years"), 1), (card.get("city") or "").strip().lower(),
                     str(card.get("work_format") or "")])


def blind_card(c: dict) -> dict:
    """Карточка v2 = карточка v1 (pack._blind_card) + статус грейда, если он не подтверждён (иначе у кандидата без
    категории эксперт не увидел бы заявленный грейд)."""
    out = P._blind_card(c)
    st = c.get("status") or {}
    if st.get("status") and st["status"] != "confirmed":
        out["grade_status"] = {"status": st["status"], "title": st.get("title"), "claimed": st.get("claimed_title"),
                               "text": st.get("text") or None}
    return out


def card_text(card: dict) -> str:
    """Текст карточки для офлайн-разметки (то же, что видит эксперт в кабинете)."""
    lines = []
    gs = card.get("grade_status") or {}
    if card.get("category"):
        lines.append(f"Категория по тесту: {card['category']}")
    if gs:
        claimed = f"; заявлен {gs['claimed']}" if gs.get("claimed") else ""
        lines.append(f"Грейд: {gs.get('title') or gs.get('status')}{claimed}" + (f" ({gs['text']})" if gs.get("text") else ""))
    t = card.get("test") or {}
    if t:
        th, se = _num(t.get("theta")).replace(".", ","), _num(t.get("se")).replace(".", ",")
        lines.append(f"Результат теста: θ = {th} ± {se}; верно {t.get('correct')} из {t.get('answered')}; "
                     f"дата {t.get('date')}")
    else:
        lines.append("Результат теста: нет")
    integ = card.get("integrity") or {}
    if integ.get("title") or integ.get("level"):
        why = "; ".join(str(r) for r in integ.get("reasons") or [])
        lines.append(f"Достоверность результата: {integ.get('title') or integ.get('level')}" + (f" ({why})" if why else ""))
    sk = card.get("skills_confirmed") or []
    lines.append("Навыки, подтверждённые тестом (балл 0–1): " + (
        "; ".join(f"{s['title']} {_num(s.get('score')).replace('.', ',')}" for s in sk) if sk else "нет"))
    st = card.get("stack_declared") or []
    lines.append("Заявленный стек (без подтверждения): " + (", ".join(st) if st else "не указан"))
    exp = card.get("experience_years")
    lines.append("Стаж, лет: " + (_num(exp, 1).replace(".", ",") if exp is not None else "не указан"))
    wf = WORK_FORMAT.get(card.get("work_format") or "", card.get("work_format") or "не указан")
    rel = card.get("relocation")
    lines.append(f"Формат работы: {wf}; город: {card.get('city') or 'не указан'}; переезд: "
                 + ("да" if rel else "нет" if rel is not None else "не указан"))
    fsp = card.get("fsp") or []
    lines.append("Достижения ФСП (реестр): " + ("; ".join(fsp) if fsp else "нет"))
    return "\n".join(lines)


# ------------------------------------------------------------------ мир: пул, match-v1, BM25
def _demo_index(email: str | None) -> int | None:
    m = _DEMO_EMAIL.match(email or "")
    return int(m.group(1)) if m else None


def _demo_pool(db: Session) -> dict:
    """Демо-кандидаты, видимые работодателю (с категорией и без подтверждённого грейда): {user_id: (номер, почта)}.
    Персоны жюри (@jury.example.com) и живые пользователи в пакет не входят."""
    from app.modules.jury.scope import DOMAIN
    from app.modules.matching import ranking

    ids = {p.user_id for p in ranking.visible_pool(db)} | {p.user_id for p, _, _ in ranking.unconfirmed_pool(db)}
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.email).where(User.id.in_(ids), User.is_demo.is_(True),
                                                        ~User.email.like(f"%@{DOMAIN}"))).all()
    return {uid: (_demo_index(email), email) for uid, email in rows}


def match_order(db: Session, req: dict, demo: dict) -> list:
    """Подборка match-v1 по демо-пулу: тот же отбор и порядок, что ranking.build_selection(db, req, {}), без лимита
    и без недемо-кандидатов (удаление элементов не меняет взаимный порядок остальных)."""
    from app.modules.catalog.models import Category
    from app.modules.matching import ranking
    from app.modules.profiles.facts import load_bundles

    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    recs = ranking.recommended_categories(req, {}, cats)
    cat_ids = [r["id"] for r in recs if r["relation"] in ("exact", "direction", "all")]
    ids = [p.user_id for p in ranking.visible_pool(db, category_ids=cat_ids) if p.user_id in demo]
    ids += [p.user_id for p, _, _ in ranking.unconfirmed_pool(db, category_ids=cat_ids) if p.user_id in demo]
    bundles = ranking.apply_filters(list(load_bundles(db, ids, direction=req.get("direction"),
                                                      category_ids=cat_ids).values()), {})
    scored = [(ranking.score_candidate(b, req)[0], b) for b in bundles]
    scored.sort(key=lambda x: (ranking.tier(x[1]), -x[0], -(x[1].rating or 0), x[1].profile.public_ref or ""))
    return scored


def _stable(uids, demo: dict) -> list:
    return sorted(uids, key=lambda u: (demo[u][0] if demo[u][0] is not None else 10 ** 6, demo[u][1] or ""))


def _sample(rnd: random.Random, frame: list, n: int) -> list:
    return rnd.sample(frame, min(n, len(frame))) if frame else []


# ------------------------------------------------------------------ сборка
def _v1_index(db: Session) -> list[dict]:
    rows = db.scalars(select(ExpertItem).where(ExpertItem.pack == P.PACK, ExpertItem.kind == "A")).all()
    return [{"key": r.key, "need": r.grp, "text": (r.payload or {}).get("need_text") or "",
             "fp": fingerprint((r.payload or {}).get("card") or {}, (r.hidden or {}).get("category"))} for r in rows]


def plan(db: Session, seed: int = SEED2) -> dict:
    """План пакета v2 по текущему миру (без записи): объекты, назначение ролям, сводка."""
    from app.modules.catalog.models import Category
    from app.modules.matching.need_parser import parse_need
    from app.modules.profiles.facts import card, load_bundles
    from app.modules.profiles.models import CandidateResume
    from app.modules.validation.matching_eval import BM25, candidate_text, label
    from app.modules.matching import ranking

    demo = _demo_pool(db)
    if len(demo) < 20:
        return {"items": [], "summary": {"error": "Нет демо-данных: сначала make seed"}}
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    everyone = load_bundles(db, list(demo))
    resumes: dict = {}
    for r in db.scalars(select(CandidateResume).where(CandidateResume.user_id.in_(list(demo)))):
        resumes[r.user_id] = (resumes.get(r.user_id, "") + " " + (r.text_redacted or "")).strip()
    bm = BM25({u: candidate_text(b, resumes.get(u, "")) for u, b in everyone.items()})
    v1 = _v1_index(db)
    per_need = []
    for need in needs2():
        nid, text = need["id"], need["text"]
        req = parse_need(text, use_llm=False)
        d = req.get("direction")
        sel = match_order(db, req, demo)
        rank_m = {b.profile.user_id: i + 1 for i, (_, b) in enumerate(sel)}
        score_m = {b.profile.user_id: s for s, b in sel}
        sel_b = {b.profile.user_id: b for _, b in sel}
        rnd = random.Random(f"{seed}:{nid}")
        bs = {u: bm.score(u, text) for u in demo}
        tie = {u: rnd.random() for u in _stable(demo, demo)}
        rank_b = {u: i + 1 for i, u in enumerate(sorted(demo, key=lambda u: (-bs[u], tie[u])))}
        uids = [b.profile.user_id for _, b in sel]
        top = uids[:TOP]
        mid = _sample(rnd, _stable(uids[MID_LO - 1:MID_HI], demo), MID_N)
        # трудные отрицательные: та же категория вне топ-30 → соседние грейды направления → остальное направление
        hard, tiers, frames = [], [], {}
        if d:
            recs = ranking.recommended_categories(req, {}, cats)
            near_ids = [r["id"] for r in recs if r["relation"] in ("below", "above")]
            same_dir = ({p.user_id for p in ranking.visible_pool(db, direction=d)}
                        | {p.user_id for p, _, _ in ranking.unconfirmed_pool(db, direction=d)}) & set(demo)
            near = ({p.user_id for p in ranking.visible_pool(db, category_ids=near_ids)}
                    | {p.user_id for p, _, _ in ranking.unconfirmed_pool(db, category_ids=near_ids)}) & set(demo) \
                if near_ids else set()
            frames = {"category": _stable(uids[MID_HI:], demo),
                      "near_grade": _stable(near - set(uids), demo),
                      "direction": _stable(same_dir - set(uids) - near, demo)}
        else:
            frames = {"category": _stable(uids[MID_HI:], demo), "near_grade": [], "direction": []}
        for tier_name in ("category", "near_grade", "direction"):
            got = _sample(rnd, frames[tier_name], HARD_N - len(hard))
            hard += got
            tiers += [tier_name] * len(got)
        outside = [u for u in hard if u not in sel_b]
        extra = load_bundles(db, outside, direction=d) if outside else {}
        pairs = []
        for stratum, group in (("top", top), ("mid", mid), ("hard", hard)):
            for j, u in enumerate(group):
                b = sel_b.get(u) or extra.get(u) or everyone[u]
                c = blind_card(card(b, cats))
                cat = b.profile.current_category_id
                fp = fingerprint(c, cat)
                dup = next((x["key"] for x in v1 if x["fp"] == fp and same_need(x["need"], x["text"], nid, text)), None)
                h = {"need": nid, "need_origin": need["origin"], "ref": b.profile.public_ref, "demo_idx": demo[u][0],
                     "category": cat, "grade_status": b.grade_status, "stratum": stratum,
                     "hard_tier": tiers[j] if stratum == "hard" else None,
                     "rank_match": rank_m.get(u), "score_match": round(score_m[u], 4) if u in score_m else None,
                     "rank_bm25": rank_b[u], "score_bm25": round(bs[u], 4), "rule_label": label(b, req),
                     "n_selection": len(sel), "n_mid_frame": len(uids[MID_LO - 1:MID_HI]),
                     "n_hard_frame": {k: len(v) for k, v in frames.items()}, "n_population": len(demo),
                     "parsed": {"direction": d, "grade": req.get("grade")}, "fingerprint": fp, "algorithm": "match-v1"}
                if dup:
                    h["borrowed_from"] = dup
                pairs.append({"kind": "A", "key": f"A:{nid}:{b.profile.public_ref}", "grp": nid,
                              "payload": {"need_id": nid, "need_text": text, "card": c}, "hidden": h})
        per_need.append({"need": need, "pairs": pairs, "new": sum(1 for p in pairs if "borrowed_from" not in p["hidden"])})
    return _assign(per_need, seed)


def _assign(per_need: list[dict], seed: int) -> dict:
    """Включение потребностей (жюри — пока помещается) и назначение: потребность целиком — паре ролей."""
    base = [x for x in per_need if x["need"]["origin"] == "demo"]
    jury = [x for x in per_need if x["need"]["origin"] != "demo"]
    total = sum(x["new"] for x in base)
    included, skipped = list(base), []
    for x in jury:
        if total + x["new"] <= PAIRS_MAX:
            included.append(x)
            total += x["new"]
        else:
            skipped.append(x["need"]["id"])
    load = {r: 0 for r in ROLES}
    order = sorted(included, key=lambda x: (-x["new"], x["need"]["id"]))
    rnd = random.Random(f"{seed}:roles")
    pair_order = list(ROLE_PAIRS)
    rnd.shuffle(pair_order)
    roles_of: dict[str, tuple] = {}
    for x in order:
        best = min(pair_order, key=lambda rp: (max(load[r] + (x["new"] if r in rp else 0) for r in ROLES),
                                               sum(load[r] for r in rp), pair_order.index(rp)))
        roles_of[x["need"]["id"]] = best
        for r in best:
            load[r] += x["new"]
    if max(load.values(), default=0) > ROLE_MAX:  # не должно случиться: total ≤ PAIRS_MAX и потребности небольшие
        raise RuntimeError(f"Объём на роль больше {ROLE_MAX}: {load}")
    items = []
    for x in included:
        for p in x["pairs"]:
            p["hidden"]["roles"] = [] if "borrowed_from" in p["hidden"] else list(roles_of[x["need"]["id"]])
            items.append(p)
    assignment = {}
    for r in ROLES:
        rr = random.Random(f"{seed}:{r}")
        needs = [x["need"]["id"] for x in included if r in roles_of[x["need"]["id"]]]
        rr.shuffle(needs)
        keys = []
        for nid in needs:
            grp = [p["key"] for p in items if p["grp"] == nid and r in p["hidden"]["roles"]]
            rr.shuffle(grp)
            keys += grp
        assignment[r] = keys
    strata: dict = {}
    for p in items:
        s = p["hidden"]["stratum"] + (":v1" if "borrowed_from" in p["hidden"] else "")
        strata[s] = strata.get(s, 0) + 1
    summary = {"pack": PACK2, "needs": [x["need"]["id"] for x in included], "skipped_jury_needs": skipped,
               "new_pairs": sum(1 for p in items if p["hidden"]["roles"]),
               "borrowed_from_v1": sum(1 for p in items if "borrowed_from" in p["hidden"]),
               "per_role": {r: len(assignment[r]) for r in ROLES}, "role_max": ROLE_MAX,
               "roles_by_need": {k: "+".join(v) for k, v in sorted(roles_of.items())},
               "strata": dict(sorted(strata.items())),
               "per_need": {x["need"]["id"]: {"pairs": len(x["pairs"]), "new": x["new"],
                                              "selection": x["pairs"][0]["hidden"]["n_selection"] if x["pairs"] else 0}
                            for x in included}}
    return {"items": items, "assignment": assignment, "summary": summary}


def exists(db: Session) -> bool:
    return db.scalar(select(ExpertItem.id).where(ExpertItem.pack == PACK2).limit(1)) is not None


def _panelist(db: Session, code: str) -> ExpertPanelist | None:
    return db.scalar(select(ExpertPanelist).where(ExpertPanelist.pack == PACK2, ExpertPanelist.code == code,
                                                  ExpertPanelist.is_demo.is_(False)))


def summary(db: Session) -> dict:
    """Сводка собранного пакета v2 из базы."""
    items = db.scalars(select(ExpertItem).where(ExpertItem.pack == PACK2)).all()
    pans = db.scalars(select(ExpertPanelist).where(ExpertPanelist.pack == PACK2)).all()
    strata: dict = {}
    for it in items:
        s = it.hidden.get("stratum", "?") + (":v1" if it.hidden.get("borrowed_from") else "")
        strata[s] = strata.get(s, 0) + 1
    return {"pack": PACK2, "needs": sorted({it.grp for it in items}),
            "new_pairs": sum(1 for it in items if not it.hidden.get("borrowed_from")),
            "borrowed_from_v1": sum(1 for it in items if it.hidden.get("borrowed_from")),
            "per_role": {p.code: len(p.assignment.get("A") or []) for p in sorted(pans, key=lambda p: p.code)},
            "role_max": ROLE_MAX, "strata": dict(sorted(strata.items()))}


def build(db: Session, *, dry_run: bool = False, seed: int = SEED2) -> dict:
    """pack2 build: собрать v2 из текущего мира. Повторный запуск ничего не дублирует (пакет — снимок)."""
    if exists(db):
        return {"created": False, "exists": True, **summary(db)}
    pl = plan(db, seed)
    if not pl["items"]:
        return {"created": False, "exists": False, **pl["summary"]}
    if dry_run:
        return {"created": False, "exists": False, "dry_run": True, **pl["summary"]}
    try:
        for i, it in enumerate(pl["items"]):
            db.add(ExpertItem(pack=PACK2, position=i, **it))
        for code in ROLES:
            u = User(email=f"{code.lower()}-{PACK2}-{secrets.token_hex(4)}@{_invite_domain()}",
                     password_hash=hash_password(secrets.token_urlsafe(24)), role=UserRole.expert,
                     is_email_verified=True, email_verified_at=utcnow(), is_demo=False)
            db.add(u)
            db.flush()
            db.add(ExpertPanelist(code=code, slot=code, team_size=len(ROLES), user_id=u.id, token_hash=None,
                                  pack=PACK2, assignment={"A": pl["assignment"][code], "B": [], "C": []}))
        db.commit()
    except IntegrityError:  # другой процесс собрал одновременно
        db.rollback()
        return {"created": False, "exists": exists(db), **summary(db)}
    return {"created": True, "exists": True, **pl["summary"]}


def _invite_domain() -> str:
    from app.modules.experts.service import INVITE_DOMAIN

    return INVITE_DOMAIN


# ------------------------------------------------------------------ экспорт и импорт
def export_rows(db: Session, code: str) -> list[dict]:
    """Объекты роли вслепую: item_id, потребность, карточка (текстом и полями), вопрос, шкала. Без hidden и ключей."""
    code = code.strip().upper()
    pan = _panelist(db, code)
    if pan is None:
        raise api_error(404, "role_not_found", f"Роли {code} в пакете {PACK2} нет: сначала pack2 build")
    keys = pan.assignment.get("A") or []
    rows = {i.key: i for i in db.scalars(select(ExpertItem).where(ExpertItem.pack == PACK2, ExpertItem.key.in_(keys)))}
    out = []
    for n, k in enumerate([k for k in keys if k in rows], start=1):
        it = rows[k]
        out.append({"item_id": str(it.id), "n": n, "total": len(keys), "need_id": it.grp,
                    "need_text": it.payload.get("need_text"), "card_text": card_text(it.payload.get("card") or {}),
                    "card": it.payload.get("card"), "question": QUESTION,
                    "scale": {str(k): v for k, v in SCALE.items()}, "rules": RULES, "answer_format": ANSWER})
    return out


def export_file(db: Session, code: str, path: str) -> int:
    rows = export_rows(db, code)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def _parse_line(obj) -> tuple[str | None, dict, str | None]:
    if not isinstance(obj, dict):
        return None, {}, None
    value = obj.get("value") if isinstance(obj.get("value"), dict) else \
        {k: obj[k] for k in ("relevance", "must_have_missing") if k in obj}
    comment = obj.get("comment")
    return (str(obj["item_id"]) if obj.get("item_id") else None), value, (str(comment) if comment is not None else None)


def import_labels(db: Session, code: str, lines: list[str], *, source: str = "people", model: str | None = None,
                  role: str | None = None) -> dict:
    """pack2 import: оценки роли из файла. Те же проверки, что save_label (оценка — целое 0–3, комментарий до 2000
    знаков, объект — из назначения роли). Всё или ничего: при любой ошибке ничего не записывается. Повторный импорт
    того же файла ничего не дублирует (одна оценка на объект и роль; изменённая — перезаписывается).

    Источник подписывается честно: под одним кодом v2 — один источник; если у роли уже есть оценки другого
    источника или другой модели, импорт отклоняется (нужен другой код)."""
    from app.modules.experts.service import SOURCES, _validate

    code = code.strip().upper()
    if source not in SOURCES:
        raise api_error(422, "bad_source", "Источник разметки — people или model")
    model = (model or "").strip() or None
    if source == "model" and not model:
        raise api_error(422, "model_required", "Для разметки моделью укажите название модели (--model)")
    pan = _panelist(db, code)
    if pan is None:
        raise api_error(404, "role_not_found", f"Роли {code} в пакете {PACK2} нет: сначала pack2 build")
    has = db.scalar(select(ExpertLabel.id).where(ExpertLabel.panelist_id == pan.id).limit(1)) is not None
    if has and ((pan.source or "people") != source or (source == "model" and (pan.source_model or "") != model[:64])):
        was = pan.source_model if pan.source == "model" else "люди"
        raise api_error(409, "source_conflict", f"У роли {code} уже есть оценки источника «{was}»: смешивать источники "
                                                "под одним кодом нельзя")
    assigned = set(pan.assignment.get("A") or [])
    items = {str(i.id): i for i in db.scalars(select(ExpertItem).where(ExpertItem.pack == PACK2, ExpertItem.kind == "A"))}
    errors, parsed, seen = [], [], set()
    for no, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            errors.append(f"строка {no}: не JSON")
            continue
        item_id, value, comment = _parse_line(obj)
        it = items.get(item_id or "")
        if it is None or it.key not in assigned:
            errors.append(f"строка {no}: нет такого объекта в назначении {code}")
            continue
        if item_id in seen:
            errors.append(f"строка {no}: объект повторяется в файле")
            continue
        seen.add(item_id)
        try:
            val = _validate("A", it, value)
        except Exception as e:  # noqa: BLE001 — api_error с понятным текстом
            det = getattr(e, "detail", None)
            errors.append(f"строка {no}: " + (det.get("message") if isinstance(det, dict) else str(e)))
            continue
        parsed.append((it, val, (comment or "")[:2000] or None))
    if errors:
        return {"code": code, "ok": False, "errors": errors[:50], "n_errors": len(errors), "added": 0, "updated": 0,
                "unchanged": 0}
    existing = {lb.item_id: lb for lb in db.scalars(select(ExpertLabel).where(ExpertLabel.panelist_id == pan.id))}
    added = updated = unchanged = 0
    for it, val, comment in parsed:
        lb = existing.get(it.id)
        if lb is None:
            db.add(ExpertLabel(panelist_id=pan.id, item_id=it.id, value=val, comment=comment))
            added += 1
        elif lb.value == val and (lb.comment or None) == comment:
            unchanged += 1
        else:
            lb.value, lb.comment = val, comment
            updated += 1
    pan.source = source
    pan.source_model = model[:64] if source == "model" and model else None
    if role:
        pan.profile = role.strip()[:255]
    pan.last_seen_at = utcnow()
    db.commit()
    total_done = len(db.scalars(select(ExpertLabel.id).where(ExpertLabel.panelist_id == pan.id)).all())
    return {"code": code, "ok": True, "errors": [], "added": added, "updated": updated, "unchanged": unchanged,
            "labeled": total_done, "assigned": len(assigned), "source": source, "model": pan.source_model}
