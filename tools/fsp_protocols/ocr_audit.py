"""Аудит точности распознавания протоколов ФСП (отложенная выборка, один прогон).

  plan   <index.json> <out_dir> [--n 120 --seed 20261021]   — на сервере: случайная выборка записей из сканов,
         файл выборки (с ПДн) остаётся на сервере; печатается хэш выборки (фиксируется в git ДО проверки).
  check  <sample.json> <images_dir> <out.json>              — в песочнице: независимая сверка каждой записи со
         страницей скана моделью другого поставщика (по умолчанию anthropic/claude-sonnet-5.5).
  report <sample.json> <check.json> <adjudication.json|-> <ocr_audit.json> — доля ошибок ФИО, места, даты
         рождения (с 95 % интервалом Уилсона); расхождения разбираются глазами (adjudication), итог — по разбору.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SCANNED = {"e5miei2aikivxs93d6qz2iqfnfaf0xp1.pdf": "sbornaya_rf_2026", "tb1vnqokiid4fiwdb40evznavplvmysg.pdf": "chr_2025_prod_final",
           "8ma6l935b05m4q88wi5n24ne23p7qbya.pdf": "kr_2025_prod_final", "go7v4ekr13s1wwepx7poocbxgxd2u92i.pdf": "kr_2025_algo_final",
           "5hs99w6a2n362vlqnonn51110vlhkvc5.pdf": "kr_2025_ib_final", "us9qvdfvm0kwathyo67wjuvje8c9v1ra.pdf": "kr_2026_robo_otbor",
           "f8mtqy9398owua73i24f999rly5fovnf.pdf": "kr_2026_prod_otbor", "p3ikqnt1g9iw1kvczvxgv5qjhv2x9tya.pdf": "kr_2026_bas_otbor",
           "e6rp6ekcljtfofzw99bao13a8mpav8i9.pdf": "kr_2026_sib_otbor", "rof2o18vujo5me8hfep08nn3bp6sd3lv.pdf": "kr_2026_algo_otbor",
           "15a3exjee1npp1vux0sl5qborm4n6q3r.pdf": "kf_2026_final", "xqhh07qp40z3mfi8lraxt53842qlw772.pdf": "pfo_2026_prod",
           "u4g6723ljtd8cxp3fa1kfhbs01f7cfbs.pdf": "cfo_2026_prod"}
MODEL = os.environ.get("FSP_AUDIT_MODEL", "anthropic/claude-sonnet-5.5")


def _norm(s: str | None) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[^а-яa-z0-9\- ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def plan(index_path: Path, out_dir: Path, n: int, seed: int) -> None:
    recs = json.loads(index_path.read_text(encoding="utf-8"))["records"]
    pop = [r for r in recs if r.get("person") and r["pdf_url"].rsplit("/", 1)[-1] in SCANNED]
    pop.sort(key=lambda r: (r["pdf_url"], r.get("page") or 0, r.get("key_hash") or ""))
    sample = random.Random(seed).sample(pop, n)
    rows = [{"i": i, "doc_id": SCANNED[r["pdf_url"].rsplit("/", 1)[-1]], "page": r["page"], "fio_norm": r["fio_norm"],
             "place": r.get("place"), "birth_date": r.get("birth_date"), "region": r.get("region"), "event_id": r.get("event_id"),
             "key_hash": r.get("key_hash")} for i, r in enumerate(sample)]
    commit = hashlib.sha256("\n".join(f"{x['key_hash']}|{x['event_id']}|{x['page']}" for x in rows).encode()).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sample.json").write_text(json.dumps({"seed": seed, "n": n, "population": len(pop), "sha256": commit, "rows": rows},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(out_dir / "sample.json", 0o600)
    print(json.dumps({"seed": seed, "n": n, "population": len(pop), "sample_sha256": commit, "index": index_path.name}, ensure_ascii=False))


PROMPT = """Это страница официального протокола (или списка) соревнований Федерации спортивного программирования.
Найди на странице строку участника, чьё ФИО совпадает или наиболее похоже на: «{fio}».
Верни СТРОГО JSON: {{"found": true|false, "fio": "ФИО ровно как напечатано на странице", "place": место участника или его команды (число) или null,
"birth_date": "ДД.ММ.ГГГГ как напечатано" или null, "region": "субъект РФ как напечатано" или null, "confidence": "high|medium|low"}}.
Если такого человека на странице нет — found=false. Место бери из колонки «Место» (у командных протоколов — объединённая ячейка команды)."""


def _ask(img: Path, fio: str, key: str) -> dict:
    b64 = base64.b64encode(img.read_bytes()).decode()
    body = {"model": MODEL, "temperature": 0, "max_tokens": 800,
            "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                                                      {"type": "text", "text": PROMPT.format(fio=fio)}]}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for a in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                txt = json.loads(r.read())["choices"][0]["message"]["content"]
            return json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
            time.sleep(3 * (a + 1))
    return {"error": err}


def check(sample_path: Path, images: Path, out: Path) -> None:
    s = json.loads(sample_path.read_text(encoding="utf-8"))
    key = os.environ["OPENROUTER_API_KEY"]

    def one(x: dict) -> dict:
        img = images / x["doc_id"] / f"page-{x['page']:02d}.jpg"
        if not img.exists():
            img = images / x["doc_id"] / f"page-{x['page']:03d}.jpg"
        return {"i": x["i"], **_ask(img, x["fio_norm"], key)}

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, s["rows"]))
    out.write_text(json.dumps({"model": MODEL, "results": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("checked", len(res))


def _bd(s: str | None) -> str | None:
    s = (s or "").strip()
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.search(r"(19|20)\d{2}", s)
    return m.group(0) if m else None


def wilson(k: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def compare(x: dict, c: dict) -> dict:
    if c.get("error") or not c.get("found"):
        return {"found": False}
    fio_ok = _norm(c.get("fio")) == x["fio_norm"]
    place_ok = None
    if c.get("place") is not None and x.get("place") is not None:
        nums = [int(n) for n in re.findall(r"\d+", str(c["place"]))]
        if nums:
            lo, hi = nums[0], nums[-1]
            place_ok = lo <= int(x["place"]) <= hi  # «14-24» — общее место
    b1, b2 = _bd(x.get("birth_date")), _bd(c.get("birth_date"))
    bd_ok = None if not b1 or not b2 else (b1 == b2 if len(b1) == len(b2) else b1[:4] == b2[:4])
    return {"found": True, "fio_ok": fio_ok, "place_ok": place_ok, "birth_ok": bd_ok}


def report(sample_path: Path, check_path: Path, adj_path: str, out: Path) -> None:
    s = json.loads(sample_path.read_text(encoding="utf-8"))
    c = {r["i"]: r for r in json.loads(check_path.read_text(encoding="utf-8"))["results"]}
    adj = json.loads(Path(adj_path).read_text(encoding="utf-8")) if adj_path != "-" else {}
    cmp = {x["i"]: compare(x, c.get(x["i"], {})) for x in s["rows"]}
    # разбор глазами: {"<i>": {"fio_ok": bool, "place_ok": bool, "birth_ok": bool|None, "note": "..."}}
    final = {}
    for i, v in cmp.items():
        a = adj.get(str(i))
        final[i] = {**v, **a, "adjudicated": True} if a else {**v, "adjudicated": False}
    def rate(field: str) -> dict:
        vals = [v[field] for v in final.values() if v.get(field) is not None]
        k = sum(1 for v in vals if v is False)
        return {"value": round(k / len(vals), 4) if vals else None, "k": k, "n": len(vals), "ci95": wilson(k, len(vals))}
    disagree = sum(1 for v in cmp.values() if not v.get("found") or v.get("fio_ok") is False or v.get("place_ok") is False or v.get("birth_ok") is False)
    doc = {
        "what": "Точность распознавания сканов официальных протоколов ФСП: случайная выборка записей индекса, сверка со страницей скана "
                "независимой моделью другого поставщика; все расхождения разобраны глазами по изображению страницы.",
        "index": s.get("index", "index_v2.json"), "population": s["population"], "n": s["n"], "seed": s["seed"],
        "sample_sha256": s["sha256"], "verifier_model": json.loads(check_path.read_text(encoding="utf-8"))["model"],
        "disagreements_model_vs_index": disagree, "adjudicated": sum(1 for v in final.values() if v["adjudicated"]),
        "not_found": sum(1 for v in final.values() if not v.get("found")),
        "error_rate_fio": rate("fio_ok"), "error_rate_place": rate("place_ok"), "error_rate_birth_date": rate("birth_ok"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recompute": "python3 tools/fsp_protocols/ocr_audit.py plan|check|report (см. docs/realdata/fsp_protocols/README.md, раздел «Аудит распознавания»)",
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(doc, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "plan":
        a = sys.argv
        n = int(a[a.index("--n") + 1]) if "--n" in a else 120
        seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 20261021
        plan(Path(a[2]), Path(a[3]), n, seed)
    elif cmd == "check":
        check(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    elif cmd == "report":
        report(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], Path(sys.argv[5]))
