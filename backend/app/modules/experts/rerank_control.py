"""Я1: контроль признака «ядро роли» (RANK_CORE_SKILL) на экспертной разметке v1 и v2 — тем же кодом, что /validation.

Запускается ТОЛЬКО на сервере, на временной копии БД (spectrek/bin/v2-control-check): персональные данные не покидают
сервер, печатаются только числа (средние, ДИ, счётчики; коды потребностей N…/J… — коды пакета, не данные людей).

Что считается. Места подборки в пакетах заморожены в hidden (v2 — rank_match, v1 — rank_platform). Здесь места
пересчитываются текущим кодом подборки (experts.pack2.match_order: условия → ярус статуса грейда → [ядро роли] →
ярус обязательного → балл → рейтинг → ref) по демо-пулу копии БД — дважды: признак выключен и включён. Затем
P@5 и nDCG@10 считает тот же A.matching_by_pack, что раздел экспертов /validation. Сравнивать надо «выкл.» с «вкл.»:
замороженные числа /validation посчитаны прежним кодом в мире сборки пакета, они печатаются для сверки.
Кандидат сопоставляется по hidden.ref, при отсутствии — по отпечатку карточки (pack2.fingerprint). v1: кандидаты вне
новой подборки идут после неё в прежнем относительном порядке (в v1 место было у всей популяции); v2: вне подборки —
None, как при сборке.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import os

from sqlalchemy.orm import Session

from app.modules.experts import analysis as A
from app.modules.experts import pack as P
from app.modules.experts import pack2
from app.modules.experts.section import load
from app.modules.matching import core_skill
from app.modules.matching.need_parser import parse_need

METRICS = ("p@5", "ndcg@10")


def _fp_index(db: Session, demo: dict) -> dict:
    from sqlalchemy import select

    from app.modules.catalog.models import Category
    from app.modules.profiles.facts import card, load_bundles

    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    out = {}
    for b in load_bundles(db, list(demo)).values():
        out.setdefault(pack2.fingerprint(pack2.blind_card(card(b, cats)), b.profile.current_category_id),
                       b.profile.public_ref)
    return out


def rerank(db: Session, items: dict, demo: dict, *, core_on: bool, rank_key: str, stats: dict,
           cache: dict | None = None) -> dict:
    """Копия items с пересчитанными местами (rank_key = rank_match | rank_platform) при RANK_CORE_SKILL = core_on."""
    from app.modules.profiles.models import CandidateProfile
    from sqlalchemy import select

    out = copy.deepcopy(items)
    refs_now = set(db.scalars(select(CandidateProfile.public_ref).where(CandidateProfile.user_id.in_(list(demo)))))
    by_need: dict[str, list] = defaultdict(list)
    for k, it in out.items():
        if it["kind"] == "A":
            by_need[it["grp"]].append(k)
    old = os.environ.get(core_skill.FLAG)
    os.environ[core_skill.FLAG] = "1" if core_on else "0"
    try:
        for nid, keys in sorted(by_need.items()):
            text = out[keys[0]]["payload"].get("need_text") or ""
            req = parse_need(text, use_llm=False)
            sel = pack2.match_order(db, req, demo)
            rank = {b.profile.public_ref: i + 1 for i, (_, b) in enumerate(sel)}
            rc = core_skill.role_core(req)
            st = stats.setdefault(nid, {"core": bool(rc), "pairs": len(keys)})
            if rc:
                info = core_skill.assess_pool([b for _, b in sel], req, on=True)
                st["core_active"] = bool(info) and next(iter(info.values()))["active"]
                states = {b.profile.public_ref: info[b.profile.user_id]["state"] for _, b in sel}
            else:
                states = {}
            mapped = []
            for k in keys:
                h = out[k]["hidden"]
                ref = h.get("ref")
                how = "ref"
                if ref not in refs_now:
                    cache = {} if cache is None else cache
                    if "fp" not in cache:
                        cache["fp"] = _fp_index(db, demo)
                    fp = pack2.fingerprint(out[k]["payload"].get("card") or {}, h.get("category"))
                    ref, how = cache["fp"].get(fp), "fingerprint"
                    if ref is None:
                        how = "none"
                st[f"map_{how}"] = st.get(f"map_{how}", 0) + 1
                mapped.append((k, ref))
                if states.get(ref) == "absent":
                    st["absent_pairs"] = st.get("absent_pairs", 0) + 1
            if rank_key == "rank_platform":  # v1: место у всей популяции — вне подборки после неё, прежний порядок
                outside = sorted((k for k, ref in mapped if ref not in rank),
                                 key=lambda k: (out[k]["hidden"].get(rank_key) or 10 ** 6, k))
                tail = {k: len(sel) + i + 1 for i, k in enumerate(outside)}
                for k, ref in mapped:
                    out[k]["hidden"][rank_key] = rank.get(ref) or tail[k]
            else:
                for k, ref in mapped:
                    out[k]["hidden"][rank_key] = rank.get(ref)
            st["in_selection"] = sum(1 for _, ref in mapped if ref in rank)
            st[f"top5_{'on' if core_on else 'off'}"] = sorted(
                (k for k, _ in mapped if out[k]["hidden"][rank_key] is not None),
                key=lambda k: (out[k]["hidden"][rank_key], k))[:5]
    finally:
        if old is None:
            os.environ.pop(core_skill.FLAG, None)
        else:
            os.environ[core_skill.FLAG] = old
    return out


def _num(x: dict | None) -> str:
    if not x:
        return "—"
    return f"{x['mean']:.3f} [{x['lo']:.3f}; {x['hi']:.3f}]"


def summary_lines(res: dict, title: str) -> list[str]:
    lines = [f"== {title}"]
    for pack in ("v1", "v2", "all"):
        r = res["packs"].get(pack) or {}
        s = r.get("summary")
        if not s:
            lines.append(f"  {pack}: нет полных потребностей ({r.get('needs_complete', 0)} из {r.get('needs_total', 0)})")
            continue
        lines.append(f"  {pack}: потребностей {r['needs_complete']}/{r['needs_total']}, пар {r['pairs']}")
        for m in METRICS:
            d = s[m]
            lines.append(f"    {m}: платформа {_num(d['platform'])}; BM25 {_num(d['bm25'])}; разница {_num(d['diff'])}"
                         f" (p={d['diff'].get('wilcoxon_p')}); TREC: платформа {_num(d['platform_trec'])}")
    return lines


def per_need_platform(res: dict) -> dict:
    return {(u["pack"], u["need"]): u["platform"] for u in res["per_need"] if u.get("platform")}


def run(db: Session) -> list[str]:
    items1, labels1 = load(db)
    items2, labels2 = load(db, pack2.PACK2)
    lines = [f"пакеты: v1 пар A {sum(1 for i in items1.values() if i['kind'] == 'A')}, оценок {len(labels1)}; "
             f"v2 пар A {sum(1 for i in items2.values() if i['kind'] == 'A')}, оценок {len(labels2)}"]
    if not labels2:
        return lines + ["v2 не размечен — контроль невозможен"]
    demo = pack2._demo_pool(db)
    lines.append(f"демо-пул копии БД: {len(demo)}; флаги кода: MATCH_MUST_FIRST={os.environ.get('MATCH_MUST_FIRST', 'умолч.')}, "
                 f"политика ядра {core_skill.POLICY}")
    frozen = A.matching_by_pack({P.PACK: (items1, labels1), pack2.PACK2: (items2, labels2)}, base=P.PACK)
    lines += summary_lines(frozen, "заморожено в пакетах (как на /validation)")
    stats1: dict = {}
    stats2: dict = {}
    cache: dict = {}
    res = {}
    for on in (False, True):
        i1 = rerank(db, items1, demo, core_on=on, rank_key="rank_platform", stats=stats1, cache=cache)
        i2 = rerank(db, items2, demo, core_on=on, rank_key="rank_match", stats=stats2, cache=cache)
        res[on] = A.matching_by_pack({P.PACK: (i1, labels1), pack2.PACK2: (i2, labels2)}, base=P.PACK)
        lines += summary_lines(res[on], f"пересчёт текущим кодом, RANK_CORE_SKILL={'1' if on else '0'}")
    # парная разница вкл. − выкл. по потребностям (тот же кластерный бутстреп, что /validation)
    off_n, on_n = per_need_platform(res[False]), per_need_platform(res[True])
    lines.append("== вкл. − выкл. (платформа), по пакетам")
    from app.modules.experts import stats as S

    for pack in ("v1", "v2", "all"):
        keys = sorted(k for k in off_n if k in on_n and (pack == "all" or k[0] == pack))
        if not keys:
            continue
        for m in METRICS:
            d = [on_n[k][m] - off_n[k][m] for k in keys]
            ci = S.boot_ci(d)
            lines.append(f"  {pack} {m}: {ci['mean']:+.3f} [{ci['lo']:+.3f}; {ci['hi']:+.3f}], лучше {sum(x > 1e-9 for x in d)},"
                         f" хуже {sum(x < -1e-9 for x in d)}, без изменений {sum(abs(x) <= 1e-9 for x in d)} из {len(d)}")
    lines.append("== потребности, где признак меняет топ-5 (код потребности: Δp@5, ΔnDCG@10)")
    for pack, st in (("v1", stats1), ("v2", stats2)):
        n_core = sum(1 for s in st.values() if s.get("core"))
        n_act = sum(1 for s in st.values() if s.get("core_active"))
        maps = {w: sum(s.get(f"map_{w}", 0) for s in st.values()) for w in ("ref", "fingerprint", "none")}
        lines.append(f"  {pack}: потребностей {len(st)}, с ядром {n_core}, признак действует {n_act}; сопоставление "
                     f"(на два прогона) по ref {maps['ref']}, по отпечатку {maps['fingerprint']}, не найдено {maps['none']}; "
                     f"пар без ядра в подборке (два прогона) {sum(s.get('absent_pairs', 0) for s in st.values())}")
        for nid, s in sorted(st.items()):
            if s.get("top5_off") != s.get("top5_on"):
                a, b = off_n.get((pack, nid)), on_n.get((pack, nid))
                if a and b:
                    lines.append(f"    {nid}: {b['p@5'] - a['p@5']:+.2f}, {b['ndcg@10'] - a['ndcg@10']:+.3f}")
                else:
                    lines.append(f"    {nid}: топ-5 изменился, потребность размечена не полностью")
    return lines


def main() -> int:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        for line in run(db):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
