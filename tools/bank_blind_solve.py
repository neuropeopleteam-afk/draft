"""Независимая проверка ключей «вслепую» (А3, 21.10.2026).

Прежняя «внешняя проверка 10 %» показывала модели задание ВМЕСТЕ с ключом и спрашивала «верен ли ключ» — так она
подтвердила 183 из 183, включая семейства LP-v2 с неверным ключом и утечкой (выведены 21.10). Здесь модель другой
компании решает вариант, НЕ видя ключа, а мы сравниваем её ответ с ключом. Расхождение — сигнал проверить задание
(неверный ключ, двусмысленность или ошибка модели); каждое расхождение разбирается и записывается.

Выборка — стратифицированная по направлению и формату, seed выборки фиксируется ДО прогона и пишется в отчёт вместе
с SHA-256 списка семейств. Только автоматически проверяемые форматы: mcq_concept, choose_fix, find_bug,
predict_output. Открытые ответы (рубрика) сюда не входят.

Запуск из backend/:
    PYTHONPATH=. python3 ../tools/bank_blind_solve.py --share 0.1 --sample-seed 20261021 \
        --model openai/gpt-5.6-luna --out ../docs/bank/blind_solve_2110.json
Ключ OpenRouter — из .secrets/openrouter.env (не печатается).
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import requests

from assessment_bank.metrics import normalize_output
from assessment_bank.registry import generate, load_specs

FORMATS = ("mcq_concept", "choose_fix", "find_bug", "predict_output")


def _env() -> tuple[str, str]:
    for p in (Path("/home/user/workspace/.secrets/openrouter.env"), Path.home() / ".secrets" / "openrouter.env"):
        if p.exists():
            kv = dict(l.split("=", 1) for l in p.read_text().splitlines() if "=" in l)
            return kv["OPENROUTER_API_KEY"].strip(), kv.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
    return os.environ["OPENROUTER_API_KEY"], os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


def _prompt(v) -> str:
    pv = v.public_view()
    fmt = v.meta.format
    parts = [f"Задание ({fmt}).", pv["stem"]]
    if pv.get("code"):
        lines = pv["code"].splitlines()
        if fmt == "find_bug":
            parts.append("Код (номера строк слева):\n" + "\n".join(f"{i + 1:>3}: {l}" for i, l in enumerate(lines)))
        else:
            parts.append("Код / данные:\n" + pv["code"])
    if pv.get("options"):
        parts.append("Варианты:\n" + "\n".join(f"{o['id']}) {o['text']}" + (f"\n{o['code']}" if o.get("code") else "")
                                               for o in pv["options"]))
    if fmt in ("mcq_concept", "choose_fix"):
        parts.append("Реши задачу. В последней строке ответа напиши только: ОТВЕТ: <буква>")
    elif fmt == "find_bug":
        parts.append("Найди строку с дефектом. В последней строке ответа напиши только: ОТВЕТ: <номер строки>")
    else:
        parts.append("Реши задачу и в последней строке напиши только: ОТВЕТ: <ответ в формате из условия>")
    return "\n\n".join(parts)


def _ask(key: str, base: str, model: str, prompt: str) -> str:
    for attempt in range(4):
        try:
            r = requests.post(f"{base}/chat/completions", timeout=180,
                              headers={"Authorization": f"Bearer {key}"},
                              json={"model": model, "messages": [{"role": "user", "content": prompt}],
                                    "temperature": 0, "max_tokens": 4000})
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"] or ""
            time.sleep(3 * (attempt + 1))
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
    return ""


def _parse(ans: str) -> str | None:
    """Всё после последнего «ОТВЕТ:» (ответ может быть многострочным)."""
    i = ans.rfind("ОТВЕТ:")
    if i < 0:
        return None
    return ans[i + len("ОТВЕТ:"):].strip().strip("*`«»\"' .") or None


def _match(v, got: str | None) -> bool:
    if got is None:
        return False
    key = v.answer_key
    if v.meta.format in ("mcq_concept", "choose_fix"):
        return got[:1].upper() == str(key.value).upper()
    if v.meta.format == "find_bug":
        nums = re.findall(r"\d+", got)
        kv = key.value if isinstance(key.value, list) else [key.value]
        return bool(nums) and int(nums[0]) in {int(x) for x in kv} | {int(x) for x in key.accept if str(x).isdigit()}
    # многострочный ответ модель пишет в одну строку после «ОТВЕТ:» — сравниваем без учёта переводов строк и пробелов
    ws = lambda x: " ".join(normalize_output(str(x)).split())  # noqa: E731
    return ws(got) in {ws(key.value)} | {ws(a) for a in key.accept}


def rescore(path: str, variant_seed: int) -> None:
    """Пересчитать совпадения в готовом отчёте (после правки сравнения), не вызывая модель заново."""
    rep = json.loads(Path(path).read_text(encoding="utf-8"))
    still = []
    for r in rep["mismatches"]:
        v = generate(r["family_id"], variant_seed)
        got = _parse(r.get("tail") or "") or r["got"]
        if _match(v, got):
            rep["n_match"] += 1
            b = rep["by_format"][r["format"]]
            b["match"] += 1
        else:
            still.append(r)
    rep["mismatches"] = still
    rep["match_rate"] = round(rep["n_match"] / max(1, rep["n_sampled"]), 4)
    rep["rescored_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    Path(path).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(rep["n_match"], rep["n_sampled"], rep["match_rate"])


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--rescore":
        rescore(sys.argv[2], 7)
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("--share", type=float, default=0.1)
    ap.add_argument("--sample-seed", type=int, default=20261021)
    ap.add_argument("--variant-seed", type=int, default=7)
    ap.add_argument("--model", default="openai/gpt-5.6-luna")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    specs = load_specs()
    strata = collections.defaultdict(list)
    for f, s in sorted(specs.items()):
        if s.format in FORMATS:
            strata[(s.direction, s.format)].append(f)
    rng = random.Random(a.sample_seed)
    sample = []
    for k in sorted(strata):
        fs = strata[k]
        n = max(1, round(len(fs) * a.share))
        sample += rng.sample(fs, min(n, len(fs)))
    sample.sort()
    sha = hashlib.sha256("\n".join(sample).encode()).hexdigest()
    key, base = _env()
    t0 = time.time()

    def one(fid: str) -> dict:
        v = generate(fid, a.variant_seed)
        ans = _ask(key, base, a.model, _prompt(v))
        got = _parse(ans)
        return {"family_id": fid, "format": v.meta.format, "direction": specs[fid].direction,
                "key": v.answer_key.value, "got": got, "match": _match(v, got), "no_answer": got is None,
                "tail": ans[-400:] if not _match(v, got) else ""}
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        rows = list(ex.map(one, sample))
    by_fmt = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows:
        b = by_fmt[r["format"]]
        b[0] += 1
        b[1] += int(r["match"])
        b[2] += int(r["no_answer"])
    rep = {
        "method": ("модель решает вариант, не видя ключа; сравнение ответа с ключом; выборка стратифицирована по "
                   "(направление, формат), seed и SHA-256 списка — до прогона"),
        "model": a.model, "sample_seed": a.sample_seed, "variant_seed": a.variant_seed, "share": a.share,
        "sample_sha256": sha, "n_sampled": len(rows), "n_bank_auto_formats": sum(len(v) for v in strata.values()),
        "n_match": sum(r["match"] for r in rows), "n_no_answer": sum(r["no_answer"] for r in rows),
        "match_rate": round(sum(r["match"] for r in rows) / max(1, len(rows)), 4),
        "by_format": {f: {"n": b[0], "match": b[1], "no_answer": b[2]} for f, b in sorted(by_fmt.items())},
        "mismatches": [r for r in rows if not r["match"]],
        "elapsed_s": round(time.time() - t0, 1), "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "recompute": "PYTHONPATH=. python3 ../tools/bank_blind_solve.py " + " ".join(sys.argv[1:]),
    }
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "mismatches"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
