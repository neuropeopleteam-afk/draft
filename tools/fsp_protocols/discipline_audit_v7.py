"""Независимый слепой аудит поля «дисциплина» (index_v7) по протоколу discipline_audit_v7_protocol.json.

  python3 discipline_audit_v7.py ask <sbornaya.pdf> <protocol.json> <answers.json>       (OPENROUTER_API_KEY; песочница)
  python3 discipline_audit_v7.py score <protocol.json> <answers.json> <rows.json> <out.json>   (сервер, rows.json — 600)
  python3 discipline_audit_v7.py crops <sbornaya.pdf> <out.json> <crops_dir>             (обрезки расхождений, без ФИО)
Проверяющему не передаются значения индекса. В out.json — только номера страниц/строк и дисциплины (без ПДн).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discipline_recover import canon  # noqa: E402

PROMPT = """Фрагмент скана официального списка ФСП: столбец 1 «№ п/п», столбец 2 «Спортивная дисциплина».
Для строк с номерами {nums} выпиши дословно текст столбца 2. Верни JSON {{"rows": [{{"n": <номер>, "discipline": "<текст>"}}]}}.
Никакого текста кроме JSON."""


def crop(pdf: Path, page: int) -> bytes:
    import pymupdf
    from PIL import Image
    pix = pymupdf.open(pdf)[page - 1].get_pixmap(dpi=200)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).rotate(-90, expand=True)
    w, h = im.size
    im = im.crop((0, 0, int(w * 0.42 * 0.33), h))
    im = im.crop((0, 0, col2_right(im) + 3, h))  # только столбцы 1–2: ФИО не видно
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def col2_right(im) -> int:
    """x правой границы столбца 2: третья слева длинная вертикальная линия таблицы (левая рамка, после №, после дисциплины)."""
    g = im.convert("L")
    w, h = g.size
    px = g.load()
    dark = [sum(1 for y in range(0, h, 2) if px[x, y] < 128) for x in range(w)]
    thr = max(dark) * 0.5
    lines, prev = [], -10
    for x, d in enumerate(dark):
        if d >= thr:
            if x - prev > 5:
                lines.append(x)
            prev = x
    assert len(lines) >= 3, f"не найдены границы столбцов: {lines}"
    return lines[2] + 2


def check_hash(proto: dict) -> list:
    s = proto["sample"]["items"]
    assert hashlib.sha256(json.dumps(s).encode()).hexdigest() == proto["sample"]["sha256"], "выборка не совпала с хэшем"
    return s


def cmd_ask(pdf, proto_p, out_p):
    proto = json.loads(Path(proto_p).read_text(encoding="utf-8"))
    sample, key, model = check_hash(proto), os.environ["OPENROUTER_API_KEY"], proto["checker"]["model"]
    assert not Path(out_p).exists(), "один прогон: answers.json уже есть"
    pages: dict[int, list[int]] = {}
    for p, n in sample:
        pages.setdefault(p, []).append(n)
    res = {"model": model, "pages": {}}
    for p, nums in sorted(pages.items()):
        body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": PROMPT.format(nums=", ".join(map(str, nums)))},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(crop(Path(pdf), p)).decode()}}]}]}
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        tries = []
        for attempt in (1, 2):  # повтор — только при техническом сбое (нет ответа, невалидный JSON), записывается
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    txt = json.loads(r.read())["choices"][0]["message"]["content"].strip()
                parsed = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", txt))
                res["pages"][str(p)] = parsed
                break
            except Exception as e:  # noqa: BLE001
                tries.append(f"попытка {attempt}: {type(e).__name__}")
        if tries:
            res.setdefault("technical_retries", {})[str(p)] = tries
    Path(out_p).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"pages": len(pages), "rows": len(sample)}))


def score(sample: list, answers: dict, rows: list[dict]) -> dict:
    idx = {(r["page"], r["n"]): r["discipline"] for r in rows}
    items, agree = [], 0
    for p, n in sample:
        got = {int(x["n"]): x.get("discipline") for x in answers["pages"].get(str(p), {}).get("rows", []) if str(x.get("n", "")).isdigit()}
        chk = canon(got.get(n))
        ok = chk is not None and chk == idx.get((p, n))
        agree += ok
        items.append({"page": p, "n": n, "index": idx.get((p, n)), "checker_raw": got.get(n), "checker": chk, "agree": ok})
    return {"checked": len(sample), "agree": agree, "disagree": len(sample) - agree, "items": items}


def cmd_score(proto_p, ans_p, rows_p, out_p):
    proto = json.loads(Path(proto_p).read_text(encoding="utf-8"))
    res = score(check_hash(proto), json.loads(Path(ans_p).read_text(encoding="utf-8")),
                json.loads(Path(rows_p).read_text(encoding="utf-8"))["rows"])
    res["protocol_sha256"] = proto["sample"]["sha256"]
    res["technical_retries"] = json.loads(Path(ans_p).read_text(encoding="utf-8")).get("technical_retries", {})
    Path(out_p).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "items"}))


def cmd_crops(pdf, out_p, crops_dir):
    """Обрезки столбцов 1–2 (без ФИО) для каждого расхождения — для разбора глазами и независимого просмотра А15."""
    d = Path(crops_dir)
    d.mkdir(parents=True, exist_ok=True)
    items = [x for x in json.loads(Path(out_p).read_text(encoding="utf-8"))["items"] if not x["agree"]]
    for x in items:
        (d / f"p{x['page']:02d}_n{x['n']:02d}.jpg").write_bytes(crop(Path(pdf), x["page"]))
    print(json.dumps({"crops": len(items)}))


if __name__ == "__main__":
    c, *a = sys.argv[1:]
    {"ask": cmd_ask, "score": cmd_score, "crops": cmd_crops}[c](*a)
