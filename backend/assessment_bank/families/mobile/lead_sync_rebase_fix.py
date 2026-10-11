"""mobile.lead.sync_rebase_fix — choose_fix (Lead, JS): синхронизация офлайн-правок с сервером, конфликты по полям.

Клиент хранит записи с версиями и очередь локальных правок полей (``base`` — версия записи, на которой сделана
правка). Ответ сервера с изменениями накладывается на локальное состояние, затем очередь «перебазируется»:
правка поля, которое сервер изменил после ``base``, — конфликт (значение сервера остаётся, правка в отчёт); на
удалённой записи — конфликт; остальные правки применяются поверх и отправляются с новой ``base``.

Показан модуль (~30 строк) с дефектом «устаревший ответ сервера не отбрасывается»: два быстрых запроса синхронизации,
ответ на первый пришёл вторым и откатил запись. Варианты — четыре замены ``rebase`` в другом стиле; каждый
дистрактор исправляет показанный дефект и нарушает одно правило (фиксированный состав):

* ``tombstone_ignored`` — удаление на сервере не учитывается: правка «воскрешает» удалённую запись;
* ``record_level_conflict`` — конфликт по версии записи, а не поля: теряются правки полей, которые сервер не трогал;
* ``base_not_moved`` — правки отправляются со старой ``base``: сервер отвергнет их как устаревшие.

Ключ — исполнение в Node всех замен в составе модуля на восьми сценариях.
"""
from __future__ import annotations

from assessment_bank.families._lead_b_utils import module_choose_fix
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "mobile.lead.sync_rebase_fix"

CONTEXTS = [("приложение выездных инженеров", "work_order", ["status", "comment", "address", "slot"]),
            ("заметки врача на обходе", "visit", ["diagnosis", "notes", "room", "plan"]),
            ("CRM торгового представителя", "deal", ["stage", "amount", "contact", "note"]),
            ("приложение склада", "pallet", ["cell", "qty", "state", "label"]),
            ("приложение курьера", "parcel", ["status", "recipient", "slot", "comment"]),
            ("инспекция объектов", "inspection", ["verdict", "remarks", "photo", "risk"])]
NAME_POOLS = {"L": ["local", "cache", "store", "db", "offline"], "P": ["pending", "queue", "outbox", "edits", "journal"],
              "R": ["remote", "pulled", "incoming", "fresh", "serverDelta"], "O": ["op", "edit", "change", "patch", "item"],
              "K": ["keep", "toSend", "resend", "outgoing", "upload"],
              "X": ["conflicts", "rejected", "clashes", "lost", "declined"],
              "F": ["fieldVersion", "versionOf", "fieldRev", "changedAt", "fieldVer"],
              "C": ["copyRecord", "clone", "copyRec", "dup", "snapshot"], "S": ["state", "merged", "view", "result"]}

HELPERS = '''function @F@(rec, field) {
  return (rec.fieldVersion && rec.fieldVersion[field]) || 0;
}

function @C@(rec) {
  return { ...rec, fields: { ...rec.fields }, fieldVersion: { ...(rec.fieldVersion || {}) } };
}'''

REPORT = '''function syncReport(result) {
  return { records: Object.keys(result.@S@).length, send: result.@K@.length, conflicts: result.@X@.length };
}'''

BUGGY = '''function rebase(@L@, @P@, @R@) {
  const @S@ = Object.fromEntries(Object.entries(@L@).map(([id, rec]) => [id, @C@(rec)]));
  Object.values(@R@).forEach((r) => { @S@[r.id] = @C@(r); });
  const @K@ = [], @X@ = [];
  @P@.forEach((@O@) => {
    const rec = @S@[@O@.id];
    const clash = !rec || rec.deleted || @F@(rec, @O@.field) > @O@.base;
    if (clash) { @X@.push(@O@.opId); return; }
    rec.fields[@O@.field] = @O@.value;
    @K@.push({ ...@O@, base: rec.version });
  });
  return { @S@, @K@, @X@ };
}'''

CORRECT = '''function rebase(@L@, @P@, @R@) {
  const @S@ = {};
  for (const id of Object.keys(@L@)) @S@[id] = @C@(@L@[id]);
  for (const r of Object.values(@R@)) {
    if (@S@[r.id] && @S@[r.id].version >= r.version) continue;
    @S@[r.id] = @C@(r);
  }
  const @K@ = [], @X@ = [];
  for (const @O@ of @P@) {
    const rec = @S@[@O@.id];
    if (!rec || rec.deleted) { @X@.push(@O@.opId); continue; }
    if (@F@(rec, @O@.field) > @O@.base) { @X@.push(@O@.opId); continue; }
    rec.fields[@O@.field] = @O@.value;
    @K@.push({ ...@O@, base: rec.version });
  }
  return { @S@, @K@, @X@ };
}'''

DISTRACTORS = {
    "tombstone_ignored": CORRECT.replace("if (!rec || rec.deleted) {", "if (!rec || !rec.fields) {"),
    "record_level_conflict": CORRECT.replace("if (@F@(rec, @O@.field) > @O@.base) {",
                                             "if (rec.version > @O@.base) {"),
    "base_not_moved": CORRECT.replace("@K@.push({ ...@O@, base: rec.version });",
                                      "@K@.push({ ...@O@, base: @O@.base });"),
}
assert all(d != CORRECT for d in DISTRACTORS.values())

WHY = {
    "tombstone_ignored": "удаление на сервере не проверяется — локальная правка «воскрешает» удалённую запись",
    "record_level_conflict": "конфликт определяется по версии всей записи — правка поля, которое сервер не "
                             "трогал, теряется",
    "base_not_moved": "правки уходят со старой base — сервер отвергнет их как сделанные на устаревшей версии",
}


def _rename(code: str, names: dict[str, str]) -> str:
    for k, v in names.items():
        code = code.replace(f"@{k}@", v)
    if "@" in code:
        raise ValueError("не заменена метка имени")
    return code


def _rec(rid, version, fields, fv, deleted=False):
    return {"id": rid, "version": version, "fields": dict(fields), "fieldVersion": dict(fv), "deleted": deleted}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, entity, fields = rng.choice(CONTEXTS)
    f1, f2 = rng.sample(fields, 2)
    names = {k: rng.choice(v) for k, v in NAME_POOLS.items()}
    K, X = names["K"], names["X"]
    rid = f"{entity}-{rng.randint(100, 999)}"
    v0 = rng.randint(3, 40)
    a, b, c, d = (f"{w}{rng.randint(1, 9)}" for w in ("A", "B", "C", "D"))
    base_local = _rec(rid, v0, {f1: a, f2: b}, {f1: v0 - 1, f2: v0 - 2})
    srv_f1 = _rec(rid, v0 + 1, {f1: c, f2: b}, {f1: v0 + 1, f2: v0 - 2})          # сервер изменил f1
    srv_del = _rec(rid, v0 + 1, {f1: a, f2: b}, {f1: v0 - 1, f2: v0 - 2}, deleted=True)
    stale = _rec(rid, v0 - 1, {f1: "old", f2: "old"}, {f1: v0 - 1, f2: v0 - 2})
    op = lambda i, f, v: {"opId": f"op{i}", "id": rid, "field": f, "value": v, "base": v0}  # noqa: E731
    L, P, R = names["L"], names["P"], names["R"]
    js = lambda o: repr(o).replace("True", "true").replace("False", "false")  # noqa: E731
    scen = [
        ("stale_response_ignored", {rid: base_local}, [], {rid: stale},
         f"__assert(res.@S@[{rid!r}].version === {v0} && res.@S@[{rid!r}].fields[{f1!r}] === {a!r}, 'stale')"),
        ("same_field_conflict", {rid: base_local}, [op(1, f1, d)], {rid: srv_f1},
         f"__assert(res.{X}.join() === 'op1' && res.@S@[{rid!r}].fields[{f1!r}] === {c!r}, 'conflict')"),
        ("other_field_kept", {rid: base_local}, [op(2, f2, d)], {rid: srv_f1},
         f"__assert(res.{X}.length === 0 && res.@S@[{rid!r}].fields[{f2!r}] === {d!r}, 'merge')"),
        ("base_moved", {rid: base_local}, [op(3, f2, d)], {rid: srv_f1},
         f"__assert(res.{K}.length === 1 && res.{K}[0].base === {v0 + 1}, 'rebase')"),
        ("deleted_on_server", {rid: base_local}, [op(4, f2, d)], {rid: srv_del},
         f"__assert(res.{X}.join() === 'op4' && res.{K}.length === 0, 'tombstone')"),
        ("no_remote", {rid: base_local}, [op(5, f1, d)], {},
         f"__assert(res.{K}.length === 1 && res.{K}[0].base === {v0} && res.@S@[{rid!r}].fields[{f1!r}] === {d!r}, 'local')"),
        ("new_remote_record", {}, [], {rid: srv_f1},
         f"__assert(res.@S@[{rid!r}].fields[{f1!r}] === {c!r}, 'insert')"),
        ("unknown_record_edit", {}, [op(6, f1, d)], {},
         f"__assert(res.{X}.join() === 'op6', 'unknown')"),
    ]
    rng.shuffle(scen)
    body = []
    for nm, loc, pend, rem, check in scen:
        body.append(f"{{ const res = rebase({js(loc)}, {js(pend)}, {js(rem)}); {check}; }}")
    tests = _rename("\n".join(body), {"S": names["S"]})
    helpers = _rename(HELPERS, names)
    blocks = [helpers, "{FN}", _rename(REPORT, names)]
    if rng.random() < 0.5:
        blocks = [helpers, _rename(REPORT, names), "{FN}"]
    module = "\n\n".join(blocks)
    buggy, correct = _rename(BUGGY, names), _rename(CORRECT, names)
    kinds = sorted(DISTRACTORS)
    dis = [_rename(DISTRACTORS[k], names) for k in kinds]
    stem = (f"{ctx.capitalize()}: записи «{entity}» правятся без сети, правки полей копятся в очереди `{P}` "
            f"(`base` — версия записи, на которой сделана правка). При синхронизации ответ сервера `{R}` "
            f"накладывается на локальное состояние `{L}`, затем очередь перебазируется. Правила: (1) ответ сервера "
            f"не новее локальной записи (версия не больше) отбрасывается; (2) правка поля, которое сервер изменил "
            f"после её `base` (`fieldVersion` поля больше `base`), — конфликт: значение сервера остаётся, правка "
            f"уходит в `{X}`; (3) правка удалённой на сервере или неизвестной записи — конфликт; (4) остальные "
            f"правки применяются поверх и уходят в `{K}` с `base`, равной текущей версии записи. Инцидент: два "
            f"быстрых запроса синхронизации подряд, ответ на первый пришёл вторым — и запись откатилась к старым "
            f"данным. Какая замена `rebase` выполняет правила целиком?")
    why = ("Верная замена отбрасывает ответ сервера, не новее локальной записи, определяет конфликт по версии "
           "поля, а не записи, считает удаление на сервере конфликтом и переносит base правок на текущую версию. "
           "Остальные варианты устраняют откат, но: " + "; ".join(WHY[k] for k in kinds) + ". Для команды: "
           "правила синхронизации фиксируются как контракт клиента и сервера и проверяются сценариями "
           "(устаревший ответ, удаление, правки разных полей), а не одним случаем инцидента.")
    return module_choose_fix(
        FAMILY_ID, seed, rng, stem=stem, module=module, buggy_fn=buggy, correct_fn=correct, distractors=dis,
        tests=tests, context=ctx, defect="stale_response_applied", why=why, label="Заменить rebase на:",
        runner="node", params={"entity": entity, "fields": [f1, f2], "distractors": kinds})
