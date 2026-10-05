"""qa.bash.trace_logs_output — predict_output: локализация дефекта по журналам двух сервисов.

Журнал шлюза и журнал сервиса платежей связаны идентификатором запроса. Четыре вида
команд: запросы, где сервис записал ERROR, а шлюз вернул 200 (comm -12); число ошибок по
версиям после меток деплоя (awk); доля 5xx по эндпоинтам (awk); число затронутых
пользователей (grep -o | sort -u | wc -l). Ключ — независимая модель на Python, сверка
исполнением в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "qa.bash.trace_logs_output"

SERVICES = [("payments.log", "платежей", ["/api/pay", "/api/refund", "/api/status"],
             ["charge_ok", "refund_ok", "status_ok"], ["bank_timeout", "card_declined", "db_lock"]),
            ("booking.log", "бронирования", ["/api/book", "/api/cancel", "/api/slots"],
             ["booked", "cancelled", "slots_ok"], ["slot_taken", "provider_timeout", "db_lock"]),
            ("delivery.log", "доставки", ["/api/quote", "/api/ship", "/api/track"],
             ["quoted", "shipped", "tracked"], ["carrier_timeout", "bad_address", "db_lock"])]
KINDS = ["masked", "per_version", "error_rate", "users"]


def _gen(rng, svc):
    log_name, _title, paths, oks, errs = svc
    n = rng.randint(8, 11)
    base = rng.randint(100, 800)
    t = rng.randint(0, 20)
    versions = ["1.%d.%d" % (rng.randint(2, 7), p) for p in sorted(rng.sample(range(0, 9), 2))]
    deploy_at = rng.randint(2, n - 3)
    users = [f"u{rng.randint(10, 99)}" for _ in range(4)]
    gw, sv = [], [f"12:{t:02d}:00 deploy version={versions[0]}"]
    rows = []
    for i in range(n):
        t += rng.randint(1, 3)
        if i == deploy_at:
            sv.append(f"12:{t:02d}:00 deploy version={versions[1]}")
        req = f"r{base + i}"
        pi = rng.randrange(3)
        err = rng.random() < (0.2 if i < deploy_at else 0.55)
        user = rng.choice(users)
        msg = rng.choice(errs) if err else oks[pi]
        if err:
            status = rng.choice([200, 502, 500, 504]) if rng.random() < 0.7 else 200
        else:
            status = 200
        ms = rng.randint(20, 1500)
        method = "GET" if paths[pi].endswith(("status", "slots", "track")) else "POST"
        gw.append(f"12:{t:02d}:{rng.randint(10, 59):02d} req={req} {method} {paths[pi]} status={status} ms={ms}")
        sv.append(f"12:{t:02d}:{rng.randint(10, 59):02d} req={req} user={user} "
                  f"level={'ERROR' if err else 'INFO'} msg={msg}")
        rows.append(dict(req=f"req={req}", path=paths[pi], status=status, err=err, user=user,
                         ver=versions[1] if i >= deploy_at else versions[0]))
    return gw, sv, rows, log_name


def _cmd(kind, log):
    return {
        "masked": (f"grep 'level=ERROR' {log} | cut -d' ' -f2 | sort -u > failed.txt\n"
                   "grep 'status=200' gateway.log | cut -d' ' -f2 | sort | comm -12 - failed.txt"),
        "per_version": (f"awk '$2 == \"deploy\" {{ split($3, a, \"=\"); ver = a[2] }}\n"
                        f"     $4 == \"level=ERROR\" {{ err[ver]++ }}\n"
                        f"     END {{ for (v in err) print v, err[v] }}' {log} | sort"),
        "error_rate": ("awk '{ split($5, s, \"=\"); total[$4]++; if (s[2] + 0 >= 500) bad[$4]++ }\n"
                       "     END { for (p in total) print p, bad[p] + 0 \"/\" total[p] }' gateway.log | sort"),
        "users": f"grep 'level=ERROR' {log} | grep -o 'user=[a-z0-9]*' | sort -u | wc -l",
    }[kind]


def _model(kind, rows):
    if kind == "masked":
        failed = {r["req"] for r in rows if r["err"]}
        ok200 = sorted({r["req"] for r in rows if r["status"] == 200})
        res = [q for q in ok200 if q in failed]
        return "\n".join(res) if res else None
    if kind == "per_version":
        cnt: dict[str, int] = {}
        for r in rows:
            if r["err"]:
                cnt[r["ver"]] = cnt.get(r["ver"], 0) + 1
        if len(cnt) < 2:
            return None
        return "\n".join(f"{v} {cnt[v]}" for v in sorted(cnt))
    if kind == "error_rate":
        tot: dict[str, list[int]] = {}
        for r in rows:
            tot.setdefault(r["path"], [0, 0])
            tot[r["path"]][1] += 1
            tot[r["path"]][0] += r["status"] >= 500
        if sum(b for b, _ in tot.values()) == 0:
            return None
        return "\n".join(f"{p} {b}/{n}" for p, (b, n) in sorted(tot.items()))
    users = {r["user"] for r in rows if r["err"]}
    return str(len(users)) if users else None


QUESTIONS = {
    "masked": "Пользователи жалуются, что получили «успешно», а операция не выполнена. Какие "
              "идентификаторы запросов выведет команда?",
    "per_version": "Команда считает ошибки сервиса в разрезе версий, выкатанных за этот период. "
                   "Что она выведет?",
    "error_rate": "Команда считает долю ответов 5xx шлюза по эндпоинтам. Что она выведет?",
    "users": "Сколько различных пользователей затронули ошибки — что выведет команда?",
}
WHY = {"masked": "comm -12 печатает строки, общие для двух отсортированных списков: запросы с "
                 "ERROR в сервисе и статусом 200 на шлюзе — ошибка замаскирована",
       "per_version": "метка deploy меняет текущую версию, каждая строка level=ERROR (поле $4) "
                      "добавляется к счётчику текущей версии; sort упорядочивает вывод",
       "error_rate": "для каждого пути считаются все запросы и запросы со статусом ≥ 500; "
                     "bad[p] + 0 печатает 0 для путей без ошибок",
       "users": "grep -o выделяет user=…, sort -u оставляет уникальные, wc -l считает строки"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    svc = rng.choice(SERVICES)
    kind = rng.choice(KINDS)
    for _ in range(500):
        gw, sv, rows, log = _gen(rng, svc)
        out = _model(kind, rows)
        if out is not None:
            break
    else:
        raise RuntimeError("не удалось подобрать журналы")
    cmd = _cmd(kind, log)
    gw_text, sv_text = "\n".join(gw) + "\n", "\n".join(sv) + "\n"
    stem = (f"Разбор инцидента в сервисе {svc[1]}. Фрагменты журналов: `gateway.log` (шлюз API, поля: "
            f"время, запрос, метод, путь, статус, длительность) и `{log}` (сервис {svc[1]}; поля: "
            f"время, запрос, пользователь, уровень, сообщение; строки `deploy` — метки выкатки).\n\n"
            f"gateway.log:\n{gw_text}\n{log}:\n{sv_text}\n{QUESTIONS[kind]} Пробелы в начале строк "
            f"можно не писать.")
    ak = AnswerKey(kind="output", value=out, explanation=WHY[kind] + ".")
    checks = [Check(name="stdout", runner="bash", program=cmd,
                    files={"gateway.log": gw_text, log: sv_text},
                    expect="stdout_equals", expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=cmd, answer_key=ak, context=svc[1],
                         verification="execution", checks=checks, params={"kind": kind})
