"""Команды проверки с живыми пользователями (на сервере: docker compose exec api python -m app.modules.study …).

    python -m app.modules.study invite --role candidate --n 5 [--batch 10.10] [--quick] [--test] [--base-url https://…]
        выпустить ссылки; код печатается один раз (в базе — только хеш). --quick: вход по ссылке без регистрации;
        --test: репетиция команды (в публичные цифры не входит).
    python -m app.modules.study status          # кто начал, на каком шаге, сколько ответило (метки, без имён)
    python -m app.modules.study report [--texts] [--json]   # служебная сводка; --texts — комментарии (очищены от контактов)
    python -m app.modules.study summary         # то, что увидит /validation (пусто при N < 3)
    python -m app.modules.study close --batch 10.10 | --label К-03   # закрыть неначатые ссылки
"""
from __future__ import annotations

import argparse
import json
import sys

from app.core.db import SessionLocal, get_engine
from fastapi import HTTPException
from app.modules.study import report, service, texts

STATUS_RU = {"not_started": "не открывал", "closed": "закрыта", "active": "идёт", "done": "путь пройден",
             "stopped": "остановился", "withdrawn": "отозвал"}


def _fmt_s(v) -> str:
    if v is None:
        return "—"
    return f"{int(v // 60)}:{int(v % 60):02d}"


def cmd_invite(a) -> int:
    with SessionLocal() as db:
        try:
            out = service.create_invites(db, a.role, a.n, batch=a.batch, mode="quick" if a.quick else "register",
                                         is_test=a.test, base_url=a.base_url)
        except HTTPException as e:
            print(e.detail["message"], file=sys.stderr)
            return 2
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(f"Выпущено ссылок: {len(out)} · роль: {texts.ROLE_TITLE[a.role]} · "
          f"{'вход по ссылке, без регистрации' if a.quick else 'с регистрацией'}{' · РЕПЕТИЦИЯ' if a.test else ''}")
    print("Ссылки показаны один раз: в базе только хеш. Потеряли — выпустите новые.\n")
    for x in out:
        print(f"{x['label']}\t{x['url']}")
    return 0


def cmd_status(_a) -> int:
    with SessionLocal() as db:
        rs = report.rows(db, include_test=True, include_unstarted=True)
    if not rs:
        print("Приглашений пока нет. Выпуск: python -m app.modules.study invite --role candidate --n 5")
        return 0
    print(f"{'метка':<7}{'роль':<13}{'пачка':<10}{'статус':<15}{'шаг сейчас':<12}{'время пути':<11}{'ошибок':<7}анкета")
    for r in rs:
        st = STATUS_RU.get(r.status if r.p.started_at else ("closed" if not r.p.is_active else "not_started"), r.status)
        print(f"{r.p.label:<7}{texts.ROLE_TITLE[r.p.role]:<13}{(r.p.batch or '—'):<10}{st:<15}{(r.d['current'] or 'все'):<12}"
              f"{_fmt_s(r.path_s):<11}{len(r.d['errors']):<7}{'да, SUS ' + str(round(r.sus)) if r.ans and r.sus is not None else 'нет'}"
              f"{'  [репетиция]' if r.p.is_test else ''}")
    real = [r for r in rs if not r.p.is_test and r.p.started_at]
    print(f"\nНачали: {len(real)} · путь пройден: {sum(1 for r in real if r.status == 'done')} · "
          f"ответили на анкету: {sum(1 for r in real if r.ans)} · блок на /validation при N ≥ 3 ответивших")
    return 0


def cmd_report(a) -> int:
    with SessionLocal() as db:
        out = report.admin_report(db, with_texts=a.texts)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    for x in out["participants"]:
        print(f"[{x['label']}] {texts.ROLE_TITLE[x['role']]} · {x['status']} · путь {_fmt_s(x['path_seconds'])} · "
              f"ошибок {len(x['errors'])} · последний экран {x['last_screen'] or '—'}{' · РЕПЕТИЦИЯ' if x['test'] else ''}")
        for k, s in x["steps"].items():
            print(f"    {k:<10}{'—' if not s else ('пропущен' if s['skipped'] else 'есть')}  {_fmt_s(x['step_seconds'].get(k))}")
        a_ = x["answers"]
        if a_:
            print(f"    анкета: SUS {a_['sus']} · P@5 {a_['p5']} · верю грейду {a_['belief']} · метки {a_['tags']}"
                  + (f"\n    комментарий: {a_['comment']}" if a_.get("comment") else ""))
    pub = out["public"]
    print("\nПубличная сводка:", pub["signature"] if pub.get("shown") else f"не показывается (нужно N ≥ {pub['min_n']} ответивших)")
    return 0


def cmd_summary(_a) -> int:
    with SessionLocal() as db:
        print(json.dumps(report.public_summary(db), ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_close(a) -> int:
    if a.batch is None and not a.label:
        print("Нужно --batch или --label: закрыть все ссылки сразу команда не позволяет", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        n = service.close_invites(db, batch=a.batch, label=a.label)
    print(f"Закрыто неначатых ссылок: {n}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.modules.study")
    sub = ap.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("invite", help="выпустить ссылки-приглашения")
    inv.add_argument("--role", required=True, choices=texts.ROLES)
    inv.add_argument("--n", type=int, required=True)
    inv.add_argument("--batch", default="")
    inv.add_argument("--quick", action="store_true")
    inv.add_argument("--test", action="store_true")
    inv.add_argument("--base-url")
    inv.add_argument("--json", action="store_true")
    sub.add_parser("status")
    rp = sub.add_parser("report")
    rp.add_argument("--texts", action="store_true")
    rp.add_argument("--json", action="store_true")
    sub.add_parser("summary")
    cl = sub.add_parser("close")
    cl.add_argument("--batch")
    cl.add_argument("--label")
    a = ap.parse_args(argv)
    get_engine()
    return {"invite": cmd_invite, "status": cmd_status, "report": cmd_report, "summary": cmd_summary,
            "close": cmd_close}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
