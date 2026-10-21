"""Поле «дисциплина» у записей «Списка кандидатов в сборные РФ 2026» (столбец 2 скана) — index_v6 → index_v7.

В index_v6 у всех 112 записей списка стоит «все дисциплины» (дисциплина бралась на уровне страницы). Столбец 2
скана содержит дисциплину каждой строки. Конвейер:

    # 1) песочница (ПДн во временном каталоге 700, не в git): чтение столбцов 1–5 двумя моделями разных поставщиков
    python3 discipline_recover.py read <sbornaya.pdf> <out_dir>                    (OPENROUTER_API_KEY)
    # 2) сопоставление ответов моделей → строки {page, n, surname, birth_date, discipline, agree}
    python3 discipline_recover.py merge <out_dir> <rows.json>
    # 3) сервер: строки → правила исправлений (по дате рождения + фамилии внутри страницы) → apply_audit_fixes.py
    python3 discipline_recover.py fixes <index_v6.json> <rows.json> <fixes.json>

Печатаются только счётчики. Модели: MODELS (разные поставщики); расхождения моделей разбираются глазами по странице
и записываются в rows.json вручную с пометкой "resolved_by": "eye" — это видно в отчёте.
"""
from __future__ import annotations

import base64
import collections
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

DOC_FILE = "e5miei2aikivxs93d6qz2iqfnfaf0xp1.pdf"
EVENT_ID = "sbornaya_rf_2026"
MODELS = ("google/gemini-2.5-pro", "anthropic/claude-sonnet-5.5")
# официальные дисциплины вида спорта (как в индексе)
CANON = {
    "алгоритм": "программирование алгоритмическое",
    "продукт": "программирование продуктовое",
    "информационной безопасности": "программирование систем информационной безопасности",
    "безопасност": "программирование систем информационной безопасности",
    "робот": "программирование робототехники",
    "беспилот": "программирование беспилотных авиационных систем",
}

PROMPT = """Перед тобой фрагмент скана официального списка кандидатов в спортивные сборные команды РФ по спортивному
программированию: столбцы 1 «№ п/п», 2 «Спортивная дисциплина», 3 «ФИО», 4 «Пол, дата рождения», 5 «Разряд».
Выпиши КАЖДУЮ строку таблицы сверху вниз. Верни JSON: {"rows": [{"n": <номер из столбца 1, число>,
"surname": "<только фамилия из столбца 3>", "birth_date": "ДД.ММ.ГГГГ", "discipline": "<текст столбца 2 дословно>"}]}.
Если строк нет — {"rows": []}. Никакого текста кроме JSON."""


def canon(text: str | None) -> str | None:
    t = re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip()
    for k, v in CANON.items():
        if k in t:
            return v
    return None


def ask(img: bytes, key: str, model: str) -> dict:
    body = {"model": model, "temperature": 0, "max_tokens": 8000, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}}]}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.loads(r.read())
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp["choices"][0]["message"]["content"].strip())
    out = json.loads(txt)
    out["_usage"] = resp.get("usage", {})
    return out


def page_crop(pdf: Path, page: int) -> bytes:
    import io

    import pymupdf
    from PIL import Image
    pix = pymupdf.open(pdf)[page - 1].get_pixmap(dpi=200)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).rotate(-90, expand=True)  # скан повёрнут
    w, h = im.size
    buf = io.BytesIO()
    im.crop((0, 0, int(w * 0.42), h)).save(buf, "JPEG", quality=85)  # столбцы 1–5
    return buf.getvalue()


def cmd_read(pdf: Path, out: Path, pages=range(4, 20)) -> None:
    key = os.environ["OPENROUTER_API_KEY"]
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    for p in pages:
        img = page_crop(pdf, p)
        for m in MODELS:
            f = out / f"p{p:02d}_{m.replace('/', '_')}.json"
            if f.exists():
                continue
            f.write_text(json.dumps(ask(img, key, m), ensure_ascii=False), encoding="utf-8")
            os.chmod(f, 0o600)
    print(json.dumps({"pages": len(list(pages)), "files": len(list(out.glob("p*.json")))}))


def cmd_merge(out: Path, rows_path: Path) -> None:
    rows, stat = [], collections.Counter()
    for p in sorted({int(f.name[1:3]) for f in out.glob("p*.json")}):
        per = []
        for m in MODELS:
            d = json.loads((out / f"p{p:02d}_{m.replace('/', '_')}.json").read_text(encoding="utf-8"))
            per.append({(r.get("birth_date") or "").strip(): r for r in d.get("rows", [])})
        for bd in sorted(set(per[0]) | set(per[1])):
            a, b = per[0].get(bd), per[1].get(bd)
            da, db = canon(a and a.get("discipline")), canon(b and b.get("discipline"))
            agree = bool(a and b and da and da == db)
            stat["agree" if agree else "disagree"] += 1
            src = a or b
            rows.append({"page": p, "n": src.get("n"), "surname": src.get("surname"), "birth_date": bd,
                         "discipline": da if agree else None, "models": [da, db], "agree": agree})
    rows_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(rows_path, 0o600)
    print(json.dumps(dict(stat), ensure_ascii=False))


def _surname(fio: str | None) -> str:
    return (fio or "").split(" ")[0].lower().replace("ё", "е")


def build_fixes(idx: dict, rows: list[dict]) -> tuple[list[dict], dict]:
    recs = [r for r in idx["records"] if r["event_id"] == EVENT_ID]
    fixes, stat = [], collections.Counter()
    for r in recs:
        bd = r.get("birth_date") or ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", bd):
            bd = ".".join(reversed(bd.split("-")))
        cand = [x for x in rows if x["page"] == r["page"] and x["birth_date"] == bd and x.get("discipline")]
        if len(cand) > 1:
            cand = [x for x in cand if _surname(x["surname"]) == _surname(r.get("fio_norm"))]
        if len(cand) != 1:
            stat["unmatched"] += 1
            continue
        stat["matched"] += 1
        stat["by:" + cand[0].get("resolved_by", "models_agree")] += 1
        fixes.append({"file": DOC_FILE, "page": r["page"], "key_hash": r["key_hash"],
                      "set": {"discipline": cand[0]["discipline"]},
                      "why": "столбец 2 скана «Спортивная дисциплина" + ("» (разбор глазами)" if cand[0].get("resolved_by") == "eye"
                                                                          else "» (совпали две модели)")})
    stat["records"] = len(recs)
    stat.update({"disc:" + k: v for k, v in collections.Counter(f["set"]["discipline"] for f in fixes).items()})
    return fixes, dict(stat)


def cmd_fixes(index: Path, rows_path: Path, fixes_path: Path) -> None:
    fixes, stat = build_fixes(json.loads(index.read_text(encoding="utf-8")),
                              json.loads(rows_path.read_text(encoding="utf-8"))["rows"])
    fixes_path.write_text(json.dumps({"fixes": fixes}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(fixes_path, 0o600)
    print(json.dumps(stat, ensure_ascii=False))


if __name__ == "__main__":
    c, *a = sys.argv[1:]
    {"read": cmd_read, "merge": cmd_merge, "fixes": cmd_fixes}[c](*map(Path, a))
