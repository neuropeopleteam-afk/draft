"""Команды экспертной разметки (запуск на сервере: docker compose exec api python -m app.modules.experts …).

    python -m app.modules.experts pack                       # собрать пакет (A, B, C) из демо-данных и банка
    python -m app.modules.experts invite E1 --name "Иван" [--profile "тимлид Backend"] [--team 2] [--rotate]
    python -m app.modules.experts status                     # прогресс экспертов
    python -m app.modules.experts llm-grade [--models yandexgpt/latest,gpt-oss-120b/latest] [--runs 3]
    python -m app.modules.experts synth-check                # расчёт на синтетической разметке (проверка)

Ссылка-приглашение печатается один раз (в базе — только хеш); потеряли — invite E1 --rotate выдаст новую,
старая перестанет работать, сделанная разметка сохранится.
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy.orm import Session

from app.core.db import init_engine


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.modules.experts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pack")
    inv = sub.add_parser("invite")
    inv.add_argument("code", help="E1, E2 или E3")
    inv.add_argument("--name")
    inv.add_argument("--profile")
    inv.add_argument("--slot")
    inv.add_argument("--team", type=int, default=3, choices=(2, 3))
    inv.add_argument("--rotate", action="store_true")
    sub.add_parser("status")
    lg = sub.add_parser("llm-grade")
    lg.add_argument("--models", default="yandexgpt/latest,gpt-oss-120b/latest")
    lg.add_argument("--runs", type=int, default=3)
    lg.add_argument("--replace", action="store_true")
    sub.add_parser("synth-check")
    a = ap.parse_args(argv)
    eng = init_engine()
    with Session(eng) as db:
        if a.cmd == "pack":
            from app.modules.experts.pack import ensure_pack

            print("Пакет готов" if ensure_pack(db) else "Нет демо-данных: сначала make seed")
        elif a.cmd == "invite":
            from app.modules.experts.service import create_invite

            try:
                r = create_invite(db, a.code, slot=a.slot, team_size=a.team, name=a.name, profile=a.profile,
                                  rotate=a.rotate)
            except Exception as e:  # noqa: BLE001
                print((getattr(e, "detail", None) or {}).get("message", e) if isinstance(getattr(e, "detail", None), dict) else e)
                return 1
            print(f"Эксперт {r['code']} (слот {r['slot']}, экспертов в команде {r['team_size']}): "
                  f"пары {r['assigned']['A']}, ответы {r['assigned']['B']}, семейства {r['assigned']['C']}")
            print(f"Персональная ссылка (показывается один раз): {r['url']}")
        elif a.cmd == "status":
            from app.modules.experts.service import panel_status

            print(json.dumps(panel_status(db), ensure_ascii=False, indent=1))
        elif a.cmd == "llm-grade":
            from app.modules.experts.llm_grade import grade_pack

            print(json.dumps(grade_pack(db, [m.strip() for m in a.models.split(",") if m.strip()], a.runs,
                                        replace=a.replace), ensure_ascii=False, indent=1))
        elif a.cmd == "synth-check":
            from app.modules.experts import section, synth

            items, _ = section.load(db)
            if not items:
                print("Пакет не собран")
                return 1
            r = synth.check(items)
            for c in r["checks"]:
                print(("OK  " if c["ok"] else "FAIL") + f" {c['what']}: заложено {c['planted']}, получено {c['got']}")
            m = r["matching"]["summary"]
            print("p@5 платформа / BM25 / случайный:", m["p@5"]["platform"], m["p@5"]["bm25"], m["p@5"]["random"])
            return 0 if r["ok"] else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
