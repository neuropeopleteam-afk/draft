"""Независимый слепой аудит поля «дисциплина» (index_v7) по протоколу discipline_audit_v7_protocol.json.

  python3 discipline_audit_v7.py ask <sbornaya.pdf> <protocol.json> <answers.json>       (OPENROUTER_API_KEY; песочница)
  python3 discipline_audit_v7.py score <protocol.json> <answers.json> <rows.json> <out.json>   (сервер, rows.json — 600)
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
    buf = io.BytesIO()
    im.crop((0, 0, int(w * 0.42 * 0.33), h)).save(buf, "JPEG", quality=90)  # только столбцы 1–2: ФИО не видно
    return buf.getvalue()


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
        with urllib.request.urlopen(req, timeout=300) as r:
            txt = json.loads(r.read())["choices"][0]["message"]["content"].strip()
        res["pages"][str(p)] = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", txt))
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
        items.append({"page": p, "n": n, "index": idx.get((p, n)), "checker": chk, "agree": ok})
    return {"checked": len(sample), "agree": agree, "disagree": len(sample) - agree, "items": items}


def cmd_score(proto_p, ans_p, rows_p, out_p):
    proto = json.loads(Path(proto_p).read_text(encoding="utf-8"))
    res = score(check_hash(proto), json.loads(Path(ans_p).read_text(encoding="utf-8")),
                json.loads(Path(rows_p).read_text(encoding="utf-8"))["rows"])
    res["protocol_sha256"] = proto["sample"]["sha256"]
    Path(out_p).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "items"}))


if __name__ == "__main__":
    c, *a = sys.argv[1:]
    {"ask": cmd_ask, "score": cmd_score}[c](*a)
