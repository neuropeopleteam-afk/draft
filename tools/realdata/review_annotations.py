import json
from pathlib import Path
import re

OUT = Path(__file__).resolve().parents[2] / "docs/realdata"
rows = json.loads((OUT / "vacancies_50.json").read_text())["vacancies"]
for r in rows:
    print("\n", r["id"], r["title"], "\n", json.dumps(r["expected"], ensure_ascii=False))
    lines = [s.strip() for s in r["text"].splitlines() if re.search(
        r"junior|middle|senior|грейд|квалификац|стаж|опыт|лет|год|месяц|полутора|удал|гибрид|офис|формат|₽|\bК\b|[0-9]К|руб|зарплат|зп|ставка|доход",
        s, re.I)]
    print("\n".join(s[:200] for s in lines[:12]))
