"""security.access.bulk_owner_check_bug — find_bug: в пакетной операции права проверяются только у одного объекта.

Порог Junior/Middle. Обработчик принимает список id, но владельца сверяет только у первого (последнего) объекта —
добавив в пакет свой документ первым, можно удалить/выгрузить чужие (IDOR в пакетном запросе). Исправление в той же
строке — проверка всех объектов до выполнения действия. Ловушки — проверка «все найдены», обход для администратора,
возврат числа. Один подтип. Проверка исполнением: смешанный пакет «свой + чужой» отклоняется и ничего не меняет.
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from assessment_bank.families.common._plus_utils import line_bug_variant

FAMILY_ID = "security.access.bulk_owner_check_bug"

# (контекст, сущность, действие, метод хранилища)
CONTEXTS = [("документооборот", "docs", "delete_documents", "delete"), ("счета клиентов", "invoices", "archive_invoices", "archive"),
            ("фотоархив", "photos", "delete_photos", "delete"), ("отчёты", "reports", "export_reports", "export"),
            ("заявки на отпуск", "requests", "cancel_requests", "cancel"), ("заметки", "notes", "share_notes", "share")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, ent, fn, act = rng.choice(CONTEXTS)
    pick = rng.choice([f"{ent}[0]", f"{ent}[-1]", f"next(iter({ent}))"])
    with_limit = rng.random() < 0.5
    limit = rng.choice([20, 50, 100, 200, 500])
    nf, fb = rng.choice([("NotFound", "Forbidden"), ("DoesNotExist", "PermissionDenied"), ("Missing", "AccessDenied")])
    st = rng.choice(["store", "repo", "storage"])
    xv = rng.choice(["x", "obj", "item"])
    adm = rng.choice(["is_admin", "is_staff", "is_superuser"])

    buggy_line = f"    if not user.{adm} and {pick}.owner_id != user.id:"
    fixed_line = f"    if not user.{adm} and any({xv}.owner_id != user.id for {xv} in {ent}):"
    found = rng.choice([f"    if any({xv} is None for {xv} in {ent}):", f"    if None in {ent}:"])

    def assemble(line: str) -> str:
        lines = [f"class {nf}(Exception):", "    pass", "", "", f"class {fb}(Exception):", "    pass", "", "",
                 f"def {fn}(user, ids, {st}):"]
        if with_limit:
            lines += [f"    if len(ids) > {limit}:", '        raise ValueError("too many")']
        lines += [f"    {ent} = [{st}.get(i) for i in ids]", found, f"        raise {nf}()", line,
                  f"        raise {fb}()", f"    for {xv} in {ent}:", f"        {st}.{act}({xv}.id)", f"    return len({ent})"]
        return "\n".join(lines) + "\n"

    buggy, fixed = assemble(buggy_line), assemble(fixed_line)
    own, other, own2 = rng.sample(range(100, 999), 3)
    test = f"""
class _Obj:
    def __init__(self, id, owner_id):
        self.id, self.owner_id = id, owner_id
class _User:
    def __init__(self, id, adm=False):
        self.id, self.{adm} = id, adm
class _Store:
    def __init__(self):
        self.rows = {{{own}: _Obj({own}, 1), {own2}: _Obj({own2}, 1), {other}: _Obj({other}, 2)}}
        self.done = []
    def get(self, i):
        return self.rows.get(i)
    def {act}(self, i):
        self.done.append(i)
for ids in ([{own}, {other}], [{other}, {own}], [{own}, {other}, {own2}]):
    s = _Store()
    try:
        {fn}(_User(1), ids, s)
        raise AssertionError("чужой объект пропущен")
    except {fb}:
        pass
    assert s.done == []
s = _Store()
assert {fn}(_User(1), [{own}, {own2}], s) == 2 and sorted(s.done) == sorted([{own}, {own2}])
s = _Store()
assert {fn}(_User(9, True), [{own}, {other}], s) == 2
"""
    stem = (f"Безопасность ({ctx}). `{fn}` выполняет действие над пакетом объектов по списку id. На баг-баунти "
            f"показали, что обычный пользователь может применить действие к чужим объектам одним запросом. "
            f"Администратору разрешено всё. Укажите номер строки с ошибкой.")
    why = (f"Владелец сверяется только у одного объекта пакета (`{pick}`): если поставить свой объект на это место, "
           f"остальные — чужие — проходят без проверки (IDOR в пакетном запросе). Проверять нужно каждый объект до "
           f"выполнения действия: `any({xv}.owner_id != user.id for {xv} in {ent})`. Проверка «все найдены», обход для "
           f"администратора и лимит размера пакета верны.")
    return line_bug_variant(FAMILY_ID, seed, stem=stem, buggy=buggy, fixed=fixed, test=test, context=ctx,
                            defect="bulk_partial_authz", why=why,
                            display_note="После показанного кода выполняются пакеты «свой + чужой» в разном порядке, "
                                         "пакет из своих объектов и запрос администратора.",
                            params={"pick": pick, "ids": [own, other, own2]})
