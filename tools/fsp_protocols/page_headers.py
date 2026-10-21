"""Разметка страниц PDF ФСП: тип страницы и реквизиты соревнования (без ФИО).

Для каждой страницы: протокол (начало/продолжение), справка о судейской коллегии, справка о составе
субъектов РФ; реквизиты (вид соревнования, дисциплина, ЕКП, сроки, возрастная группа), число участников
и субъектов из справки, судейские категории (без ФИО). Нужна для разметки событий (events.json) и
условий ЕВСК (п. 29, 30–32, 40.2 Положения о ЕВСК).

Запуск (из песочницы, где доступен сервис моделей):
  python3 tools/fsp_protocols/page_headers.py <pdf> <out.json> [--dpi 100]
Ключ — переменная OPENROUTER_API_KEY. ФИО в результат не попадают (запрещено подсказкой и
проверяется после ответа).
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

MODEL = os.environ.get("FSP_HEADER_MODEL", "google/gemini-2.5-flash")
PROMPT = """Это страница официального документа Федерации спортивного программирования (ФСП России).
Верни СТРОГО JSON без пояснений:
{"page_type": "protocol_start" | "protocol_continuation" | "judges_certificate" | "subjects_certificate" | "subjects_certificate_continuation" | "other",
 "doc_title": "заголовок документа дословно (например «ИТОГОВЫЙ ПРОТОКОЛ отборочного этапа Кубка России …», «СПРАВКА о составе субъектов …») или null",
 "competition": "наименование соревнования дословно из заголовка (например «Чемпионат Северо-Западного федерального округа», «отборочный этап Кубка России», «финал Всероссийского физкультурного мероприятия «Кубок Федерации спортивного программирования»») или null",
 "discipline": "дисциплина дословно или null",
 "ekp_no": "номер ЕКП только цифрами или null",
 "date_start": "ГГГГ-ММ-ДД или null", "date_end": "ГГГГ-ММ-ДД или null",
 "venue": "место проведения или null",
 "age_group": "возрастная группа дословно (например «мужчины, женщины», «юноши, девушки до 19 лет») или null",
 "participants_total": число спортсменов из фразы «Всего участников …» или null,
 "subjects_total": число субъектов РФ из этой фразы или null,
 "subjects_listed": число строк в таблице субъектов на этой странице или null,
 "judges": [{"role": "должность (главный судья, главный секретарь …)", "category": "ВК|1К|2К|3К|ЮС|другое"}] — только для справки о судейской коллегии, БЕЗ ФИО,
 "result_rows_on_page": число строк результатов (мест/участников) на странице протокола или null,
 "first_place_on_page": первое место на странице или null, "last_place_on_page": последнее место на странице или null}
Никогда не выписывай фамилии, имена и отчества людей."""


def render(pdf: Path, out: Path, dpi: int) -> list[Path]:
    subprocess.run(["pdftoppm", "-r", str(dpi), "-jpeg", "-jpegopt", "quality=80", str(pdf), str(out / "p")], check=True)
    return sorted(out.glob("p-*.jpg"), key=lambda p: int(re.findall(r"(\d+)", p.stem)[-1]))


def ask(img: Path, key: str) -> dict:
    b64 = base64.b64encode(img.read_bytes()).decode()
    body = {"model": MODEL, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": PROMPT},
                                                      {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                txt = json.loads(r.read())["choices"][0]["message"]["content"]
            txt = txt.strip().strip("`")
            if txt.startswith("json"):
                txt = txt[4:]
            return json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                return {"error": str(e)[:200]}
            time.sleep(3 * (attempt + 1))
    return {}


def main() -> None:
    pdf, out = Path(sys.argv[1]), Path(sys.argv[2])
    dpi = int(sys.argv[sys.argv.index("--dpi") + 1]) if "--dpi" in sys.argv else 100
    key = os.environ["OPENROUTER_API_KEY"]
    with tempfile.TemporaryDirectory() as td:
        pages = render(pdf, Path(td), dpi)
        with cf.ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda p: ask(p, key), pages))
    for i, r in enumerate(res, 1):
        r["page"] = i
        for j in r.get("judges") or []:
            j.pop("fio", None)
            j.pop("name", None)
    out.write_text(json.dumps({"pdf": pdf.name, "model": MODEL, "pages": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(pdf.name, len(res), "pages")


if __name__ == "__main__":
    main()
