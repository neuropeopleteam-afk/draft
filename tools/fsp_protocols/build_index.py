"""Сборка единого индекса официальных протоколов ФСП России (`index.json`)
и обезличенного примера для репозитория (`sample_anonymized.json`).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request
from collections import Counter
from pathlib import Path

from .extract_scan_pdfs import extract_scanned_pdf
from .extract_text_pdfs import parse_algo_otbor_pdf, parse_team_otbor_pdf
from .sources import SOURCES, ProtocolSource


def ensure_pdf_downloaded(src: ProtocolSource, pdf_dir: Path) -> Path:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    target = pdf_dir / src.filename
    if target.exists() and target.stat().st_size > 1000:
        return target
    req = urllib.request.Request(
        src.pdf_url,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) DraftFSPVerifier/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        target.write_bytes(resp.read())
    return target


def build_full_index(
    pdf_dir: Path,
    cache_dir: Path,
    out_index_path: Path,
    out_sample_path: Path | None = None,
    api_key: str | None = None,
    max_workers: int = 12,
) -> dict:
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "").strip()
    all_records: list[dict] = []
    by_doc_counts: dict[str, int] = {}

    for src in SOURCES:
        pdf_path = ensure_pdf_downloaded(src, pdf_dir)
        if src.is_text_pdf:
            if src.doc_id == "kr_2025_algo_otbor":
                recs = parse_algo_otbor_pdf(pdf_path, src)
                # Дополнительно проходим сканером по страницам algo_otbor, если разорванные многострочные ФИО были пропущены
                if api_key and len(recs) < 110:
                    scan_recs = extract_scanned_pdf(pdf_path, src, cache_dir, api_key, max_workers=max_workers)
                    known_places = {r["place"] for r in recs if r.get("place") is not None}
                    for sr in scan_recs:
                        if sr.get("place") not in known_places and sr.get("fio_norm"):
                            recs.append(sr)
                    recs.sort(key=lambda x: (x.get("place") or 9999))
            else:
                recs = parse_team_otbor_pdf(pdf_path, src)
        else:
            if not api_key:
                raise RuntimeError(f"Для разбора сканированного протокола {src.filename} требуется OPENROUTER_API_KEY")
            recs = extract_scanned_pdf(pdf_path, src, cache_dir, api_key, max_workers=max_workers)

        by_doc_counts[src.doc_id] = len(recs)
        all_records.extend(recs)
        print(f"[{src.doc_id}] {src.filename}: извлечено записей = {len(recs)}", flush=True)

    # Нормализуем выходную схему каждой записи согласно ТЗ оркестратора
    clean_records: list[dict] = []
    seen_keys: set[tuple] = set()
    for r in all_records:
        dedup_key = (
            r.get("doc_id"),
            r.get("page"),
            r.get("key_hash"),
            r.get("place"),
            r.get("team"),
        )
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        clean_records.append(
            {
                "key_hash": r.get("key_hash"),
                "fio_hash": r.get("fio_hash"),
                "fio_norm": r.get("fio_norm"),
                "birth_date": r.get("birth_date"),
                "discipline": r.get("discipline"),
                "event_title": r.get("event_title"),
                "ekp_no": r.get("ekp_no"),
                "date": r.get("date"),
                "place": r.get("place"),
                "rank": r.get("rank"),
                "team": r.get("team"),
                "region": r.get("region"),
                "pdf_url": r.get("pdf_url"),
                "page": r.get("page"),
            }
        )

    disc_counter = Counter(r["discipline"] for r in clean_records if r.get("discipline"))
    unique_fios = {r["fio_hash"] for r in clean_records if r.get("fio_hash")}
    unique_teams = {r["team"].lower() for r in clean_records if r.get("team")}

    index_payload = {
        "schema_version": "1.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_registry_url": "https://fsp-russia.ru/about/documents/",
        "legal_note": (
            "Индекс сформирован по открытым официальным протоколам соревнований ОФСОО «ФСП» и Минспорта РФ "
            "(329-ФЗ «О физической культуре и спорте в РФ»). Персональные поля (fio_norm, birth_date) хранятся "
            "исключительно на защищённом сервере вне публичного git-репозитория (152-ФЗ) и используются только "
            "для автоматического подтверждения достижений по запросу самого кандидата."
        ),
        "stats": {
            "documents_count": len(SOURCES),
            "total_records": len(clean_records),
            "unique_athletes_count": len(unique_fios),
            "unique_teams_count": len(unique_teams),
            "by_doc_id": by_doc_counts,
            "by_discipline": dict(disc_counter),
        },
        "sources": [
            {
                "doc_id": s.doc_id,
                "filename": s.filename,
                "title": s.title,
                "discipline": s.discipline,
                "ekp_no": s.ekp_no,
                "date": s.event_date,
                "pdf_url": s.pdf_url,
                "is_text_pdf": s.is_text_pdf,
                "records_count": by_doc_counts.get(s.doc_id, 0),
            }
            for s in SOURCES
        ],
        "records": clean_records,
    }

    out_index_path.parent.mkdir(parents=True, exist_ok=True)
    out_index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if out_sample_path is not None:
        out_sample_path.parent.mkdir(parents=True, exist_ok=True)
        # Выбираем 3 показательные записи из разных протоколов и полностью обезличиваем ФИО и дату рождения
        sample_rows = []
        picked_docs = set()
        for r in clean_records:
            if r.get("fio_hash") and r.get("rank") and r.get("pdf_url") not in picked_docs:
                picked_docs.add(r.get("pdf_url"))
                anon = dict(r)
                anon["fio_norm"] = "<хранится только в серверном индексе вне git (152-ФЗ)>"
                anon["birth_date"] = "<хранится только в серверном индексе вне git (152-ФЗ)>" if r.get("birth_date") else None
                anon["team"] = None
                sample_rows.append(anon)
                if len(sample_rows) == 3:
                    break
        sample_payload = {
            "schema_version": "1.0",
            "note": "Обезличенный пример 3 записей индекса официальных протоколов ФСП России (без ФИО и дат рождения согласно 152-ФЗ). Полный индекс расположен на сервере в /opt/spectrek_fsp/data_local/fsp_protocols/index.json.",
            "stats": index_payload["stats"],
            "sources": index_payload["sources"],
            "sample_records": sample_rows,
        }
        out_sample_path.write_text(json.dumps(sample_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return index_payload
