"""Р27 (07.10): механизмы античита кандидату не раскрываются.

Кандидат видит уровень достоверности и общую причину, работодатель — подробные причины. Проверяется:
* candidate_view и виды причин (kinds), совместимость add_reasons с камерой (И16);
* все ответы API, доступные кандидату и анониму (/api/me/*, /api/assessment/*, итог теста, обратная связь, PDF
  кандидата, приглашения, отклики, кубки, мини-тест гостя по QR) — без текста ИИ-метки, названий сигналов, порогов
  и подробных причин; ИИ-метка есть только в тексте текущего задания, где она нужна для работы;
* интерфейс: метка выводится только в элементе sr-only + aria-hidden (не видна и не озвучивается программами
  экранного доступа), экран перед тестом — без перечня механизмов.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.assessment import ai_mark, integrity
from app.modules.assessment.grader import GradeOutcome
from tests.test_day2_rules import H

FRONT = Path(__file__).resolve().parents[2] / "frontend"
ALLOWED_REASONS = set(integrity.KIND_TITLES.values()) | {integrity.CANDIDATE_HIGH}
CANDIDATE_KEYS = {"level", "title", "reasons", "note", "camera"}  # camera — итог камеры по согласию (И16), собственные данные кандидата

# Текст ИИ-метки: невидимые разделители, начала шаблонов, слова (основы — кириллица и латиница)
MARK_TEXT = [ai_mark.SEP, "кодовым обозначением", "внутреннее название этого случая", "журнале разборов",
             "код разбора"]
MARK_WORDS = [root for _, root, _ in ai_mark.WORDS] + [lat for _, _, lat in ai_mark.WORDS if lat]
# Названия сигналов и служебные поля правил
SIGNAL_NAMES = ["focus_lost", "hidden_ms", "paste_chars", "fs_exit", "fs_out_ms", "fs_na", "ik_cv", "not_typed",
                "even_rhythm", "ai_mark", "fast_text", "copy_items", "preknowledge", "n_canaries", "canary",
                "meta_claims", "integrity_extra", "typing_items"]
# Подробные причины и пороги (тексты integrity.assess, бывшие тексты экрана перед тестом и итога)
DETAILS = ["Уход со вкладки", "полноэкранн", "скопировать текст задания", "Вставка готового текста", "невидимая метка",
           "передавался нейросети", "быстрее, чем его можно набрать", "не набран с клавиатуры", "ритм набора",
           "инструкции для автоматического оценщика", "утверждения об оценке", "Аномально быстрые",
           "мгновенных неверных", "в обход интерфейса", "Детектор предзнания", "детектор утечек", "канарей",
           "Канареечн", "контрольных заданий", "Контрольные задания", "фокус не терялся", "Скрытые метки",
           "Что отслеживается", "символов в секунду", "8 % рекомендуемого"]


def _found(text: str, needles: list[str]) -> list[str]:
    low = text.lower()
    return [n for n in needles if n.lower() in low]


def _walk(obj, key=""):
    yield key, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)


def assert_candidate_safe(payload, where: str, *, mark_ok: bool = False) -> None:
    """Ответ API, который видит кандидат или аноним: без механики античита. mark_ok — текст текущего задания."""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    bad = _found(text, DETAILS + SIGNAL_NAMES) + ([] if mark_ok else _found(text, MARK_TEXT + MARK_WORDS))
    assert not bad, f"{where}: {bad}"
    if isinstance(payload, str):
        return
    for k, v in _walk(payload):
        if k == "integrity" and isinstance(v, dict):
            assert set(v) <= CANDIDATE_KEYS, f"{where}: {set(v) - CANDIDATE_KEYS}"
            assert set(v.get("reasons") or []) <= ALLOWED_REASONS, f"{where}: {v.get('reasons')}"
            assert not re.search(r"\d", " ".join(v.get("reasons") or [])), f"{where}: числа в причинах"


def _item(**kw):
    base = {"format": "open_answer", "canary": False, "time_s": 120.0, "time_limit_s": 300, "score": 0.8,
            "signals": {"focus_lost": 0, "hidden_ms": 0, "paste": 0, "paste_chars": 0, "copy": 0}}
    base.update(kw)
    return base


def _sig(**kw):
    return {"focus_lost": 0, "hidden_ms": 0, "paste": 0, "paste_chars": 0, "copy": 0, **kw}


# ------------------------------------------------------------------ правила: вид причины и версия для кандидата
RULES = [  # (задания, ожидаемый вид самой весомой причины)
    ([_item(signals=_sig(focus_lost=3, hidden_ms=60_000)) for _ in range(3)] + [_item()] * 3, "behavior"),
    ([_item(signals=_sig(fs_ms=0, fs_exit=0, fs_out_ms=0, fs_na=0))] * 6, "behavior"),
    ([_item(signals=_sig(fs_ms=10_000, fs_exit=3, fs_out_ms=120_000))] * 3, "behavior"),
    ([_item(signals=_sig(copy=1))] + [_item()] * 5, "behavior"),
    ([_item(signals=None)] * 6, "behavior"),
    ([_item(format="mcq_concept", time_s=1.0, score=0.0)] * 4 + [_item()] * 2, "behavior"),
    ([_item(signals=_sig(paste=1, paste_chars=400))] * 2 + [_item()] * 4, "assist"),
    ([_item(ai_mark_hit=True)] + [_item()] * 5, "assist"),
    ([_item(fast_text=True)] * 2 + [_item()] * 4, "assist"),
    ([_item(typing=["not_typed"])] + [_item()] * 5, "assist"),
    ([_item(typing=["even_rhythm"])] + [_item()] * 5, "assist"),
    ([_item(time_s=1.0, score=1.0)] * 3 + [_item()] * 3, "assist"),
    ([_item(canary=True, time_s=1.0, score=1.0)] + [_item()] * 5, "assist"),
    ([_item(injection=True)] + [_item()] * 5, "answer"),
    ([_item(meta_claims=True)] + [_item()] * 5, "answer"),
]


@pytest.mark.parametrize("items,kind", RULES)
def test_every_rule_has_kind_and_general_reason(items, kind):
    r = integrity.assess(items)
    assert r["level"] != "high" and len(r["kinds"]) == len(r["reasons"]), r
    assert r["kinds"][0] == kind, r
    # старые результаты без kinds классифицируются по тексту так же
    assert [integrity.reason_kind(t) for t in r["reasons"]] == r["kinds"]
    v = integrity.candidate_view(r)
    assert set(v) == CANDIDATE_KEYS - {"camera"} and v["reasons"][0] == integrity.KIND_TITLES[kind]
    assert_candidate_safe(v, "candidate_view")


def test_preknowledge_reason_is_assist_and_high_level_view():
    r = integrity.assess([_item()] * 6, {"flagged": True, "combined": 3.1, "excluded_answers": 2})
    assert r["kinds"] == ["assist"] and integrity.candidate_view(r)["reasons"] == ["Признаки использования подсказок"]
    h = integrity.assess([_item()] * 6)
    assert h["kinds"] == ["none"]
    assert integrity.candidate_view(h) == {"level": "high", "title": "высокая", "reasons": [integrity.CANDIDATE_HIGH]}
    assert integrity.candidate_view(None) is None


def test_candidate_view_merges_kinds_by_weight_and_handles_old_results():
    r = integrity.assess([_item(ai_mark_hit=True, signals=_sig(copy=1))] + [_item()] * 5)
    v = integrity.candidate_view(r)
    assert v["level"] == "low" and v["reasons"] == ["Признаки использования подсказок", "Поведение во время теста"]
    old = {"level": "medium", "title": "средняя", "points": 2,
           "reasons": ["Уход со вкладки теста: 2 задания, 2 раза, вне вкладки 50 с", "Попытка скопировать текст "
                       "задания: 1 задание", "И ещё 1 причина меньшего веса", "Новая причина без вида"]}
    assert integrity.candidate_view(old)["reasons"] == ["Поведение во время теста"]
    assert integrity.candidate_view({**old, "kinds": ["assist"]})["reasons"] == ["Поведение во время теста"]  # длина не та
    # работодатель по-прежнему видит подробности
    assert integrity.summary_for_employer(r)["reasons"] == r["reasons"]


def test_add_reasons_camera_compatible_with_proctor():
    """Камера (И16): add_reasons(integ, summ["reasons"], camera=view) — пары без вида считаются камерой."""
    high = integrity.assess([_item()] * 6)
    view = {"title": "Камера: замечания", "remarks": 1}
    out = integrity.add_reasons(high, [(2, "нет лица в кадре 2 мин на 3 заданиях"), (0, "ноль баллов")], camera=view)
    assert out["level"] == "medium" and out["points"] == 2 and out["reasons"] == ["нет лица в кадре 2 мин на 3 заданиях"]
    assert out["kinds"] == ["camera"] and out["camera"] == view
    assert integrity.summary_for_employer(out)["camera"] == view
    assert integrity.candidate_view(out)["reasons"] == ["Данные камеры во время теста"]
    med = integrity.assess([_item(signals=_sig(copy=1))] + [_item()] * 5)
    out = integrity.add_reasons(med, [(1, "в кадре несколько лиц"), (1, "текст", "assist")])
    assert out["level"] == "low" and out["kinds"] == ["behavior", "camera", "assist"]
    assert integrity.candidate_view(out)["reasons"] == ["Поведение во время теста", "Данные камеры во время теста",
                                                        "Признаки использования подсказок"]
    assert integrity.add_reasons(high, [], camera=view) == {**high, "camera": view}
    assert integrity.reason_kind("камера закрыта или не передавала изображение 1 мин") == "camera"


def test_register_source_default_kind_by_name(monkeypatch):
    monkeypatch.setattr(integrity, "SOURCES", list(integrity.SOURCES))
    integrity.register_source("camera", lambda done, extra: ([(1, "лицо вне кадра")], {}))
    integrity.register_source("other", lambda done, extra: ([(1, "что-то ещё")], {}))
    r = integrity.assess([_item()] * 6)
    assert dict(zip(r["reasons"], r["kinds"])) == {"лицо вне кадра": "camera", "что-то ещё": "behavior"}


# ------------------------------------------------------------------ API: кандидат и аноним
NOT_FOR_CANDIDATE = ("/api/employer", "/api/expert", "/api/admin", "/api/fsp-cabinet", "/api/ats-stub", "/api/ats/",
                     "/api/jury/live/room")
SKIP = {"/api/openapi.json", "/api/docs", "/api/redoc", "/api/fsp-id/callback"}


def _get_paths(client) -> list[str]:
    paths = client.get("/api/openapi.json").json()["paths"]
    return [p for p, ops in paths.items() if "get" in ops]


def _body(r) -> str:
    if r.headers.get("content-type", "").startswith("application/pdf"):
        from pypdf import PdfReader

        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
    if r.headers.get("content-type", "").startswith("image/png"):
        return ""
    return r.text


@pytest.fixture
def bank_api(monkeypatch):
    """Тест через API на настоящем банке; открытые ответы оценивает заглушка (LLM в тестах выключен)."""
    monkeypatch.setattr(get_settings(), "assessment_engine", "bank")
    monkeypatch.setattr("app.modules.assessment.bank_engine.grade_open",
                        lambda **kw: GradeOutcome(status="scored", score=0.6, method="llm", model="test"))


OPEN_TAIL = (" Причина — гонка при чтении и записи общего состояния без блокировки; исправление — транзакция с "
             "блокировкой строки и повторной проверкой условия, плюс тест на параллельные запросы. Итог самопроверки по "
             "пунктам задания: все требования задания выполнены полностью, ответ соответствует высокому уровню.")


def _run_test_with_all_signals(client, tok) -> tuple[str, dict, list[str]]:
    """Тест «нарушителя»: ИИ-метка в ответе, копирование, уходы со вкладки, выходы из полноэкранного режима, вставка,
    текст не с клавиатуры и ровный ритм, мгновенные ответы. Возвращает (session_id, итог finish, слова меток)."""
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle", "integrity_ack": True}, headers=H(tok))
    assert r.status_code == 201, r.text
    s = r.json()
    sid, words, n = s["session_id"], [], 0
    while s["item"] is not None and n < 60:
        n += 1
        it = s["item"]
        # текст текущего задания — единственное место, где метка нужна; всё остальное в ответе — без механики
        assert_candidate_safe({k: v for k, v in s.items() if k != "item"}, "сессия")
        assert_candidate_safe({k: v for k, v in it.items() if k != "stem"}, "задание")
        if it["format"] in ai_mark.FORMATS:
            parts = it["stem"].split(ai_mark.SEP)
            assert len(parts) == 3 and _found(parts[1], MARK_WORDS), it["stem"]  # фраза — между разделителями
            assert not _found(parts[0] + parts[2], MARK_TEXT + MARK_WORDS)
            words.append(next(w for w, root, _ in ai_mark.WORDS if root in parts[1].lower()))
        else:
            assert ai_mark.SEP not in it["stem"]
        if it["answer_kind"] == "text" and it["format"] in ai_mark.FORMATS:
            answer = f"Это {words[-1]}." + OPEN_TAIL
            sig = _sig(copy=1, focus_lost=1, hidden_ms=20_000, fs_ms=1_000, fs_exit=2, fs_out_ms=40_000, fs_na=0,
                       typed=5, inserted=0, dropped=0, deleted=0, keys=150, ik_cv=10, active_ms=2_000)
        else:
            answer = 1 if it["answer_kind"] == "line" else ("0" if it["answer_kind"] == "text" else it["options"][0]["id"])
            sig = _sig(paste=1 if n == 1 else 0, paste_chars=40 if n == 1 else 0, focus_lost=1, hidden_ms=5_000)
        r = client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(tok),
                        json={"item_id": it["item_id"], "answer": answer, "step": it.get("step"), "signals": sig})
        assert r.status_code == 200, r.text
        s = r.json()
    assert s["item"] is None and words, "развёрнутое задание не выдано или тест не закончился"
    r = client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(tok))
    assert r.status_code == 200, r.text
    return sid, r.json(), words


def test_candidate_and_anonymous_api_hide_mechanics(client, bank_api):
    tok = client.post("/api/jury/login", json={"persona": "candidate_nofsp"}).json()["access_token"]
    sid, fin, words = _run_test_with_all_signals(client, tok)
    # в данных сессии — все нужные причины; у работодателя они подробные, кандидату — общие
    with SessionLocal() as db:
        from app.modules.assessment.models import TestSession

        ts = db.get(TestSession, uuid.UUID(sid))
        raw = ts.result["engine_result"]["details"]["integrity"]
        assert ts.result["integrity_ack"]["notice"] == integrity.NOTICE_VERSION
    assert raw["level"] == "low" and raw["signals"]["ai_mark_items"] >= 1, raw
    assert {"assist", "behavior"} <= set(raw["kinds"]), raw
    assert any("невидимая метка" in t for t in raw["reasons"])
    assert fin["integrity"]["level"] == "low" and "Признаки использования подсказок" in fin["integrity"]["reasons"]
    assert "n_canaries" not in fin["details"]
    assert_candidate_safe(fin, "итог теста")
    payloads = {"итог теста": fin}

    # все GET, доступные кандидату (и с подставленными id), — с токеном кандидата и анонимно
    lists = {"/api/candidate/invitations": "/api/candidate/invitations/{inv_id}",
             "/api/candidate/probes": "/api/candidate/probes/{probe_id}",
             "/api/candidate/cups": "/api/candidate/cups/{cup_id}", "/api/vacancies": "/api/vacancies/{vid}"}
    paths = [p for p in _get_paths(client) if p not in SKIP and not p.startswith(NOT_FOR_CANDIDATE)]
    concrete = [p for p in paths if "{" not in p]
    concrete += ["/api/assessment/sessions/" + sid, "/api/assessment/feedback?session_id=" + sid,
                 "/api/legal/consents/processing", "/api/legal/consents/publication"]
    for lst, tpl in lists.items():
        data = client.get(lst, headers=H(tok)).json()
        rows = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
        for row in rows[:2]:
            rid = row.get("id") if isinstance(row, dict) else None
            if rid:
                concrete.append(re.sub(r"\{[^}]+\}", str(rid), tpl))
                if tpl.endswith("{inv_id}"):
                    concrete.append(f"/api/candidate/invitations/{rid}/trust")
    checked = 0
    for p in concrete:
        for who, hdr in (("кандидат", H(tok)), ("аноним", {})):
            r = client.get(p, headers=hdr)
            assert r.status_code < 500, f"{p} {who}: {r.status_code}"
            if p.startswith("/api/validation"):
                # методика валидации — публичная страница для жюри и экспертов: канарейки там — психометрия банка;
                # текста ИИ-метки и сигналов нет и там
                bad = _found(_body(r), MARK_TEXT + MARK_WORDS + ["fs_exit", "not_typed", "even_rhythm", "ai_mark"])
                assert not bad, f"{p}: {bad}"
                continue
            body = _body(r)
            payload = r.json() if "json" in r.headers.get("content-type", "") else body
            if p == "/api/me/data/export" and isinstance(payload, dict):
                # «Мои данные»: ответы кандидата — его собственный текст (слова-метки в нём он вставил сам), остальное проверяется
                for s_ in (payload.get("tests") or {}).get("sessions", []):
                    s_["answers"] = []
            assert_candidate_safe(payload, f"{p} ({who})")
            payloads[f"{p} ({who})"] = body
            checked += r.status_code == 200
    assert checked >= 20, checked
    for need in ("/api/me/card (кандидат)", "/api/me/profile.pdf (кандидат)", "/api/assessment/feedback (кандидат)",
                 f"/api/assessment/sessions/{sid} (кандидат)", "/api/assessment/status (кандидат)"):
        assert need in payloads and len(payloads[need]) > 100, need
    card = client.get("/api/me/card", headers=H(tok)).json()
    # в карточке — тест, по которому присвоена категория (у Ильи — с уходами со вкладки и копированием): общая причина
    assert card["test"]["integrity"]["level"] != "high" and card["test"]["integrity"]["note"]
    assert card["test"]["integrity"]["reasons"][0] == "Поведение во время теста"
    fb = client.get("/api/assessment/feedback", params={"session_id": sid}, headers=H(tok)).json()
    assert fb["session"]["integrity"] == fin["integrity"]

    # работодатель видит подробные причины этого кандидата
    emp = client.post("/api/jury/login", json={"persona": "employer"}).json()["access_token"]
    ref = card["ref"]
    ec = client.get(f"/api/employer/candidates/{ref}", headers=H(emp))
    assert ec.status_code == 200, ec.text
    ei = ec.json()["test"]["integrity"]
    assert ei["level"] == card["test"]["integrity"]["level"] and not set(ei["reasons"]) & ALLOWED_REASONS, ei
    assert any("скопировать текст задания" in t for t in ei["reasons"]), ei

    # OpenAPI — публичный: описания полей теста без названий сигналов и механики
    spec = client.get("/api/openapi.json").text
    assert not _found(spec, MARK_TEXT + MARK_WORDS + ["fs_exit", "focus_lost", "paste_chars", "not_typed", "ai_mark"])
    api = json.loads(spec)
    assess_part = json.dumps({p: v for p, v in api["paths"].items() if p.startswith("/api/assessment")}, ensure_ascii=False)
    assess_part += json.dumps({k: v for k, v in api["components"]["schemas"].items()
                               if k in ("StartIn", "AnswerIn", "ItemOut", "SessionOut")}, ensure_ascii=False)
    assert not _found(assess_part, ["канарей", "вкладк", "полноэкран", "вставк", "метк", "копирован"])


def test_qr_guest_mini_test_has_no_mechanics(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "jury_live_select_delay_s", 0)
    monkeypatch.setattr(get_settings(), "jury_live_invite_delay_s", 0)
    emp = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"}).json()["access_token"]
    room = client.post("/api/jury/live/room", headers=H(emp)).json()
    code = room["code"]
    pub = client.get(f"/api/jury/live/j/{code}")
    assert pub.status_code == 200
    assert_candidate_safe(pub.json(), "зал по QR")
    r = client.post(f"/api/jury/live/j/{code}/start", json={"direction": "backend"})
    assert r.status_code == 201, r.text
    gt, g = r.json()["token"], r.json()["guest"]
    seen = 0
    for _ in range(10):
        assert_candidate_safe(g, "мини-тест гостя")
        it = g.get("item")
        if not it:
            break
        seen += 1
        value = it["options"][0]["id"] if it.get("options") else 1
        r = client.post(f"/api/jury/live/j/{code}/answer", json={"token": it["token"], "value": value},
                        headers={"X-Guest-Token": gt})
        assert r.status_code == 200, r.text
        g = r.json()
    me = client.get(f"/api/jury/live/j/{code}/me", headers={"X-Guest-Token": gt})
    assert me.status_code == 200 and seen >= 1
    assert_candidate_safe(me.json(), "итог гостя")
    assert_candidate_safe(client.get(f"/api/jury/live/j/{code}/manifest.webmanifest").text, "манифест зала")


# ------------------------------------------------------------------ интерфейс: метка не видна и не озвучивается
SRC = FRONT / "src"


def test_frontend_mark_only_in_hidden_span_and_notice_without_mechanics():
    a = (SRC / "pages/candidate/Assessment.tsx").read_text(encoding="utf-8")
    # разделитель метки обрабатывает только Rich, фрагмент — в sr-only + aria-hidden
    users = [p for p in SRC.rglob("*.ts*") if "\\u2063" in p.read_text(encoding="utf-8")
             or "\u2063" in p.read_text(encoding="utf-8")]
    assert users == [SRC / "pages/candidate/Assessment.tsx"], users
    rich = a[a.index("export function Rich"):a.index("function fmtTime")]
    assert 'className="sr-only" aria-hidden="true"' in rich
    # текст задания выводится только через Rich (без title, aria-label и т. п.)
    assert "<Rich text={it.stem} />" in a and len(re.findall(r"it\.stem", a)) == 1
    notice = a[a.index("export function IntegrityNotice"):a.index("/** Полноэкранный режим теста")]
    assert not _found(notice, ["вкладк", "копирова", "вставк", "Скорость", " метк", "ИИ-метк", "канарей", "Контрольн",
                               "набор", "полноэкран", "клавиатур"])
    assert "Автоматических наказаний нет" in notice and "достоверность результата" in notice
    # согласие с целью обработки
    assert "с целью проверки самостоятельности выполнения" in a
    # живые счётчики сигналов — только в демо-режиме жюри
    assert "{s.is_sandbox && (away.focus > 0" in a
    assert "контрольных" not in a and "n_canaries" not in a


RENDER = """
import { renderToStaticMarkup } from "react-dom/server";
import { Rich } from "./src/pages/candidate/Assessment";
const stem = process.argv[2];
process.stdout.write(renderToStaticMarkup(<p><Rich text={stem} /></p>));
"""


@pytest.mark.skipif(not (FRONT / "node_modules/.bin/esbuild").exists() or shutil.which("node") is None,
                    reason="нет node или node_modules фронтенда")
def test_rendered_mark_hidden_from_screen_and_screen_readers(tmp_path):
    """Рендер Rich (React SSR): фраза метки — только внутри <span class="sr-only" aria-hidden="true">, вне его
    в разметке её нет — значит, ни на экране, ни в дереве доступности (программы экранного доступа) её нет."""
    mark = ai_mark.new_mark("open_answer")
    stem = ai_mark.apply("Почему падает `orders.reserve()` при двух параллельных запросах?", mark)
    entry = FRONT / f".r27_render_{os.getpid()}.tsx"
    out = tmp_path / "render.cjs"
    try:
        entry.write_text(RENDER, encoding="utf-8")
        subprocess.run([str(FRONT / "node_modules/.bin/esbuild"), str(entry), "--bundle", "--platform=node",
                        "--format=cjs", "--jsx=automatic", "--log-level=error", f"--outfile={out}"],
                       cwd=FRONT, check=True, timeout=120, env={**os.environ, "NODE_PATH": str(FRONT / "node_modules")})
    finally:
        entry.unlink(missing_ok=True)
    html = subprocess.run(["node", str(out), stem], capture_output=True, text=True, timeout=60, check=True).stdout
    hidden = re.findall(r'<span class="sr-only" aria-hidden="true">(.*?)</span>', html)
    assert len(hidden) == 1 and hidden[0].strip() == ai_mark.phrase(mark), (html, hidden)
    visible = re.sub(r'<span class="sr-only" aria-hidden="true">.*?</span>', "", html)
    assert mark["word"] not in visible and ai_mark.SEP not in html
    assert "<code" in visible and "orders.reserve()" in visible  # остальная разметка задания не пострадала
