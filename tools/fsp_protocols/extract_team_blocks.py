"""Распознавание командных протоколов блоками «место — команда — состав» (объединённые ячейки).

Построчное распознавание путает границы команд, когда место и название команды стоят в объединённой
ячейке на несколько строк (КР-2026, СИБ: у первой команды страницы терялись участники). Здесь модель
возвращает блоки команд целиком; проверка — сумма участников по странице и непрерывность мест.
Запуск: python3 tools/fsp_protocols/extract_team_blocks.py <jpg> <out.json>  (OPENROUTER_API_KEY)
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

MODEL = os.environ.get("FSP_OCR_MODEL", "google/gemini-2.5-pro")
PROMPT = """Это страница итогового протокола командного соревнования ФСП России. В таблице колонки: Место, Название команды,
ФИО участников (несколько строк на одну команду — место и название в объединённых ячейках), Дата рождения,
Субъект РФ, Баллы. Верни СТРОГО JSON:
{"teams": [{"place": число или null, "team": "название", "region": "субъект РФ", "score": "баллы как в документе",
  "members": [{"fio": "Фамилия Имя Отчество полностью", "birth_date": "ДД.ММ.ГГГГ"}],
  "continues_from_previous_page": true/false}]}
Внимательно отнеси каждого участника к своей команде по горизонтальным линиям таблицы. Если в начале страницы
идут строки без места и названия — это продолжение команды с прошлой страницы: place=null, team=null,
continues_from_previous_page=true. Никакого текста кроме JSON."""


def ask(img: Path, key: str) -> dict:
    b64 = base64.b64encode(img.read_bytes()).decode()
    body = {"model": MODEL, "temperature": 0, "max_tokens": 16000, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": PROMPT},
                                                      {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        txt = json.loads(r.read())["choices"][0]["message"]["content"]
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip())
    return json.loads(txt)


if __name__ == "__main__":
    d = ask(Path(sys.argv[1]), os.environ["OPENROUTER_API_KEY"])
    Path(sys.argv[2]).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(sys.argv[1], [(t.get("place"), (t.get("team") or "")[:10], len(t.get("members") or [])) for t in d.get("teams", [])])
