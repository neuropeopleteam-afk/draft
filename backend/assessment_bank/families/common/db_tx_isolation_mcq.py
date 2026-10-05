"""common.db.tx_isolation_mcq — mcq_concept: уровни изоляции транзакций в PostgreSQL.

Две сессии выполняют команды в заданном порядке. Ключ берётся из таблицы правил
PostgreSQL (снимок в READ COMMITTED — на каждый оператор, в REPEATABLE READ — при первом
операторе транзакции, а не при BEGIN; обновление строки, изменённой после снимка, в
REPEATABLE READ даёт ошибку 40001, в READ COMMITTED перечитывает свежую версию; читатели
не блокируются и не видят незафиксированное). Проверка независимо исполняет пошаговую
MVCC-модель (версии строк, снимки, блокировки) и сверяет исход с ключом.
"""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.db.tx_isolation_mcq"

LEVELS = {"RC": "READ COMMITTED", "RR": "REPEATABLE READ", "RU": "READ UNCOMMITTED",
          "SER": "SERIALIZABLE"}

# Пошаговая MVCC-модель PostgreSQL для одной таблицы (исполняется в песочнице).
SIM = r'''
import json, sys

def run(sc):
    rows = {}  # rid -> [версии {xmin, xmax, data}]
    for rid, data in sc["rows"].items():
        rows[rid] = [{"xmin": 0, "xmax": None, "data": dict(data)}]
    committed, aborted = {0}, set()
    tx, locks, out = {}, {}, {"probe": None}
    names = iter(range(1, 100))

    def snap(t):
        if t["level"] in ("RR", "SER"):
            if t["snap"] is None:
                t["snap"] = set(committed)
            return t["snap"]
        return set(committed)  # RC и RU: снимок на каждый оператор

    def visible(v, t, s):
        ok = v["xmin"] == t["id"] or v["xmin"] in s
        dead = v["xmax"] is not None and (v["xmax"] == t["id"] or v["xmax"] in s)
        return ok and not dead

    def read(t, rid, s):
        for v in reversed(rows[rid]):
            if visible(v, t, s):
                return v
        return None

    def latest(rid):
        for v in reversed(rows[rid]):
            if v["xmin"] not in aborted:
                return v

    def lock(name, rid):
        t = tx[name]
        s = snap(t)  # снимок берётся в начале оператора, до ожидания блокировки
        holder = locks.get(rid)
        if holder is not None and holder != name:
            return "wait"
        cur = latest(rid)
        if cur["xmin"] != t["id"] and cur["xmin"] not in s:
            if t["level"] in ("RR", "SER"):
                return "error"
        locks[rid] = name
        return cur

    def finish(name, ok):
        t = tx[name]
        (committed if ok else aborted).add(t["id"])
        t["done"] = True
        for rid in [r for r, h in locks.items() if h == name]:
            del locks[rid]

    def apply(name, op):
        kind = op["op"]
        if kind == "begin":
            tx[name] = {"id": next(names), "level": op["level"], "snap": None, "done": False,
                        "last": None, "aborted": False}
            return "ok"
        t = tx[name]
        if t["aborted"]:
            return "ok"
        if kind == "commit":
            finish(name, True)
            return "ok"
        if kind == "select":
            s = snap(t)
            v = read(t, op["rid"], s)
            t["last"] = v["data"][sc["col"]]
            if op.get("probe"):
                out["probe"] = t["last"]
            return "ok"
        if kind == "count":
            s = snap(t)
            n = sum(1 for rid in rows if (lambda v: v is not None and v["data"].get("status") == op["status"])(read(t, rid, s)))
            if op.get("probe"):
                out["probe"] = n
            return "ok"
        if kind == "insert":
            snap(t)
            rows[op["rid"]] = [{"xmin": t["id"], "xmax": None, "data": dict(op["data"])}]
            return "ok"
        if kind in ("select_for_update", "update_expr", "update_set"):
            cur = lock(name, op["rid"])
            if cur == "wait":
                return "wait"
            if cur == "error":
                t["aborted"] = True
                finish(name, False)
                out.setdefault("errors", []).append(name)
                return "ok"
            val = cur["data"][sc["col"]]
            if kind == "select_for_update":
                t["last"] = val
                return "ok"
            new = val - op["delta"] if kind == "update_expr" else t["last"] - op["delta"]
            cur["xmax"] = t["id"]
            d = dict(cur["data"]); d[sc["col"]] = new
            rows[op["rid"]].append({"xmin": t["id"], "xmax": None, "data": d})
            return "ok"
        raise ValueError(kind)

    pending = {}
    for name, op in sc["steps"]:
        if name in pending:
            raise RuntimeError("шаг заблокированной сессии")
        if apply(name, op) == "wait":
            pending[name] = op
        progress = True
        while progress:
            progress = False
            for n2, op2 in list(pending.items()):
                if apply(n2, op2) != "wait":
                    del pending[n2]
                    progress = True
    if pending:
        raise RuntimeError("взаимоблокировка")
    if sc["kind"] == "write":
        rid = sc["target"]
        final = None
        for v in reversed(rows[rid]):
            if v["xmin"] in committed:
                final = v["data"][sc["col"]]
                break
        return f"{final}|{','.join(out.get('errors', [])) or '-'}"
    return f"{out['probe']}|nowait"
'''

SCEN = {
    # имя: (тип, допустимые уровни, правило ключа по уровню)
    "rmw_t1_first": ("write", ["RC", "RR"], {"RC": "lost_t1", "RR": "ser_t2"}),
    "rmw_t2_first": ("write", ["RC", "RR"], {"RC": "lost_t2", "RR": "ser_t1"}),
    "atomic_blocked": ("write", ["RC", "RR"], {"RC": "sum", "RR": "ser_t2"}),
    "for_update": ("write", ["RC", "RR"], {"RC": "sum", "RR": "ser_t2"}),
    "late_snapshot": ("write", ["RC", "RR"], {"RC": "sum", "RR": "sum"}),
    "non_repeatable": ("read", ["RC", "RR"], {"RC": "new", "RR": "old"}),
    "first_stmt_snapshot": ("read", ["RC", "RR"], {"RC": "new", "RR": "new"}),
    "dirty": ("read", ["RU", "RC", "RR"], {"RU": "old", "RC": "old", "RR": "old"}),
    "phantom": ("read", ["RC", "RR", "SER"], {"RC": "new", "RR": "old", "SER": "old"}),
}
TABLES = [("accounts", "balance", "списание"), ("wallets", "amount", "оплата"),
          ("products", "stock", "резерв"), ("limits", "quota", "расход квоты")]
CNT_TABLES = [("tasks", "new"), ("orders", "paid"), ("tickets", "open"), ("invoices", "draft")]


def _steps(name, level, col, x1, x2, cnt_status, n0):
    b = {"op": "begin", "level": level}
    sel = {"op": "select", "rid": "1"}
    fu = {"op": "select_for_update", "rid": "1"}
    c = {"op": "commit"}
    S = {
        "rmw_t1_first": [("T1", b), ("T2", b), ("T1", sel), ("T2", sel),
                         ("T1", {"op": "update_set", "rid": "1", "delta": x1}), ("T1", c),
                         ("T2", {"op": "update_set", "rid": "1", "delta": x2}), ("T2", c)],
        "rmw_t2_first": [("T1", b), ("T2", b), ("T1", sel), ("T2", sel),
                         ("T2", {"op": "update_set", "rid": "1", "delta": x2}), ("T2", c),
                         ("T1", {"op": "update_set", "rid": "1", "delta": x1}), ("T1", c)],
        "atomic_blocked": [("T1", b), ("T2", b), ("T1", {"op": "update_expr", "rid": "1", "delta": x1}),
                           ("T2", {"op": "update_expr", "rid": "1", "delta": x2}), ("T1", c), ("T2", c)],
        "for_update": [("T1", b), ("T2", b), ("T1", fu), ("T2", fu),
                       ("T1", {"op": "update_set", "rid": "1", "delta": x1}), ("T1", c),
                       ("T2", {"op": "update_set", "rid": "1", "delta": x2}), ("T2", c)],
        "late_snapshot": [("T1", b), ("T2", b), ("T1", sel),
                          ("T1", {"op": "update_set", "rid": "1", "delta": x1}), ("T1", c),
                          ("T2", sel), ("T2", {"op": "update_set", "rid": "1", "delta": x2}), ("T2", c)],
        "non_repeatable": [("T1", b), ("T1", sel), ("T2", b),
                           ("T2", {"op": "update_expr", "rid": "1", "delta": x2}), ("T2", c),
                           ("T1", {**sel, "probe": True}), ("T1", c)],
        "first_stmt_snapshot": [("T1", b), ("T2", b), ("T2", {"op": "update_expr", "rid": "1", "delta": x2}),
                                ("T2", c), ("T1", {**sel, "probe": True}), ("T1", c)],
        "dirty": [("T1", b), ("T2", b), ("T2", {"op": "update_expr", "rid": "1", "delta": x2}),
                  ("T1", {**sel, "probe": True}), ("T2", c), ("T1", c)],
        "phantom": [("T1", b), ("T1", {"op": "count", "status": cnt_status}), ("T2", b),
                    ("T2", {"op": "insert", "rid": str(n0 + 10), "data": {"status": cnt_status}}),
                    ("T2", c), ("T1", {"op": "count", "status": cnt_status, "probe": True}), ("T1", c)],
    }
    return S[name]


def _sql(steps, level, table, col, cnt_table):
    lines = []
    for n, op in steps:
        k = op["op"]
        if k == "begin":
            s = f"BEGIN ISOLATION LEVEL {LEVELS[level]};"
        elif k == "commit":
            s = "COMMIT;"
        elif k == "select":
            s = f"SELECT {col} FROM {table} WHERE id = 1;"
        elif k == "select_for_update":
            s = f"SELECT {col} FROM {table} WHERE id = 1 FOR UPDATE;"
        elif k == "update_expr":
            s = f"UPDATE {table} SET {col} = {col} - {op['delta']} WHERE id = 1;"
        elif k == "update_set":
            s = (f"UPDATE {table} SET {col} = :v - {op['delta']} WHERE id = 1;"
                 f"  -- :v — прочитанное {n} значение")
        elif k == "count":
            s = f"SELECT count(*) FROM {cnt_table} WHERE status = '{op['status']}';"
        else:
            s = f"INSERT INTO {cnt_table} (status) VALUES ('{op['data']['status']}');"
        if op.get("probe"):
            s += "  -- (?)"
        lines.append(f"{n}: {s}")
    return "\n".join(lines)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    name = rng.choice(sorted(SCEN))
    kind, levels, rule = SCEN[name]
    level = rng.choice(levels)
    table, col, act = rng.choice(TABLES)
    cnt_table, cnt_status = rng.choice(CNT_TABLES)
    B = rng.choice([800, 1000, 1500, 2000, 2500, 5000])
    x1, x2 = rng.sample([100, 150, 200, 250, 300, 400, 500], 2)
    n0 = rng.randint(3, 9)
    steps = _steps(name, level, col, x1, x2, cnt_status, n0)
    code = _sql(steps, level, table, col, cnt_table)
    if name == "phantom":
        rows = {str(i): {"status": cnt_status} for i in range(1, n0 + 1)}
        sc = {"rows": rows, "col": "status", "steps": steps, "kind": "read"}
    else:
        sc = {"rows": {"1": {col: B}}, "col": col, "steps": steps, "kind": kind, "target": "1"}
    if kind == "write":
        out = {"sum": (B - x1 - x2, "-"), "lost_t1": (B - x2, "-"), "lost_t2": (B - x1, "-"),
               "ser_t2": (B - x1, "T2"), "ser_t1": (B - x2, "T1")}
        text = {"sum": "{c} = {v}; обе транзакции успешно зафиксированы",
                "lost_t1": "{c} = {v}; обе зафиксированы, изменение T1 потеряно",
                "lost_t2": "{c} = {v}; обе зафиксированы, изменение T2 потеряно",
                "ser_t2": "{c} = {v}; T2 откатывается с ошибкой 40001",
                "ser_t1": "{c} = {v}; T1 откатывается с ошибкой 40001"}
        pref = ["sum", "ser_t2", "lost_t1", "lost_t2", "ser_t1"]
        q = f"Каким будет `{col}` в строке id = 1 после выполнения всех шагов и чем закончатся транзакции?"
        init = f"В `{table}` одна строка: id = 1, {col} = {B}"
    else:
        old, new = (n0, n0 + 1) if name == "phantom" else (B, B - x2)
        out = {"old": (old, "nowait"), "new": (new, "nowait"), "wait": (new, "wait"),
               "error": ("error", "-")}
        text = {"old": "сразу вернёт {v}", "new": "сразу вернёт {v}",
                "wait": "дождётся конца T2 и вернёт {v}", "error": "завершится ошибкой 40001"}
        pref = ["old", "new", "wait", "error"]
        q = "Что вернёт запрос, отмеченный `(?)`?"
        init = (f"В `{cnt_table}` {n0} строк со статусом '{cnt_status}'" if name == "phantom"
                else f"В `{table}` одна строка: id = 1, {col} = {B}")
    key_code = rule[level]
    distract = [k for k in pref if k != key_code and out[k] != out[key_code]][:3]

    def opt_text(k):
        v, _ = out[k]
        t = text[k].format(v=v, c=col)
        return t if kind == "write" else t[0].upper() + t[1:]
    opts, key = make_options(rng, (opt_text(key_code), None), [(opt_text(k), None) for k in distract])
    exp_code = "{}|{}".format(*out[key_code])
    stem = (f"PostgreSQL 16. {init}. Две сессии T1 и T2 выполняют команды строго в указанном "
            f"порядке (`:v` — значение, которое сессия получила своим последним SELECT; если "
            f"команда блокируется, следующая строка выполняется в другой сессии, а "
            f"заблокированная продолжает работу, как только блокировка снята). {q}")
    why = {
        "rmw_t1_first": "чтение и запись разделены: в READ COMMITTED T2 записывает значение, "
                        "вычисленное из устаревшего чтения (потерянное обновление), в REPEATABLE "
                        "READ обновление строки, изменённой после снимка T2, даёт ошибку 40001",
        "rmw_t2_first": "то же потерянное обновление, но первой фиксируется T2: в READ COMMITTED "
                        "теряется изменение T2, в REPEATABLE READ ошибку получает T1",
        "atomic_blocked": "UPDATE ... SET x = x - d в READ COMMITTED после ожидания перечитывает "
                          "свежую версию строки, поэтому оба изменения сохраняются; в REPEATABLE "
                          "READ снимок T2 взят до фиксации T1 — ошибка 40001",
        "for_update": "SELECT ... FOR UPDATE ждёт T1 и в READ COMMITTED возвращает уже новую "
                      "версию; в REPEATABLE READ строка изменена после снимка — ошибка 40001",
        "late_snapshot": "снимок REPEATABLE READ берётся при первом операторе, а не при BEGIN: "
                         "T2 впервые читает после фиксации T1 и видит новое значение",
        "non_repeatable": "READ COMMITTED берёт снимок на каждый оператор (неповторяемое чтение), "
                          "REPEATABLE READ читает по снимку первого оператора",
        "first_stmt_snapshot": "снимок REPEATABLE READ берётся при первом операторе T1, а он "
                               "выполнен после фиксации T2",
        "dirty": "PostgreSQL никогда не показывает незафиксированные данные (READ UNCOMMITTED "
                 "работает как READ COMMITTED), а читатели не ждут писателей",
        "phantom": "в PostgreSQL REPEATABLE READ и SERIALIZABLE читают по снимку и фантомов не "
                   "видят; READ COMMITTED видит новую зафиксированную строку",
    }[name]
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"Уровень {LEVELS[level]}: {why}.")
    program = SIM + f"\nprint(run(json.loads({json.dumps(json.dumps(sc))})))\n"
    checks = [Check(name="mvcc_model", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=exp_code, embeds_display_code=False)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=(cnt_table if name == "phantom" else table) + "/" + name, verification="execution", checks=checks,
                         display_code_note="Проверка исполняет пошаговую модель MVCC PostgreSQL "
                                           "(версии строк, снимки, блокировки строк) и сверяет "
                                           "исход с ключом из таблицы правил.",
                         params={"scenario": name, "level": level, "key_code": key_code})
