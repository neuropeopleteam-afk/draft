"""Авторизация объекта по владельцу из доверенной сессии.

Версия 2 (после калибровки 05.10): код больше не одинаков во всех вариантах — меняются форма
функции (возврат None или исключения), поле объекта, форма проверки «только вход в систему»
и необязательная корректная проверка-приманка (удалённый/архивный объект), поэтому номер
строки дефекта меняется. Формулировка уточнена: ищется строка с условием, а не строка с
действием (в версии 1 65 % ответов моделей ≥ 7B указывали следующую строку — `return`).
"""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from ._support import CONTEXTS, SOURCES, bug_variant

FAMILY_ID = "security.access.owner_check_bug"

OBJECTS = [("document", "doc", "документ"), ("ticket", "tk", "заявка"), ("report", "rep", "отчёт"),
           ("booking", "bk", "бронь"), ("invoice", "inv", "счёт")]
FIELDS = ["title", "body", "summary", "status"]
# формы проверки «пользователь вошёл»: (для формы return, для формы raise)
AUTH_ONLY = [("session['user_id'] is not None", "session['user_id'] is None"),
             ("session.get('user_id')", "not session.get('user_id')"),
             ("'user_id' in session", "'user_id' not in session")]
DECOYS = [("deleted", "удалён"), ("archived", "в архиве")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    obj, var, ru = rng.choice(OBJECTS)
    field = rng.choice(FIELDS)
    allow, deny = rng.choice(AUTH_ONLY)
    shape = rng.choice(["return", "raise"])
    decoy = rng.choice([None, *DECOYS])
    owner, other = rng.sample(range(10, 900), 2)
    oid = rng.randint(100, 9000)
    value = rng.choice(["План", "Черновик", "Отчёт", "Архив", "Итоги", "Заметка"])
    record = {"id": oid, "owner_id": owner, field: value}
    if decoy:
        record[decoy[0]] = False
    fn = f"{rng.choice(['read', 'get', 'load'])}_{obj}"
    lines = [f"def {fn}(repo, {obj}_id, session):", f"    {var} = repo.get({obj}_id)"]
    if shape == "return":
        lines += [f"    if {var} is None:", "        return None"]
        if decoy:
            lines += [f"    if {var}.get('{decoy[0]}'):", "        return None"]
        lines += [f"    if {allow}:", f"        return {var}['{field}']", "    return None"]
        good = f"    if {var}['owner_id'] == session['user_id']:"
        bad = f"    if {allow}:"
        test_other = f"assert {fn}(repo, {oid}, {{'user_id': {other}}}) is None"
        test_missing = f"assert {fn}(repo, {oid + 1}, {{'user_id': {owner}}}) is None"
    else:
        lines += [f"    if {var} is None:", f"        raise KeyError({obj}_id)"]
        if decoy:
            lines += [f"    if {var}.get('{decoy[0]}'):", f"        raise KeyError({obj}_id)"]
        lines += [f"    if {deny}:", "        raise PermissionError('forbidden')",
                  f"    return {var}['{field}']"]
        good = f"    if {var}['owner_id'] != session['user_id']:"
        bad = f"    if {deny}:"
        test_other = (f"try:\n    {fn}(repo, {oid}, {{'user_id': {other}}})\n    raise AssertionError('чужой объект выдан')\n"
                      "except PermissionError:\n    pass")
        test_missing = (f"try:\n    {fn}(repo, {oid + 1}, {{'user_id': {owner}}})\n    raise AssertionError('нет объекта')\n"
                        "except KeyError:\n    pass")
    code = "\n".join(lines)
    fixed = "\n".join(good if l == bad else l for l in lines)
    test = (f"repo = {{{oid}: {record!r}}}\n"
            f"assert {fn}(repo, {oid}, {{'user_id': {owner}}}) == {value!r}\n{test_other}\n{test_missing}")
    deny_txt = ("вернуть None" if shape == "return" else "выбросить PermissionError")
    stem = (f"{ctx.capitalize()}: {ru} id={oid} принадлежит пользователю {owner}; пользователь "
            f"{other} тоже вошёл в систему, но читать чужой объект не вправе — функция должна "
            f"{deny_txt}. Контракт даёт доступ только владельцу, общей роли администратора нет. "
            "`session` уже проверена системой аутентификации, `user_id` в ней — ненулевое целое "
            "число; поле `owner_id` хранится в доверенных серверных метаданных объекта. Укажите "
            "номер строки с условием, которое путает вход в систему с правом на конкретный объект.")
    return bug_variant(
        FAMILY_ID, seed, stem=stem, buggy=code, fixed=fixed, test=test, context=ctx,
        defect="missing_object_authorization",
        params={"why": "Условие проверяет только факт входа. Нужно сравнить owner_id объекта с "
                "user_id из доверенной сессии. Наличие сессии само по себе не даёт доступ ко всем "
                "объектам. Для БД предпочтителен запрос сразу с ограничением по владельцу.",
                "source_urls": [SOURCES["coding"]], "shape": shape, "decoy": bool(decoy)},
    )
