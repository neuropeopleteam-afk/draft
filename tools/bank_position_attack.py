"""Атака «решатель без знаний, изучивший открытый код»: учится на одних зёрнах, проверяется на других.

Зачем. Эвристики bank_audit.py («медиана», «ближайший к среднему» и т. п.) — фиксированные правила. Код банка открыт,
поэтому честный противник сильнее: он может посмотреть на сотни вариантов семейства (или прочитать генератор) и
выучить, где обычно стоит ключ — на какой букве, на каком месте по величине, на каком месте по длине текста, и как эти
признаки связаны, а также какой текст варианта (для вариантов-формулировок) и какой сюжет задачи (контекст) чаще
идут вместе с ключом. Атака воспроизводит такого противника без знания предмета.

Как считается. Для каждого семейства с выбором варианта: обучающие зёрна и проверочные зёрна — случайные из диапазона
выдачи кандидатам (bank_engine: 10 000 000 … 2³¹ − 1), наборы не пересекаются. Признаки варианта ответа: буква
(позиция в списке), ранг по величине (если все варианты — числа), ранг по длине текста. На обучающих зёрнах для
каждого значения признака считается доля «этот вариант — ключ» (сглаживание Лапласа к 1/k). На проверочных зёрнах
выбирается вариант с наибольшей долей (ничья — случайный выбор, засчитывается доля). Атаки: letter, value_rank,
len_rank, letter×value_rank, letter×len_rank, text (текст варианта, цифры заменены на #), text×letter,
ctx×letter, ctx×value_rank, ctx×text (ctx — сюжет варианта, meta.context; кандидат видит его в условии).
Уровень случайного выбора — 1/k.

Выход: сводка по всем семействам и список семейств, где лучшая атака заметно выше случайного выбора
(порог по умолчанию +10 п. п. при 100 проверочных зёрнах ≈ 2,3 стандартной ошибки).

Запуск из backend:
    PYTHONPATH=. python3 ../tools/bank_position_attack.py --train 100 --test 100 --jobs 2 --out /tmp/pos.json
    PYTHONPATH=. python3 ../tools/bank_position_attack.py --families common.net.cidr_mcq,devops.k8s.pdb_disruptions_mcq
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing as mp
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bank_audit  # noqa: E402  (разбор чисел в вариантах — тот же, что у эвристик)

SEED_MIN, SEED_MAX = 10_000_000, 2 ** 31 - 1
ATTACKS = ("letter", "value_rank", "len_rank", "letter_x_value_rank", "letter_x_len_rank",
           "text", "text_x_letter", "ctx_x_letter", "ctx_x_value_rank", "ctx_x_text")
_DIGITS = __import__("re").compile(r"\d+")


def _seeds(n: int, key: str) -> list[int]:
    r = random.Random(f"bank_position_attack:{key}")
    return [SEED_MIN + r.randrange(SEED_MAX - SEED_MIN) for _ in range(n)]


def _features(v: Any) -> tuple[list[dict[str, Any]], int] | None:
    """Признаки вариантов ответа и индекс ключа; None — у варианта нет выбора из списка."""
    opts = v.options or []
    if len(opts) < 2 or getattr(v.answer_key, "kind", None) != "option":
        return None
    ids = [o.id for o in opts]
    if v.answer_key.value not in ids:
        return None
    k = ids.index(v.answer_key.value)
    vals = [bank_audit._num(o.text) for o in opts]
    numeric = all(x is not None for x in vals) and len(set(vals)) == len(vals)
    lens = [len((o.text or "") + (o.code or "")) for o in opts]
    ctx = str(getattr(v.meta, "context", "") or "")
    feats = []
    for i, o in enumerate(opts):
        txt = _DIGITS.sub("#", (o.text or "") + "\x00" + (o.code or ""))
        f: dict[str, Any] = {"letter": i, "len_rank": sum(1 for x in lens if x < lens[i]), "text": txt,
                             "text_x_letter": (txt, i), "ctx_x_letter": (ctx, i), "ctx_x_text": (ctx, txt)}
        f["letter_x_len_rank"] = (i, f["len_rank"])
        if numeric:
            f["value_rank"] = sum(1 for x in vals if x < vals[i])
            f["letter_x_value_rank"] = (i, f["value_rank"])
            f["ctx_x_value_rank"] = (ctx, f["value_rank"])
        feats.append(f)
    return feats, k


def _one(args: tuple[str, list[int], list[int]]) -> dict[str, Any] | None:
    fid, train, test = args
    from assessment_bank.registry import generate

    def rows(seeds: list[int]) -> list[tuple[list[dict[str, Any]], int]]:
        out = []
        for s in seeds:
            try:
                r = _features(generate(fid, s))
            except Exception:  # noqa: BLE001  (ошибки генерации ловит валидатор, здесь — только атака)
                r = None
            if r:
                out.append(r)
        return out

    tr, te = rows(train), rows(test)
    if len(tr) < 10 or len(te) < 10:
        return None
    k_opts = collections.Counter(len(f) for f, _ in tr + te)
    res: dict[str, float] = {}
    for a in ATTACKS:
        hit, tot = collections.Counter(), collections.Counter()
        usable = True
        for feats, key in tr:
            if a not in feats[0]:
                usable = False
                break
            for i, f in enumerate(feats):
                tot[f[a]] += 1
                hit[f[a]] += i == key
        if not usable:
            continue
        acc = 0.0
        n = 0
        for feats, key in te:
            if a not in feats[0]:
                continue
            k = len(feats)
            sc = [(hit[f[a]] + 1.0 / k) / (tot[f[a]] + 1.0) for f in feats]
            m = max(sc)
            best = [i for i, x in enumerate(sc) if abs(x - m) < 1e-12]
            acc += (1.0 / len(best)) if key in best else 0.0
            n += 1
        if n:
            res[a] = acc / n
    chance = sum(1.0 / len(f) for f, _ in te) / len(te)
    best = max(res, key=res.get) if res else None
    return {"family_id": fid, "n_test": len(te), "n_options": dict(k_opts), "chance": round(chance, 4),
            "by_attack": {a: round(x, 4) for a, x in res.items()}, "best": best,
            "best_acc": round(res[best], 4) if best else None,
            "excess": round(res[best] - chance, 4) if best else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=100)
    ap.add_argument("--test", type=int, default=100)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--families", default="", help="через запятую; по умолчанию — все семейства с выбором варианта")
    ap.add_argument("--key", default="2110", help="ключ ГСЧ зёрен (обучающие и проверочные — разные потоки)")
    ap.add_argument("--flag", type=float, default=0.10, help="порог превышения для списка семейств")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    from assessment_bank.registry import list_families
    if a.families:
        fids = [f.strip() for f in a.families.split(",") if f.strip()]
    else:
        fids = sorted(sp.family_id for sp in list_families() if sp.invariants.n_options)
    train, test = _seeds(a.train, f"{a.key}:train"), _seeds(a.test, f"{a.key}:test")
    assert not set(train) & set(test)
    with mp.Pool(a.jobs) as pool:
        rows = [r for r in pool.imap_unordered(_one, [(f, train, test) for f in fids], chunksize=4) if r]
    rows.sort(key=lambda r: -(r["excess"] or 0))
    n_te = sum(r["n_test"] for r in rows)
    summ: dict[str, Any] = {"chance": round(sum(r["chance"] * r["n_test"] for r in rows) / max(1, n_te), 4)}
    for att in ATTACKS:
        rs = [r for r in rows if att in r["by_attack"]]
        nn = sum(r["n_test"] for r in rs)
        if nn:
            summ[att] = {"acc": round(sum(r["by_attack"][att] * r["n_test"] for r in rs) / nn, 4),
                         "chance": round(sum(r["chance"] * r["n_test"] for r in rs) / nn, 4),
                         "n_families": len(rs), "n_test_variants": nn}
    flagged = [r for r in rows if (r["excess"] or 0) > a.flag]
    out = {"command": " ".join(sys.argv), "train_seeds": a.train, "test_seeds": a.test, "key": a.key,
           "n_families": len(rows), "summary": summ, "flag_threshold": a.flag, "n_flagged": len(flagged),
           "flagged": [r["family_id"] for r in flagged], "families": rows}
    print(json.dumps({k: out[k] for k in ("n_families", "summary", "n_flagged")}, ensure_ascii=False, indent=1))
    for r in rows[:a.top]:
        print(f"{r['excess']:+.3f} {r['best_acc']:.3f} ({r['best']}) шанс {r['chance']:.3f}  {r['family_id']}")
    if a.out:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
