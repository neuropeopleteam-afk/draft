"""Команды экспертной разметки (запуск на сервере: docker compose exec api python -m app.modules.experts …).

    python -m app.modules.experts pack                       # собрать пакет (A, B, C) из демо-данных и банка
    python -m app.modules.experts invite E1 --name "Иван" [--profile "тимлид Backend"] [--team 2] [--rotate]
    python -m app.modules.experts status                     # прогресс экспертов
    python -m app.modules.experts source E1 E2 E3 --model "Claude Fable 5.1" --roles "тимлид Backend; Data/ML; QA/ИБ"
                                                             # разметку под кодами делает модель (роли — по порядку)
    python -m app.modules.experts source E1 --people         # под кодом размечает человек (по умолчанию)
    python -m app.modules.experts llm-grade [--models yandexgpt/latest,gpt-oss-120b/latest] [--runs 3]
    python -m app.modules.experts synth-check                # расчёт на синтетической разметке (проверка)

Пакет v2 (только блок A, разметка офлайн файлами; docs/validation/EXPERT_PROTOCOL.md, раздел «Пакет v2»):
    python -m app.modules.experts pack2 build [--dry-run]    # собрать v2 из текущего мира (повторно — ничего не делает)
    python -m app.modules.experts pack2 export --code E1 --out e1.jsonl          # объекты роли вслепую
    python -m app.modules.experts pack2 import --code E1 --file e1_labels.jsonl --source model --model "Claude Fable 5.1"
                                                             # [--role "тимлид Backend"]; повторный импорт не дублирует
    python -m app.modules.experts pack2 status               # объём и прогресс ролей v2

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
    src = sub.add_parser("source", help="кто размечает под кодами: люди или языковая модель (подпись на /validation)")
    src.add_argument("codes", nargs="+")
    who = src.add_mutually_exclusive_group(required=True)
    who.add_argument("--model", help="название модели, например «Claude Fable 5.1»")
    who.add_argument("--people", action="store_true")
    src.add_argument("--roles", help="роли модели по порядку кодов через «;»: «тимлид Backend; Data/ML; QA/ИБ»")
    lg = sub.add_parser("llm-grade")
    lg.add_argument("--models", default="yandexgpt/latest,gpt-oss-120b/latest")
    lg.add_argument("--runs", type=int, default=3)
    lg.add_argument("--replace", action="store_true")
    sub.add_parser("synth-check")
    p2 = sub.add_parser("pack2", help="пакет v2 блока A: build, export, import, status")
    p2s = p2.add_subparsers(dest="action", required=True)
    b2 = p2s.add_parser("build")
    b2.add_argument("--dry-run", action="store_true", help="только показать состав, ничего не записывать")
    e2 = p2s.add_parser("export")
    e2.add_argument("--code", required=True)
    e2.add_argument("--out", required=True, help="файл JSONL или - (stdout)")
    i2 = p2s.add_parser("import")
    i2.add_argument("--code", required=True)
    i2.add_argument("--file", required=True, help="файл JSONL или - (stdin)")
    i2.add_argument("--source", choices=("people", "model"), default="people")
    i2.add_argument("--model", help="название модели, если --source model")
    i2.add_argument("--role", help="роль разметчика для подписи: «тимлид Backend»")
    p2s.add_parser("status")
    src.add_argument("--pack", default="v1", help="пакет кодов: v1 (по умолчанию) или v2")
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

            print(json.dumps({"v1": panel_status(db), "v2": panel_status(db, "v2")}, ensure_ascii=False, indent=1))
        elif a.cmd == "source":
            from app.modules.experts.service import panel_status, set_source, source_summary

            roles = [r for r in (a.roles or "").split(";") if r.strip()]
            done = set_source(db, a.codes, "people" if a.people else "model", a.model, roles, pack=a.pack)
            print(f"Источник разметки обновлён: {', '.join(done) or 'коды не найдены'}")
            s = source_summary(panel_status(db, a.pack)) or {}
            print(f"Подпись на /validation: {s.get('caption') or s.get('title', '—')}")
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
        elif a.cmd == "pack2":
            return _pack2(db, a)
    return 0


def _pack2(db: Session, a) -> int:
    from app.modules.experts import pack2

    def fail(e: Exception) -> int:
        det = getattr(e, "detail", None)
        print(det.get("message") if isinstance(det, dict) else e)
        return 1

    if a.action == "build":
        r = pack2.build(db, dry_run=a.dry_run)
        if r.get("error"):
            print(r["error"])
            return 1
        head = ("Пакет v2 уже собран — ничего не изменено" if r.get("exists") and not r.get("created") else
                "Пакет v2 собран" if r.get("created") else "Пробный расчёт (ничего не записано)")
        print(head)
        print(json.dumps({k: v for k, v in r.items() if k not in ("created", "exists", "dry_run")}, ensure_ascii=False,
                         indent=1))
    elif a.action == "export":
        try:
            if a.out == "-":  # в stdout: docker compose exec -T api … --out - > e1.jsonl
                rows = pack2.export_rows(db, a.code)
                for r in rows:
                    sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
                print(f"Роль {a.code.upper()}: {len(rows)} объектов", file=sys.stderr)
                return 0
            n = pack2.export_file(db, a.code, a.out)
        except Exception as e:  # noqa: BLE001
            return fail(e)
        print(f"Роль {a.code.upper()}: {n} объектов → {a.out} (вслепую: без мест, баллов, метода и скрытых полей)")
    elif a.action == "import":
        try:
            if a.file == "-":  # из stdin: docker compose exec -T api … --file - < e1_labels.jsonl
                lines = sys.stdin.read().splitlines()
            else:
                with open(a.file, encoding="utf-8") as f:
                    lines = f.read().splitlines()
            r = pack2.import_labels(db, a.code, lines, source=a.source, model=a.model, role=a.role)
        except Exception as e:  # noqa: BLE001
            return fail(e)
        if not r["ok"]:
            print(f"Импорт отклонён, ничего не записано: ошибок {r['n_errors']}")
            for e in r["errors"]:
                print(" ", e)
            return 2
        who = f"модель {r['model']}" if r["source"] == "model" else "люди"
        print(f"Роль {r['code']}: добавлено {r['added']}, обновлено {r['updated']}, без изменений {r['unchanged']}; "
              f"размечено {r['labeled']} из {r['assigned']}; источник — {who}")
    elif a.action == "status":
        from app.modules.experts.service import panel_status

        print(json.dumps({"pack": pack2.summary(db) if pack2.exists(db) else None,
                          "panel": panel_status(db, pack2.PACK2)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
