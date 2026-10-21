"""«Рыночный режим» (решение владельца 20.10, п. 2): настоящие учётки видят только настоящие объекты.

Продукт готов к выходу на рынок: всё демо живёт только во вкладке «Демо для жюри» (/demo) и в песочницах жюри
(/api/jury/*, ссылки /x/). Настоящие пользователи — аноним, кандидат, работодатель, представитель ФСП (не жюри,
users.is_demo = false) — не должны видеть ни одного демо-объекта: синтетических и демо-профилей кандидатов, демо-компаний,
демо-вакансий, демо-кубков, демо-заданий, учёток жюри и подписей «Демо жюри», «демо-профиль», «для жюри».

Мир: основные демо-данные (demo.seed + демо-вакансии) + мир матрицы прав (test_access_matrix.build_world: настоящие
кандидат C1 с категорией, работодатели E1/E2, аналитик ФСП, песочницы жюри A и B со своими объектами).
Маршруты — ВСЕ GET-маршруты приложения из обхода FastAPI (tests/route_walk.py), а не список вручную: кроме явно
демонстрационных пространств (/api/jury/*, /api/demo/*) и статики. Параметры пути — объекты «настоящей» стороны
(как в матрице прав). Плюс новая версия подборки настоящего работодателя с фильтрами по умолчанию.

Демо-признаки собираются из БД после построения мира: id и почты демо-пользователей, публичные номера (C-XXXXXX)
синтетических и демо-профилей, id и названия демо-компаний, id демо-вакансий, кубков и заданий; флаги is_demo /
is_synthetic / demo_model в ответах; тексты «Демо жюри», «демо-профиль», «Демо-кандидат», «для жюри», «Роль в 1 клик».
Тест печатает все утечки разом: маршрут, роль, вид признака, путь поля в JSON и пример значения.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path

from sqlalchemy import or_, select

from app.core.db import SessionLocal
from tests.route_walk import iter_routes
from tests.test_access_matrix import build_world, fill, no_ats_network, params_for  # noqa: F401 (фикстура)
from tests.test_day2_rules import H

ROLES = ("anon", "candidate", "employer", "fsp_analyst")
# явно демонстрационные пространства: вход в демо — только через них
DEMO_PREFIXES = ("/api/jury/", "/api/demo/")
SKIP_PREFIXES = DEMO_PREFIXES + ("/apidocs", "/api/docs", "/api/redoc", "/api/openapi")
TEXT_MARKERS = ("Демо жюри", "демо жюри", "демо-профиль", "Демо-профиль", "Демо-кандидат", "демо-кандидат",
                "Демо-компания", "демо-компания", "для жюри", "Роль в 1 клик", "@jury.example.com", ".invalid")
FLAG_KEYS = ("is_demo", "is_synthetic", "demo_model", "synthetic")
# Где слова «демо» и «синтетический» — честная подпись, а не демо-объект: только текстовые признаки и флаги
# (id, номера профилей и названия демо-компаний проверяются везде).
TEXT_ALLOWED = {
    "/api/interview/concierge/script": "сценарий экскурсии проводника по демо-песочнице (зона «Аватар»)",
    "/api/validation/criteria": "методика: ограничение «демо-компании и демо-кандидаты» названо прямо",
    "/api/validation/report": "методика: флаг synthetic у проверки на синтетике — подпись источника",
}
REPORT = Path(os.environ.get("MARKET_MODE_REPORT", "/tmp/market_mode_leaks.json"))


def _seed_demo() -> None:
    """Основные демо-данные стенда (как `python -m app.modules.demo.seed`): синтетические кандидаты, демо-компании,
    их потребности, кубки и вакансии — именно они не должны просачиваться к настоящим учёткам."""
    from app.integrations.vacancies import demo as vacancies_demo
    from app.modules.demo.seed import seed

    with SessionLocal() as db:
        seed(db)
        vacancies_demo.ensure(db)
        db.commit()


def _demo_markers() -> dict[str, dict[str, str]]:
    """Значения, по которым узнаётся демо-объект в ответе: {значение: вид}."""
    from app.cup.models import Cup
    from app.integrations.vacancies.models import Vacancy
    from app.modules.assignments.models import Assignment
    from app.modules.auth.models import User
    from app.modules.profiles.models import CandidateProfile, Company

    ids: dict[str, str] = {}
    names: dict[str, str] = {}
    with SessionLocal() as db:
        for uid, email in db.execute(select(User.id, User.email).where(User.is_demo.is_(True))):
            ids[str(uid)] = "демо-пользователь (id)"
            names[email] = "демо-пользователь (почта)"
        q = (select(CandidateProfile.public_ref, CandidateProfile.user_id)
             .join(User, User.id == CandidateProfile.user_id)
             .where(or_(User.is_demo.is_(True), CandidateProfile.is_synthetic.is_(True))))
        for ref, uid in db.execute(q):
            if ref:
                names[ref] = "синтетический или демо-профиль кандидата (публичный номер)"
        for cid, name in db.execute(select(Company.id, Company.name).where(Company.is_demo.is_(True))):
            ids[str(cid)] = "демо-компания (id)"
            if name and len(name) >= 6:
                names[name] = "демо-компания (название)"
        for (vid,) in db.execute(select(Vacancy.id).where(Vacancy.is_demo.is_(True))):
            ids[str(vid)] = "демо-вакансия (id)"
        for (cup_id,) in db.execute(select(Cup.id).where(Cup.is_demo.is_(True))):
            ids[str(cup_id)] = "демо-кубок (id)"
        for (aid,) in db.execute(select(Assignment.id).where(Assignment.is_demo.is_(True))):
            ids[str(aid)] = "демо-задание (id)"
    return {"ids": ids, "names": names}


def _scan(obj, markers: dict[str, dict[str, str]], path: str = "$", out: list | None = None) -> list:
    """Все демо-признаки в JSON: [(вид, путь, пример)]."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if k in FLAG_KEYS and v is True:
                out.append((f"флаг {k}=true", p, ""))
            _scan(v, markers, p, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _scan(v, markers, f"{path}[{i}]", out)
    elif isinstance(obj, str):
        if obj in markers["ids"]:
            out.append((markers["ids"][obj], path, obj))
        elif obj in markers["names"]:
            out.append((markers["names"][obj], path, obj))
        else:
            for ref in re.findall(r"C-[A-Z0-9]{6}", obj):
                if ref in markers["names"]:
                    out.append((markers["names"][ref], path, ref))
                    break
            for m in TEXT_MARKERS:
                if m in obj:
                    out.append((f"текст «{m}»", path, obj[:80]))
                    break
    return out


def _routes(client) -> list:
    return [r for r in iter_routes(client.app)
            if r.method == "GET" and r.path.startswith("/api/") and not r.path.startswith(SKIP_PREFIXES)]


def test_market_mode_real_accounts_see_no_demo(client, no_ats_network):
    _seed_demo()
    world = build_world(client)
    tokens, real = world["tokens"], world["real"]
    # новая версия подборки настоящего работодателя с фильтрами по умолчанию (как нажатие «Обновить подборку»)
    r = client.post(f"/api/employer/needs/{real.ids['need_id']}/selections", json={}, headers=H(tokens["employer"]))
    assert r.status_code in (200, 201), r.text
    real.ids["version"] = r.json().get("version", real.ids["version"])
    markers = _demo_markers()
    assert markers["ids"] and markers["names"], "мир без демо-данных — тест ничего не проверил бы"

    leaks: dict[tuple[str, str], dict] = {}
    unchecked: list[str] = []
    checked = 0
    for route in _routes(client):
        try:
            url = fill(route.path, params_for(route.key, real))
        except AssertionError:
            unchecked.append(route.path)
            continue
        for role in ROLES:
            resp = client.get(url, headers=H(tokens[role]) if tokens[role] else {})
            if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
                continue
            checked += 1
            hits = _scan(resp.json(), markers)
            if route.path in TEXT_ALLOWED:
                hits = [h for h in hits if not (h[0].startswith("текст") or h[0].startswith("флаг"))]
            if hits:
                kinds = defaultdict(list)
                for kind, p, ex in hits:
                    kinds[kind].append((p, ex))
                leaks[(route.path, role)] = {"endpoint": route.name, "n": len(hits),
                                            "kinds": {k: v[:3] for k, v in kinds.items()}}
    REPORT.write_text(json.dumps([{"route": k[0], "role": k[1], **v} for k, v in sorted(leaks.items())],
                                 ensure_ascii=False, indent=2))
    print(f"\nпроверено ответов: {checked}; без значений параметров пути: {len(unchecked)}; утечек: {len(leaks)} "
          f"(подробно — {REPORT})")
    lines = []
    for (path, role), v in sorted(leaks.items()):
        kinds = "; ".join(f"{k}: {ps[0][0]} = {ps[0][1]!r}" for k, ps in v["kinds"].items())
        lines.append(f"GET {path} [{role}] {v['endpoint']} — {v['n']} признак(ов): {kinds}")
    assert not leaks, f"{len(leaks)} ответов с демо-данными у настоящих учёток:\n" + "\n".join(lines)
