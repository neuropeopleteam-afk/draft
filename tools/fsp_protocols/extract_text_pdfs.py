"""Детерминированный разбор текстовых PDF-протоколов ФСП России (`pdftotext`)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .normalize import (
    compute_fio_hash,
    compute_key_hash,
    compute_team_hash,
    normalize_fio,
)
from .sources import ProtocolSource


def _run_pdftotext(pdf_path: Path, layout: bool = True) -> list[str]:
    cmd = ["pdftotext"]
    if layout:
        cmd.append("-layout")
    cmd.extend([str(pdf_path), "-"])
    out = subprocess.check_output(cmd, timeout=20).decode("utf-8", "replace")
    return out.split("\f")


def parse_team_otbor_pdf(pdf_path: Path, src: ProtocolSource) -> list[dict]:
    """Парсит командные отборочные протоколы (hack_otbor.pdf, ib_otbor.pdf)."""
    pages = _run_pdftotext(pdf_path, layout=True)
    records: list[dict] = []
    row_re = re.compile(r"^\s*(\d{1,3})\s+(.+?)\s{2,}(\d+)\s*$")
    for page_idx, page_txt in enumerate(pages, start=1):
        for line in page_txt.splitlines():
            m = row_re.match(line)
            if not m:
                continue
            place = int(m.group(1))
            team = m.group(2).strip()
            score = m.group(3).strip()
            region = "Дистанционно (РФ)"
            reg_m = re.search(r"\(([^)]+)\)\s*$", team)
            if reg_m:
                region = reg_m.group(1).strip()
            team_hash = compute_team_hash(team)
            records.append(
                {
                    "key_hash": team_hash,
                    "fio_hash": None,
                    "fio_norm": None,
                    "birth_date": None,
                    "discipline": src.discipline,
                    "event_title": src.title,
                    "ekp_no": src.ekp_no,
                    "date": src.event_date,
                    "place": place,
                    "rank": None,
                    "team": team,
                    "region": region,
                    "score": score,
                    "pdf_url": src.pdf_url,
                    "page": page_idx,
                    "doc_id": src.doc_id,
                }
            )
    return records


def parse_algo_otbor_pdf(pdf_path: Path, src: ProtocolSource) -> list[dict]:
    """Парсит личный протокол отборочного этапа Кубка России по алгоритмике (algo_otbor.pdf)."""
    pages = _run_pdftotext(pdf_path, layout=True)
    records: list[dict] = []
    cyr_re = re.compile(r"^[А-ЯЁA-Z][а-яёa-z\-]+(?:\s+[А-ЯЁA-Z][а-яёa-z\-]+){0,3}$")

    for page_idx, page_txt in enumerate(pages, start=1):
        lines = page_txt.splitlines()
        n = len(lines)
        for i, line in enumerate(lines):
            # Случай 1: номер и часть/всё ФИО в одной строке: `   1     Кудряшов Кирилл Сергеевич   0:02 ...`
            m = re.match(r"^\s*(\d{1,3})\s{2,}([А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){1,3})\b", line)
            if m:
                place = int(m.group(1))
                fio_raw = m.group(2).strip()
                fio_norm = normalize_fio(fio_raw)
                records.append(
                    {
                        "key_hash": compute_key_hash(fio_norm),
                        "fio_hash": compute_fio_hash(fio_norm),
                        "fio_norm": fio_norm,
                        "fio_display": fio_raw,
                        "birth_date": None,
                        "discipline": src.discipline,
                        "event_title": src.title,
                        "ekp_no": src.ekp_no,
                        "date": src.event_date,
                        "place": place,
                        "rank": "I" if place <= 10 else ("II" if place <= 30 else None),
                        "team": None,
                        "region": "РФ (отборочный этап)",
                        "pdf_url": src.pdf_url,
                        "page": page_idx,
                        "doc_id": src.doc_id,
                    }
                )
                continue

            # Случай 2: ФИО разорвано вокруг строки с номером:
            # строка i-1: `         Степанов Антон               + ...`
            # строка i:   `   3                                      8  590`
            # строка i+1: `         Александрович               0:03 ...`
            m_num = re.match(r"^\s*(\d{1,3})\s*(?:[\.\-\+\d:\s]+)?$", line)
            if m_num and i > 0 and i + 1 < n:
                place = int(m_num.group(1))
                prev_part = lines[i - 1][:38].strip()
                next_part = lines[i + 1][:38].strip()
                if cyr_re.match(prev_part) and cyr_re.match(next_part):
                    fio_raw = f"{prev_part} {next_part}".strip()
                    fio_norm = normalize_fio(fio_raw)
                    records.append(
                        {
                            "key_hash": compute_key_hash(fio_norm),
                            "fio_hash": compute_fio_hash(fio_norm),
                            "fio_norm": fio_norm,
                            "fio_display": fio_raw,
                            "birth_date": None,
                            "discipline": src.discipline,
                            "event_title": src.title,
                            "ekp_no": src.ekp_no,
                            "date": src.event_date,
                            "place": place,
                            "rank": "I" if place <= 10 else ("II" if place <= 30 else None),
                            "team": None,
                            "region": "РФ (отборочный этап)",
                            "pdf_url": src.pdf_url,
                            "page": page_idx,
                            "doc_id": src.doc_id,
                        }
                    )
    # Сортируем по месту и убираем дубли
    seen = set()
    uniq = []
    for r in sorted(records, key=lambda x: x["place"]):
        k = (r["place"], r["fio_norm"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq
