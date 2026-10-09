"""И27: быстрый разбор потребности — ответ словарём сразу, уточнение моделью в фоне, кэш по тексту.

POST /api/employer/needs/parse (mode=fast, по умолчанию):
  1. Тот же нормализованный текст с теми же подсказками уже разбирался моделью не позже PARSE_CACHE_TTL_S назад —
     отдаём готовый разбор (словарь + модель) мгновенно, llm.cached=True, без обращения к модели.
  2. Иначе — разбор словарём и правилами (миллисекунды) и, если модель настроена, задача в фоне: строка
     need_parse_jobs (pending) + поток процесса api. Ответ: требования словаря, llm.pending=True, parse_job.id.
     Карточка опрашивает GET /api/employer/needs/parse/{id}: done — итог (result) и что изменила модель (delta),
     failed — причина (модель не ответила → честно «разобрано словарём»).
  Задачи — в БД, а не в памяти: api работает в несколько процессов (uvicorn --workers 2), опрос может прийти в
  другой процесс. Ключ кэша — sha256 нормализованного текста, подсказок и версии разбора: персональных данных в
  ключе нет; в модель текст уходит с вырезанными контактами и ФИО (need_parser._merge_llm, resume.pii).

delta — список изменений модели поверх словаря (id, kind, …):
  add_tag (новый навык с цитатой), set_scalar (направление/грейд/опыт/формат, которых словарь не нашёл),
  confirm_tag (тег словаря подтверждён моделью) — применяются сами, пока работодатель ничего не правил (auto=True);
  remove_tag и suggest_scalar (модель не согласна со словарём) — только предложения (auto=False). После того как
  работодатель подтвердил или поправил поля, карточка не перезаписывается: всё — «модель предлагает: принять /
  отклонить».
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import logging
import threading
import time
import unicodedata
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal, utcnow
from app.modules.catalog.seed_data import STACK
from app.modules.llm import client as llm_client
from app.modules.matching.models import NeedParseJob
from app.modules.matching.need_parser import parse_need

log = logging.getLogger("fast_parse")

PARSER_VERSION = "fp1"  # меняется при изменении правил или запроса — старый кэш не используется
STALE_S = 120  # задача pending дольше — считаем оборвавшейся (перезапуск процесса), отдаём failed
MAX_PENDING_PER_USER = 4  # защита от очереди из одного окна (повторные нажатия)
SCALARS = ("direction", "grade", "experience_years_min", "work_format")
_slots = threading.BoundedSemaphore(4)  # одновременных фоновых запросов к модели на процесс


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").replace("\r\n", "\n").strip()


def cache_key(text: str, hint_direction: str | None = None, hint_grade: str | None = None) -> str:
    raw = "\x1f".join((PARSER_VERSION, hint_direction or "", hint_grade or "", normalize_text(text)))
    return hashlib.sha256(raw.encode()).hexdigest()


def _spawn(fn, *args) -> None:
    """Фоновый запуск (поток процесса api). В тестах подменяется на синхронный или отложенный запуск."""
    threading.Thread(target=fn, args=args, daemon=True, name="need-parse").start()


def _aware(dt):
    from datetime import timezone

    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite отдаёт без зоны


def _job_out(job: NeedParseJob) -> dict:
    return {"id": str(job.id), "status": job.status}


def start(db: Session, text: str, hint_direction: str | None, hint_grade: str | None,
          user_id: uuid.UUID | None) -> dict:
    """Ответ словарём сразу (или из кэша) и, если нужно, фоновое уточнение моделью."""
    t = normalize_text(text)
    key = cache_key(t, hint_direction, hint_grade)
    ttl = get_settings().parse_cache_ttl_s
    now = utcnow()
    if ttl > 0:
        hit = db.scalar(select(NeedParseJob).where(NeedParseJob.key == key, NeedParseJob.status == "done",
                                                   NeedParseJob.created_at >= now - timedelta(seconds=ttl))
                        .order_by(NeedParseJob.created_at.desc()).limit(1))
        if hit is not None and hit.result:
            return {**hit.result, "text": t, "llm": {**(hit.result.get("llm") or {}), "cached": True},
                    "delta": hit.delta or [], "parse_job": {**_job_out(hit), "cached": True}}
    rules = parse_need(t, hint_direction, hint_grade, use_llm=False)
    if not llm_client.available("parse_need"):
        return {**rules, "text": t, "llm": {"used": False, "reason": "not_configured", "attempts": []},
                "parse_job": None}
    if user_id is not None:
        mine = db.scalars(select(NeedParseJob).where(NeedParseJob.user_id == user_id, NeedParseJob.status == "pending",
                                                     NeedParseJob.created_at >= now - timedelta(seconds=STALE_S))
                          ).all()
        same = next((j for j in mine if j.key == key), None)
        if same is not None:  # тот же текст уже уточняется — подключаемся к той же задаче
            return {**rules, "text": t, "llm": {"used": False, "pending": True}, "parse_job": _job_out(same)}
        if len(mine) >= MAX_PENDING_PER_USER:
            return {**rules, "text": t, "llm": {"used": False, "reason": "busy", "attempts": []}, "parse_job": None}
    db.execute(delete(NeedParseJob).where(NeedParseJob.created_at < now - timedelta(seconds=max(ttl, STALE_S))))
    job = NeedParseJob(key=key, user_id=user_id, status="pending", result=rules, created_at=now)
    db.add(job)
    db.commit()
    _spawn(run_job, job.id, t, hint_direction, hint_grade)
    return {**rules, "text": t, "llm": {"used": False, "pending": True}, "parse_job": _job_out(job)}


def run_job(job_id: uuid.UUID, text: str, hint_direction: str | None, hint_grade: str | None) -> None:
    """Фоновая часть: тот же разбор с запросом-дельтой к модели; итог и delta — в строку задачи."""
    with _slots:
        db = SessionLocal()
        try:
            job = db.get(NeedParseJob, job_id)
            if job is None or job.status != "pending":
                return
            base = job.result or parse_need(text, hint_direction, hint_grade, use_llm=False)
            t0 = time.monotonic()
            try:
                merged = parse_need(text, hint_direction, hint_grade, use_llm=True)
            except Exception:  # noqa: BLE001 — сбой разбора не должен оставить задачу висеть
                log.exception("фоновый разбор потребности упал")
                merged = {**base, "llm": {"used": False, "reason": "error", "attempts": []}}
            info = dict(merged.get("llm") or {})
            info["total_ms"] = int((time.monotonic() - t0) * 1000)
            db.refresh(job)
            if job.status != "pending":
                return
            if info.get("used"):
                job.status, job.result, job.delta = "done", merged, diff(base, merged)
            else:
                job.status, job.result, job.delta = "failed", {**base, "llm": info}, []
            job.llm, job.finished_at = info, utcnow()
            db.commit()
        finally:
            db.close()


def get(db: Session, job_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
    """Состояние задачи для опроса карточкой; чужая или удалённая — None (404)."""
    job = db.get(NeedParseJob, job_id)
    if job is None or job.user_id != user_id:
        return None
    if job.status == "pending" and (utcnow() - _aware(job.created_at)).total_seconds() > STALE_S:
        job.status, job.finished_at = "failed", utcnow()
        job.llm = {"used": False, "reason": "timeout", "attempts": []}
        job.result = {**(job.result or {}), "llm": job.llm}
        db.commit()
    out = {**_job_out(job), "llm": job.llm or {"used": False, "pending": True}, "delta": job.delta or []}
    if job.status != "pending":
        out["result"] = {**(job.result or {}), "parse_job": _job_out(job)}
    return out


def _name(tag: str) -> str:
    return STACK[tag][0] if tag in STACK else tag


def diff(base: dict, merged: dict) -> list[dict]:
    """Что модель изменила поверх словаря (см. описание модуля)."""
    out: list[dict] = []
    zone_of = {i["tag"]: z for z in ("required", "desired") for i in base.get(f"stack_{z}") or []}
    for z in ("required", "desired"):
        for i in merged.get(f"stack_{z}") or []:
            ev = i.get("evidence") or {}
            if i["tag"] not in zone_of:
                out.append({"id": f"add:{i['tag']}", "kind": "add_tag", "auto": True, "zone": z, "tag": i["tag"],
                            "name": _name(i["tag"]), "weight": i.get("weight"), "evidence": ev or None})
            elif ev.get("confirmed_by"):
                out.append({"id": f"confirm:{i['tag']}", "kind": "confirm_tag", "auto": True, "zone": z,
                            "tag": i["tag"], "name": _name(i["tag"])})
    m_ev = merged.get("evidence") or {}
    for k in SCALARS:
        if base.get(k) is None and merged.get(k) is not None:
            out.append({"id": f"set:{k}", "kind": "set_scalar", "auto": True, "field": k, "value": merged[k],
                        "evidence": m_ev.get(k)})
    for s in merged.get("llm_suggest") or []:
        out.append({"id": f"suggest:{s['field']}", "kind": "suggest_scalar", "auto": False, **s})
    for r in merged.get("llm_remove") or []:
        out.append({"id": f"remove:{r['tag']}", "kind": "remove_tag", "auto": False, "zone": zone_of.get(r["tag"]),
                    "name": _name(r["tag"]), **r})
    return out
