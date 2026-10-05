"""Авторизация объекта по владельцу из доверенной сессии."""
from __future__ import annotations

from assessment_bank.gen_utils import make_rng
from ._support import CONTEXTS, SOURCES, bug_variant

FAMILY_ID = "security.access.owner_check_bug"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    owner, other = rng.sample(range(10, 900), 2)
    oid = rng.randint(100, 9000)
    record = {"id": oid, "owner_id": owner, "title": rng.choice(["План", "Черновик", "Отчёт", "Архив"])}
    code = """def read_document(repo, doc_id, session):
    doc = repo.get(doc_id)
    if doc is None:
        return None
    if session['user_id'] is not None:
        return doc['title']
    return None"""
    fixed = code.replace("session['user_id'] is not None", "doc['owner_id'] == session['user_id']")
    test = f"""repo = {{{oid}: {record!r}}}
assert read_document(repo, {oid}, {{'user_id': {owner}}}) == {record['title']!r}
assert read_document(repo, {oid}, {{'user_id': {other}}}) is None
assert read_document(repo, {oid + 1}, {{'user_id': {owner}}}) is None"""
    stem = (f"{ctx.capitalize()}: документ id={oid} принадлежит пользователю {owner}; "
            f"пользователь {other} тоже вошёл, но не имеет права его читать. Контракт даёт доступ "
            "только владельцу, без общей роли администратора. `session` уже проверена системой "
            "аутентификации, `user_id` — ненулевое целое число; поле `owner_id` находится в "
            "доверенных серверных метаданных. Укажите строку, путающую вход в систему с правом на объект.")
    return bug_variant(
        FAMILY_ID, seed, stem=stem, buggy=code, fixed=fixed, test=test, context=ctx,
        defect="missing_object_authorization",
        params={"why": "Проверить owner_id документа против user_id из доверенной сессии. "
                "Наличие сессии само по себе не даёт доступ ко всем объектам. "
                "Для БД предпочтителен запрос сразу с ограничением по владельцу.",
                "source_urls": [SOURCES["coding"]]},
    )
