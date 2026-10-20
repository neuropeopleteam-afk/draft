"""Поиск и автоматическая верификация достижений кандидата по индексу официальных протоколов ФСП России.

Использование из бэкенда (например, в `app/modules/fsp/`):
    from tools.fsp_protocols.lookup import verify_candidate_fsp
    res = verify_candidate_fsp(fio="...", birth_date="2004-02-22")
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from .normalize import (
    compute_fio_hash,
    compute_key_hash,
    compute_team_hash,
    extract_birth_date,
    normalize_fio,
)

DEFAULT_INDEX_PATH = Path(
    os.environ.get("FSP_PROTOCOLS_INDEX", "/opt/spectrek_fsp/data_local/fsp_protocols/index.json")
)


@lru_cache(maxsize=1)
def _load_index(index_path_str: str) -> dict:
    p = Path(index_path_str)
    if not p.exists():
        return {"records": [], "sources": [], "stats": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def verify_candidate_fsp(
    fio: str | None = None,
    birth_date: str | None = None,
    team: str | None = None,
    index_path: Path = DEFAULT_INDEX_PATH,
) -> dict:
    """Проверяет достижения кандидата по индексу 18 официальных протоколов ФСП и Списка сборной РФ 2026.

    Возвращает словарь:
      {
        "verified": bool,
        "match_type": "exact_key_hash" | "fio_hash" | "team_hash" | "none",
        "highest_rank": str | None,
        "achievements": [
          {
            "discipline": ...,
            "event_title": ...,
            "ekp_no": ...,
            "date": ...,
            "place": ...,
            "rank": ...,
            "team": ...,
            "region": ...,
            "pdf_url": ...,
            "page": ...
          }
        ]
      }
    """
    idx = _load_index(str(index_path))
    records = idx.get("records") or []

    fio_norm = normalize_fio(fio) if fio else ""
    _, byear = extract_birth_date(birth_date)
    target_key_hash = compute_key_hash(fio_norm, byear) if fio_norm else None
    target_fio_hash = compute_fio_hash(fio_norm) if fio_norm else None
    target_team_hash = compute_team_hash(team) if team else None

    matches: list[dict] = []
    match_type = "none"

    if target_key_hash and byear:
        for r in records:
            if r.get("key_hash") == target_key_hash:
                matches.append(r)
        if matches:
            match_type = "exact_key_hash"

    if not matches and target_fio_hash:
        for r in records:
            if r.get("fio_hash") == target_fio_hash:
                matches.append(r)
        if matches:
            match_type = "fio_hash"

    if not matches and target_team_hash:
        for r in records:
            if r.get("key_hash") == target_team_hash or (
                r.get("team") and compute_team_hash(r.get("team")) == target_team_hash
            ):
                matches.append(r)
        if matches:
            match_type = "team_hash"

    rank_order = {"ЗМС": 7, "МСМК": 6, "МС": 5, "КМС": 4, "I": 3, "II": 2, "III": 1}
    best_rank = None
    best_rank_score = 0
    public_achievements = []
    for m in matches:
        rk = m.get("rank")
        if rk and rank_order.get(rk, 0) > best_rank_score:
            best_rank_score = rank_order[rk]
            best_rank = rk
        public_achievements.append(
            {
                "key_hash": m.get("key_hash"),
                "discipline": m.get("discipline"),
                "event_title": m.get("event_title"),
                "ekp_no": m.get("ekp_no"),
                "date": m.get("date"),
                "place": m.get("place"),
                "rank": m.get("rank"),
                "team": m.get("team"),
                "region": m.get("region"),
                "pdf_url": m.get("pdf_url"),
                "page": m.get("page"),
            }
        )

    return {
        "verified": bool(public_achievements),
        "match_type": match_type,
        "highest_rank": best_rank,
        "count": len(public_achievements),
        "achievements": public_achievements,
    }
