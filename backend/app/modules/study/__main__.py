"""Команды обезличенной статистики прохождения (на сервере: docker compose exec api python -m app.modules.study …).

    python -m app.modules.study status          # сколько человек в статистике, на каком шаге, сколько завершили
    python -m app.modules.study report [--texts] [--json]   # служебная сводка; --texts — комментарии (очищены от контактов)
    python -m app.modules.study summary         # то, что увидит /validation (пусто при N < 3 завершённых путей)
    python -m app.modules.study reset-study [--yes] [--include-declined]
        сбросить собранную статистику (данные, не код): события, анкеты, участников. Отказавшиеся остаются отказавшимися
        (их выбор не статистика); --include-declined убирает и отметки отказа. Без --yes только показывает, что будет удалено.
"""
from __future__ import annotations

import argparse
import json
import sys

from app.core.db import SessionLocal
from app.modules.study import report, service, texts
from app.modules.study.models import StudyAnswer, StudyEvent, StudyParticipant

STATUS_RU = {"active": "идёт", "done": "путь пройден", "stopped": "остановился"}


def _fmt_s(v) -> str:
    if v is None:
        return "—"
    return f"{int(v // 60)}:{int(v % 60):02d}"


def cmd_status(_a) -> int:
    with SessionLocal() as db:
        rs = report.rows(db)
        declined = db.query(StudyParticipant).filter(StudyParticipant.declined_at.is_not(None)).count()
    if not rs:
        print(f"В статистике пока никого. Отказались: {declined}.")
        return 0
    print(f"{'запись':<8}{'роль':<13}{'статус':<15}{'шаг сейчас':<12}{'время пути':<11}{'ошибок':<7}анкета")
    for r in rs:
        print(f"{'П-' + str(r.p.id).replace('-', '')[:4]:<8}{texts.ROLE_TITLE[r.p.role]:<13}"
              f"{STATUS_RU.get(r.status, r.status):<15}{(r.d['current'] or 'все'):<12}{_fmt_s(r.path_s):<11}{len(r.d['errors']):<7}"
              f"{'да' + (', SUS ' + str(round(r.sus)) if r.sus is not None else '') if r.ans else 'нет'}")
    done = sum(1 for r in rs if r.status == "done")
    print(f"\nВ статистике: {len(rs)} · путь пройден: {done} · ответили на анкету: {sum(1 for r in rs if r.ans)} · "
          f"отказались: {declined} · блок на /validation при N ≥ 3 завершённых путей")
    return 0


def cmd_report(a) -> int:
    with SessionLocal() as db:
        out = report.admin_report(db, with_texts=a.texts)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    for x in out["participants"]:
        print(f"[{x['id']}] {texts.ROLE_TITLE[x['role']]} · {STATUS_RU.get(x['status'], x['status'])} · путь {_fmt_s(x['path_seconds'])} · "
              f"ошибок {len(x['errors'])} · последний экран {x['last_screen'] or '—'}")
        for k, s in x["steps"].items():
            print(f"    {k:<10}{'—' if not s else ('заранее' if s['skipped'] else 'есть')}  {_fmt_s(x['step_seconds'].get(k))}")
        a_ = x["answers"]
        if a_:
            print(f"    анкета: SUS {a_['sus']} · P@5 {a_['p5']} · верю грейду {a_['belief']} · метки {a_['tags']}"
                  + (f"\n    комментарий: {a_['comment']}" if a_.get("comment") else ""))
    pub = out["public"]
    print(f"\nОтказались: {out['declined']}")
    print("Публичная сводка:", pub["signature"] if pub.get("shown") else f"не показывается (нужно N ≥ {pub['min_n']} завершённых путей)")
    return 0


def cmd_summary(_a) -> int:
    with SessionLocal() as db:
        print(json.dumps(report.public_summary(db), ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_reset(a) -> int:
    with SessionLocal() as db:
        n_p = db.query(StudyParticipant).count()
        n_d = db.query(StudyParticipant).filter(StudyParticipant.declined_at.is_not(None)).count()
        n_e, n_a = db.query(StudyEvent).count(), db.query(StudyAnswer).count()
        will = n_p - (0 if a.include_declined else n_d)
        print(f"Сейчас: записей {n_p} (из них отказавшихся {n_d}), событий {n_e}, анкет {n_a}.")
        if not a.yes:
            print(f"Будет удалено записей: {will}, событий: {n_e}, анкет: {n_a}. Для выполнения добавьте --yes.")
            return 0
        out = service.reset_all(db, keep_declined=not a.include_declined)
    print(f"Сброшено: записей {out['participants']}, событий {out['events']}, анкет {out['answers']}; "
          f"отметок отказа оставлено: {out['declined_kept']}. Блок на /validation скрыт до N ≥ 3.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.modules.study")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    rp = sub.add_parser("report")
    rp.add_argument("--texts", action="store_true")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(fn=cmd_report)
    sub.add_parser("summary").set_defaults(fn=cmd_summary)
    rs = sub.add_parser("reset-study")
    rs.add_argument("--yes", action="store_true")
    rs.add_argument("--include-declined", action="store_true")
    rs.set_defaults(fn=cmd_reset)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
