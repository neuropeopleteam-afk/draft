"""Извлечение строк из сканированных PDF-протоколов ФСП России с помощью рендеринга страниц (`pdftoppm`)
и мультимодального распознавания таблиц (OpenRouter Vision LLM) с локальным кэшированием по страницам.
"""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

from .normalize import (
    compute_fio_hash,
    compute_key_hash,
    compute_team_hash,
    extract_birth_date,
    normalize_fio,
    normalize_rank,
)
from .sources import ProtocolSource

VISION_MODEL = os.environ.get("FSP_OCR_MODEL", "google/gemini-2.5-flash")

PROMPT_EXTRACTION = """Перед тобой отсканированная страница официального документа Федерации спортивного программирования России (ФСП) / Минспорта РФ:
итоговый протокол соревнований, турнирная таблица, список сборной команды РФ или справка о составе судейской коллегии.
Твоя задача — извлечь ВСЕ строки таблицы участников / спортсменов / команд / тренеров / судей на этой странице в строгом формате JSON.
Если страница повернута на 90 градусов (альбомная таблица), прочитай её правильно.
Верни ТОЛЬКО валидный JSON-объект вида:
{
  "ekp_no": "строка с номером ЕКП на странице, если виден, иначе null",
  "event_date": "дата проведения в формате YYYY-MM-DD, если видна, иначе null",
  "discipline": "название дисциплины, если видно, иначе null",
  "rows": [
    {
      "fio": "Фамилия Имя Отчество человека полностью (или null, если указана только команда без имён)",
      "birth_date": "ДД.ММ.ГГГГ или ГГГГ, если указана дата/год рождения, иначе null",
      "place": 1,
      "rank": "спортивное звание/разряд или категория (МС, КМС, I, II, III, ВК, 1К и т.д.), либо выполненный норматив/результат ЧР 1 / КР 1, иначе null",
      "role": "Спортсмен | Тренер | Судья | Команда",
      "team": "название команды или физкультурно-спортивной организации, если есть, иначе null",
      "region": "субъект РФ / город / федеральный округ, если есть, иначе null",
      "score": "баллы / решённые задачи / время, если есть, иначе null"
    }
  ]
}
Никакого текста до или после JSON не пиши."""


def render_pdf_pages(pdf_path: Path, out_dir: Path, dpi: int = 125) -> list[Path]:
    """Рендерит все страницы PDF в JPEG через pdftoppm."""
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / "page"
    existing = sorted(out_dir.glob("page-*.jpg"))
    if existing:
        return existing
    subprocess.run(
        ["pdftoppm", "-jpeg", "-jpegopt", "quality=82", "-r", str(dpi), str(pdf_path), str(prefix)],
        check=True,
        timeout=120,
    )
    return sorted(out_dir.glob("page-*.jpg"))


def _call_vision_llm(img_path: Path, api_key: str) -> dict:
    b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
    payload = {
        "model": VISION_MODEL,
        "temperature": 0.0,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT_EXTRACTION},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    return json.loads(content)


def extract_scanned_pdf(
    pdf_path: Path,
    src: ProtocolSource,
    cache_dir: Path,
    api_key: str,
    max_workers: int = 10,
    max_pages: int | None = None,
) -> list[dict]:
    """Рендерит страницы сканированного PDF и извлекает все записи участников с кэшированием."""
    doc_cache = cache_dir / src.doc_id
    img_dir = doc_cache / "pages_jpg"
    json_dir = doc_cache / "pages_json"
    json_dir.mkdir(parents=True, exist_ok=True)

    pages = render_pdf_pages(pdf_path, img_dir)
    if max_pages is not None and len(pages) > max_pages:
        pages = pages[:max_pages]

    def process_one(idx_and_img: tuple[int, Path]) -> tuple[int, dict]:
        page_num, img_path = idx_and_img
        cache_file = json_dir / f"page_{page_num:03d}.json"
        if cache_file.exists():
            try:
                return page_num, json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        for attempt in range(2):
            try:
                parsed = _call_vision_llm(img_path, api_key)
                cache_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
                return page_num, parsed
            except Exception as e:
                if attempt == 1:
                    return page_num, {"rows": [], "error": str(e)}
        return page_num, {"rows": []}

    page_results: list[tuple[int, dict]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(process_one, (idx, p)) for idx, p in enumerate(pages, start=1)]
        for f in concurrent.futures.as_completed(futs):
            page_results.append(f.result())

    page_results.sort(key=lambda x: x[0])

    records: list[dict] = []
    doc_ekp = src.ekp_no
    doc_date = src.event_date
    for page_num, data in page_results:
        if not isinstance(data, dict):
            continue
        p_ekp = data.get("ekp_no")
        if p_ekp and isinstance(p_ekp, str) and len(re.sub(r"\D", "", p_ekp)) >= 10:
            doc_ekp = re.sub(r"\D", "", p_ekp)
        p_disc = data.get("discipline")
        rows = data.get("rows") or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            fio_raw = (row.get("fio") or "").strip() or None
            team_raw = (row.get("team") or "").strip() or None
            if not fio_raw and not team_raw:
                continue
            fio_norm = normalize_fio(fio_raw) if fio_raw else None
            bdate, byear = extract_birth_date(row.get("birth_date"))
            place = row.get("place")
            if isinstance(place, str) and place.strip().isdigit():
                place = int(place.strip())
            rank = normalize_rank(row.get("rank"), place=place, is_sbornaya=(src.doc_id == "sbornaya_rf_2026"))
            if not rank and row.get("rank"):
                rank = str(row.get("rank")).strip()[:24]
            if fio_norm:
                key_hash = compute_key_hash(fio_norm, byear)
                fio_hash = compute_fio_hash(fio_norm)
            else:
                key_hash = compute_team_hash(team_raw)
                fio_hash = None
            disc = (p_disc or src.discipline or "").strip()
            records.append(
                {
                    "key_hash": key_hash,
                    "fio_hash": fio_hash,
                    "fio_norm": fio_norm,
                    "fio_display": fio_raw,
                    "birth_date": bdate or byear,
                    "discipline": disc,
                    "event_title": src.title,
                    "ekp_no": doc_ekp,
                    "date": doc_date,
                    "place": place,
                    "rank": rank,
                    "role": (row.get("role") or "Спортсмен").strip(),
                    "team": team_raw,
                    "region": (row.get("region") or "").strip() or "РФ",
                    "score": str(row.get("score")).strip() if row.get("score") is not None else None,
                    "pdf_url": src.pdf_url,
                    "page": page_num,
                    "doc_id": src.doc_id,
                }
            )
    return records
